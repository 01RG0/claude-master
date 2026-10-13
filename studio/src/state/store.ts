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

  toasts: ToastMessage[];
}

type Listener = (state: AppState) => void;

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

      providers: [],
      models: [],
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
      ]);

      this.state.providers = providers;
      this.state.models = models;
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

      this.notify();
    } catch {
      // Offline fallback already handled in api client
    }

    this.startHealthPolling();
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
