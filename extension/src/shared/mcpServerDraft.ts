export function parseMcpArgs(text: string): string[] {
  const value: unknown = text.trim() ? JSON.parse(text) : [];
  if (!Array.isArray(value) || value.some((arg) => typeof arg !== 'string')) { throw new Error('invalid_mcp_args'); }
  return value;
}

export function parseMcpStringMap(text: string): Record<string, string> | undefined {
  const value: unknown = text.trim() ? JSON.parse(text) : {};
  if (!value || typeof value !== 'object' || Array.isArray(value) || Object.values(value).some((item) => typeof item !== 'string')) {
    throw new Error('invalid_mcp_map');
  }
  return Object.keys(value).length ? value as Record<string, string> : undefined;
}
