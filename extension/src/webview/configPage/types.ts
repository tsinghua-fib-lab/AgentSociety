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
  // LLM 默认配置
  llmApiBase: string;
  llmModel: string;
  // 可选
  backendLogLevel: string;
  coderLlmApiKey: string;
  coderLlmApiBase: string;
  coderLlmModel: string;
  nanoLlmApiKey: string;
  nanoLlmApiBase: string;
  nanoLlmModel: string;
  // Analysis LLM (for data analysis, insight generation, and report writing)
  analysisLlmApiKey: string;
  analysisLlmApiBase: string;
  analysisLlmModel: string;
  // Embedding
  embeddingApiKey: string;
  embeddingApiBase: string;
  embeddingModel: string;
  embeddingDims: number;
  // Web Search
  webSearchApiUrl: string;
  webSearchApiToken: string;
  miroflowDefaultLlm: string;
  miroflowDefaultAgent: string;
  // EasyPaper (optional, for generate_paper tool)
  easypaperApiUrl: string;
  easypaperLlmApiKey: string;
  easypaperLlmModel: string;
  easypaperVlmModel: string;
  easypaperVlmApiKey: string;
  // Literature Search (optional, for search_literature tool)
  literatureSearchApiUrl: string;
  literatureSearchApiKey: string;
}

export interface WorkspaceInfo {
  hasWorkspace: boolean;
  workspacePath?: string;
}

export interface BackendStatus {
  isRunning: boolean;
  port?: number;
  url?: string;
}
