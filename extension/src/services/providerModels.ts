import { inferApiKindFromBaseUrl, resolveProviderBaseUrl, type AiCliApiKind } from '../aiCli/officialEndpoints';
import { requestJson } from './httpClient';

export type ProviderModelOption = { id: string; label?: string };
export type FetchProviderModelsResult =
  | { ok: true; models: ProviderModelOption[]; apiKind: AiCliApiKind }
  | { ok: false; error: string; status?: number; detail?: string };

export function buildModelsUrl(baseUrl: string): string {
  const base = baseUrl.trim().replace(/\/+$/, '');
  return /\/v\d+$/.test(base) ? `${base}/models` : `${base}/v1/models`;
}

function modelUrls(baseUrl: string): string[] {
  const base = baseUrl.trim().replace(/\/+$/, '');
  const root = base.replace(/\/(?:api\/|apps\/)?(?:anthropic|openai)$/, '');
  return [...new Set([
    buildModelsUrl(base), `${base}/models`,
    ...(root !== base ? [buildModelsUrl(root), `${root}/models`] : []),
  ])];
}

export function parseProviderModelsResponse(body: unknown): ProviderModelOption[] {
  if (!body || typeof body !== 'object') { return []; }
  const record = body as Record<string, unknown>;
  const rows: unknown[] = Array.isArray(record.data) ? record.data
    : Array.isArray(record.models) ? record.models : Array.isArray(body) ? body : [];
  const result = new Map<string, ProviderModelOption>();
  for (const row of rows) {
    if (!row || typeof row !== 'object') { continue; }
    const entry = row as Record<string, unknown>;
    const id = [entry.id, entry.slug, entry.name].find((value): value is string => typeof value === 'string' && Boolean(value.trim()))?.trim();
    if (!id || result.has(id)) { continue; }
    const label = entry.display_name;
    result.set(id, typeof label === 'string' && label.trim() !== id ? { id, label: label.trim() } : { id });
  }
  return [...result.values()].sort((a, b) => a.id.localeCompare(b.id));
}

export async function fetchProviderModels(
  baseUrl: string, apiKey: string, apiKind: AiCliApiKind = inferApiKindFromBaseUrl(baseUrl)
): Promise<FetchProviderModelsResult> {
  const key = apiKey.trim();
  if (!key) { return { ok: false, error: 'missing_api_key' }; }
  const base = resolveProviderBaseUrl(baseUrl, apiKind);
  try {
    if (!['http:', 'https:'].includes(new URL(base).protocol)) { throw new Error('Expected HTTP(S)'); }
  } catch {
    return { ok: false, error: 'invalid_base_url' };
  }
  const bearer: Record<string, string> = { Authorization: `Bearer ${key}`, Accept: 'application/json' };
  const headers = apiKind === 'anthropic'
    ? [{ 'x-api-key': key, 'anthropic-version': '2023-06-01', Accept: 'application/json' }, { ...bearer, 'anthropic-version': '2023-06-01' }]
    : [bearer];
  const deadline = Date.now() + 12_000;
  try {
    for (const url of modelUrls(base)) {
      for (const auth of headers) {
        const remaining = deadline - Date.now();
        if (remaining <= 0) { return { ok: false, error: 'timeout' }; }
        const response = await requestJson<unknown>(url, {
          method: 'GET', headers: auth, timeoutMs: remaining, fallbackToNodeOnFetchError: true,
        });
        if (response.status === 404 || response.status === 405) { break; }
        if (response.status === 401 || response.status === 403) {
          if (auth !== headers[headers.length - 1]) { continue; }
          return { ok: false, error: 'auth_failed', status: response.status };
        }
        if (!response.ok) { return { ok: false, error: 'http_error', status: response.status }; }
        const models = parseProviderModelsResponse(await response.json());
        if (!models.length) { return { ok: false, error: 'empty_list' }; }
        return { ok: true, models, apiKind };
      }
    }
    return { ok: false, error: 'models_not_supported' };
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    return {
      ok: false,
      error: (error instanceof Error && error.name === 'AbortError') || /timeout|超时/i.test(detail) ? 'timeout' : 'network_error',
      detail: detail.split(key).join('[redacted]'),
    };
  }
}
