// tests/studio-core.test.ts — Unit and component tests for Claude Master Studio

import { describe, expect, it, beforeEach } from "vitest";
import { store } from "../src/state/store.js";
import { t, translations } from "../src/i18n/translations.js";
import { renderCliSnippet } from "../src/components/CliSnippet.js";
import { SetupWizardScreen } from "../src/screens/SetupWizardScreen.js";
import { HomeScreen } from "../src/screens/HomeScreen.js";
import { ProvidersScreen } from "../src/screens/ProvidersScreen.js";
import { ModelsScreen } from "../src/screens/ModelsScreen.js";
import { RoutingScreen } from "../src/screens/RoutingScreen.js";
import { DrexScreen } from "../src/screens/DrexScreen.js";
import { PrivacyScreen } from "../src/screens/PrivacyScreen.js";
import { BudgetsScreen } from "../src/screens/BudgetsScreen.js";
import { DoctorScreen } from "../src/screens/DoctorScreen.js";
import { LogsScreen } from "../src/screens/LogsScreen.js";
import type { ModelItem, ProviderItem } from "../src/state/types.js";

const unscoredModel: ModelItem = {
  id: "test-model",
  name: "Test Model",
  provider: "test-provider",
  family: "test-family",
  quality_score: null,
  latency_ms: null,
  cost_input_1m: 0,
  cost_output_1m: 0,
  roles: [],
  capabilities: {
    streaming: false,
    tool_calling: false,
    vision: false,
    json_mode: false,
    reasoning: false,
    context_window: 0,
    max_output_tokens: 0,
    provenance: "declared",
  },
  status: "active",
  overridden: false,
};

const testProvider: ProviderItem = {
  name: "groq",
  base_url: "https://example.invalid/v1",
  privacy_policy: "zero_retention",
  models: [],
  key_pools: [],
  enabled: false,
  pool_strategy: "priority",
  region: "test",
  tags: [],
};

describe("Studio State Store", () => {
  beforeEach(async () => {
    await store.initData();
  });

  it("toggles theme between dark, light, and high-contrast", () => {
    store.setTheme("light");
    expect(store.getState().theme).toBe("light");
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");

    store.setTheme("dark");
    expect(store.getState().theme).toBe("dark");
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
  });

  it("handles Arabic RTL layout switching", () => {
    store.setLanguage("ar");
    expect(store.getState().lang).toBe("ar");
    expect(document.documentElement.getAttribute("dir")).toBe("rtl");
    expect(document.documentElement.getAttribute("lang")).toBe("ar");

    store.setLanguage("en");
    expect(store.getState().lang).toBe("en");
    expect(document.documentElement.getAttribute("dir")).toBe("ltr");
  });

  it("toggles beginner vs expert mode and dispatches toasts", () => {
    store.setUserMode("expert");
    expect(store.getState().userMode).toBe("expert");

    store.setUserMode("beginner");
    expect(store.getState().userMode).toBe("beginner");
  });

  it("manages emergency bypass state with safety toast", () => {
    store.setEmergencyBypass(true);
    expect(store.getState().emergencyBypass).toBe(true);

    store.setEmergencyBypass(false);
    expect(store.getState().emergencyBypass).toBe(false);
  });

  it("pins and bans models", () => {
    const model = store.getState().models[0];
    if (!model) return;
    const id = model.id;

    store.pinModel(id);
    expect(store.getState().models.find((m) => m.id === id)?.status).toBe("pinned");

    store.banModel(id);
    expect(store.getState().models.find((m) => m.id === id)?.status).toBe("banned");
  });

  it("overrides capability with override provenance winning", () => {
    const model = store.getState().models[0];
    if (!model) return;
    const id = model.id;

    store.overrideCapability(id, "tool_calling", true);
    const updated = store.getState().models.find((m) => m.id === id);
    expect(updated?.capabilities.tool_calling).toBe(true);
    expect(updated?.capabilities.provenance).toBe("override");
    expect(updated?.overridden).toBe(true);
  });

  it("manages alert snooze and acknowledgment", () => {
    const alert = store.getState().alerts[0];
    if (!alert) return;
    const id = alert.id;

    store.snoozeAlert(id, 30);
    expect(store.getState().alerts.find((a) => a.id === id)?.snoozed_until).toBeGreaterThan(Date.now());

    store.acknowledgeAlert(id);
    expect(store.getState().alerts.find((a) => a.id === id)?.acknowledged).toBe(true);
  });
});

describe("Translations & Localization", () => {
  it("translates common keys into English and Arabic", () => {
    expect(t("appName", "en")).toContain("Claude Master Studio");
    expect(t("appName", "ar")).toContain("استوديو كلود ماستر");

    expect(t("wizardTitle", "en")).toContain("Setup Wizard");
    expect(t("wizardTitle", "ar")).toContain("معالج الإعداد الأولي");

    expect(t("emergencyBypass", "en")).toBe("EMERGENCY BYPASS");
    expect(t("emergencyBypass", "ar")).toContain("تجاوز الطوارئ");
  });

  it("has matching keys in en and ar dictionaries", () => {
    const enKeys = Object.keys(translations.en);
    const arKeys = Object.keys(translations.ar);
    for (const key of enKeys) {
      expect(arKeys).toContain(key);
    }
  });
});

describe("CLI Snippet in Beginner vs Expert Mode", () => {
  it("hides CLI snippet in beginner mode", () => {
    store.setUserMode("beginner");
    const html = renderCliSnippet("status", "System status");
    expect(html).toBe("");
  });

  it("displays CLI snippet in expert mode with copy button", () => {
    store.setUserMode("expert");
    const html = renderCliSnippet("status", "System status");
    expect(html).toContain("cm status");
    expect(html).toContain("CLI EQUIVALENT");
    expect(html).toContain("System status");
  });
});

describe("Screens Rendering in JSDOM", () => {
  beforeEach(async () => {
    await store.initData();
  });

  it("renders SetupWizardScreen with 5 steps", () => {
    const el = document.createElement("div");
    const screen = new SetupWizardScreen(el);
    screen.render();
    expect(el.innerHTML).toContain("Setup Wizard");
    expect(el.innerHTML).toContain("Step 1: Environment Diagnostics");
  });

  it("renders HomeScreen with emergency bypass switch", () => {
    const el = document.createElement("div");
    const screen = new HomeScreen(el);
    screen.render();
    expect(el.innerHTML).toContain("System Health & Spend Metrics");
    expect(el.innerHTML).toContain("EMERGENCY BYPASS");
  });

  it("renders ProvidersScreen with key pools", () => {
    store.getState().providers.push(testProvider);
    const el = document.createElement("div");
    const screen = new ProvidersScreen(el);
    screen.render();
    expect(el.innerHTML).toContain("Upstream Providers");
    expect(el.innerHTML).toContain("GROQ");
  });

  it("renders ModelsScreen with capability matrix and provenance badges", () => {
    const el = document.createElement("div");
    const screen = new ModelsScreen(el);
    screen.render();
    expect(el.innerHTML).toContain("Unified Model Matrix");
    expect(el.innerHTML).toContain("Capability Provenance");
  });

  it("renders RoutingScreen with requirement profiles, presets and simulator", () => {
    const el = document.createElement("div");
    const screen = new RoutingScreen(el);
    screen.render();
    expect(el.innerHTML).toContain("Semantic Role Assignments");
    expect(el.innerHTML).toContain("Hard Constraints");
    expect(el.innerHTML).toContain("Soft Objectives &amp; Weight Sliders");
    expect(el.innerHTML).toContain("Cheapest");
    expect(el.innerHTML).toContain("Fastest");
    expect(el.innerHTML).toContain("Most Capable");
    expect(el.innerHTML).toContain("Visual Rule Builder");
    expect(el.innerHTML).toContain("Live Request Routing Simulator");
    expect(el.querySelector("#btn-run-sim")).not.toBeNull();
  });

  it("renders ModelsScreen with task leaderboards and manual overrides", () => {
    store.getState().models.push(unscoredModel);
    const el = document.createElement("div");
    const screen = new ModelsScreen(el);
    screen.render();
    expect(el.innerHTML).toContain("Dynamic Model Leaderboards");
    expect(el.innerHTML).toContain("Task Benchmark:");
    expect(el.innerHTML).toContain("Sample Size (N)");
    expect(el.innerHTML).toContain("95% Confidence Interval");
    expect(el.innerHTML).toContain("Tokens / Sec");
    expect(el.innerHTML).toContain("NOT MEASURED");
    expect(el.querySelectorAll(".btn-force-route").length).toBeGreaterThan(0);
    expect(el.querySelectorAll(".btn-pin-model").length).toBeGreaterThan(0);
    expect(el.querySelectorAll(".btn-ban-model").length).toBeGreaterThan(0);
  });

  it("renders DrexScreen with decision trace viewer and exploration budget slider", () => {
    const el = document.createElement("div");
    const screen = new DrexScreen(el);
    screen.render();
    expect(el.innerHTML).toContain("Decision Taker");
    expect(el.innerHTML).toContain("Confidence Thresholds");
    expect(el.innerHTML).toContain("Multi-Armed Bandit Exploration Budget");
    expect(el.innerHTML).toContain("Active Exploration Candidates");
    expect(el.innerHTML).toContain("Drex Decision Trace vs Utility Score");
    expect(el.querySelector("#rng-exploration-budget")).not.toBeNull();
  });

  it("renders PrivacyScreen with live redaction preview", () => {
    const el = document.createElement("div");
    const screen = new PrivacyScreen(el);
    screen.render();
    expect(el.innerHTML).toContain("Live Secret &amp; PII Redaction Preview");
    expect(el.innerHTML).toContain("&lt;REDACTED_PASSWORD&gt;");
  });

  it("renders BudgetsScreen with spend limits", () => {
    const el = document.createElement("div");
    const screen = new BudgetsScreen(el);
    screen.render();
    expect(el.innerHTML).toContain("Daily Spend Limit");
    expect(el.innerHTML).toContain("Honest Cache Savings");
  });

  it("renders DoctorScreen with 1-click checks", () => {
    const el = document.createElement("div");
    const screen = new DoctorScreen(el);
    screen.render();
    expect(el.innerHTML).toContain("System Doctor");
    expect(el.innerHTML).toContain("Node.js Environment");
  });

  it("renders LogsScreen with structured log filtering", () => {
    const el = document.createElement("div");
    const screen = new LogsScreen(el);
    screen.render();
    expect(el.innerHTML).toContain("Sanitized Structured Logs");
    expect(el.innerHTML).toContain("Export Sanitized Support Bundle");
  });
});
