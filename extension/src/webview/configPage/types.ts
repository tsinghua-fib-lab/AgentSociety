/**
 * 配置页 Webview 的类型定义
 */

export interface VSCodeAPI {
  postMessage(message: unknown): void;
  getState(): unknown;
  setState(state: unknown): void;
}

export interface ConfigValues {
  // 必填
  llmApiKey: string;
  // 后端服务
  backendHost: string;
  backendPort: number;
  pythonPath: string;
  backendAutoStart: boolean;
  // LLM 默认配置
  llmApiBase: string;
  llmModel: string;
  /** 推理（thinking）开关：'' = 跟随网关默认（不发送该参数）/ 'on' / 'off' */
  llmThinking: string;
  // 可选
  backendLogLevel: string;
  coderLlmApiKey: string;
  coderLlmApiBase: string;
  coderLlmModel: string;
  /** coder 角色的 thinking 开关：'' = 沿用默认 LLM 的取值 / 'on' / 'off' */
  coderLlmThinking: string;
  // Embedding
  embeddingApiKey: string;
  embeddingApiBase: string;
  embeddingModel: string;
  embeddingDims: number;
  // Literature Search
  literatureSearchMcpUrl: string;
  literatureSearchApiKey: string;
}

export interface ValidationState {
  validating: boolean;
  valid: boolean | null;
  error: string | null;
}

export interface WorkspaceInfo {
  hasWorkspace: boolean;
  workspacePath?: string;
  /** Relative path to the loaded .env file, e.g. agentsociety/.env */
  envFilePath?: string;
  /** True after first successful LLM save (or wizard finish). Skip forced wizard. */
  hasCompletedInitialSetup?: boolean;
}

export interface BackendStatus {
  isRunning: boolean;
  port?: number;
  url?: string;
}

export interface ImportedModelOptions {
  openaiCompatible: string[];
  claudeCode: string[];
  embedding: string[];
}

export interface ImportedModelDefaults {
  simulation: string;
  coder: string;
  codex?: string;
  embedding: string;
  claudeCode: string;
  claudeCodeSonnet: string;
  claudeCodeOpus: string;
  claudeCodeFable?: string;
  claudeCodeHaiku: string;
  claudeCodeSonnet1m?: string;
  claudeCodeOpus1m?: string;
  easyPaperVlm: string;
}

export interface OverviewStatusMessage {
  backendStatus: BackendStatus;
  claudeCodeCustomized?: boolean;
}

export interface EasyPaperConfigValues {
  llmModelName: string;
  llmApiKey: string;
  llmBaseUrl: string;
  vlmEnabled: boolean;
  vlmModel: string;
  vlmApiKey: string;
  vlmBaseUrl: string;
}
