import type { McpServerRecord } from '../services/mcpClient';

export const DEFAULT_MCP_REGISTRY = 'https://registry.modelcontextprotocol.io/v0.1';
export const MCP_REGISTRY_SOURCES = [
  { id: 'official', url: DEFAULT_MCP_REGISTRY },
  { id: 'github', url: 'https://api.mcp.github.com/v0.1' },
] as const;

export type RegistryInput = {
  name?: string;
  valueHint?: string;
  type?: 'named' | 'positional';
  value?: string;
  default?: string;
  description?: string;
  placeholder?: string;
  format?: string;
  isRequired?: boolean;
  isSecret?: boolean;
  isRepeated?: boolean;
  choices?: string[];
  variables?: Record<string, RegistryInput>;
};
export type RegistryRemote = {
  type: string;
  url: string;
  headers?: RegistryInput[];
  variables?: Record<string, RegistryInput>;
};
export type RegistryPackage = {
  registryType: string;
  identifier: string;
  version?: string;
  registryBaseUrl?: string;
  runtimeHint?: string;
  fileSha256?: string;
  transport?: { type: string };
  runtimeArguments?: RegistryInput[];
  packageArguments?: RegistryInput[];
  environmentVariables?: RegistryInput[];
};
export type RegistryServer = {
  name: string;
  title?: string;
  description?: string;
  version: string;
  websiteUrl?: string;
  repository?: { url?: string };
  remotes?: RegistryRemote[];
  packages?: RegistryPackage[];
};
export type RegistryPage = { servers: RegistryServer[]; nextCursor?: string };
export type RegistryVariant = { key: string; label: string; remote?: RegistryRemote; package?: RegistryPackage };
export type RegistryField = RegistryInput & { key: string; label: string };

export function registryVariants(server: RegistryServer): RegistryVariant[] {
  const remotes = (server.remotes ?? []).filter((remote) => ['streamable-http', 'sse'].includes(remote.type))
    .map((remote, index) => ({ key: `remote-${index}`, label: `${remote.type} · ${remote.url}`, remote }));
  const packages = (server.packages ?? []).filter((pkg) => ['npm', 'pypi', 'oci'].includes(pkg.registryType) && pkg.transport?.type === 'stdio')
    .map((pkg, index) => ({ key: `package-${index}`, label: `${pkg.registryType} · ${pkg.identifier}${pkg.version ? `@${pkg.version}` : ''}`, package: pkg }));
  return [...remotes, ...packages];
}

export function registryFields(variant: RegistryVariant): RegistryField[] {
  const fields = new Map<string, RegistryField>();
  const collect = (input: RegistryInput, key: string, label = input.name ?? input.valueHint ?? key) => {
    for (const [name, variable] of Object.entries(input.variables ?? {})) { collect(variable, `${key}:variable:${name}`, variable.name ?? name); }
    if (input.value === undefined) { fields.set(key, { ...input, key, label }); }
  };
  for (const [name, variable] of Object.entries(variant.remote?.variables ?? {})) { collect(variable, name); }
  (variant.remote?.headers ?? []).forEach((input, index) => collect(input, `header:${input.name ?? index}`));
  const pkg = variant.package;
  (pkg?.environmentVariables ?? []).forEach((input, index) => collect(input, input.name ?? `env:${index}`));
  (pkg?.runtimeArguments ?? []).forEach((input, index) => collect(input, input.valueHint ?? input.name ?? `runtime:${index}`));
  (pkg?.packageArguments ?? []).forEach((input, index) => collect(input, input.valueHint ?? input.name ?? `argument:${index}`));
  return [...fields.values()];
}

/** Resolve metadata into an editable configuration; no package is installed or started. */
export function resolveRegistryServer(server: RegistryServer, variant: RegistryVariant, values: Record<string, string>): Omit<McpServerRecord, 'id'> {
  const fields = registryFields(variant);
  const resolved = new Map(fields.map((field) => [field.key, values[field.key] ?? field.default ?? '']));
  for (const field of fields) {
    const value = resolved.get(field.key)!;
    if (field.isRequired && !value.trim()) { throw new Error(`required:${field.label}`); }
    if (value && field.format === 'number' && !Number.isFinite(Number(value))) { throw new Error(`number:${field.label}`); }
    if (value && field.format === 'boolean' && !['true', 'false'].includes(value)) { throw new Error(`boolean:${field.label}`); }
    if (value && field.choices?.length && !field.choices.includes(value)) { throw new Error(`choice:${field.label}`); }
  }
  const inputValue = (input: RegistryInput, key: string) => {
    const raw = input.value ?? resolved.get(key) ?? input.default ?? '';
    return raw.replace(/\{([^{}]+)\}/g, (_match, name: string) => {
      const definition = input.variables?.[name];
      if (!definition) { return _match; }
      return definition.value ?? resolved.get(`${key}:variable:${name}`) ?? definition.default ?? '';
    });
  };
  const common = { name: server.name, enabledClaude: false, enabledCodex: false };
  if (variant.remote) {
    const remote = variant.remote;
    const endpoint = remote.url.replace(/\{([^{}]+)\}/g, (_match, name: string) => {
      const value = values[name] ?? remote.variables?.[name]?.value ?? remote.variables?.[name]?.default;
      if (!value) { throw new Error(`required:${name}`); }
      return value;
    });
    const url = new URL(endpoint);
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.hash) { throw new Error('invalid_registry_endpoint'); }
    const headers = (remote.headers ?? []).flatMap((input, index) => {
      const value = inputValue(input, `header:${input.name ?? index}`);
      return input.name && value ? [[input.name, value]] : [];
    });
    return { ...common, transport: remote.type === 'sse' ? 'sse' : 'http', url: url.href, httpHeaders: headers.length ? Object.fromEntries(headers) : undefined };
  }
  const pkg = variant.package;
  if (!pkg) { throw new Error('unsupported_registry_package'); }
  if (pkg.fileSha256) { throw new Error('registry_integrity_required'); }
  const argumentsOf = (inputs: RegistryInput[], prefix: string): string[] => inputs.flatMap((input, index) => {
    const value = inputValue(input, input.valueHint ?? input.name ?? `${prefix}:${index}`);
    if (!value) { return []; }
    const values = input.isRepeated && input.value === undefined && value.trim().startsWith('[') ? JSON.parse(value) as unknown : [value];
    if (!Array.isArray(values) || values.some((item) => typeof item !== 'string')) { throw new Error(`array:${input.name ?? input.valueHint}`); }
    return values.flatMap((item) => input.type === 'named' && input.name ? [input.name, item] : [item]);
  });
  const env = (pkg.environmentVariables ?? []).flatMap((input, index) => {
    const value = inputValue(input, input.name ?? `env:${index}`);
    if (input.name && value) { return [[input.name, value]]; }
    return [];
  });
  const runtime = argumentsOf(pkg.runtimeArguments ?? [], 'runtime');
  const args = argumentsOf(pkg.packageArguments ?? [], 'argument');
  const identifier = pkg.identifier;
  if (!identifier || identifier.startsWith('-') || /\s/.test(identifier)) { throw new Error('invalid_registry_package'); }
  let command: string, launch: string[];
  if (pkg.registryType === 'npm') {
    if (pkg.runtimeHint && pkg.runtimeHint !== 'npx') { throw new Error('unsupported_registry_runtime'); }
    command = 'npx'; launch = ['-y', ...runtime, ...(pkg.registryBaseUrl ? ['--registry', pkg.registryBaseUrl] : []), `${identifier}${pkg.version ? `@${pkg.version}` : ''}`, ...args];
  } else if (pkg.registryType === 'pypi') {
    if (pkg.runtimeHint && pkg.runtimeHint !== 'uvx') { throw new Error('unsupported_registry_runtime'); }
    command = 'uvx'; launch = [...runtime, ...(pkg.registryBaseUrl ? ['--index-url', pkg.registryBaseUrl.replace(/\/+$/, '').replace(/(?:\/simple)?$/, '/simple')] : []), '--from', `${identifier}${pkg.version ? `==${pkg.version}` : ''}`, identifier, ...args];
  } else if (pkg.registryType === 'oci') {
    if (pkg.runtimeHint && pkg.runtimeHint !== 'docker') { throw new Error('unsupported_registry_runtime'); }
    command = 'docker'; launch = ['run', '--rm', '-i', ...env.flatMap(([name]) => ['-e', name]), ...runtime, `${identifier}${pkg.version && !identifier.includes('@') && !identifier.slice(identifier.lastIndexOf('/') + 1).includes(':') ? `:${pkg.version}` : ''}`, ...args];
  } else { throw new Error('unsupported_registry_package'); }
  return { ...common, transport: 'stdio', command, args: launch, env: env.length ? Object.fromEntries(env) : undefined };
}
