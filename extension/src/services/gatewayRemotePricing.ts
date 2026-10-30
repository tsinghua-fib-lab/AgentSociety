import * as https from 'https';
import type { ModelPrice, ModelPricingMap } from './gatewayModelPricing';

const OPENROUTER_MODELS_URL = 'https://openrouter.ai/api/v1/models';
const LITELLM_PRICING_URL =
  'https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json';
const FETCH_TIMEOUT_MS = 5_000;

type JsonObject = Record<string, unknown>;

function isObject(value: unknown): value is JsonObject {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function fetchJson(url: string): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const req = https.get(
      url,
      {
        timeout: FETCH_TIMEOUT_MS,
        headers: {
          accept: 'application/json',
          'user-agent': 'AgentSociety-AI-CLI-Gateway',
        },
      },
      (res) => {
        if (!res.statusCode || res.statusCode < 200 || res.statusCode >= 300) {
          res.resume();
          reject(new Error(`HTTP ${res.statusCode ?? 'unknown'}`));
          return;
        }
        const chunks: Buffer[] = [];
        res.on('data', (chunk) => chunks.push(Buffer.from(chunk)));
        res.on('end', () => {
          try {
            resolve(JSON.parse(Buffer.concat(chunks).toString('utf8')));
          } catch (error) {
            reject(error);
          }
        });
      }
    );
    req.on('timeout', () => req.destroy(new Error('pricing_fetch_timeout')));
    req.on('error', reject);
  });
}

function perTokenToPerMillion(value: unknown): number | undefined {
  const n = typeof value === 'string' ? Number(value) : typeof value === 'number' ? value : NaN;
  if (!Number.isFinite(n) || n < 0) {
    return undefined;
  }
  return Number((n * 1_000_000).toPrecision(15));
}

function readFirstNumber(entry: JsonObject, keys: string[]): number | undefined {
  for (const key of keys) {
    const value = perTokenToPerMillion(entry[key]);
    if (value !== undefined) {
      return value;
    }
  }
  return undefined;
}

function addPrice(
  map: ModelPricingMap,
  modelId: unknown,
  price: Partial<ModelPrice> | undefined
): void {
  if (typeof modelId !== 'string' || !modelId.trim() || !price) {
    return;
  }
  if (price.inputPerMillion === undefined || price.outputPerMillion === undefined) {
    return;
  }
  map[modelId.trim()] = {
    inputPerMillion: price.inputPerMillion,
    outputPerMillion: price.outputPerMillion,
    cacheReadPerMillion: price.cacheReadPerMillion,
    cacheCreationPerMillion: price.cacheCreationPerMillion,
    cacheCreationLongPerMillion: price.cacheCreationLongPerMillion,
  };
}

export function normalizePricingModelId(modelId: string): string {
  let id = modelId.trim();
  const lastSlash = id.lastIndexOf('/');
  if (lastSlash >= 0) {
    id = id.slice(lastSlash + 1);
  }
  const colonIdx = id.indexOf(':');
  if (colonIdx >= 0) {
    id = id.slice(0, colonIdx);
  }
  return id
    .replace(/@/g, '-')
    .toLowerCase()
    .replace(/\[1m\]$/, '')
    .replace(/-(?:19|20)\d{2}-\d{2}-\d{2}$/, '')
    .replace(/-(?:19|20)\d{6}$/, '');
}

function findPriceForModel(modelId: string, pricing: ModelPricingMap): ModelPrice | undefined {
  const normalized = normalizePricingModelId(modelId);
  for (const [key, price] of Object.entries(pricing)) {
    if (normalizePricingModelId(key) === normalized) {
      return price;
    }
  }
  return undefined;
}

export function parseOpenRouterPricing(json: unknown): ModelPricingMap {
  const map: ModelPricingMap = {};
  if (!isObject(json) || !Array.isArray(json.data)) {
    return map;
  }
  for (const model of json.data) {
    if (!isObject(model) || !isObject(model.pricing)) {
      continue;
    }
    addPrice(map, model.id, {
      inputPerMillion: perTokenToPerMillion(model.pricing.prompt),
      outputPerMillion: perTokenToPerMillion(model.pricing.completion),
      cacheReadPerMillion: perTokenToPerMillion(model.pricing.input_cache_read),
      cacheCreationPerMillion: perTokenToPerMillion(model.pricing.input_cache_write),
      cacheCreationLongPerMillion: perTokenToPerMillion(model.pricing.input_cache_write_1h),
    });
  }
  return map;
}

async function fetchOpenRouterPricing(): Promise<ModelPricingMap> {
  return parseOpenRouterPricing(await fetchJson(OPENROUTER_MODELS_URL));
}

export function parseLiteLlmPricing(json: unknown): ModelPricingMap {
  const map: ModelPricingMap = {};
  if (!isObject(json)) {
    return map;
  }
  for (const [modelId, entry] of Object.entries(json)) {
    if (!isObject(entry) || modelId === 'sample_spec') {
      continue;
    }
    addPrice(map, modelId, {
      inputPerMillion: readFirstNumber(entry, ['input_cost_per_token']),
      outputPerMillion: readFirstNumber(entry, ['output_cost_per_token']),
      cacheReadPerMillion: readFirstNumber(entry, [
        'cache_read_input_token_cost',
        'input_cache_read_cost_per_token',
        'cache_read_input_cost_per_token',
      ]),
      cacheCreationPerMillion: readFirstNumber(entry, [
        'cache_creation_input_token_cost',
        'input_cache_write_cost_per_token',
        'cache_creation_input_cost_per_token',
      ]),
      cacheCreationLongPerMillion: readFirstNumber(entry, [
        'cache_creation_input_token_cost_above_12hr',
        'cache_creation_input_token_cost_above_1hr',
      ]),
    });
  }
  return map;
}

async function fetchLiteLlmPricing(): Promise<ModelPricingMap> {
  return parseLiteLlmPricing(await fetchJson(LITELLM_PRICING_URL));
}

export async function fetchRemoteGatewayPricing(): Promise<{
  pricing: ModelPricingMap;
  sources: string[];
}> {
  const settled = await Promise.allSettled([
    fetchOpenRouterPricing().then((pricing) => ({ source: 'OpenRouter', pricing })),
    fetchLiteLlmPricing().then((pricing) => ({ source: 'LiteLLM', pricing })),
  ]);
  const pricing: ModelPricingMap = {};
  const sources: string[] = [];
  for (const result of settled) {
    if (result.status !== 'fulfilled') {
      continue;
    }
    Object.assign(pricing, result.value.pricing);
    if (Object.keys(result.value.pricing).length > 0) {
      sources.push(result.value.source);
    }
  }
  return { pricing, sources };
}

export function selectObservedRemotePricing(
  remotePricing: ModelPricingMap,
  modelIds: string[]
): ModelPricingMap {
  const selected: ModelPricingMap = {};
  for (const modelId of modelIds) {
    const price = findPriceForModel(modelId, remotePricing);
    if (price) {
      selected[modelId] = price;
    }
  }
  return selected;
}
