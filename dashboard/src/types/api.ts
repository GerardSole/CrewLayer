export type AgentStatus = 'idle' | 'working' | 'error'
export type ActionStatus = 'success' | 'error' | 'timeout' | 'pending'
export type MemoryStatus = 'active' | 'archived'
export type Plan = 'free' | 'pro' | 'enterprise'

// ── Agents ───────────────────────────────────────────────────────────────────
export interface Agent {
  id: string
  name: string
  description?: string
  status: AgentStatus
  tags: string[]
  config?: Record<string, unknown>
  tenant_id: string
  current_session_id?: string
  status_updated_at: string
}

// GET /v1/agents returns a plain array
export type AgentList = Agent[]

// ── Memory ───────────────────────────────────────────────────────────────────
export interface Memory {
  id: string
  agent_id: string
  content: string
  summary?: string
  importance: number
  base_importance: number
  tags: string[]
  merged_from?: string[]
  created_at: string
  status: MemoryStatus
  similarity?: number
}

export interface MemoryListResponse {
  items: Memory[]
  total: number
  page: number
  page_size: number
}

export interface RecallResponse {
  query: string
  results: Memory[]
}

export interface MemoryMiniResponse {
  id: string
  content: string
  importance: number
  created_at: string
  access_count: number
}

export interface MemoryStatsResponse {
  total_active: number
  total_archived: number
  avg_importance: number
  oldest_memory?: MemoryMiniResponse
  most_accessed_memory?: MemoryMiniResponse
}

export interface MessageOut {
  role: string
  content: string
  metadata?: Record<string, unknown>
}

export interface ShortMemoryResponse {
  session_id: string
  messages: MessageOut[]
  count: number
}

// ── Actions ──────────────────────────────────────────────────────────────────
export interface Action {
  id: string
  tool_name: string
  input_params: Record<string, unknown>
  output_result: Record<string, unknown>
  status: ActionStatus
  duration_ms?: number
  error_msg?: string
  timestamp: string
  session_id?: string
  agent_id: string
  tenant_id: string
  metadata?: Record<string, unknown>
}

export interface ActionListResponse {
  items: Action[]
  count: number
  next_cursor?: string | null
}

export interface ToolStat {
  tool_name: string
  count: number
  avg_duration_ms?: number
  error_rate: number
}

export interface ActionStatsResponse {
  total_actions: number
  error_rate: number
  avg_duration_ms?: number
  by_tool: ToolStat[]
}

// ── Sessions ─────────────────────────────────────────────────────────────────
export interface Session {
  id: string
  agent_id: string
  tenant_id: string
  episode_id?: string
  status: 'active' | 'closed' | 'archived'
  summary?: string
  message_count: number
  started_at: string
  closed_at?: string
  metadata: Record<string, unknown>
}

// GET /v1/sessions returns a plain array
export type SessionList = Session[]

// ── Context ──────────────────────────────────────────────────────────────────
export interface ContextEntry {
  id: string
  tenant_id: string
  namespace: string
  key: string
  value: Record<string, unknown>
  written_by?: string
  version: number
  expires_at?: string
  created_at: string
  updated_at: string
}

export interface ContextNamespaceResponse {
  namespace: string
  entries: ContextEntry[]
  count: number
}

// ── Webhooks ─────────────────────────────────────────────────────────────────
export interface WebhookEndpoint {
  id: string
  url: string
  events: string[]
  active: boolean
  created_at: string
}

export interface WebhookDelivery {
  id: string
  webhook_id: string
  event: string
  payload: Record<string, unknown>
  status: string
  attempts: number
  last_attempt_at?: string
  response_status?: number
}

export interface DeliveryListResponse {
  items: WebhookDelivery[]
  count: number
}

// GET /v1/webhooks returns a plain array
export type WebhookList = WebhookEndpoint[]

// ── API Keys ─────────────────────────────────────────────────────────────────
export interface ApiKey {
  id: string
  name: string
  scopes: string[]
  agent_ids: string[]
  last_used_at?: string
  expires_at?: string
}

export interface ApiKeyCreated extends ApiKey {
  key: string
}

// GET /v1/api-keys returns a plain array
export type ApiKeyList = ApiKey[]

// ── Audit Log ────────────────────────────────────────────────────────────────
export interface AuditEntry {
  id: string
  tenant_id: string
  api_key_id?: string
  actor_key_name: string
  method: string
  path: string
  resource_type?: string
  resource_id?: string
  ip_address?: string
  status_code: number
  timestamp: string
}

export interface AuditLogResponse {
  items: AuditEntry[]
  next_cursor?: string | null
}

// ── Prompts ──────────────────────────────────────────────────────────────────
export interface PromptVersion {
  id: string
  agent_id: string
  tenant_id: string
  version: number
  content: string
  description?: string
  is_active: boolean
  created_at: string
  created_by?: string
}

export interface PromptVersionListResponse {
  items: PromptVersion[]
  count: number
}

// ── Evaluations ──────────────────────────────────────────────────────────────
export interface DayTrend {
  day: string
  count: number
  avg_score?: number
  thumbs_up: number
  thumbs_down: number
}

export interface EvaluationSummary {
  agent_id: string
  total_evaluations: number
  avg_score?: number
  thumbs_up: number
  thumbs_down: number
  thumbs_up_ratio: number
  trend_7d: DayTrend[]
  by_prompt_version: Array<{
    prompt_version_id?: string
    count: number
    avg_score?: number
    thumbs_up: number
    thumbs_down: number
  }>
}

export interface Anomaly {
  id: string
  agent_id: string
  anomaly_type: string
  severity: 'low' | 'medium' | 'high'
  details: Record<string, unknown>
  resolved: boolean
  created_at: string
}

export interface AnomalyListResponse {
  items: Anomaly[]
  count: number
}

// ── Context history ───────────────────────────────────────────────────────────
export interface ContextHistoryEntry {
  id: string
  namespace: string
  key: string
  value: Record<string, unknown> | null
  version: number
  written_by?: string | null
  operation: string
  timestamp: string
}

export interface ContextHistoryResponse {
  namespace: string
  key: string
  entries: ContextHistoryEntry[]
  next_cursor?: string | null
}

export interface RollbackResponse {
  namespace: string
  key: string
  restored_version: number
  new_version: number
  entry: ContextEntry
}

// ── Episodes ──────────────────────────────────────────────────────────────────
export interface Episode {
  id: string
  tenant_id: string
  agent_id: string
  title: string
  description?: string
  status: 'open' | 'completed'
  summary?: string
  started_at: string
  completed_at?: string
  metadata: Record<string, unknown>
}

export interface EpisodeMemorySummary {
  id: string
  content: string
  importance: number
  created_at: string
}

export interface EpisodeSessionSummary {
  id: string
  status: string
  started_at: string
  closed_at?: string
  message_count: number
}

export interface EpisodeDetail extends Episode {
  sessions: EpisodeSessionSummary[]
  memories: EpisodeMemorySummary[]
}

// ── Agent extras ─────────────────────────────────────────────────────────────
export interface AgentStatusResponse {
  agent_id: string
  status: AgentStatus
  current_session_id?: string | null
  updated_at: string
}

export interface TagCount {
  tag: string
  count: number
}

// ── Replays ──────────────────────────────────────────────────────────────────
export interface Replay {
  id: string
  tenant_id: string
  agent_id: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  from_timestamp: string
  to_timestamp: string
  speed: number
  action_count: number
  created_at: string
  started_at?: string
  completed_at?: string
}

export interface ReplayListResponse {
  items: Replay[]
  count: number
}

// ── Evaluation ────────────────────────────────────────────────────────────────
export interface Evaluation {
  id: string
  tenant_id: string
  agent_id: string
  action_id: string
  session_id?: string
  prompt_version_id?: string
  rating_thumbs?: 'up' | 'down'
  rating_score?: number
  evaluator: string
  notes?: string
  created_at: string
  created_by?: string
}

// ── A/B Tests ────────────────────────────────────────────────────────────────
export type ABTestStatus = 'active' | 'completed' | 'cancelled'
export type ABTestWinner = 'a' | 'b' | 'inconclusive'

export interface ABTest {
  id: string
  tenant_id: string
  agent_id: string
  name: string
  status: ABTestStatus
  variant_a_prompt_version_id: string
  variant_b_prompt_version_id: string
  traffic_split: number
  started_at: string
  completed_at?: string
  winner?: ABTestWinner | null
}

export interface ABTestListResponse {
  items: ABTest[]
  count: number
}

export interface VariantResults {
  variant: string
  prompt_version_id: string
  total_actions: number
  error_rate: number
  avg_score?: number | null
  thumbs_up_ratio: number
}

export interface ABTestResults {
  ab_test_id: string
  name: string
  status: string
  variant_a: VariantResults
  variant_b: VariantResults
}

// ── Prompt Diff ───────────────────────────────────────────────────────────────
export interface DiffLine {
  operation: 'equal' | 'insert' | 'delete'
  content: string
  line_a?: number | null
  line_b?: number | null
}

export interface PromptDiffResponse {
  version_id_a: string
  version_id_b: string
  lines: DiffLine[]
}

// ── Usage ────────────────────────────────────────────────────────────────────
export interface UsageStats {
  requests_today: number
  requests_this_minute: number
  embedding_requests_this_minute: number
}

export interface UsageLimits {
  per_minute?: number | null
  per_day?: number | null
  embedding_per_minute?: number | null
}

export interface UsageResponse {
  tenant_id: string
  plan: string
  usage: UsageStats
  limits: UsageLimits
  timestamp: string
}
