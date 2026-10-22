export type Kind = "postgresql" | "mysql" | "duckdb" | "sqlite" | "mongodb" | "csv";

export interface Table {
  columns: string[];
  rows: unknown[][];
}

export interface EndpointSpec {
  kind: Kind;
  config: Record<string, string | number>;
  table?: string | null;
}

export interface Preset {
  id: string;
  label: string;
  csv: string;
  target: string;
  normalize_column: string;
  lookup_table: string;
  blurb: string;
  rows: number | null;
  defect_total: number;
  defects: { defect: string; count: number; example: string }[];
}

export interface SystemInfo {
  kind: Kind;
  label: string;
  source: boolean;
  target: boolean;
  defaults: Record<string, string | number>;
  target_defaults?: Record<string, string>;
  password_set: boolean;
}

export interface AppConfig {
  presets: Preset[];
  systems: SystemInfo[];
  ai: { providers: { name: string; models: string[]; default_model: string; server_key: boolean }[] };
}

export interface Health {
  systems: Record<string, { ok: boolean; detail: string }>;
  ai: Record<string, boolean>;
}

export interface Check {
  check: string;
  sql: string;
  expected: unknown;
  actual: unknown;
  passed: boolean;
}

export interface LogEntry {
  column: string;
  action: string;
  detail: string;
  rows_affected: number;
}

export interface MigrationResult {
  status: "success" | "verification_failed" | "error";
  message: string;
  result_id: string;
  run_id: number;
  mode: "flat" | "normalized";
  source_system: string;
  target_system: string;
  target_kind: Kind;
  source_location: string;
  target_location: string;
  source_table: string;
  target_table: string;
  lookup_table: string | null;
  normalize_column: string | null;
  dependents: string[];
  stats: { source_rows: number; loaded_rows: number; exact_duplicates_removed: number; quarantined_rows: number; null_cells_before: number; null_cells_after: number };
  transformation_log: LogEntry[];
  quarantine: Table;
  source_preview: Table;
  target_preview: Table;
  type_mapping: Table;
  ddl: Record<string, string>;
  explain: { before?: Record<string, unknown>[]; after?: Record<string, unknown>[]; query?: string; note?: string };
  protocol: string;
  checks: Check[];
  target_info: Record<string, { ddl: string; ddl_source: string; columns: Table; constraints: Table }>;
  history: Table;
  timings: Record<string, number>;
  queries: { name: string; text: string }[];
}

export interface DslStep {
  action: string;
  column?: string | null;
  confidence?: number;
  [k: string]: unknown;
}

export interface AgentState {
  profile?: { row_count?: number; column_count?: number; duplicate_rows?: number; data_quality_score?: number; columns?: Record<string, any> };
  assessment?: { dataset_assessment?: string; identified_issues?: string[]; schema_mapping_recommendations?: string[] };
  transformation_dsl?: {
    transformations?: DslStep[];
    reasoning?: { reason?: string }[];
    fallback_reason?: string;
    planning_method?: string;
    _metadata?: { provider_used?: string; model_used?: string; fallback_chain?: string[]; fallback_used?: boolean };
  };
  preview?: { samples?: Record<string, unknown>[] }[];
  preview_impact?: Record<string, number>;
  risk?: { overall_confidence?: number; high_risk?: string[]; medium_risk?: string[]; low_risk?: string[] };
  executed_steps?: string[];
  timings?: Record<string, number>;
  reconciliation?: { overall_success?: boolean; rows_read?: number; rows_written?: number; rows_skipped?: number; [k: string]: unknown };
  report?: Record<string, any>;
  execution_log?: { action: string; status: string; details?: any; reason?: string }[];
  quarantine_report?: { column: string; action: string; rows_affected: number; sample_indices?: number[] }[];
  execution_impact?: Record<string, number>;
  provider_used?: string;
  model_used?: string;
  fallback_used?: boolean;
  raw_prompt?: string;
  raw_ai_response?: string;
  success?: boolean;
  source_type?: string;
  target_type?: string;
  table_name?: string;
  database_download?: boolean;
}

export interface AgentView {
  thread_id: string;
  status: "paused" | "finished" | "running";
  next: string[];
  state: AgentState;
}
