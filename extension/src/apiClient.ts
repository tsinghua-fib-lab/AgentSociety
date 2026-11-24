/**
 * API客户端 - 用于与FastAPI后端通信
 *
 * 关联文件：
 * - @extension/src/extension.ts - 主入口，创建ApiClient实例并传递给各组件
 * - @extension/src/prefillParamsViewProvider.ts - 使用ApiClient获取预填充参数
 * - @extension/src/projectStructureProvider.ts - 使用ApiClient进行项目初始化、模块扫描
 * - @extension/src/services/backendService.ts - AS2 请求与鉴权
 *
 * 后端API路由：
 * - @packages/agentsociety2/agentsociety2/backend/routers/prefill_params.py - /api/v1/prefill-params
 * - @packages/agentsociety2/agentsociety2/backend/routers/experiments.py - /api/v1/experiments
 * - @packages/agentsociety2/agentsociety2/backend/routers/replay.py - /api/v1/replay
 * - @packages/agentsociety2/agentsociety2/backend/routers/custom.py - /api/v1/custom
 * - @packages/agentsociety2/agentsociety2/backend/routers/modules.py - /api/v1/modules
 */

import type { BackendService } from './services/backendService';

/**
 * API客户端 - 用于与FastAPI后端通信
 */

/**
 * SSE事件类型
 */
export type SSEEventType = 'message' | 'tool' | 'complete' | 'heartbeat';

/**
 * SSE消息事件（MessageEvent）
 * 完全匹配后端 sse/models.py 中的 MessageEvent
 */
export interface MessageSSEEvent {
  type: 'message';
  content: string;
  is_thinking: boolean;
  is_error: boolean;
}

/**
 * SSE工具事件（ToolEvent）
 * 完全匹配后端 sse/models.py 中的 ToolEvent
 */
export interface ToolSSEEvent {
  type: 'tool';
  content: string;
  tool_name: string;
  tool_id: string;
  status: 'start' | 'progress' | 'success' | 'error';
}

/**
 * SSE完成事件（CompleteEvent）
 * 完全匹配后端 sse/models.py 中的 CompleteEvent
 */
export interface CompleteSSEEvent {
  type: 'complete';
  content: string;
}

/**
 * SSE心跳事件（HeartbeatEvent）
 * 完全匹配后端 sse/models.py 中的 HeartbeatEvent
 * 前端应该直接丢弃此事件，仅用于保持连接活跃
 */
export interface HeartbeatSSEEvent {
  type: 'heartbeat';
  content: string;
}

/**
 * SSE事件联合类型
 */
export type SSEEvent = MessageSSEEvent | ToolSSEEvent | CompleteSSEEvent | HeartbeatSSEEvent;

export interface AgentInfo {
  type: string;
  class_name: string;
  description: string;
  is_custom?: boolean;
}

export interface EnvModuleInfo {
  type: string;
  class_name: string;
  description: string;
  is_custom?: boolean;
}

export interface AgentsListResponse {
  success: boolean;
  agents: Record<string, AgentInfo>;
  count: number;
}

export interface EnvModulesListResponse {
  success: boolean;
  modules: Record<string, EnvModuleInfo>;
  count: number;
}

export interface PrefillParams {
  version?: string;
  env_modules: Record<string, Record<string, any>>;
  agents: Record<string, Record<string, any>>;
}

export interface PrefillParamsResponse {
  success: boolean;
  data: PrefillParams;
}

export interface ClassInfo {
  type: string;
  class_name: string;
  description: string;
  has_prefill?: boolean;
  is_custom?: boolean;
}

export interface AvailableClassesResponse {
  success: boolean;
  env_modules: Record<string, ClassInfo>;
  agents: Record<string, ClassInfo>;
  env_module_count: number;
  agent_count: number;
}

// ========== Custom Module API Interfaces ==========

export interface CustomModulesScanRequest {
  workspace_path?: string;
}

export interface CustomModulesTestRequest {
  workspace_path?: string;
  module_kind?: 'agent' | 'env_module';
  module_class_name?: string;
}

export interface CustomModulesScanResponse {
  success: boolean;
  agents_found: number;
  envs_found: number;
  agents_generated: number;
  envs_generated: number;
  errors: string[];
  message?: string;
}

export interface ModuleTestResult {
  name: string;
  success: boolean;
  output: string;
  error?: string;
}

export interface CustomModulesTestResponse {
  success: boolean;
  test_output: string;
  error?: string;
  returncode?: number;
  // 结构化测试结果
  results?: ModuleTestResult[];
  total_tests?: number;
  passed_tests?: number;
  failed_tests?: number;
}

export interface CustomModulesListResponse {
  success: boolean;
  agents: Array<{
    type: string;
    class_name: string;
    description: string;
    is_custom: boolean;
    module_path: string;
    file_path: string;
  }>;
  envs: Array<{
    type: string;
    class_name: string;
    description: string;
    is_custom: boolean;
    module_path: string;
    file_path: string;
  }>;
  total_agents: number;
  total_envs: number;
}

export interface CustomModulesStatusResponse {
  custom_dir_exists: boolean;
  agents_dir_exists: boolean;
  envs_dir_exists: boolean;
  agent_files_count: number;
  env_files_count: number;
  registered_agents: number;
  registered_envs: number;
}

// ── Agent Skills 接口 ──

export interface AgentSkillItem {
  skill_id: string;
  name: string;
  description: string;
  /** Registry source: `built-in` | `custom` | `env`. */
  source: string;
  source_label?: string;
  path: string;
  has_skill_md: boolean;
  script: string;
}

export interface AgentSkillsListResponse {
  success: boolean;
  skills: AgentSkillItem[];
  total: number;
}

export interface AgentSkillsSimpleResponse {
  success: boolean;
  message: string;
}

export interface AgentSkillsScanResponse {
  success: boolean;
  new_skills: string[];
  total: number;
  message: string;
}

export interface AgentSkillInfoResponse {
  success: boolean;
  skill_id: string;
  name: string;
  description: string;
  source: string;
  path: string;
  script: string;
  skill_md: string;
}

export class ApiClient {
  constructor(private readonly backend: BackendService) {}

  getAgentClasses(): Promise<AgentsListResponse> {
    return this.backend.requestJson('/api/v1/modules/agent_classes');
  }

  getEnvModules(): Promise<EnvModulesListResponse> {
    return this.backend.requestJson('/api/v1/modules/env_module_classes');
  }

  getPrefillParams(workspace_path: string): Promise<PrefillParamsResponse> {
    const query = new URLSearchParams({ workspace_path });
    return this.backend.requestJson(`/api/v1/prefill-params?${query}`);
  }

  getAvailableClasses(workspace_path: string): Promise<AvailableClassesResponse> {
    const query = new URLSearchParams({ workspace_path });
    return this.backend.requestJson(`/api/v1/custom/classes?${query}`);
  }

  scanCustomModules(request: CustomModulesScanRequest): Promise<CustomModulesScanResponse> {
    return this.backend.requestJson('/api/v1/custom/scan', { body: request });
  }

  testCustomModules(request: CustomModulesTestRequest): Promise<CustomModulesTestResponse> {
    return this.backend.requestJson('/api/v1/custom/test', { body: request });
  }

  listCustomModules(): Promise<CustomModulesListResponse> {
    return this.backend.requestJson('/api/v1/custom/list');
  }

  getCustomModulesStatus(): Promise<CustomModulesStatusResponse> {
    return this.backend.requestJson('/api/v1/custom/status');
  }

  listAgentSkills(): Promise<AgentSkillsListResponse> {
    return this.backend.requestJson('/api/v1/agent-skills/list');
  }

  scanAgentSkills(workspace_path?: string): Promise<AgentSkillsScanResponse> {
    return this.backend.requestJson('/api/v1/agent-skills/scan', { body: { workspace_path } });
  }

  importAgentSkill(source_path: string, workspace_path?: string): Promise<AgentSkillsSimpleResponse> {
    return this.backend.requestJson('/api/v1/agent-skills/import', { body: { source_path, workspace_path } });
  }

  getAgentSkillInfo(skillId: string): Promise<AgentSkillInfoResponse> {
    return this.backend.requestJson(`/api/v1/agent-skills/${encodeURIComponent(skillId)}/info`);
  }
}
