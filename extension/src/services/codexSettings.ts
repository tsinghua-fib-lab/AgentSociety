import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import * as cp from 'child_process';
import { parse as parseToml } from 'smol-toml';
import writeFileAtomic from 'write-file-atomic';
import {
  getOrCreateGatewayAuthToken,
  AI_CLI_GATEWAY_PLACEHOLDER_TOKEN,
  buildLocalGatewayBaseUrl,
  isLocalGatewayBaseUrl,
} from './aiCliGatewayUpstream';
import { resolveProviderBaseUrl } from '../aiCli/officialEndpoints';
import {
  CODEX_MODEL_CATALOG_FILENAME,
  CODEX_ONE_M_AUTO_COMPACT_LIMIT,
  inferCodexContextWindow,
  writeCodexModelCatalog,
} from './codexModelCatalog';
import {
  CODEX_WEB_SEARCH_DISABLED_VALUE,
  shouldDisableCodexWebSearch,
} from './codexWebSearchPolicy';

export const CODEX_GATEWAY_PROVIDER_ID = 'agentsociety-gateway';
export const CODEX_DIRECT_PROVIDER_ID = 'agentsociety-codex';

export type CodexProviderPatch = {
  baseUrl: string;
  apiKey: string;
  model?: string;
  codexEnable1m?: boolean;
  codexContextWindow?: number;
  codexAutoCompactLimit?: number;
};

function resolveCodexHome(): string {
  const codexHome = process.env.CODEX_HOME?.trim();
  return codexHome || path.join(os.homedir(), '.codex');
}

export function resolveCodexConfigPath(): string {
  return path.join(resolveCodexHome(), 'config.toml');
}

export function resolveCodexAuthPath(): string {
  return path.join(resolveCodexHome(), 'auth.json');
}

function atomicWriteFile(filePath: string, content: string): void {
  const dir = path.dirname(filePath);
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }
  writeFileAtomic.sync(filePath, content, { encoding: 'utf8', mode: 0o600 });
}

export type CodexAuthTokens = {
  access_token?: string;
  refresh_token?: string;
  account_id?: string;
  /** Newer Codex builds store a JWT string; older ones used a decoded object. */
  id_token?: string | {
    chatgpt_account_id?: string;
  };
};

export type CodexAuthDocument = {
  auth_mode?: string;
  OPENAI_API_KEY?: string | null;
  tokens?: CodexAuthTokens | null;
  last_refresh?: string;
  personal_access_token?: string;
  [key: string]: unknown;
};

export function readCodexAuthDocument(): CodexAuthDocument | null {
  const authPath = resolveCodexAuthPath();
  if (!fs.existsSync(authPath)) {
    return null;
  }
  try {
    return JSON.parse(fs.readFileSync(authPath, 'utf-8')) as CodexAuthDocument;
  } catch {
    return null;
  }
}

function extractAccountIdFromIdToken(idToken: CodexAuthTokens['id_token']): string | undefined {
  if (!idToken) {
    return undefined;
  }
  if (typeof idToken === 'object') {
    return idToken.chatgpt_account_id?.trim() || undefined;
  }
  const parts = idToken.split('.');
  if (parts.length < 2) {
    return undefined;
  }
  try {
    const payload = JSON.parse(Buffer.from(parts[1], 'base64url').toString('utf-8')) as Record<string, unknown>;
    const account =
      (typeof payload.chatgpt_account_id === 'string' && payload.chatgpt_account_id) ||
      (typeof payload['https://api.openai.com/auth'] === 'object' &&
        payload['https://api.openai.com/auth'] &&
        typeof (payload['https://api.openai.com/auth'] as Record<string, unknown>).chatgpt_account_id ===
          'string' &&
        ((payload['https://api.openai.com/auth'] as Record<string, unknown>).chatgpt_account_id as string)) ||
      '';
    return typeof account === 'string' && account.trim() ? account.trim() : undefined;
  } catch {
    return undefined;
  }
}

/**
 * ChatGPT / Codex official login material in auth.json.
 * Aligns with cc-switch: any non-empty OAuth payload counts, not only access_token.
 */
export function readCodexSubscriptionSession(): { accessToken: string; accountId?: string } | null {
  const auth = readCodexAuthDocument();
  if (!auth) {
    return null;
  }
  const tokens = auth.tokens && typeof auth.tokens === 'object' ? auth.tokens : undefined;
  const accessToken =
    tokens?.access_token?.trim() ||
    tokens?.refresh_token?.trim() ||
    auth.personal_access_token?.trim() ||
    '';
  const authMode = (auth.auth_mode ?? '').trim().toLowerCase();
  const hasOauthObject = Boolean(
    tokens &&
      Object.values(tokens).some((value) => {
        if (typeof value === 'string') {
          return Boolean(value.trim());
        }
        return Boolean(value);
      })
  );
  if (!accessToken && !(authMode === 'chatgpt' && hasOauthObject)) {
    return null;
  }
  const accountId =
    tokens?.account_id?.trim() || extractAccountIdFromIdToken(tokens?.id_token);
  const token = accessToken || (hasOauthObject ? 'chatgpt-session' : '');
  if (!token) {
    return null;
  }
  return accountId ? { accessToken: token, accountId } : { accessToken: token };
}

export type CodexOfficialLoginSnapshot = {
  present: boolean;
  authPath: string;
  authMode?: string;
  storeHint: 'file' | 'keyring_or_cli' | 'missing' | 'api_key_only';
};

export function getCodexOfficialLoginSnapshot(): CodexOfficialLoginSnapshot {
  const authPath = resolveCodexAuthPath();
  const auth = readCodexAuthDocument();
  if (!auth) {
    return { present: false, authPath, storeHint: 'missing' };
  }
  if (readCodexSubscriptionSession()) {
    return {
      present: true,
      authPath,
      authMode: typeof auth.auth_mode === 'string' ? auth.auth_mode : undefined,
      storeHint: 'file',
    };
  }
  if (typeof auth.OPENAI_API_KEY === 'string' && auth.OPENAI_API_KEY.trim()) {
    return {
      present: false,
      authPath,
      authMode: typeof auth.auth_mode === 'string' ? auth.auth_mode : undefined,
      storeHint: 'api_key_only',
    };
  }
  return {
    present: false,
    authPath,
    authMode: typeof auth.auth_mode === 'string' ? auth.auth_mode : undefined,
    storeHint: 'missing',
  };
}

/**
 * True when ~/.codex/auth.json still has ChatGPT/Codex OAuth material.
 * Used for mobile remote control / official plugins while model traffic
 * goes through config.toml + local gateway (cc-switch style).
 */
export function hasCodexOfficialLogin(): boolean {
  return Boolean(readCodexSubscriptionSession()?.accessToken);
}

export function isCodexChatGptLoginStatusOutput(output: string): boolean {
  return /\blogged\s+in\s+using\s+chatgpt\b/i.test(output);
}

/**
 * Resolve official login through Codex itself so keyring-backed credentials are
 * detected as well as file-backed ~/.codex/auth.json credentials.
 */
export async function detectCodexOfficialLogin(): Promise<CodexOfficialLoginSnapshot> {
  const fileSnapshot = getCodexOfficialLoginSnapshot();
  if (fileSnapshot.present) {
    return fileSnapshot;
  }

  return new Promise((resolve) => {
    cp.execFile(
      'codex',
      ['login', 'status'],
      { timeout: 5_000, windowsHide: true },
      (error, stdout, stderr) => {
        const output = `${stdout ?? ''}\n${stderr ?? ''}`;
        if (!error && isCodexChatGptLoginStatusOutput(output)) {
          resolve({
            present: true,
            authPath: fileSnapshot.authPath,
            authMode: 'chatgpt',
            storeHint: 'keyring_or_cli',
          });
          return;
        }
        resolve(fileSnapshot);
      }
    );
  });
}

export function readCodexConfigText(): string {
  const configPath = resolveCodexConfigPath();
  if (!fs.existsSync(configPath)) {
    return '';
  }
  return fs.readFileSync(configPath, 'utf-8');
}

export function writeCodexConfigText(text: string): void {
  const normalized = text.endsWith('\n') ? text : `${text}\n`;
  parseCodexConfigText(normalized);
  atomicWriteFile(resolveCodexConfigPath(), normalized);
}

function parseCodexConfigText(text: string): Record<string, unknown> {
  try {
    return parseToml(text) as Record<string, unknown>;
  } catch (error) {
    throw new Error(
      `Invalid Codex config.toml: ${error instanceof Error ? error.message : String(error)}`
    );
  }
}

function tomlString(value: string): string {
  return JSON.stringify(value);
}

function removeProviderBlock(text: string, providerId: string): string {
  const newline = text.includes('\r\n') ? '\r\n' : '\n';
  const target = `model_providers.${providerId}`;
  const lines = text.split(/\r?\n/);
  const output: string[] = [];
  let removing = false;
  for (const line of lines) {
    const header = line.match(/^\s*\[([^\]]+)\]\s*(?:#.*)?$/)?.[1]?.trim();
    if (header) {
      removing = header === target || header.startsWith(`${target}.`);
    }
    if (!removing) {
      output.push(line);
    }
  }
  return output.join(newline).replace(/\n{3,}/g, '\n\n');
}

function readProviderBlock(text: string, providerId: string): string {
  const target = `model_providers.${providerId}`;
  const lines = text.split(/\r?\n/);
  const block: string[] = [];
  let reading = false;
  for (const line of lines) {
    const header = line.match(/^\s*\[([^\]]+)\]\s*(?:#.*)?$/)?.[1]?.trim();
    if (header) {
      if (reading) {
        break;
      }
      reading = header === target;
    }
    if (reading) {
      block.push(line);
    }
  }
  return block.join('\n');
}

function upsertModelProvider(text: string, providerId: string): string {
  return updateTopLevelTomlField(text, 'model_provider', tomlString(providerId));
}

function appendProviderBlock(
  text: string,
  providerId: string,
  lines: string[]
): string {
  let updated = removeProviderBlock(text, providerId).replace(/\n+$/, '');
  updated += ['', `[model_providers.${providerId}]`, ...lines, ''].join('\n');
  return updated;
}

function codexBaseUrlForProvider(baseUrl: string): string {
  const resolved = resolveProviderBaseUrl(baseUrl, 'openai').replace(/\/+$/, '');
  return /\/v\d+(?:[a-z]+\d*)?$/i.test(resolved) ? resolved : `${resolved}/v1`;
}

function upsertTopLevelTomlField(text: string, key: string, value: string): string {
  return updateTopLevelTomlField(text, key, value);
}

function removeTopLevelTomlField(text: string, key: string): string {
  return updateTopLevelTomlField(text, key, null);
}

function updateTopLevelTomlField(text: string, key: string, value: string | null): string {
  const newline = text.includes('\r\n') ? '\r\n' : '\n';
  const escapedKey = key.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const assignment = new RegExp(`^\\s*${escapedKey}\\s*=`);
  const lines = text.split(/\r?\n/);
  const output: string[] = [];
  let inTopLevel = true;
  let written = false;

  for (const line of lines) {
    if (/^\s*\[/.test(line)) {
      inTopLevel = false;
    }
    if (inTopLevel && assignment.test(line)) {
      if (!written && value !== null) {
        output.push(`${key} = ${value}`);
        written = true;
      }
      continue;
    }
    output.push(line);
  }

  if (!written && value !== null) {
    output.unshift(`${key} = ${value}`);
  }
  return output.join(newline);
}

function readTopLevelTomlString(text: string, key: string): string | undefined {
  if (!text.trim()) {
    return undefined;
  }
  const value = parseCodexConfigText(text)[key];
  return typeof value === 'string' ? value.trim() || undefined : undefined;
}

function isAgentSocietyProvider(providerId: string | undefined): boolean {
  return providerId === CODEX_GATEWAY_PROVIDER_ID || providerId === CODEX_DIRECT_PROVIDER_ID;
}

function isAgentSocietyCatalog(catalogRef: string | undefined): boolean {
  const basename = catalogRef?.replace(/\\/g, '/').split('/').pop();
  return basename === CODEX_MODEL_CATALOG_FILENAME;
}

function removeAgentSocietyCatalogPolicy(text: string): string {
  if (!isAgentSocietyCatalog(readTopLevelTomlString(text, 'model_catalog_json'))) {
    return text;
  }
  let updated = removeTopLevelTomlField(text, 'model_catalog_json');
  updated = removeTopLevelTomlField(updated, 'model_auto_compact_token_limit');
  if (readTopLevelTomlString(updated, 'web_search') === CODEX_WEB_SEARCH_DISABLED_VALUE) {
    updated = removeTopLevelTomlField(updated, 'web_search');
  }
  return updated;
}

function applyCodexCatalogAndPolicy(text: string, provider: CodexProviderPatch): string {
  const modelName = provider.model?.trim();
  if (!modelName) {
    return text;
  }
  const contextWindow =
    provider.codexContextWindow && provider.codexContextWindow > 0
      ? provider.codexContextWindow
      : inferCodexContextWindow(modelName, provider.codexEnable1m);
  writeCodexModelCatalog({
    entries: [
      {
        modelId: modelName,
        displayName: modelName,
        contextWindow,
        effectiveContextPercent: provider.codexEnable1m ? 100 : undefined,
      },
    ],
  });
  let updated = upsertTopLevelTomlField(
    text,
    'model_catalog_json',
    tomlString(CODEX_MODEL_CATALOG_FILENAME)
  );
  if (provider.codexEnable1m) {
    const compactLimit =
      provider.codexAutoCompactLimit && provider.codexAutoCompactLimit > 0
        ? provider.codexAutoCompactLimit
        : CODEX_ONE_M_AUTO_COMPACT_LIMIT;
    updated = upsertTopLevelTomlField(
      updated,
      'model_auto_compact_token_limit',
      String(compactLimit)
    );
  } else {
    updated = removeTopLevelTomlField(updated, 'model_auto_compact_token_limit');
  }
  if (shouldDisableCodexWebSearch(provider.baseUrl, modelName)) {
    updated = upsertTopLevelTomlField(
      updated,
      'web_search',
      tomlString(CODEX_WEB_SEARCH_DISABLED_VALUE)
    );
  } else {
    const current = readTopLevelTomlString(updated, 'web_search');
    if (current === CODEX_WEB_SEARCH_DISABLED_VALUE) {
      updated = removeTopLevelTomlField(updated, 'web_search');
    }
  }
  return updated;
}

export function applyCodexGatewayConfig(port: number, provider?: CodexProviderPatch): void {
  const gatewayUrl = `${buildLocalGatewayBaseUrl(port)}/v1`;
  let text = readCodexConfigText();
  parseCodexConfigText(text);
  // Align with cc-switch: never leave a stale top-level proxy placeholder.
  text = removeTopLevelTomlField(text, 'experimental_bearer_token');
  const previousProvider = readTopLevelTomlString(text, 'model_provider');
  text = removeProviderBlock(text, CODEX_DIRECT_PROVIDER_ID);
  text = appendProviderBlock(text, CODEX_GATEWAY_PROVIDER_ID, [
    'name = "AgentSociety Gateway"',
    `base_url = ${tomlString(gatewayUrl)}`,
    'wire_api = "responses"',
    'requires_openai_auth = false',
    'supports_websockets = false',
    // 2026-11-06 二轮审计修复:写真令牌(网关逐请求校验),非静态占位。
    `experimental_bearer_token = ${tomlString(getOrCreateGatewayAuthToken())}`,
  ]);
  text = upsertModelProvider(text, CODEX_GATEWAY_PROVIDER_ID);
  const modelName = provider?.model?.trim();
  if (modelName) {
    text = upsertTopLevelTomlField(text, 'model', tomlString(modelName));
    text = applyCodexCatalogAndPolicy(text, {
      baseUrl: provider?.baseUrl ?? gatewayUrl,
      apiKey: getOrCreateGatewayAuthToken(),
      model: modelName,
      codexEnable1m: provider?.codexEnable1m,
      codexContextWindow: provider?.codexContextWindow,
      codexAutoCompactLimit: provider?.codexAutoCompactLimit,
    });
  } else {
    if (isAgentSocietyProvider(previousProvider)) {
      text = removeTopLevelTomlField(text, 'model');
    }
    text = removeAgentSocietyCatalogPolicy(text);
  }
  writeCodexConfigText(text);
}

export function buildCodexDirectProviderConfigText(
  baseText: string,
  provider: CodexProviderPatch
): string {
  const baseUrl = codexBaseUrlForProvider(provider.baseUrl);
  let text = baseText;
  parseCodexConfigText(text);
  const previousProvider = readTopLevelTomlString(text, 'model_provider');
  text = removeProviderBlock(text, CODEX_GATEWAY_PROVIDER_ID);
  text = appendProviderBlock(text, CODEX_DIRECT_PROVIDER_ID, [
    'name = "AgentSociety Codex"',
    `base_url = ${tomlString(baseUrl)}`,
    'wire_api = "responses"',
    'requires_openai_auth = false',
    'supports_websockets = false',
    `experimental_bearer_token = ${tomlString(provider.apiKey.trim())}`,
  ]);
  text = upsertModelProvider(text, CODEX_DIRECT_PROVIDER_ID);
  if (provider.model?.trim()) {
    text = upsertTopLevelTomlField(text, 'model', tomlString(provider.model.trim()));
    text = applyCodexCatalogAndPolicy(text, provider);
  } else {
    if (isAgentSocietyProvider(previousProvider)) {
      text = removeTopLevelTomlField(text, 'model');
    }
    text = removeAgentSocietyCatalogPolicy(text);
  }
  return text;
}

export function applyCodexDirectProvider(provider: CodexProviderPatch): void {
  const text = buildCodexDirectProviderConfigText(readCodexConfigText(), provider);
  writeCodexConfigText(text);
}

function stripAgentsocietyCodexProviders(text: string): string {
  const activeProvider = readTopLevelTomlString(text, 'model_provider');
  let updated = removeProviderBlock(text, CODEX_GATEWAY_PROVIDER_ID);
  updated = removeProviderBlock(updated, CODEX_DIRECT_PROVIDER_ID);
  if (
    activeProvider === CODEX_GATEWAY_PROVIDER_ID ||
    activeProvider === CODEX_DIRECT_PROVIDER_ID
  ) {
    updated = removeTopLevelTomlField(updated, 'model_provider');
  }
  return updated;
}

export function buildCodexOfficialSubscriptionConfigText(baseText: string): string {
  let text = baseText;
  if (!text) {
    return text;
  }
  const activeProvider = readTopLevelTomlString(text, 'model_provider');
  if (isAgentSocietyProvider(activeProvider)) {
    text = removeTopLevelTomlField(text, 'model');
  }
  text = removeTopLevelTomlField(text, 'experimental_bearer_token');
  text = removeAgentSocietyCatalogPolicy(text);
  text = stripAgentsocietyCodexProviders(text);
  return text;
}

export function applyCodexOfficialSubscription(): void {
  const text = buildCodexOfficialSubscriptionConfigText(readCodexConfigText());
  if (!text) {
    return;
  }
  writeCodexConfigText(text);
}

/**
 * True when live config.toml is our local-proxy takeover (cc-switch placeholder style).
 * Used to avoid saving a corrupted backup or restoring a placeholder as "pre-takeover".
 */
export function isCodexGatewayTakeoverConfig(text: string): boolean {
  if (!text.trim()) {
    return false;
  }
  try {
    parseCodexConfigText(text);
  } catch {
    return false;
  }
  const active = readTopLevelTomlString(text, 'model_provider');
  if (active !== CODEX_GATEWAY_PROVIDER_ID) {
    return false;
  }
  const block = readProviderBlock(text, CODEX_GATEWAY_PROVIDER_ID);
  // 兼容两种:本进程写的真令牌,或旧配置遗留的静态占位。
  return block.includes('name = "AgentSociety Gateway"')
    || block.includes(`experimental_bearer_token = ${tomlString(AI_CLI_GATEWAY_PLACEHOLDER_TOKEN)}`)
    || block.includes(`experimental_bearer_token = "${AI_CLI_GATEWAY_PLACEHOLDER_TOKEN}"`);
}

/**
 * Snapshot live config before proxy takeover.
 * Returns null when live is already a gateway placeholder (do not clobber a good backup).
 */
export function snapshotCodexLiveBackup(liveText: string): string | null {
  if (isCodexGatewayTakeoverConfig(liveText)) {
    return null;
  }
  return liveText;
}

/**
 * Restore pre-takeover live config (cc-switch stop_with_restore).
 * Returns false when backup is missing or itself a placeholder — caller should rebuild from SSOT.
 */
export function restoreCodexLiveBackup(backup: string | null | undefined): boolean {
  if (backup === null || backup === undefined) {
    return false;
  }
  if (isCodexGatewayTakeoverConfig(backup)) {
    return false;
  }
  writeCodexConfigText(backup);
  return true;
}

/**
 * Release Codex local-proxy takeover: prefer clean live backup, else rebuild callback.
 */
export function releaseCodexGatewayTakeover(
  backup: string | null | undefined,
  rebuildFromProvider: () => void
): 'backup' | 'rebuild' {
  if (restoreCodexLiveBackup(backup)) {
    return 'backup';
  }
  rebuildFromProvider();
  return 'rebuild';
}

export function stripCodexGatewayConfig(): void {
  let text = readCodexConfigText();
  if (!text) {
    return;
  }
  parseCodexConfigText(text);
  const activeProvider = readTopLevelTomlString(text, 'model_provider');
  text = removeProviderBlock(text, CODEX_GATEWAY_PROVIDER_ID);
  if (activeProvider === CODEX_GATEWAY_PROVIDER_ID) {
    text = removeTopLevelTomlField(text, 'model_provider');
    text = removeTopLevelTomlField(text, 'model');
  }
  text = removeAgentSocietyCatalogPolicy(text);
  writeCodexConfigText(text);
}

export function getCodexRoutingSnapshot(): {
  configPath: string;
  authPath: string;
  routedViaGateway: boolean;
  directConfigured: boolean;
  gatewayBaseUrl?: string;
} {
  const configPath = resolveCodexConfigPath();
  const authPath = resolveCodexAuthPath();
  const text = fs.existsSync(configPath) ? fs.readFileSync(configPath, 'utf-8') : '';
  const providerMatch = text.match(/^model_provider\s*=\s*"([^"]*)"/m);
  const activeProvider = providerMatch?.[1]?.trim();
  const routedViaGateway = activeProvider === CODEX_GATEWAY_PROVIDER_ID;
  const directConfigured =
    activeProvider === CODEX_DIRECT_PROVIDER_ID ||
    text.includes(`[model_providers.${CODEX_DIRECT_PROVIDER_ID}]`);
  const gatewayBlock = readProviderBlock(text, CODEX_GATEWAY_PROVIDER_ID);
  const gatewayUrlMatch = gatewayBlock.match(/^base_url\s*=\s*"([^"]*)"/m);
  const gatewayBaseUrl = gatewayUrlMatch?.[1]?.trim();
  return {
    configPath,
    authPath,
    routedViaGateway: routedViaGateway && Boolean(gatewayBaseUrl && isLocalGatewayBaseUrl(gatewayBaseUrl)),
    directConfigured,
    gatewayBaseUrl: gatewayBaseUrl && !isLocalGatewayBaseUrl(gatewayBaseUrl) ? gatewayBaseUrl : undefined,
  };
}

/**
 * True when ~/.codex/config.toml carries configuration that was NOT written by AgentSociety.
 * Used to guard against clobbering a user's own Codex setup during one-click import.
 *
 * Detection: any `model_provider` / `[model_providers.X]` block whose id is not one of
 * our managed provider ids counts as user-authored. An active AgentSociety provider alone
 * does NOT trigger this (we may have written it in a prior session).
 */
export function isCodexConfiguredByUser(): boolean {
  const configPath = resolveCodexConfigPath();
  if (!fs.existsSync(configPath)) {
    return false;
  }
  const text = fs.readFileSync(configPath, 'utf-8');
  if (!text.trim()) {
    return false;
  }
  const activeProvider = readTopLevelTomlString(text, 'model_provider');
  if (activeProvider && !isAgentSocietyProvider(activeProvider)) {
    return true;
  }
  const providerBlockRe = /^\s*\[model_providers\.([^\]\s]+)\]\s*(?:#.*)?$/gm;
  let match: RegExpExecArray | null;
  while ((match = providerBlockRe.exec(text)) !== null) {
    const providerId = match[1]?.trim();
    if (providerId && !isAgentSocietyProvider(providerId)) {
      return true;
    }
  }
  return false;
}

/**
 * Single decision point for defaulting the Codex gateway route on: only when the
 * user never made an explicit choice (state key undefined), has no own Codex
 * setup (no user-authored provider config, no official OAuth login, no API-key
 * auth.json), and there is an eligible provider to route. Any explicit toggle or
 * a value persisted by an older build wins — this probe never overrides it.
 */
export function shouldEnableCodexRouteByDefault(state: {
  explicitlySet: boolean;
  userConfigured: boolean;
  officialLoginPresent: boolean;
  hasEligibleProvider: boolean;
}): boolean {
  return (
    !state.explicitlySet &&
    !state.userConfigured &&
    !state.officialLoginPresent &&
    state.hasEligibleProvider
  );
}
