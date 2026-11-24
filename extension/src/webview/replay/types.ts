/**
 * Type definitions for the Replay Webview
 */

/** VSCode API type */
export interface VSCodeAPI {
  postMessage: (message: any) => void;
  getState: () => any;
  setState: (state: any) => void;
}

/** Agent profile information */
export interface AgentProfile {
  id: number;
  name: string;
  profile: Record<string, any>;
}

/** Timeline point */
export interface TimelinePoint {
  step: number;
  t: string;
}

/** Experiment information */
export interface ExperimentInfo {
  hypothesis_id: string;
  experiment_id: string;
  total_steps: number;
  start_time: string | null;
  end_time: string | null;
  agent_count: number;
  run_status?: string | null;
  pid_step_count?: number | null;
  simulation_time?: string | null;
  registered_datasets?: number;
  nonempty_snapshot_tables?: number;
}

/** Playback state */
export interface PlaybackState {
  isPlaying: boolean;
  speed: number;
  currentStep: number;
}

/** Layout mode for agent visualization */
export type LayoutMode = 'map' | 'random';

export interface ReplayDatasetColumn {
  column_name: string;
  sqlite_type: string;
  logical_type?: string | null;
  analysis_role?: string | null;
  title?: string | null;
  description?: string | null;
  unit?: string | null;
  nullable: boolean;
  enum_values?: any;
  example?: any;
  tags: string[];
}

export interface ReplayDatasetInfo {
  dataset_id: string;
  table_name: string;
  module_name: string;
  kind: string;
  title: string;
  description: string;
  entity_key?: string | null;
  step_key?: string | null;
  time_key?: string | null;
  default_order: string[];
  capabilities: string[];
  version: number;
  created_at: string;
  columns: ReplayDatasetColumn[];
}

export interface ReplayDatasetRows {
  dataset_id: string;
  columns: string[];
  rows: Record<string, any>[];
  total: number;
}

export interface ReplayDatasetPanelRef {
  dataset_id: string;
  module_name: string;
  title: string;
}

export interface ReplayPanelSchema {
  agent_profile_dataset?: ReplayDatasetInfo | null;
  agent_state_datasets: ReplayDatasetInfo[];
  env_state_datasets: ReplayDatasetInfo[];
  geo_dataset?: ReplayDatasetInfo | null;
  primary_agent_state_dataset_id?: string | null;
  layout_hint: LayoutMode;
  supports_map: boolean;
}

export interface ReplayPosition {
  agent_id: number;
  lng: number | null;
  lat: number | null;
}

export interface ReplayAgentStateAtStep {
  dataset: ReplayDatasetPanelRef;
  rows_by_agent_id: Record<string, Record<string, any>>;
}

export interface ReplayEnvStateAtStep {
  dataset: ReplayDatasetPanelRef;
  row: Record<string, any> | null;
}

export interface ReplayStepBundle {
  step: number;
  t?: string | null;
  layout_hint: LayoutMode;
  positions: ReplayPosition[];
  agent_state_rows: Record<string, ReplayAgentStateAtStep>;
  env_state_rows: Record<string, ReplayEnvStateAtStep>;
}

/** Message types from extension to webview */
export type ExtensionMessage =
  | { type: 'init'; data: InitData }
  | { type: 'experimentInfo'; data: ExperimentInfo }
  | { type: 'timeline'; data: TimelinePoint[] }
  | { type: 'agentProfiles'; data: AgentProfile[] }
  | { type: 'panelSchema'; data: ReplayPanelSchema }
  | { type: 'stepBundle'; data: ReplayStepBundle }
  | { type: 'replayDatasetRows'; data: ReplayDatasetRows; requestKey?: string }
  | { type: 'error'; message: string };

/** Initial data from extension */
export interface InitData {
  workspacePath: string;
  hypothesisId: string;
  experimentId: string;
}

/** Message types from webview to extension */
export type WebviewMessage =
  | { command: 'ready' }
  | { command: 'fetchExperimentInfo' }
  | { command: 'fetchTimeline' }
  | { command: 'fetchAgentProfiles' }
  | { command: 'fetchPanelSchema' }
  | { command: 'fetchStepBundle'; step: number }
  | { command: 'fetchReplayDatasetRows'; datasetId: string; requestKey?: string; page?: number; pageSize?: number; step?: number; entityId?: number; startStep?: number; endStep?: number; maxStep?: number; columns?: string[]; descOrder?: boolean; latestPerEntity?: boolean }
  | { command: 'error'; message: string };
