import { randomUUID } from 'crypto';

type JsonObject = Record<string, unknown>;

function nowSec(): number {
  return Math.floor(Date.now() / 1000);
}

function newId(prefix: string): string {
  return `${prefix}_${randomUUID().replace(/-/g, '')}`;
}

function isObject(value: unknown): value is JsonObject {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value));
}

function parseJsonObject(text: string): JsonObject {
  try {
    const parsed = JSON.parse(text);
    return isObject(parsed) ? parsed : {};
  } catch {
    return {};
  }
}

function flattenResponsesContent(content: unknown): string {
  if (typeof content === 'string') {
    return content;
  }
  if (!Array.isArray(content)) {
    return content === undefined || content === null ? '' : String(content);
  }
  return content
    .filter(isObject)
    .map((part) => {
      if (typeof part.text === 'string') {
        return part.text;
      }
      if (typeof part.content === 'string') {
        return part.content;
      }
      return '';
    })
    .filter(Boolean)
    .join('\n');
}

function normalizeAnthropicUsage(usage: unknown): JsonObject | null {
  if (!isObject(usage)) {
    return null;
  }
  const input = typeof usage.input_tokens === 'number' ? usage.input_tokens : 0;
  const output = typeof usage.output_tokens === 'number' ? usage.output_tokens : 0;
  const cacheRead =
    typeof usage.cache_read_input_tokens === 'number' ? usage.cache_read_input_tokens : 0;
  const cacheCreation =
    typeof usage.cache_creation_input_tokens === 'number' ? usage.cache_creation_input_tokens : 0;
  return {
    input_tokens: input + cacheRead + cacheCreation,
    output_tokens: output,
    total_tokens: input + cacheRead + cacheCreation + output,
    input_tokens_details: { cached_tokens: cacheRead },
  };
}

function mapResponsesToolChoiceToAnthropic(toolChoice: unknown): unknown {
  if (toolChoice === 'required') {
    return { type: 'any' };
  }
  if (toolChoice === 'auto' || toolChoice === 'none') {
    return { type: toolChoice };
  }
  if (!isObject(toolChoice)) {
    return toolChoice;
  }
  if (toolChoice.type === 'function' && isObject(toolChoice.function) && typeof toolChoice.function.name === 'string') {
    return { type: 'tool', name: toolChoice.function.name };
  }
  return toolChoice;
}

export function translateResponsesRequestToAnthropicMessages(
  request: JsonObject,
  model: string
): JsonObject {
  const messages: JsonObject[] = [];
  const input = request.input;
  if (typeof input === 'string') {
    messages.push({ role: 'user', content: input });
  } else if (Array.isArray(input)) {
    for (const item of input) {
      if (!isObject(item)) {
        continue;
      }
      if (item.type === 'function_call_output') {
        messages.push({
          role: 'user',
          content: [{
            type: 'tool_result',
            tool_use_id: String(item.call_id ?? item.tool_call_id ?? ''),
            content: typeof item.output === 'string' ? item.output : JSON.stringify(item.output ?? ''),
          }],
        });
        continue;
      }
      if (item.type === 'function_call') {
        messages.push({
          role: 'assistant',
          content: [{
            type: 'tool_use',
            id: String(item.call_id ?? item.id ?? ''),
            name: String(item.name ?? ''),
            input: isObject(item.arguments)
              ? item.arguments
              : typeof item.arguments === 'string'
                ? parseJsonObject(item.arguments)
                : {},
          }],
        });
        continue;
      }
      const role = item.role === 'assistant' ? 'assistant' : 'user';
      const text = flattenResponsesContent(item.content);
      if (text) {
        messages.push({ role, content: text });
      }
    }
  }

  const out: JsonObject = {
    model,
    messages,
    max_tokens: request.max_output_tokens ?? 4096,
    stream: request.stream !== false,
  };
  if (request.instructions) {
    out.system = String(request.instructions);
  }
  if (request.temperature !== undefined) {
    out.temperature = request.temperature;
  }
  if (request.top_p !== undefined) {
    out.top_p = request.top_p;
  }
  if (Array.isArray(request.tools)) {
    out.tools = request.tools
      .filter(isObject)
      .filter((tool) => tool.type === 'function')
      .map((tool) => {
        const fn = isObject(tool.function) ? tool.function : tool;
        return {
          name: String(fn.name ?? tool.name ?? ''),
          description: typeof fn.description === 'string' ? fn.description : undefined,
          input_schema: isObject(fn.parameters)
            ? fn.parameters
            : isObject(tool.parameters)
              ? tool.parameters
              : { type: 'object', properties: {} },
        };
      })
      .filter((tool) => tool.name);
  }
  if (request.tool_choice !== undefined) {
    out.tool_choice = mapResponsesToolChoiceToAnthropic(request.tool_choice);
  }
  return out;
}

export function translateAnthropicMessageToResponses(
  message: JsonObject,
  request: JsonObject
): JsonObject {
  const output: JsonObject[] = [];
  const content = Array.isArray(message.content) ? message.content.filter(isObject) : [];
  for (const block of content) {
    if (block.type === 'thinking' && typeof block.thinking === 'string') {
      output.push({
        id: newId('rs'),
        type: 'reasoning',
        status: 'completed',
        content: [{ type: 'reasoning_text', text: block.thinking }],
        summary: [],
      });
    } else if (block.type === 'text' && typeof block.text === 'string') {
      output.push({
        id: newId('msg'),
        type: 'message',
        status: 'completed',
        role: 'assistant',
        content: [{ type: 'output_text', text: block.text, annotations: [] }],
      });
    } else if (block.type === 'tool_use') {
      const id = String(block.id ?? newId('call'));
      output.push({
        id,
        type: 'function_call',
        call_id: id,
        name: String(block.name ?? ''),
        arguments: JSON.stringify(block.input ?? {}),
      });
    }
  }
  return {
    id: String(message.id ?? newId('resp')),
    object: 'response',
    created_at: nowSec(),
    status: 'completed',
    completed_at: nowSec(),
    error: null,
    incomplete_details: null,
    input: request.input ?? [],
    instructions: request.instructions ?? null,
    max_output_tokens: request.max_output_tokens ?? null,
    model: message.model ?? request.model ?? '',
    output,
    previous_response_id: request.previous_response_id ?? null,
    store: false,
    temperature: request.temperature ?? 1,
    text: request.text ?? { format: { type: 'text' } },
    tool_choice: request.tool_choice ?? 'auto',
    tools: request.tools ?? [],
    top_p: request.top_p ?? 1,
    truncation: 'disabled',
    usage: normalizeAnthropicUsage(message.usage),
    user: request.user ?? null,
    metadata: request.metadata ?? {},
  };
}

export type ResponsesSseEvent = JsonObject;

export function formatResponsesSseEvent(event: ResponsesSseEvent): string {
  return `data: ${JSON.stringify(event)}\n\n`;
}

export class AnthropicMessagesToResponsesStreamTranslator {
  private seq = 1;
  private readonly responseId = newId('resp');
  private readonly createdAt = nowSec();
  private readonly request: JsonObject;
  private model = '';
  private latestUsage: JsonObject | null = null;
  private outputIndexByBlock = new Map<number, number>();
  private itemIdByBlock = new Map<number, string>();
  private nextOutputIndex = 0;
  private outputTextByBlock = new Map<number, string>();
  private reasoningByBlock = new Map<number, string>();
  private toolByBlock = new Map<number, { id: string; name: string; arguments: string }>();

  constructor(request: JsonObject) {
    this.request = request;
    this.model = String(request.model ?? '');
  }

  initialEvents(): ResponsesSseEvent[] {
    const shell = this.responseShell('in_progress', []);
    return [
      { type: 'response.created', response: shell, sequence_number: this.seq++ },
      { type: 'response.in_progress', response: shell, sequence_number: this.seq++ },
    ];
  }

  private responseShell(status: string, output: JsonObject[], usage?: JsonObject | null): JsonObject {
    return {
      id: this.responseId,
      object: 'response',
      created_at: this.createdAt,
      status,
      completed_at: status === 'completed' ? nowSec() : null,
      error: null,
      incomplete_details: null,
      input: this.request.input ?? [],
      instructions: this.request.instructions ?? null,
      max_output_tokens: this.request.max_output_tokens ?? null,
      model: this.model || this.request.model || '',
      output,
      previous_response_id: this.request.previous_response_id ?? null,
      store: false,
      temperature: this.request.temperature ?? 1,
      text: this.request.text ?? { format: { type: 'text' } },
      tool_choice: this.request.tool_choice ?? 'auto',
      tools: this.request.tools ?? [],
      top_p: this.request.top_p ?? 1,
      truncation: 'disabled',
      usage: usage ?? null,
      user: this.request.user ?? null,
      metadata: this.request.metadata ?? {},
    };
  }

  consumeAnthropicEvent(eventName: string, data: JsonObject): ResponsesSseEvent[] {
    const events: ResponsesSseEvent[] = [];
    if (eventName === 'message_start' && isObject(data.message)) {
      if (typeof data.message.model === 'string') {
        this.model = data.message.model;
      }
      return events;
    }
    if (eventName === 'content_block_start') {
      const index = typeof data.index === 'number' ? data.index : 0;
      const block = isObject(data.content_block) ? data.content_block : {};
      const outputIndex = this.nextOutputIndex++;
      this.outputIndexByBlock.set(index, outputIndex);
      if (block.type === 'thinking') {
        const id = newId('rs');
        this.itemIdByBlock.set(index, id);
        events.push({
          type: 'response.output_item.added',
          output_index: outputIndex,
          item: { id, type: 'reasoning', status: 'in_progress', content: [], summary: [] },
          sequence_number: this.seq++,
        });
      } else if (block.type === 'tool_use') {
        const id = String(block.id ?? newId('call'));
        const name = String(block.name ?? '');
        this.itemIdByBlock.set(index, id);
        this.toolByBlock.set(index, { id, name, arguments: '' });
        events.push({
          type: 'response.output_item.added',
          output_index: outputIndex,
          item: { id, type: 'function_call', call_id: id, name, arguments: '' },
          sequence_number: this.seq++,
        });
      } else {
        const id = newId('msg');
        this.itemIdByBlock.set(index, id);
        events.push({
          type: 'response.output_item.added',
          output_index: outputIndex,
          item: { id, type: 'message', status: 'in_progress', role: 'assistant', content: [] },
          sequence_number: this.seq++,
        });
        events.push({
          type: 'response.content_part.added',
          item_id: id,
          output_index: outputIndex,
          content_index: 0,
          part: { type: 'output_text', annotations: [] },
          sequence_number: this.seq++,
        });
      }
      return events;
    }
    if (eventName === 'content_block_delta') {
      const index = typeof data.index === 'number' ? data.index : 0;
      const delta = isObject(data.delta) ? data.delta : {};
      const outputIndex = this.outputIndexByBlock.get(index) ?? 0;
      const itemId = this.itemIdByBlock.get(index) ?? '';
      if (delta.type === 'text_delta' && typeof delta.text === 'string') {
        this.outputTextByBlock.set(index, (this.outputTextByBlock.get(index) ?? '') + delta.text);
        events.push({
          type: 'response.output_text.delta',
          item_id: itemId,
          output_index: outputIndex,
          content_index: 0,
          delta: delta.text,
          sequence_number: this.seq++,
        });
      } else if (delta.type === 'thinking_delta' && typeof delta.thinking === 'string') {
        this.reasoningByBlock.set(index, (this.reasoningByBlock.get(index) ?? '') + delta.thinking);
        events.push({
          type: 'response.reasoning_text.delta',
          item_id: itemId,
          output_index: outputIndex,
          content_index: 0,
          delta: delta.thinking,
          sequence_number: this.seq++,
        });
      } else if (delta.type === 'input_json_delta' && typeof delta.partial_json === 'string') {
        const state = this.toolByBlock.get(index);
        if (state) {
          state.arguments += delta.partial_json;
        }
        events.push({
          type: 'response.function_call_arguments.delta',
          item_id: itemId,
          output_index: outputIndex,
          delta: delta.partial_json,
          sequence_number: this.seq++,
        });
      }
      return events;
    }
    if (eventName === 'message_delta') {
      this.latestUsage = normalizeAnthropicUsage(data.usage);
    }
    return events;
  }

  completionEvent(): ResponsesSseEvent {
    const output: JsonObject[] = [];
    for (const [index, text] of this.reasoningByBlock) {
      output.push({
        id: this.itemIdByBlock.get(index) ?? newId('rs'),
        type: 'reasoning',
        status: 'completed',
        content: [{ type: 'reasoning_text', text }],
        summary: [],
      });
    }
    for (const state of this.toolByBlock.values()) {
      output.push({
        id: state.id,
        type: 'function_call',
        call_id: state.id,
        name: state.name,
        arguments: state.arguments,
      });
    }
    for (const [index, text] of this.outputTextByBlock) {
      output.push({
        id: this.itemIdByBlock.get(index) ?? newId('msg'),
        type: 'message',
        status: 'completed',
        role: 'assistant',
        content: [{ type: 'output_text', text, annotations: [] }],
      });
    }
    return {
      type: 'response.completed',
      response: this.responseShell('completed', output, this.latestUsage),
      sequence_number: this.seq++,
    };
  }
}
