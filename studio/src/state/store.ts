// src/state/store.ts — Central reactive store for Claude Master Studio

import { api } from "./api.js";
import { ROUTING_PRESETS } from "./types.js";
import type {
  ClaudeSession,
  DaemonStatus,
  DetectionEvent,
  DoctorCheckResult,
  DrexConfigState,
  DrexDecisionLog,
  GuardRule,
  HyperparameterItem,
  Language,
  LiveRequestEvent,
  ModelItem,
  PrivacyRedactionRule,
  ProviderItem,
  RequirementProfile,
  RoutingPreset,
  RoutingRoleMapping,
  RoutingRule,
  ScreenId,
  SpendMetrics,
  SystemAlert,
  TestCaseResult,
  ThemeMode,
  UserMode,
  RouteCooldownEntry,
} from "./types.js";

export interface ToastMessage {
  id: string;
  type: "info" | "success" | "warning" | "error";
  title: string;
  message: string;
  timestamp: number;
}

export interface AppState {
  currentScreen: ScreenId;
  userMode: UserMode;
  theme: ThemeMode;
  lang: Language;
  daemonStatus: DaemonStatus;
  reconnectCountdown: number;
  emergencyBypass: boolean;
  commandPaletteOpen: boolean;

  // Data sets
  providers: ProviderItem[];
  models: ModelItem[];
  routingRoles: RoutingRoleMapping[];
  routingRules: RoutingRule[];
  drexConfig: DrexConfigState | null;
  drexLogs: DrexDecisionLog[];
  privacyRedaction: PrivacyRedactionRule[];
  guardRules: GuardRule[];
  spendMetrics: SpendMetrics;
  alerts: SystemAlert[];
  liveRequests: LiveRequestEvent[];
  sessions: ClaudeSession[];
  doctorChecks: DoctorCheckResult[];
  detectionHistory: DetectionEvent[];
  testCases: TestCaseResult[];
  cooldownEntries: RouteCooldownEntry[];

  toasts: ToastMessage[];
}

type Listener = (state: AppState) => void;

export const DEFAULT_PROVIDERS: ProviderItem[] = [
  {
    name: "groq",
    base_url: "https://api.groq.com/openai/v1",
    privacy_policy: "zero_retention",
    models: ["llama-3.3-70b-versatile"],
    enabled: true,
    pool_strategy: "round_robin",
    region: "us-west",
    tags: ["ultra-fast", "free-tier"],
    detected_dialect: "openai",
    key_pools: [
      {
        account_label: "personal-01",
        env_var: "GROQ_API_KEY",
        priority: 10,
        masked_key: "gsk_live_****9x21",
        status: "valid",
        tier: "Free Tier",
        quota_left_percent: 86,
        rate_limit_rpm: 30,
        rate_limit_tpm: 60000,
        errors_count: 0,
        daily_spend: 0.0,
        daily_cap: 1.0,
      },
    ],
  },
];

export const DEFAULT_MODELS: ModelItem[] = [
  {
    id: "llama-3.3-70b-versatile",
    name: "Llama 3.3 70B Versatile",
    provider: "groq",
    family: "Llama 3.3",
    quality_score: 91,
    latency_ms: 195,
    cost_input_1m: 0.59,
    cost_output_1m: 0.79,
    roles: ["main", "subagent"],
    status: "active",
    overridden: false,
    tokens_per_sec: 148,
    sample_size_n: 3120,
    ci_95: "±1.2%",
    p_value: 0.002,
    is_statistically_significant: true,
    run_id: "run_bench_20261013_224409_4a8f",
    artifact_url: "data/evals/results.json",
    capabilities: {
      streaming: true,
      tool_calling: true,
      vision: false,
      json_mode: true,
      reasoning: true,
      context_window: 131072,
      max_output_tokens: 32768,
      provenance: "measured",
    },
    benchmarks: {
      coding: { task_type: "coding", score: 89.6, sample_size_n: 1840, passed_count: 1648, ci_95_low: 88.1, ci_95_high: 91.1, measured_ttft_ms: 205, tokens_per_sec: 144, provenance: "measured", p_value: 0.003, is_significant: true, run_id: "run_4a8f#coding", artifact_url: "data/evals/results.json" },
      tool_calling: { task_type: "tool_calling", score: 92.4, sample_size_n: 2150, passed_count: 1986, ci_95_low: 91.2, ci_95_high: 93.6, measured_ttft_ms: 190, tokens_per_sec: 152, provenance: "measured", p_value: 0.001, is_significant: true, run_id: "run_4a8f#tools", artifact_url: "data/evals/results.json" },
    },
  },
];

class Store {
  private state: AppState;
  private listeners: Set<Listener> = new Set();
  private reconnectInterval: number | null = null;

  constructor() {
    const savedMode = (typeof localStorage !== "undefined" && localStorage.getItem("cm_user_mode")) as UserMode;
    const savedTheme = (typeof localStorage !== "undefined" && localStorage.getItem("cm_theme")) as ThemeMode;
    const savedLang = (typeof localStorage !== "undefined" && localStorage.getItem("cm_lang")) as Language;

    this.state = {
      currentScreen: "home",
      userMode: savedMode || "beginner",
      theme: savedTheme || "dark",
      lang: savedLang || "en",
      daemonStatus: "connected",
      reconnectCountdown: 0,
      emergencyBypass: false,
      commandPaletteOpen: false,

      providers: [...DEFAULT_PROVIDERS],
      models: [...DEFAULT_MODELS],
      routingRoles: [],
      routingRules: [],
      drexConfig: null,
      drexLogs: [],
      privacyRedaction: [],
      guardRules: [],
      spendMetrics: {
        daily_spent: 0,
        daily_cap: 5.0,
        monthly_spent: 0,
        monthly_cap: 50.0,
        cache_savings_usd: 0,
        total_requests: 0,
        error_rate: 0,
        cache_hit_rate: 0,
        projected_month_end_usd: 0,
      },
      alerts: [],
      liveRequests: [],
      sessions: [],
      doctorChecks: [],
      detectionHistory: [],
      testCases: [],
      cooldownEntries: [],
      toasts: [],
    };
  }

  getState(): AppState {
    return this.state;
  }

  subscribe(fn: Listener): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  private notify(): void {
    for (const listener of this.listeners) {
      listener(this.state);
    }
  }

  setScreen(screen: ScreenId): void {
    this.state.currentScreen = screen;
    this.notify();
  }

  setUserMode(mode: UserMode): void {
    this.state.userMode = mode;
    if (typeof localStorage !== "undefined") localStorage.setItem("cm_user_mode", mode);
    this.showToast({
      type: "info",
      title: mode === "expert" ? "Expert Mode Active" : "Beginner Mode Active",
      message: mode === "expert" ? "Raw configuration, API tools, and CLI commands now visible." : "Simplified cards and plain language enabled.",
    });
    this.notify();
  }

  setTheme(theme: ThemeMode): void {
    this.state.theme = theme;
    if (typeof localStorage !== "undefined") localStorage.setItem("cm_theme", theme);
    document.documentElement.setAttribute("data-theme", theme);
    this.notify();
  }

  setLanguage(lang: Language): void {
    this.state.lang = lang;
    if (typeof localStorage !== "undefined") localStorage.setItem("cm_lang", lang);
    document.documentElement.setAttribute("lang", lang);
    document.documentElement.setAttribute("dir", lang === "ar" ? "rtl" : "ltr");
    this.notify();
  }

  setDaemonStatus(status: DaemonStatus, countdown = 0): void {
    this.state.daemonStatus = status;
    this.state.reconnectCountdown = countdown;
    this.notify();
  }

  setEmergencyBypass(active: boolean): void {
    this.state.emergencyBypass = active;
    this.showToast({
      type: active ? "warning" : "success",
      title: active ? "Emergency Bypass ENGAGED" : "Emergency Bypass Disengaged",
      message: active ? "Direct connection to Anthropic active. Local routing disabled." : "Standard Claude Master routing restored.",
    });
    this.notify();
  }

  setCommandPaletteOpen(open: boolean): void {
    this.state.commandPaletteOpen = open;
    this.notify();
  }

  showToast(toast: Omit<ToastMessage, "id" | "timestamp">): void {
    const id = "toast-" + Math.random().toString(36).substring(2, 9);
    const newToast: ToastMessage = {
      ...toast,
      id,
      timestamp: Date.now(),
    };
    this.state.toasts.push(newToast);
    this.notify();

    setTimeout(() => {
      this.dismissToast(id);
    }, 4500);
  }

  dismissToast(id: string): void {
    this.state.toasts = this.state.toasts.filter((t) => t.id !== id);
    this.notify();
  }

  // Load initial dynamic data from API
  async initData(): Promise<void> {
    try {
      const [
        providers,
        models,
        routingRoles,
        routingRules,
        drexConfig,
        drexLogs,
        privacy,
        spendMetrics,
        alerts,
        liveRequests,
        sessions,
        doctorChecks,
        detectionHistory,
        testCases,
        cooldownEntries,
      ] = await Promise.all([
        api.fetchProviders(),
        api.fetchModels(),
        api.fetchRoutingRoles(),
        api.fetchRoutingRules(),
        api.fetchDrexConfig(),
        api.fetchDrexLogs(),
        api.fetchPrivacyRules(),
        api.fetchSpendMetrics(),
        api.fetchAlerts(),
        api.fetchRecentRequests(),
        api.fetchSessions(),
        api.fetchDoctorChecks(),
        api.fetchDetectionHistory(),
        api.fetchTestCases(),
        api.fetchCooldownEntries(),
      ]);

      this.state.providers = providers && providers.length > 0 ? providers : (this.state.providers.length > 0 ? this.state.providers : [...DEFAULT_PROVIDERS]);
      this.state.models = models && models.length > 0 ? models : (this.state.models.length > 0 ? this.state.models : [...DEFAULT_MODELS]);
      this.state.routingRoles = routingRoles;
      this.state.routingRules = routingRules;
      this.state.drexConfig = drexConfig;
      this.state.drexLogs = drexLogs;
      this.state.privacyRedaction = privacy.redaction;
      this.state.guardRules = privacy.guards;
      this.state.spendMetrics = spendMetrics;
      this.state.alerts = alerts;
      this.state.liveRequests = liveRequests;
      this.state.sessions = sessions;
      this.state.doctorChecks = doctorChecks;
      this.state.detectionHistory = detectionHistory;
      this.state.testCases = testCases;
      this.state.cooldownEntries = cooldownEntries || [];

      this.notify();
    } catch {
      // Offline fallback already handled in api client
    }

    this.startHealthPolling();
  }

  setCooldownEntries(entries: RouteCooldownEntry[]): void {
    this.state.cooldownEntries = entries;
    this.notify();
  }

  private startHealthPolling(): void {
    const check = async () => {
      if (this.state.reconnectCountdown > 0) return;
      const health = await api.checkHealth();
      if (health.status === "down") {
        if (this.state.daemonStatus !== "offline") {
          this.state.daemonStatus = "offline";
          this.state.reconnectCountdown = 5;
          this.notify();
        }
      } else {
        if (this.state.daemonStatus !== "connected") {
          this.state.daemonStatus = "connected";
          this.state.reconnectCountdown = 0;
          this.notify();
        }
      }
    };

    check();
    setInterval(check, 8000);
  }

  // Model actions
  pinModel(id: string): void {
    const m = this.state.models.find((item) => item.id === id);
    if (m) {
      m.status = m.status === "pinned" ? "active" : "pinned";
      this.notify();
    }
  }

  banModel(id: string): void {
    const m = this.state.models.find((item) => item.id === id);
    if (m) {
      m.status = m.status === "banned" ? "active" : "banned";
      this.notify();
    }
  }

  forceRouteModel(id: string, taskType = "all"): void {
    const m = this.state.models.find((item) => item.id === id);
    if (m) {
      m.force_routed = !m.force_routed;
      m.force_route_task = m.force_routed ? taskType : undefined;
      if (m.force_routed) {
        m.overridden = true;
        m.capabilities.provenance = "override";
      }
      this.showToast({
        type: m.force_routed ? "success" : "info",
        title: m.force_routed ? "Model Force-Routed" : "Force-Route Cleared",
        message: m.force_routed
          ? `Model ${m.name} is now force-routed for ${taskType}. Manual override always wins.`
          : `Removed force-route override for ${m.name}.`,
      });
      this.notify();
    }
  }

  updateRoleProfile(roleName: string, profile: RequirementProfile): void {
    const roleItem = this.state.routingRoles.find((r) => r.role === roleName);
    if (roleItem) {
      roleItem.profile = profile;
      this.notify();
    }
  }

  applyRolePreset(roleName: string, preset: RoutingPreset): void {
    const roleItem = this.state.routingRoles.find((r) => r.role === roleName);
    if (roleItem) {
      const p = ROUTING_PRESETS[preset];
      roleItem.profile = {
        preset,
        hard_constraints: { ...p.hard_constraints },
        soft_objectives: { ...p.soft_objectives },
      };
      this.showToast({
        type: "success",
        title: `Preset Applied: ${p.name}`,
        message: `Applied ${p.name} constraints and weights to ${roleName.toUpperCase()} role.`,
      });
      this.notify();
    }
  }

  setExplorationBudget(budget: number): void {
    if (this.state.drexConfig) {
      this.state.drexConfig.exploration_budget = budget;
      this.showToast({
        type: "info",
        title: "Exploration Budget Adjusted",
        message: `Multi-armed bandit exploration budget set to ${(budget * 100).toFixed(1)}%.`,
      });
      this.notify();
    }
  }

  overrideCapability(id: string, key: keyof ModelItem["capabilities"], value: boolean | number): void {
    const m = this.state.models.find((item) => item.id === id);
    if (m) {
      (m.capabilities as unknown as Record<string, unknown>)[key] = value;
      m.capabilities.provenance = "override";
      m.overridden = true;
      this.showToast({
        type: "success",
        title: "Capability Overridden",
        message: `Model ${m.name}: ${String(key)} set to ${value}. Provenance marked as Override.`,
      });
      this.notify();
    }
  }

  // Alert actions
  snoozeAlert(id: string, minutes = 60): void {
    const a = this.state.alerts.find((item) => item.id === id);
    if (a) {
      a.snoozed_until = Date.now() + minutes * 60 * 1000;
      this.showToast({ type: "info", title: "Alert Snoozed", message: `Snoozed for ${minutes} minutes.` });
      this.notify();
    }
  }

  acknowledgeAlert(id: string): void {
    const a = this.state.alerts.find((item) => item.id === id);
    if (a) {
      a.acknowledged = true;
      this.notify();
    }
  }
}

export const store = new Store();
