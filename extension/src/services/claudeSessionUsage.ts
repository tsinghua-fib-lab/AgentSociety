import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import type { TokenUsageRecord } from './gatewayUsageTracker';

type SessionUsage = {
  input_tokens?: unknown;
  output_tokens?: unknown;
  cache_read_input_tokens?: unknown;
  cache_creation_input_tokens?: unknown;
  cache_creation?: {
    ephemeral_1h_input_tokens?: unknown;
  };
};

type SessionMessage = {
  id?: unknown;
  role?: unknown;
  model?: unknown;
  usage?: SessionUsage;
};

type SessionEntry = {
  type?: unknown;
  timestamp?: unknown;
  message?: SessionMessage;
};

export type ClaudeSessionUsageCursor = Record<string, number>;

export type ClaudeSessionUsageScanResult = {
  records: TokenUsageRecord[];
  cursor: ClaudeSessionUsageCursor;
};

function tokenCount(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0
    ? value
    : 0;
}

export function parseClaudeSessionUsageLine(
  line: string,
  provider?: string
): TokenUsageRecord | null {
  let entry: SessionEntry;
  try {
    entry = JSON.parse(line) as SessionEntry;
  } catch {
    return null;
  }
  if (entry.type !== 'assistant' || entry.message?.role !== 'assistant') {
    return null;
  }
  const messageId =
    typeof entry.message.id === 'string' ? entry.message.id.trim() : '';
  const model =
    typeof entry.message.model === 'string' ? entry.message.model.trim() : '';
  const timestamp =
    typeof entry.timestamp === 'string' ? entry.timestamp.trim() : '';
  const usage = entry.message.usage;
  if (!messageId || !model || !timestamp || !usage) {
    return null;
  }
  const inputTokens = tokenCount(usage.input_tokens);
  const outputTokens = tokenCount(usage.output_tokens);
  const cacheReadTokens = tokenCount(usage.cache_read_input_tokens);
  const cacheCreationTokens = tokenCount(usage.cache_creation_input_tokens);
  const cacheCreationLongTokens = tokenCount(
    usage.cache_creation?.ephemeral_1h_input_tokens
  );
  if (
    inputTokens === 0 &&
    outputTokens === 0 &&
    cacheReadTokens === 0 &&
    cacheCreationTokens === 0
  ) {
    return null;
  }
  return {
    app: 'claude',
    source: 'session',
    model,
    inputTokens,
    outputTokens,
    cacheReadTokens,
    cacheCreationTokens,
    ...(cacheCreationLongTokens > 0 ? { cacheCreationLongTokens } : {}),
    serverToolUseTokens: 0,
    requestId: messageId,
    upstream: 'claude-session',
    provider: provider?.trim() || 'Claude session',
    status: 200,
    ts: timestamp,
  };
}

async function listJsonlFiles(directory: string): Promise<string[]> {
  let entries: fs.Dirent[];
  try {
    entries = await fs.promises.readdir(directory, { withFileTypes: true });
  } catch {
    return [];
  }
  const nested = await Promise.all(
    entries.map(async (entry) => {
      const entryPath = path.join(directory, entry.name);
      if (entry.isDirectory()) {
        return listJsonlFiles(entryPath);
      }
      return entry.isFile() && entry.name.endsWith('.jsonl') ? [entryPath] : [];
    })
  );
  return nested.flat();
}

async function readAppendedLines(
  filePath: string,
  offset: number
): Promise<{ lines: string[]; nextOffset: number }> {
  const stat = await fs.promises.stat(filePath);
  const start = offset <= stat.size ? offset : 0;
  if (start === stat.size) {
    return { lines: [], nextOffset: start };
  }
  const handle = await fs.promises.open(filePath, 'r');
  try {
    const buffer = Buffer.alloc(stat.size - start);
    const { bytesRead } = await handle.read(buffer, 0, buffer.length, start);
    const content = buffer.subarray(0, bytesRead);
    const newlineIndex = content.lastIndexOf(0x0a);
    if (newlineIndex < 0) {
      return { lines: [], nextOffset: start };
    }
    const complete = content.subarray(0, newlineIndex + 1);
    return {
      lines: complete.toString('utf-8').split('\n').filter(Boolean),
      nextOffset: start + newlineIndex + 1,
    };
  } finally {
    await handle.close();
  }
}

export async function scanClaudeSessionUsage(
  cursor: ClaudeSessionUsageCursor,
  provider?: string,
  projectsDirectory = path.join(os.homedir(), '.claude', 'projects')
): Promise<ClaudeSessionUsageScanResult> {
  const files = await listJsonlFiles(projectsDirectory);
  const nextCursor = { ...cursor };
  const recordsByRequestId = new Map<string, TokenUsageRecord>();
  for (const filePath of files) {
    const { lines, nextOffset } = await readAppendedLines(
      filePath,
      cursor[filePath] ?? 0
    );
    nextCursor[filePath] = nextOffset;
    for (const line of lines) {
      const record = parseClaudeSessionUsageLine(line, provider);
      if (!record) {
        continue;
      }
      const previous = recordsByRequestId.get(record.requestId);
      const previousTotal = previous
        ? previous.inputTokens +
          previous.outputTokens +
          previous.cacheReadTokens +
          previous.cacheCreationTokens
        : -1;
      const currentTotal =
        record.inputTokens +
        record.outputTokens +
        record.cacheReadTokens +
        record.cacheCreationTokens;
      if (!previous || currentTotal >= previousTotal) {
        recordsByRequestId.set(record.requestId, record);
      }
    }
  }
  return { records: [...recordsByRequestId.values()], cursor: nextCursor };
}
