// src/state/types.ts — Core schema and state types for Claude Master Studio

export type ScreenId =
  | "setup"
  | "home"
  | "providers"
  | "models"
  | "routing"
  | "drex"
  | "privacy"
  | "budgets"
  | "brain"
  | "claude_code"
  | "settings"
  | "live_requests"
  | "sessions"
  | "alerts"
  | "doctor"
  | "logs"
  | "detection"
  | "reports"
  | "test_center"
  | "version_update";

export type UserMode = "beginner" | "expert";
export type ThemeMode = "dark" | "light" | "high-contrast";
export type Language = "en" | "ar";
export type DaemonStatus = "connected" | "reconnecting" | "offline";

export type Provenance = "declared" | "measured" | "learned" | "override";

export interface ModelCapability {
  streaming: boolean;
  tool_calling: boolean;
  vision: boolean;
  json_mode: boolean;
  reasoning: boolean;
  context_window: number;
  max_output_tokens: number;
  provenance: Provenance;
}

export interface ModelItem {
  id: string;
  name: string;
  provider: string;
  family: string;
  quality_score: number; // 0-100
  latency_ms: number; // TTFT
  cost_input_1m: number; // $ per 1M input
  cost_output_1m: number; // $ per 1M output
  roles: string[]; // e.g. ["main", "small-fast"]
  capabilities: ModelCapability;
  status: "active" | "pinned" | "banned";
  overridden: boolean;
  force_routed?: boolean;
  force_route_task?: string;
  tokens_per_sec?: number;
  sample_size_n?: number;
  raw_success_count?: number;
  p_value?: number;
  is_statistically_significant?: boolean;
  run_id?: string;
  artifact_url?: string;
  ci_95?: string;
  benchmarks?: Record<string, TaskBenchmark>;
  notes?: string;
}

export interface KeyPoolItem {
  account_label: string;
  env_var: string;
  priority: number;
  masked_key?: string;
  status: "valid" | "degraded" | "invalid" | "cooldown";
  tier: string;
  quota_left_percent: number;
  rate_limit_rpm: number;
  rate_limit_tpm: number;
  errors_count: number;
  daily_spend: number;
  daily_cap: number;
}

export interface ProviderPolicyDetails {
  provider: string;
  display_name: string;
  zero_retention_compliant: boolean;
  policy_tier: "zero_retention" | "internal" | "public_data_only";
  retention_period: string;
  training_policy: string;
  exact_terms: string;
  source_url: string;
  verified_date: string;
  provenance: string;
  conditions?: string;
}

export interface ProviderItem {
  name: string;
  base_url: string;
  privacy_policy: "zero_retention" | "internal" | "public_data_only";
  models: string[];
  key_pools: KeyPoolItem[];
  enabled: boolean;
  pool_strategy: "round_robin" | "least_loaded" | "priority" | "cost_first" | "latency_first" | "sticky";
  region: string;
  tags: string[];
  detected_dialect?: "openai" | "anthropic" | "cohere" | "google" | "mistral";
  policy_info?: ProviderPolicyDetails;
}

export type RoutingPreset = "cheapest" | "fastest" | "most_capable" | "balanced" | "custom";

export interface HardConstraints {
  tool_calling: boolean;
  vision: boolean;
  context_size: number;
  max_cost_1m: number;
}

export interface SoftObjectives {
  quality: number; // 0-100 weight
  ttft: number; // 0-100 weight
  cost: number; // 0-100 weight
  reliability: number; // 0-100 weight
}

export interface RequirementProfile {
  preset: RoutingPreset;
  hard_constraints: HardConstraints;
  soft_objectives: SoftObjectives;
}

export const ROUTING_PRESETS: Record<
  RoutingPreset,
  {
    name: string;
    description: string;
    hard_constraints: HardConstraints;
    soft_objectives: SoftObjectives;
  }
> = {
  cheapest: {
    name: "Cheapest",
    description: "Minimizes cost; routes to low-cost, high-throughput models.",
    hard_constraints: { tool_calling: false, vision: false, context_size: 8192, max_cost_1m: 0.5 },
    soft_objectives: { quality: 30, ttft: 40, cost: 100, reliability: 50 },
  },
  fastest: {
    name: "Fastest",
    description: "Prioritizes minimal time-to-first-token (TTFT) and high streaming speed.",
    hard_constraints: { tool_calling: false, vision: false, context_size: 8192, max_cost_1m: 2.0 },
    soft_objectives: { quality: 35, ttft: 100, cost: 40, reliability: 60 },
  },
  most_capable: {
    name: "Most Capable",
    description: "Highest agentic capability, reasoning, and tool calling regardless of cost.",
    hard_constraints: { tool_calling: true, vision: false, context_size: 32768, max_cost_1m: 20.0 },
    soft_objectives: { quality: 100, ttft: 30, cost: 15, reliability: 95 },
  },
  balanced: {
    name: "Balanced",
    description: "Smart compromise between quality, responsiveness, cost, and stability.",
    hard_constraints: { tool_calling: true, vision: false, context_size: 16384, max_cost_1m: 5.0 },
    soft_objectives: { quality: 75, ttft: 65, cost: 60, reliability: 80 },
  },
  custom: {
    name: "Custom",
    description: "Custom user-defined constraints and objective weights.",
    hard_constraints: { tool_calling: false, vision: false, context_size: 16384, max_cost_1m: 10.0 },
    soft_objectives: { quality: 50, ttft: 50, cost: 50, reliability: 50 },
  },
};

export interface RoutingRoleMapping {
  role: "main" | "small-fast" | "subagent" | "summarizer" | "vision";
  model_id: string;
  fallback_model_id: string;
  description: string;
  profile?: RequirementProfile;
}

export interface RoutingRule {
  id: string;
  name: string;
  condition: string; // e.g. "task == 'coding' and tokens < 2000"
  target_model: string;
  enabled: boolean;
}

export interface RoutingSimulateRequest {
  task: string;
  prompt: string;
  role?: string;
  prompt_tokens?: number;
  requires_tool_calling?: boolean;
  requires_vision?: boolean;
  budget_cap?: number;
}

export interface RoutingSimulateResult {
  resolved_role: string;
  selected_model: string;
  selected_provider: string;
  selection_reason: string;
  estimated_cost_usd: number;
  fallback_chain: string[];
  utility_scores?: {
    quality: number;
    ttft: number;
    cost: number;
    reliability: number;
    total: number;
  };
  constraints_passed?: {
    tool_calling: boolean;
    vision: boolean;
    context_size: boolean;
    budget: boolean;
  };
}

export type TaskType = "coding" | "tool_calling" | "reasoning" | "vision" | "arabic" | "english";

export interface TaskBenchmark {
  task_type: TaskType;
  score: number; // 0 - 100
  sample_size_n: number;
  passed_count?: number; // S in S/N
  ci_95_low: number;
  ci_95_high: number;
  measured_ttft_ms: number;
  tokens_per_sec: number;
  provenance: Provenance;
  p_value?: number;
  is_significant?: boolean;
  run_id?: string;
  artifact_url?: string;
}

export interface HyperparameterItem {
  name?: string;
  value: number;
  type?: "float" | "int" | "str";
  range?: [number, number];
  description: string;
  provenance: string;
  source?: string;
  calibration_status?: string;
  last_calibrated_at?: number | null;
}

export interface ExplorationCandidate {
  model_id: string;
  name: string;
  provider: string;
  status: "probing" | "evaluating" | "promoted" | "cooldown";
  probes_count: number;
  target_probes: number;
  mean_reward: number; // 0.0 - 1.0
  ci_95: string;
  target_tasks: TaskType[];
}

export interface DrexDecisionTrace {
  id: string;
  timestamp: number;
  prompt_summary: string;
  task_type: TaskType;
  drex_recommendation: {
    model_id: string;
    model_name: string;
    confidence: number;
    reason: string;
  };
  utility_recommendation: {
    model_id: string;
    model_name: string;
    utility_score: number;
    quality_component: number;
    ttft_component: number;
    cost_component: number;
    reliability_component: number;
  };
  status: "consensus" | "divergence";
  divergence_note?: string;
  final_winner: string;
  is_exploration: boolean;
  latency_ms: number;
  outcome: "accepted" | "rejected" | "fallback";
}

export interface DrexConfigState {
  enabled: boolean;
  base_url: string;
  model: string;
  api_key_masked: string;
  timeout_ms: number;
  cache_ttl_s: number;
  daily_budget_cap: number;
  daily_spend: number;
  degraded_mode: "fail_open" | "fail_closed";
  exploration_budget: number; // 0.0 - 0.25 (e.g. 0.05 for 5%)
  toggles: {
    routing: boolean;
    guard: boolean;
    judge: boolean;
    learning: boolean;
    sleep: boolean;
    watchdog: boolean;
  };
  confidence_thresholds: {
    routing: number;
    guard: number;
    judge: number;
  };
  exploration_candidates?: ExplorationCandidate[];
  traces?: DrexDecisionTrace[];
}

export interface DrexDecisionLog {
  id: string;
  timestamp: number;
  decision_type: "routing" | "guard" | "judge";
  prompt_summary: string;
  chosen_action: string;
  confidence: number;
  latency_ms: number;
  outcome: "accepted" | "rejected" | "fallback";
}

export interface PrivacyRedactionRule {
  id: string;
  name: string;
  pattern_type: "api_key" | "jwt" | "email" | "ip" | "credit_card" | "custom";
  description: string;
  enabled: boolean;
}

export interface GuardRule {
  id: string;
  pattern: string; // e.g. "rm -rf", "git push --force", ".env"
  action: "allow" | "ask" | "deny";
  description: string;
}

export interface SpendMetrics {
  daily_spent: number;
  daily_cap: number;
  monthly_spent: number;
  monthly_cap: number;
  cache_savings_usd: number;
  total_requests: number;
  error_rate: number;
  cache_hit_rate: number;
  projected_month_end_usd: number;
}

export interface SystemAlert {
  id: string;
  timestamp: number;
  level: "info" | "warning" | "error" | "critical";
  title: string;
  message: string;
  source: string;
  fix_action?: string;
  snoozed_until?: number;
  acknowledged: boolean;
}

export interface LiveRequestEvent {
  id: string;
  timestamp: number;
  session_id: string;
  provider: string;
  model: string;
  prompt_snippet: string;
  status_code: number;
  total_tokens: number;
  prompt_tokens: number;
  completion_tokens: number;
  cost_usd: number;
  cached: boolean;
  duration_ms: number;
  timeline: {
    step: string;
    duration_ms: number;
    status: "ok" | "warn" | "fail";
    detail: string;
  }[];
  explanation: string;
}

export interface ClaudeSession {
  id: string;
  started_at: number;
  title: string;
  duration_s: number;
  request_count: number;
  models_used: string[];
  total_cost_usd: number;
  outcome: "success" | "interrupted" | "error";
  failovers: number;
}

export interface DoctorCheckResult {
  id: string;
  title: string;
  passed: boolean;
  severity: "critical" | "warning" | "info";
  detail: string;
  fix_command: string;
  fix_action_label: string;
}

export interface DetectionEvent {
  id: string;
  timestamp: number;
  provider: string;
  model: string;
  change_type: "added" | "updated" | "deprecated";
  details: string;
  diff: { before: string; after: string };
}

export interface TestCaseResult {
  id: string;
  scenario: string;
  category: "smoke" | "tools" | "coding" | "reasoning" | "vision";
  model: string;
  passed: boolean;
  latency_ms: number;
  cost_usd: number;
  log?: string;
}

export interface RouteCooldownEntry {
  key_hash: string;
  model: string;
  status: string;
  state: "rate_limited" | "exhausted" | "dead" | "restricted" | "probing" | "active" | string;
  cooldown_until: string;
  backoff_s: number;
  remaining_s: number;
  duration_ms: number;
  learned_backoff_ms: number;
  failure_count: number;
  provenance: "retry_after_header" | "adaptive_backoff" | "probe_recovery" | "status_code_default" | string;
  last_tested_at: string;
}

