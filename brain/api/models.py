"""brain/api/models.py — Pydantic models and schemas for claude-master Backend API.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# General / Status / Bypass
# ---------------------------------------------------------------------------

class ProcessStatus(BaseModel):
    name: str
    status: str  # "running" | "stopped" | "unhealthy"
    pid: Optional[int] = None
    uptime_s: Optional[float] = None
    memory_mb: Optional[float] = None
    cpu_percent: Optional[float] = None
    listen_port: Optional[int] = None


class SystemStatusResponse(BaseModel):
    daemon: ProcessStatus
    gateway: ProcessStatus
    watchdog: ProcessStatus
    brain: Dict[str, Any]
    spend: Dict[str, Any]
    error_rates: Dict[str, float]
    active_sessions: List[str]
    bypass_state: Dict[str, Any]
    attention_list: List[Dict[str, str]]


class BypassStateResponse(BaseModel):
    enabled: bool
    active_since: Optional[int] = None
    reason: str = ""


class BypassToggleRequest(BaseModel):
    enabled: bool
    reason: str = ""


class ControlRequest(BaseModel):
    action: Optional[str] = None  # "start" | "stop" | "restart"
    component: str = "all"  # "all" | "gateway" | "brain" | "watchdog"


class ControlResponse(BaseModel):
    ok: bool
    message: str
    affected: List[str]


# ---------------------------------------------------------------------------
# Dynamic UI Schema
# ---------------------------------------------------------------------------

class DialectSchema(BaseModel):
    id: str
    name: str
    endpoint_suffix: str
    auth_header_format: str
    supports_streaming: bool
    supports_tools: bool
    supports_vision: bool


class PresetModeSchema(BaseModel):
    id: str
    name: str
    description: str
    routing_strategy: str
    default_role_mapping: Dict[str, str]


class DynamicSchemaResponse(BaseModel):
    dialects: List[DialectSchema]
    preset_modes: List[PresetModeSchema]
    privacy_policies: List[Dict[str, str]]
    roles: List[str]
    config_fields: Dict[str, Any]


# ---------------------------------------------------------------------------
# Wizard
# ---------------------------------------------------------------------------

class EnvCheckItem(BaseModel):
    check_id: str
    category: str
    title: str
    status: str  # "pass" | "warn" | "fail"
    details: str
    recommendation: str = ""
    fix_action_available: bool = False
    fix_action_id: Optional[str] = None


class EnvCheckResponse(BaseModel):
    system_info: Dict[str, Any]
    checks: List[EnvCheckItem]
    overall_status: str


class ImportEnvRequest(BaseModel):
    file_path: Optional[str] = None
    env_content: Optional[str] = None
    apply: bool = False


class DiscoveredKey(BaseModel):
    env_var: str
    provider: str
    masked_key: str
    already_configured: bool


class ImportEnvResponse(BaseModel):
    discovered: List[DiscoveredKey]
    applied: bool
    imported_count: int


class WizardFixRequest(BaseModel):
    action_id: str
    params: Dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Providers & Keys
# ---------------------------------------------------------------------------

class KeyPoolItem(BaseModel):
    account_label: str = "personal"
    env_var: str
    priority: int = 10
    key_masked: Optional[str] = None
    is_active: bool = True
    cooldown_until: Optional[int] = None
    failure_count: int = 0
    budget_usd: Optional[float] = None
    tags: List[str] = Field(default_factory=list)

class KeyItem(BaseModel):
    key_hash: str
    provider: str
    account_label: str = "personal"
    env_var: str
    key_masked: str
    is_active: bool = True
    cooldown_until: Optional[int] = None
    failure_count: int = 0
    budget_usd: Optional[float] = None
    tags: List[str] = Field(default_factory=list)


class ProviderConfig(BaseModel):
    name: str
    base_url: str
    privacy_policy: str = "zero_retention"
    adapter: Optional[Dict[str, Any]] = None
    models: List[str] = Field(default_factory=list)
    key_pools: List[KeyPoolItem] = Field(default_factory=list)


class ProviderAddRequest(BaseModel):
    name: str
    base_url: str
    privacy_policy: str = "zero_retention"
    models: List[str] = Field(default_factory=list)
    key_pools: List[KeyPoolItem] = Field(default_factory=list)


class ProviderUpdateRequest(BaseModel):
    base_url: Optional[str] = None
    privacy_policy: Optional[str] = None
    models: Optional[List[str]] = None
    key_pools: Optional[List[KeyPoolItem]] = None


class ProviderTestRequest(BaseModel):
    provider: str
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    model: Optional[str] = None


class ProviderTestResponse(BaseModel):
    ok: bool
    provider: str
    detected_dialect: str
    latency_ms: float
    models: List[str]
    capabilities: Dict[str, bool]
    cost_estimate_probe_usd: float
    message: str


class KeyAddRequest(BaseModel):
    provider: str
    account_label: str = "personal"
    env_var: str
    key: str  # plaintext write-only
    priority: int = 10
    models: List[str] = Field(default_factory=list)
    budget_usd: Optional[float] = None
    tags: List[str] = Field(default_factory=list)


class KeyRotateRequest(BaseModel):
    provider: str
    env_var: str
    new_key: str


class KeyRevealRequest(BaseModel):
    provider: str
    account_label: str
    confirm: bool


class KeyRevealResponse(BaseModel):
    provider: str
    account_label: str
    plaintext_key: str


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class ModelInfo(BaseModel):
    model_id: str
    provider: str
    capabilities: Dict[str, bool]
    context_window: int = 128000
    pricing: Dict[str, float] = Field(default_factory=dict)
    successes: int = 0
    failures: int = 0
    latency_p50_ms: float = 0.0
    is_pinned: bool = False
    is_banned: bool = False


class ModelPinBanRequest(BaseModel):
    models: List[str]


class ModelOverrideRequest(BaseModel):
    model_id: str
    capabilities: Dict[str, Any] = Field(default_factory=dict)


class ModelCompareRequest(BaseModel):
    model_ids: List[str]


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

class RoutingConfigResponse(BaseModel):
    strategy: str
    cooldown_base_s: int
    cooldown_max_s: int
    roles: Dict[str, str]
    model_aliases: Dict[str, str]
    fallback_chains: Dict[str, List[str]]
    rules: List[Dict[str, Any]]
    profiles: Optional[Dict[str, Any]] = None


class RoutingUpdateRequest(BaseModel):
    strategy: Optional[str] = None
    cooldown_base_s: Optional[int] = None
    cooldown_max_s: Optional[int] = None
    roles: Optional[Dict[str, str]] = None
    model_aliases: Optional[Dict[str, str]] = None
    fallback_chains: Optional[Dict[str, List[str]]] = None
    rules: Optional[List[Dict[str, Any]]] = None
    profiles: Optional[Dict[str, Any]] = None


class RoutingSimulateRequest(BaseModel):
    task: str = "general-query"
    model: Optional[str] = None
    role: str = "main"
    prompt_tokens: int = 500
    requires_vision: bool = False
    privacy_tier: str = "zero_retention"
    session_id: Optional[str] = None
    is_tool_loop: bool = False
    force_explore: bool = False


class RoutingSimulateResponse(BaseModel):
    resolved_role: str
    selected_provider: str
    selected_model: str
    selection_reason: str
    estimated_cost_usd: float
    fallback_chain: List[str]
    request_id: Optional[str] = None
    decision_source: Optional[str] = None
    confidence: Optional[float] = None


class RequirementProfileItem(BaseModel):
    name: str
    description: str = ""
    hard_constraints: Dict[str, Any] = Field(default_factory=dict)
    soft_objectives: Dict[str, float] = Field(default_factory=dict)


class RouteExplanationResponse(BaseModel):
    request_id: str
    timestamp: float
    decision: Dict[str, Any]
    all_scored_candidates: List[Dict[str, Any]]
    filtered_out: Dict[str, str]
    task_understanding: Dict[str, Any]



# ---------------------------------------------------------------------------
# Drex
# ---------------------------------------------------------------------------

class DrexDecisionItem(BaseModel):
    decision_id: str
    state_summary: str
    questions: Any
    answers: Any
    confidence: Optional[float] = None
    latency_ms: Optional[float] = None
    model: str
    created_at: int


class DrexStatusResponse(BaseModel):
    connected: bool
    resolved_model: str
    decision_toggles: Dict[str, bool]
    confidence_threshold: float
    budget_caps_usd: float
    accuracy_vs_rules: Dict[str, float]
    recent_decisions: List[DrexDecisionItem]


class DrexUpdateRequest(BaseModel):
    confidence_threshold: Optional[float] = None
    budget_caps_usd: Optional[float] = None
    decision_toggles: Optional[Dict[str, bool]] = None


# ---------------------------------------------------------------------------
# Privacy
# ---------------------------------------------------------------------------

class PrivacyConfigResponse(BaseModel):
    provider_policies: Dict[str, str]
    secret_redaction_patterns: List[str]
    pii_redaction_patterns: List[str]
    guard_paths: List[str]


class PrivacyUpdateRequest(BaseModel):
    provider_policies: Optional[Dict[str, str]] = None
    secret_redaction_patterns: Optional[List[str]] = None
    pii_redaction_patterns: Optional[List[str]] = None
    guard_paths: Optional[List[str]] = None


class PrivacyPreviewRequest(BaseModel):
    text: str
    provider: Optional[str] = None


class PrivacyPreviewResponse(BaseModel):
    original_text: str
    redacted_text: str
    matches_found: List[Dict[str, str]]


# ---------------------------------------------------------------------------
# Budgets
# ---------------------------------------------------------------------------

class BudgetResponse(BaseModel):
    today_usd: float
    month_usd: float
    hard_cap_usd: float
    alert_threshold_pct: float
    cache_savings_usd: float
    projection_usd: float
    by_provider: Dict[str, float]
    by_model: Dict[str, float]
    by_day: List[Dict[str, Any]]


class BudgetUpdateRequest(BaseModel):
    hard_cap_usd: Optional[float] = None
    alert_threshold_pct: Optional[float] = None


# ---------------------------------------------------------------------------
# Brain Memory
# ---------------------------------------------------------------------------

class LessonItem(BaseModel):
    lesson_id: str
    rule_text: str
    confidence: float
    usage_count: int
    reinforcements: int
    removals: int
    source_task_ids: List[str]
    created_at: int
    updated_at: int


class EpisodicEventItem(BaseModel):
    event_id: int
    session_id: str
    event_type: str
    tool_name: Optional[str] = None
    action_payload: Any
    outcome_reward: Optional[float] = None
    created_at: int


class MemoryQueryResponse(BaseModel):
    lessons: List[LessonItem]
    recent_events: List[EpisodicEventItem]
    total_lessons: int
    total_events: int
    ab_learning_enabled: bool


class MemorySnapshotResponse(BaseModel):
    snapshot_id: str
    created_at: int
    nodes_count: int
    lessons_count: int


# ---------------------------------------------------------------------------
# Claude Code Integration
# ---------------------------------------------------------------------------

class ClaudeStatusResponse(BaseModel):
    installed: bool
    version: str
    config_file: str
    current_base_url: Optional[str] = None
    is_routed_to_gateway: bool
    backup_file_exists: bool


class ClaudeConfigureRequest(BaseModel):
    action: str  # "route_to_gateway" | "restore_original"


# ---------------------------------------------------------------------------
# Doctor
# ---------------------------------------------------------------------------

class DoctorCheck(BaseModel):
    check_id: str
    name: str
    category: str
    status: str  # "pass" | "warn" | "fail"
    details: str
    recommendation: str
    can_auto_fix: bool


class DoctorReport(BaseModel):
    overall_status: str
    passed: int
    warnings: int
    failed: int
    checks: List[DoctorCheck]


class DoctorFixRequest(BaseModel):
    check_id: str


class DoctorFixResponse(BaseModel):
    check_id: str
    before_status: str
    after_status: str
    fixed: bool
    message: str


# ---------------------------------------------------------------------------
# Requests & Explain & Sessions
# ---------------------------------------------------------------------------

class RequestRecord(BaseModel):
    request_id: str
    session_id: Optional[str] = None
    model_id: str
    provider: str
    key_hash: str
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    latency_ms: Optional[float] = None
    http_status: int
    outcome: str
    privacy_class: str
    created_at: int
    cost_usd: float = 0.0


class RequestsPageResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: List[RequestRecord]


class ExplainTimelineStep(BaseModel):
    stage: str
    timestamp_ms: int
    duration_ms: float
    description: str
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ExplainResponse(BaseModel):
    request_id: str
    plain_summary: str
    timeline: List[ExplainTimelineStep]
    routing_breakdown: Dict[str, Any]
    drex_decision: Optional[Dict[str, Any]] = None
    tokens: Dict[str, int]
    cost_breakdown: Dict[str, float]


class SessionItem(BaseModel):
    session_id: str
    start_time: int
    last_active: int
    request_count: int
    total_tokens: int
    total_cost_usd: float
    models_used: List[str]
    outcomes: Dict[str, int]
    failovers: int


# ---------------------------------------------------------------------------
# Alerts & Logs
# ---------------------------------------------------------------------------

class AlertItem(BaseModel):
    alert_id: str
    level: str  # "info" | "warning" | "critical"
    title: str
    message: str
    component: str
    acknowledged: bool
    snoozed_until: Optional[int] = None
    created_at: int


class LogItem(BaseModel):
    timestamp: str
    level: str
    source: str
    message: str


# ---------------------------------------------------------------------------
# Test Center & Backup & Update
# ---------------------------------------------------------------------------

class TestRunRequest(BaseModel):
    suite: str = "smoke"  # "smoke" | "standard" | "full"


class TestHeatmapItem(BaseModel):
    test_name: str
    duration_ms: float
    status: str  # "pass" | "fail" | "skip"
    error: Optional[str] = None


class TestRunStatus(BaseModel):
    run_id: str
    suite: str
    status: str  # "running" | "completed" | "failed"
    passed: int
    failed: int
    total: int
    heatmap: List[TestHeatmapItem]


class BackupItem(BaseModel):
    backup_id: str
    file_path: str
    size_bytes: int
    notes: Optional[str] = None
    created_at: int


class BackupRestoreRequest(BaseModel):
    backup_id: str


class UpdateCheckResponse(BaseModel):
    current_version: str
    latest_version: str
    up_to_date: bool
    changelog: List[str]


class UpdateApplyRequest(BaseModel):
    version: Optional[str] = None
    mock: bool = True
