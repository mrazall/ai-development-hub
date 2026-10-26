// Shapes of control-plane API responses (packages/contracts, API v0).

export type Project = {
  id: string;
  name: string;
  visibility: 'private' | 'shared' | 'public';
  repo_url?: string | null;
  allowed_paths?: string[];
  allowed_commands?: string[];
};

export const taskStatuses = ['draft', 'ready', 'in_progress', 'review', 'done', 'cancelled'] as const;
export type TaskStatus = (typeof taskStatuses)[number];

export type Task = {
  id: string;
  project_id: string;
  title: string;
  body: string;
  status: TaskStatus;
  created_at: string;
  updated_at: string;
};

export type Worker = {
  id: string;
  host: string;
  kind: 'local' | 'ssh' | 'codeman';
  status: 'online' | 'offline' | 'draining';
  labels: string[];
  last_heartbeat_at: string | null;
  lease_ttl_s: number;
  worker_token?: string | null;
};

export const sessionStatuses = [
  'queued',
  'starting',
  'running',
  'waiting_approval',
  'blocked',
  'offline',
  'failed',
  'completed',
] as const;

export type Session = {
  id: string;
  task_id: string | null;
  project_id: string;
  worker_id: string;
  permission_mode?: string;
  engine: string;
  provider: string;
  model: string;
  auth_mode: string;
  workdir: string;
  branch: string | null;
  status: (typeof sessionStatuses)[number];
  status_source: 'native' | 'cli_parser' | 'heartbeat';
  external_ref: string | null;
  created_at: string;
  updated_at: string;
  parent_session_id?: string | null;
  account_profile_id?: string | null;
  workspace_ref?: string | null;
  title?: string | null;
  role?: 'orchestrator' | 'executor' | null;
  /** Set while the hub waits for a provider limit to reset before continuing the session. */
  resume_at?: string | null;
  orchestration?: {
    max_executors?: number;
    executor_account_profile_id?: string;
    executor_model?: string;
    base_branch?: string;
  } | null;
};

export type Executor = {
  id: string;
  title: string;
  status: string;
  branch: string | null;
  workdir: string | null;
  last_message?: string | null;
  changed_files?: string[];
  started_at?: string | null;
  finished_at?: string | null;
  merge?: { state: string; summary?: string; error?: string; reason?: string; head?: string } | null;
};

export type Usage = {
  input_tokens: number;
  cached_input_tokens: number;
  output_tokens: number;
  cost_usd: number | null;
};
export type AccountUsage = {
  id: string;
  name: string;
  windows: { kind: string; used_percent: number; resets_at: number | null }[];
} | null;
export type PlanStep = {
  title: string;
  status: 'pending' | 'in_progress' | 'done' | 'blocked';
  executor_id?: string | null;
};
export type OrchestrationView = {
  plan: PlanStep[];
  plan_updated_at: string | null;
  manual_merge: boolean;
  max_executors: number | null;
  base_branch: string | null;
  orchestrator: { usage: Usage; account: AccountUsage };
  executors: (Executor & { usage: Usage; account: AccountUsage })[];
};

export type WorkerDetails = Worker & {
  workspace_url?: string | null;
  capabilities?: Record<string, string>;
};

export type GraphNode = {
  id: string;
  type: 'session' | 'task' | string;
  engine?: string | null;
  model?: string | null;
  account_profile_id?: string | null;
  worker_id?: string | null;
  task_id?: string | null;
  title?: string | null;
  status?: string | null;
  started_at?: string | null;
  updated_at?: string | null;
  duration_s?: number | null;
  latest_event?: { kind?: string; ts?: string } | null;
};
export type GraphEdge = { from: string; to: string; type?: string };
export type AgentGraph = { nodes: GraphNode[]; edges: GraphEdge[] };

export type AccountProfile = {
  id: string;
  name: string;
  kind: string;
  worker_id: string;
  config_dir?: string | null;
  base_url?: string | null;
  secret_ref?: string | null;
  secret_fingerprint?: string | null;
  default_model?: string | null;
  models: string[];
  status: string;
  status_detail?: string | null;
  checked_at?: string | null;
  created_at?: string;
  updated_at?: string;
};

export type McpServer = {
  id: string;
  name: string;
  source: string;
  version: string;
  license: string;
  transport: 'stdio' | 'http';
  command: string[];
  url?: string | null;
  scopes: string[];
  project_ids: string[];
  enabled: boolean;
  status: string;
  status_detail?: string | null;
  tools: string[];
};

export type SessionEvent = {
  cursor: number;
  session_id: string;
  kind: string;
  source: string;
  ts: string;
  payload: Record<string, unknown>;
  redacted?: boolean;
};

export type Notification = {
  id: string;
  category: string;
  severity: 'info' | 'warning' | 'critical';
  title: string;
  body: string;
  project_id?: string | null;
  session_id?: string | null;
  link?: string | null;
  created_at: string;
  read_at?: string | null;
};

export type ChatMessage = {
  id?: string;
  role: 'user' | 'assistant' | 'tool' | 'system';
  text: string;
  created_at?: string;
  partial?: boolean;
  tool_name?: string;
  tool_summary?: string;
};

export type Chat = {
  id: string;
  title: string;
  pinned: boolean;
  archived?: boolean;
  session_id?: string | null;
  model?: string | null;
  account_profile_id?: string | null;
  effort?: string | null;
  updated_at: string;
  created_at?: string;
  first_message?: string | null;
  messages?: ChatMessage[];
  context?: { used: number; limit: number } | null;
  status?: string | null;
};

export type Approval = {
  id: string;
  action: string;
  summary: string;
  risk: string;
  status: 'pending' | 'approved' | 'rejected' | 'expired';
  session_id?: string | null;
  created_at?: string;
};

export type SearchHit = {
  doc_id: string;
  path: string;
  title: string;
  heading: string | null;
  excerpt: string;
  line_start: number;
  line_end: number;
  project_id: string | null;
  updated_at: string;
  score: number;
  match: 'lexical' | 'vector' | 'hybrid';
};

export type SearchResponse = { hits: SearchHit[]; degraded?: string[] };

export type KnowledgeGraphNode = {
  id: string;
  title: string;
  path: string | null;
  project_id: string | null;
  degree: number;
  ghost: boolean;
  type?: string;
};

export type KnowledgeGraphEdge = { source: string; target: string; type?: 'wiki' | 'embed' | 'markdown' | string };
export type KnowledgeGraphResponse = { nodes: KnowledgeGraphNode[]; edges: KnowledgeGraphEdge[] };
