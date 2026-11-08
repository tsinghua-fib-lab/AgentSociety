import * as http from 'http';
import * as https from 'https';
import { createOutboundProxyAgent, type OutboundProxyConfig } from './gatewayOutboundProxy';
import type { RegistryInput, RegistryPage, RegistryServer } from '../shared/mcpRegistry';

export function normalizeRegistrySource(source: string): string {
  const url = new URL(source.trim());
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash) { throw new Error('invalid_registry_source'); }
  return url.href.replace(/\/+$/, '');
}

export function registryRequestUrl(source: string, search = '', cursor = ''): string {
  const url = new URL(normalizeRegistrySource(source) + '/servers');
  url.searchParams.set('limit', '20');
  url.searchParams.set('version', 'latest');
  if (search.trim()) { url.searchParams.set('search', search.trim()); }
  if (cursor) { url.searchParams.set('cursor', cursor); }
  return url.href;
}

export function registryProxy(source: string, configured?: string): OutboundProxyConfig | null {
  const url = new URL(source);
  const exclusions = (process.env.no_proxy ?? process.env.NO_PROXY ?? '').split(',').map((part) => part.trim().toLowerCase()).filter(Boolean);
  if (exclusions.some((part) => part === '*' || part === url.host.toLowerCase() || part === url.hostname.toLowerCase() ||
    (part.startsWith('.') && (url.hostname.toLowerCase() === part.slice(1) || url.hostname.toLowerCase().endsWith(part))))) { return null; }
  const proxy = configured?.trim() || (url.protocol === 'https:' ? process.env.https_proxy ?? process.env.HTTPS_PROXY : process.env.http_proxy ?? process.env.HTTP_PROXY);
  return proxy ? { url: proxy } : null;
}

function inputDefinition(value: unknown): RegistryInput | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) { return null; }
  const raw = value as Record<string, unknown>;
  const fields = Object.fromEntries(['name', 'valueHint', 'type', 'value', 'default', 'description', 'placeholder', 'format'].filter((key) => typeof raw[key] === 'string').map((key) => [key, raw[key]]));
  return { ...fields, isRequired: raw.isRequired === true, isSecret: raw.isSecret === true, isRepeated: raw.isRepeated === true,
    choices: Array.isArray(raw.choices) ? raw.choices.filter((item): item is string => typeof item === 'string') : undefined,
    variables: raw.variables && typeof raw.variables === 'object' && !Array.isArray(raw.variables)
      ? Object.fromEntries(Object.entries(raw.variables).flatMap(([key, item]) => { const input = inputDefinition(item); return input ? [[key, input]] : []; })) : undefined,
  };
}
function inputs(value: unknown): RegistryInput[] { return Array.isArray(value) ? value.map(inputDefinition).filter((item): item is RegistryInput => Boolean(item)) : []; }

export function parseRegistryPage(body: unknown): RegistryPage {
  const data = body as { servers?: unknown[]; metadata?: { nextCursor?: unknown } } | null;
  if (!data || !Array.isArray(data.servers)) { throw new Error('invalid_registry_response'); }
  const servers = data.servers.flatMap((value): RegistryServer[] => {
    if (!value || typeof value !== 'object') { return []; }
    const row = value as { server?: Record<string, unknown>; _meta?: Record<string, { status?: string }> };
    const status = row._meta?.['io.modelcontextprotocol.registry/official']?.status;
    const server = row.server;
    if ((status && status !== 'active') || !server || typeof server.name !== 'string' || !server.name.trim() || typeof server.version !== 'string' || !server.version.trim()) { return []; }
    return [{ name: server.name, version: server.version,
      title: typeof server.title === 'string' ? server.title : undefined,
      description: typeof server.description === 'string' ? server.description : undefined,
      websiteUrl: typeof server.websiteUrl === 'string' ? server.websiteUrl : undefined,
      repository: server.repository && typeof server.repository === 'object' && typeof (server.repository as { url?: unknown }).url === 'string' ? { url: (server.repository as { url: string }).url } : undefined,
      remotes: Array.isArray(server.remotes) ? server.remotes.flatMap((remote) => {
        if (!remote || typeof remote !== 'object' || typeof remote.type !== 'string' || typeof remote.url !== 'string') { return []; }
        return [{ type: remote.type, url: remote.url, headers: inputs(remote.headers), variables: inputDefinition({ variables: remote.variables })?.variables }];
      }) : [],
      packages: Array.isArray(server.packages) ? server.packages.flatMap((pkg) => {
        if (!pkg || typeof pkg !== 'object' || typeof pkg.registryType !== 'string' || typeof pkg.identifier !== 'string') { return []; }
        return [{ registryType: pkg.registryType, identifier: pkg.identifier, version: typeof pkg.version === 'string' ? pkg.version : undefined,
          registryBaseUrl: typeof pkg.registryBaseUrl === 'string' ? pkg.registryBaseUrl : undefined,
          runtimeHint: typeof pkg.runtimeHint === 'string' ? pkg.runtimeHint : undefined,
          fileSha256: typeof pkg.fileSha256 === 'string' ? pkg.fileSha256 : undefined,
          transport: pkg.transport && typeof pkg.transport.type === 'string' ? { type: pkg.transport.type } : undefined,
          runtimeArguments: inputs(pkg.runtimeArguments), packageArguments: inputs(pkg.packageArguments), environmentVariables: inputs(pkg.environmentVariables),
        }];
      }) : [],
    }];
  });
  return { servers, nextCursor: typeof data.metadata?.nextCursor === 'string' && data.metadata.nextCursor ? data.metadata.nextCursor : undefined };
}

export async function fetchRegistryPage(options: { source: string; search?: string; cursor?: string; proxy?: OutboundProxyConfig | null }): Promise<RegistryPage> {
  const endpoint = new URL(registryRequestUrl(options.source, options.search, options.cursor));
  const body = await new Promise<unknown>((resolve, reject) => {
    const agent = createOutboundProxyAgent(options.proxy);
    const transport = endpoint.protocol === 'https:' ? https : http;
    const request = transport.get(endpoint, { agent, headers: { Accept: 'application/json' } }, (response) => {
      const chunks: Buffer[] = []; let size = 0;
      response.on('error', reject);
      response.on('data', (chunk: Buffer) => {
        size += chunk.length;
        if (size > 4 * 1024 * 1024) { request.destroy(new Error('registry_response_too_large')); return; }
        chunks.push(chunk);
      });
      response.on('end', () => {
        if (response.statusCode !== 200) { reject(new Error(`registry_http_${response.statusCode}`)); return; }
        try { resolve(JSON.parse(Buffer.concat(chunks).toString('utf-8'))); }
        catch { reject(new Error('invalid_registry_response')); }
      });
    });
    const timer = setTimeout(() => request.destroy(new Error('registry_timeout')), 12_000);
    request.on('error', reject);
    request.on('close', () => { clearTimeout(timer); agent?.destroy(); });
  });
  return parseRegistryPage(body);
}
