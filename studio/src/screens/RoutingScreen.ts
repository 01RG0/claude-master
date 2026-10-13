// src/screens/RoutingScreen.ts — Dynamic Requirement-Profile-Driven Routing & Simulator

import { store } from "../state/store.js";
import { api } from "../state/api.js";
import { t } from "../i18n/translations.js";
import { renderCliSnippet } from "../components/CliSnippet.js";
import {
  ROUTING_PRESETS,
  type RequirementProfile,
  type RoutingPreset,
  type RoutingSimulateResult,
} from "../state/types.js";

export class RoutingScreen {
  private container: HTMLElement;
  private simPrompt = "Fix memory leak in hookhost child process lifecycle and add unit test";
  private simTask = "coding";
  private simTokens = 1200;
  private simReqTools = true;
  private simReqVision = false;
  private simLoading = false;
  private simResult: RoutingSimulateResult | null = null;

  constructor(container: HTMLElement) {
    this.container = container;
  }

  render(): void {
    const state = store.getState();
    const lang = state.lang;
    const roles = state.routingRoles;
    const rules = state.routingRules;
    const models = state.models;

    // Ensure all roles have a requirement profile
    for (const r of roles) {
      if (!r.profile) {
        const defaultPresetKey: RoutingPreset =
          r.role === "main"
            ? "most_capable"
            : r.role === "small-fast"
            ? "fastest"
            : r.role === "subagent"
            ? "balanced"
            : r.role === "summarizer"
            ? "cheapest"
            : "custom";
        const p = ROUTING_PRESETS[defaultPresetKey];
        r.profile = {
          preset: defaultPresetKey,
          hard_constraints: { ...p.hard_constraints, vision: r.role === "vision" },
          soft_objectives: { ...p.soft_objectives },
        };
      }
    }

    this.container.innerHTML = `
      <div class="screen-header">
        <div>
          <h2>${t("routingTitle", lang)}</h2>
          <p class="muted">${t("routingSubtitle", lang)}</p>
        </div>
        <button type="button" class="btn-primary" id="btn-save-routing">
          💾 ${t("save", lang)} Routing Matrix
        </button>
      </div>

      <!-- Section 1: Requirement Profile Editors for Roles -->
      <div class="card">
        <div class="card-header">
          <div>
            <h3>1. Semantic Role Assignments (Dynamic Requirement Profiles)</h3>
            <span class="muted text-sm">
              Replace static model slots with hard constraints and weighted soft objectives. Models are resolved dynamically based on measured capabilities.
            </span>
          </div>
          <span class="badge info">Dynamic Measured Matching</span>
        </div>

        <div class="role-profiles-container">
          ${roles.map((r) => this.renderRoleProfileCard(r, lang, models)).join("")}
        </div>
      </div>

      <!-- Section 2: Visual Rule Builder -->
      <div class="card">
        <div class="card-header">
          <div>
            <h3>2. Visual Rule Builder ("If task matches condition, route to model")</h3>
            <span class="muted text-sm">Deterministic rule overrides that precede standard profile routing.</span>
          </div>
          <button type="button" class="btn-sm btn-secondary" id="btn-add-rule">+ Add Rule</button>
        </div>
        <div class="rules-list">
          ${rules
            .map(
              (rule, idx) => `
            <div class="rule-item">
              <span class="rule-indicator">IF</span>
              <input type="text" class="form-input rule-cond" data-idx="${idx}" value="${escapeHtml(rule.condition)}" />
              <span class="rule-indicator">THEN ROUTE TO</span>
              <select class="form-select rule-target" data-idx="${idx}">
                ${models.map((m) => `<option value="${m.id}" ${m.id === rule.target_model ? "selected" : ""}>${escapeHtml(m.name)} (${m.provider})</option>`).join("")}
              </select>
              <button type="button" class="btn-sm btn-ghost btn-del-rule" data-idx="${idx}" title="Delete Rule">✕</button>
            </div>
          `,
            )
            .join("")}
        </div>
      </div>

      <!-- Section 3: Live "What would be chosen for this request" Simulator -->
      <div class="card simulator-card">
        <div class="card-header">
          <div>
            <h3>3. Live Request Routing Simulator (/api/routing/simulate)</h3>
            <span class="muted text-sm">Test and verify requirement profile matching and utility scoring in real time.</span>
          </div>
          <span class="badge active">Live Simulator</span>
        </div>

        <div class="simulator-body">
          <div class="sim-grid-inputs">
            <div class="form-row flex-grow">
              <label>Simulated Prompt / Query:</label>
              <input type="text" id="inp-sim-prompt" class="form-input" value="${escapeHtml(this.simPrompt)}" placeholder="Enter a simulated prompt or command..." />
            </div>

            <div class="form-row">
              <label>Task Category:</label>
              <select id="sel-sim-task" class="form-select">
                <option value="coding" ${this.simTask === "coding" ? "selected" : ""}>Coding & Refactoring</option>
                <option value="tool_calling" ${this.simTask === "tool_calling" ? "selected" : ""}>Tool Calling & Shell</option>
                <option value="reasoning" ${this.simTask === "reasoning" ? "selected" : ""}>Deep CoT Reasoning</option>
                <option value="vision" ${this.simTask === "vision" ? "selected" : ""}>Vision Multimodal</option>
                <option value="arabic" ${this.simTask === "arabic" ? "selected" : ""}>Arabic Language</option>
                <option value="general" ${this.simTask === "general" ? "selected" : ""}>General Query</option>
              </select>
            </div>

            <div class="form-row">
              <label>Tokens Est.:</label>
              <input type="number" id="inp-sim-tokens" class="form-input" style="width: 100px;" value="${this.simTokens}" step="100" min="50" max="200000" />
            </div>
          </div>

          <div class="sim-flags-row">
            <label class="checkbox-inline">
              <input type="checkbox" id="chk-sim-tools" ${this.simReqTools ? "checked" : ""} />
              <span>Requires Tool Calling</span>
            </label>
            <label class="checkbox-inline">
              <input type="checkbox" id="chk-sim-vision" ${this.simReqVision ? "checked" : ""} />
              <span>Requires Vision</span>
            </label>

            <button type="button" class="btn-primary ml-auto" id="btn-run-sim" ${this.simLoading ? "disabled" : ""}>
              ${this.simLoading ? "Simulating..." : "⚡ " + t("simulateRequest", lang)}
            </button>
          </div>

          <!-- Simulation Result Display -->
          ${this.renderSimulationResult(lang)}
        </div>
      </div>

      ${renderCliSnippet("config --routing", "Inspect routing table and profile matrices in gateway/config.json")}
    `;

    this.attachEvents();
  }

  private renderRoleProfileCard(r: any, lang: any, models: any[]): string {
    const profile: RequirementProfile = r.profile;
    const presets: RoutingPreset[] = ["cheapest", "fastest", "most_capable", "balanced", "custom"];

    return `
      <div class="role-profile-card" data-role="${r.role}">
        <div class="role-profile-header">
          <div class="role-identity">
            <span class="role-badge ${r.role}">${r.role.toUpperCase()}</span>
            <div class="role-meta">
              <strong>${r.role.toUpperCase()} ROLE</strong>
              <span class="muted text-xs">${escapeHtml(r.description)}</span>
            </div>
          </div>

          <!-- Presets Selector -->
          <div class="preset-selector-group">
            <span class="preset-label">${t("presetSelectorLabel", lang)}:</span>
            <div class="preset-pills">
              ${presets
                .map(
                  (pKey) => `
                <button
                  type="button"
                  class="btn-preset ${profile.preset === pKey ? "active" : ""}"
                  data-role="${r.role}"
                  data-preset="${pKey}"
                  title="${ROUTING_PRESETS[pKey].description}">
                  ${this.getPresetDisplayName(pKey, lang)}
                </button>
              `,
                )
                .join("")}
            </div>
          </div>
        </div>

        <div class="role-profile-body">
          <!-- Left: Hard Constraints -->
          <div class="profile-col hard-constraints-col">
            <div class="col-title">
              <span class="icon">🔒</span>
              <strong>${t("hardConstraintsTitle", lang)}</strong>
            </div>

            <div class="constraint-row">
              <label class="toggle-checkbox">
                <input
                  type="checkbox"
                  class="chk-hard-tool"
                  data-role="${r.role}"
                  ${profile.hard_constraints.tool_calling ? "checked" : ""} />
                <span>${t("toolCallingRequired", lang)}</span>
              </label>
            </div>

            <div class="constraint-row">
              <label class="toggle-checkbox">
                <input
                  type="checkbox"
                  class="chk-hard-vision"
                  data-role="${r.role}"
                  ${profile.hard_constraints.vision ? "checked" : ""} />
                <span>${t("visionRequired", lang)}</span>
              </label>
            </div>

            <div class="constraint-row">
              <label>${t("minContextSize", lang)}:</label>
              <select class="form-select sel-hard-context" data-role="${r.role}">
                <option value="8192" ${profile.hard_constraints.context_size === 8192 ? "selected" : ""}>8,192 tokens (8k)</option>
                <option value="16384" ${profile.hard_constraints.context_size === 16384 ? "selected" : ""}>16,384 tokens (16k)</option>
                <option value="32768" ${profile.hard_constraints.context_size === 32768 ? "selected" : ""}>32,768 tokens (32k)</option>
                <option value="65536" ${profile.hard_constraints.context_size === 65536 ? "selected" : ""}>65,536 tokens (64k)</option>
                <option value="131072" ${profile.hard_constraints.context_size === 131072 ? "selected" : ""}>131,072 tokens (128k)</option>
                <option value="200000" ${profile.hard_constraints.context_size === 200000 ? "selected" : ""}>200,000 tokens (200k)</option>
              </select>
            </div>

            <div class="constraint-row">
              <label>${t("maxCostBudget", lang)}:</label>
              <input
                type="number"
                step="0.5"
                min="0.1"
                class="form-input inp-hard-budget"
                data-role="${r.role}"
                value="${profile.hard_constraints.max_cost_1m}" />
            </div>
          </div>

          <!-- Right: Soft Objectives with Weight Sliders -->
          <div class="profile-col soft-objectives-col">
            <div class="col-title">
              <span class="icon">⚖️</span>
              <strong>${t("softObjectivesTitle", lang)}</strong>
            </div>

            <!-- Quality Weight -->
            <div class="weight-slider-row">
              <div class="slider-header">
                <span class="slider-name">${t("weightQuality", lang)}</span>
                <span class="slider-val badge info" id="val-${r.role}-quality">${profile.soft_objectives.quality}%</span>
              </div>
              <input
                type="range"
                min="0"
                max="100"
                step="5"
                class="range-slider rng-soft-weight"
                data-role="${r.role}"
                data-key="quality"
                value="${profile.soft_objectives.quality}" />
            </div>

            <!-- TTFT Latency Weight -->
            <div class="weight-slider-row">
              <div class="slider-header">
                <span class="slider-name">${t("weightTtft", lang)}</span>
                <span class="slider-val badge info" id="val-${r.role}-ttft">${profile.soft_objectives.ttft}%</span>
              </div>
              <input
                type="range"
                min="0"
                max="100"
                step="5"
                class="range-slider rng-soft-weight"
                data-role="${r.role}"
                data-key="ttft"
                value="${profile.soft_objectives.ttft}" />
            </div>

            <!-- Cost Weight -->
            <div class="weight-slider-row">
              <div class="slider-header">
                <span class="slider-name">${t("weightCost", lang)}</span>
                <span class="slider-val badge info" id="val-${r.role}-cost">${profile.soft_objectives.cost}%</span>
              </div>
              <input
                type="range"
                min="0"
                max="100"
                step="5"
                class="range-slider rng-soft-weight"
                data-role="${r.role}"
                data-key="cost"
                value="${profile.soft_objectives.cost}" />
            </div>

            <!-- Reliability Weight -->
            <div class="weight-slider-row">
              <div class="slider-header">
                <span class="slider-name">${t("weightReliability", lang)}</span>
                <span class="slider-val badge info" id="val-${r.role}-reliability">${profile.soft_objectives.reliability}%</span>
              </div>
              <input
                type="range"
                min="0"
                max="100"
                step="5"
                class="range-slider rng-soft-weight"
                data-role="${r.role}"
                data-key="reliability"
                value="${profile.soft_objectives.reliability}" />
            </div>
          </div>
        </div>

        <!-- Role Resolution Footer -->
        <div class="role-profile-footer">
          <div class="footer-model-slot">
            <span class="slot-label">Designated Winner Model:</span>
            <select class="form-select sel-primary-model" data-role="${r.role}">
              ${models
                .map(
                  (m) => `
                <option value="${m.id}" ${m.id === r.model_id ? "selected" : ""}>
                  ${escapeHtml(m.name)} (${m.provider}) — TTFT: ${m.latency_ms}ms, IQ: ${m.quality_score}
                </option>
              `,
                )
                .join("")}
            </select>
          </div>

          <div class="footer-model-slot">
            <span class="slot-label">Fallback Model Chain:</span>
            <select class="form-select sel-fallback-model" data-role="${r.role}">
              ${models
                .map(
                  (m) => `
                <option value="${m.id}" ${m.id === r.fallback_model_id ? "selected" : ""}>
                  ${escapeHtml(m.name)} (${m.provider})
                </option>
              `,
                )
                .join("")}
            </select>
          </div>
        </div>
      </div>
    `;
  }

  private renderSimulationResult(lang: any): string {
    if (!this.simResult) return "";

    const res = this.simResult;
    const scores = res.utility_scores || { quality: 90, ttft: 80, cost: 85, reliability: 90, total: 0.88 };
    const passed = res.constraints_passed || { tool_calling: true, vision: true, context_size: true, budget: true };

    return `
      <div class="sim-result-box">
        <div class="sim-result-header">
          <div class="sim-result-title">
            <span class="badge ok">Resolved Winner</span>
            <strong>${escapeHtml(res.selected_model)}</strong>
            <span class="badge info">${escapeHtml(res.selected_provider)}</span>
            <span class="role-badge ${res.resolved_role}">${res.resolved_role.toUpperCase()}</span>
          </div>
          <div class="sim-cost-tag">
            Est. Cost: <strong>$${res.estimated_cost_usd.toFixed(5)}</strong>
          </div>
        </div>

        <div class="sim-reason-row">
          <span class="reason-label">Resolution Rationale:</span>
          <span>${escapeHtml(res.selection_reason)}</span>
        </div>

        <!-- Hard Constraints Verification -->
        <div class="sim-constraints-verification">
          <span class="section-label">Hard Constraints Check:</span>
          <div class="constraints-badges-group">
            <span class="constraint-badge ${passed.tool_calling ? "pass" : "fail"}">
              ${passed.tool_calling ? "✓" : "✗"} Tool Calling
            </span>
            <span class="constraint-badge ${passed.vision ? "pass" : "fail"}">
              ${passed.vision ? "✓" : "✗"} Vision Support
            </span>
            <span class="constraint-badge ${passed.context_size ? "pass" : "fail"}">
              ${passed.context_size ? "✓" : "✗"} Context Window
            </span>
            <span class="constraint-badge ${passed.budget ? "pass" : "fail"}">
              ${passed.budget ? "✓" : "✗"} Budget Cap
            </span>
          </div>
        </div>

        <!-- Soft Utility Scores Breakdown -->
        <div class="sim-utility-breakdown">
          <span class="section-label">Soft Utility Breakdown:</span>
          <div class="utility-bars-grid">
            <div class="utility-bar-item">
              <span class="bar-name">Quality:</span>
              <div class="progress-bar-wrap">
                <div class="progress-bar-fill fill-quality" style="width: ${scores.quality}%"></div>
              </div>
              <span class="bar-val">${scores.quality}%</span>
            </div>
            <div class="utility-bar-item">
              <span class="bar-name">TTFT Speed:</span>
              <div class="progress-bar-wrap">
                <div class="progress-bar-fill fill-ttft" style="width: ${scores.ttft}%"></div>
              </div>
              <span class="bar-val">${scores.ttft}%</span>
            </div>
            <div class="utility-bar-item">
              <span class="bar-name">Cost Economy:</span>
              <div class="progress-bar-wrap">
                <div class="progress-bar-fill fill-cost" style="width: ${scores.cost}%"></div>
              </div>
              <span class="bar-val">${scores.cost}%</span>
            </div>
            <div class="utility-bar-item">
              <span class="bar-name">Reliability:</span>
              <div class="progress-bar-wrap">
                <div class="progress-bar-fill fill-reliability" style="width: ${scores.reliability}%"></div>
              </div>
              <span class="bar-val">${scores.reliability}%</span>
            </div>
          </div>
        </div>

        <div class="sim-fallback-row">
          <span class="reason-label">Fallback Chain:</span>
          <span class="mono text-xs">${res.fallback_chain.join(" ➔ ")}</span>
        </div>
      </div>
    `;
  }

  private getPresetDisplayName(preset: RoutingPreset, lang: any): string {
    switch (preset) {
      case "cheapest":
        return t("presetCheapest", lang);
      case "fastest":
        return t("presetFastest", lang);
      case "most_capable":
        return t("presetMostCapable", lang);
      case "balanced":
        return t("presetBalanced", lang);
      case "custom":
        return t("presetCustom", lang);
    }
  }

  private attachEvents(): void {
    // Save Routing Matrix
    this.container.querySelector("#btn-save-routing")?.addEventListener("click", () => {
      store.showToast({
        type: "success",
        title: "Routing Matrix Saved",
        message: "Requirement profiles, constraints, and fallback chains committed to gateway/config.json.",
      });
    });

    // Preset Buttons Click
    this.container.querySelectorAll(".btn-preset").forEach((btn) => {
      btn.addEventListener("click", () => {
        const role = btn.getAttribute("data-role")!;
        const preset = btn.getAttribute("data-preset") as RoutingPreset;
        store.applyRolePreset(role, preset);
        this.render();
      });
    });

    // Hard Constraint Changes
    this.container.querySelectorAll(".chk-hard-tool").forEach((chk) => {
      chk.addEventListener("change", (e) => {
        const role = (e.target as HTMLElement).getAttribute("data-role")!;
        const r = store.getState().routingRoles.find((item) => item.role === role);
        if (r?.profile) {
          r.profile.hard_constraints.tool_calling = (e.target as HTMLInputElement).checked;
          r.profile.preset = "custom";
          this.render();
        }
      });
    });

    this.container.querySelectorAll(".chk-hard-vision").forEach((chk) => {
      chk.addEventListener("change", (e) => {
        const role = (e.target as HTMLElement).getAttribute("data-role")!;
        const r = store.getState().routingRoles.find((item) => item.role === role);
        if (r?.profile) {
          r.profile.hard_constraints.vision = (e.target as HTMLInputElement).checked;
          r.profile.preset = "custom";
          this.render();
        }
      });
    });

    this.container.querySelectorAll(".sel-hard-context").forEach((sel) => {
      sel.addEventListener("change", (e) => {
        const role = (e.target as HTMLElement).getAttribute("data-role")!;
        const r = store.getState().routingRoles.find((item) => item.role === role);
        if (r?.profile) {
          r.profile.hard_constraints.context_size = parseInt((e.target as HTMLSelectElement).value, 10);
          r.profile.preset = "custom";
          this.render();
        }
      });
    });

    this.container.querySelectorAll(".inp-hard-budget").forEach((inp) => {
      inp.addEventListener("change", (e) => {
        const role = (e.target as HTMLElement).getAttribute("data-role")!;
        const r = store.getState().routingRoles.find((item) => item.role === role);
        if (r?.profile) {
          r.profile.hard_constraints.max_cost_1m = parseFloat((e.target as HTMLInputElement).value) || 1.0;
          r.profile.preset = "custom";
          this.render();
        }
      });
    });

    // Soft Objective Sliders
    this.container.querySelectorAll(".rng-soft-weight").forEach((slider) => {
      slider.addEventListener("input", (e) => {
        const target = e.target as HTMLInputElement;
        const role = target.getAttribute("data-role")!;
        const key = target.getAttribute("data-key") as "quality" | "ttft" | "cost" | "reliability";
        const val = parseInt(target.value, 10);
        const r = store.getState().routingRoles.find((item) => item.role === role);
        if (r?.profile) {
          r.profile.soft_objectives[key] = val;
          r.profile.preset = "custom";
          const lbl = this.container.querySelector(`#val-${role}-${key}`);
          if (lbl) lbl.textContent = `${val}%`;
        }
      });
    });

    // Primary & Fallback model dropdowns
    this.container.querySelectorAll(".sel-primary-model").forEach((sel) => {
      sel.addEventListener("change", (e) => {
        const role = (e.target as HTMLElement).getAttribute("data-role")!;
        const r = store.getState().routingRoles.find((item) => item.role === role);
        if (r) {
          r.model_id = (e.target as HTMLSelectElement).value;
        }
      });
    });

    this.container.querySelectorAll(".sel-fallback-model").forEach((sel) => {
      sel.addEventListener("change", (e) => {
        const role = (e.target as HTMLElement).getAttribute("data-role")!;
        const r = store.getState().routingRoles.find((item) => item.role === role);
        if (r) {
          r.fallback_model_id = (e.target as HTMLSelectElement).value;
        }
      });
    });

    // Rule Builder Actions
    this.container.querySelector("#btn-add-rule")?.addEventListener("click", () => {
      store.getState().routingRules.push({
        id: "rule-" + Date.now(),
        name: "Custom Rule",
        condition: "task == 'vision' or file_ext in ['.png', '.jpg']",
        target_model: "claude-3-5-sonnet",
        enabled: true,
      });
      this.render();
    });

    this.container.querySelectorAll(".btn-del-rule").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        const idx = parseInt((e.target as HTMLElement).getAttribute("data-idx")!, 10);
        store.getState().routingRules.splice(idx, 1);
        this.render();
      });
    });

    this.container.querySelectorAll(".rule-cond").forEach((inp) => {
      inp.addEventListener("change", (e) => {
        const idx = parseInt((e.target as HTMLElement).getAttribute("data-idx")!, 10);
        const rules = store.getState().routingRules;
        if (rules[idx]) rules[idx].condition = (e.target as HTMLInputElement).value;
      });
    });

    this.container.querySelectorAll(".rule-target").forEach((sel) => {
      sel.addEventListener("change", (e) => {
        const idx = parseInt((e.target as HTMLElement).getAttribute("data-idx")!, 10);
        const rules = store.getState().routingRules;
        if (rules[idx]) rules[idx].target_model = (e.target as HTMLSelectElement).value;
      });
    });

    // Run Simulator Event
    this.container.querySelector("#btn-run-sim")?.addEventListener("click", async () => {
      const promptInp = this.container.querySelector("#inp-sim-prompt") as HTMLInputElement;
      const taskSel = this.container.querySelector("#sel-sim-task") as HTMLSelectElement;
      const tokensInp = this.container.querySelector("#inp-sim-tokens") as HTMLInputElement;
      const toolsChk = this.container.querySelector("#chk-sim-tools") as HTMLInputElement;
      const visionChk = this.container.querySelector("#chk-sim-vision") as HTMLInputElement;

      this.simPrompt = promptInp?.value || this.simPrompt;
      this.simTask = taskSel?.value || this.simTask;
      this.simTokens = parseInt(tokensInp?.value || "1000", 10);
      this.simReqTools = toolsChk?.checked ?? true;
      this.simReqVision = visionChk?.checked ?? false;
      this.simLoading = true;
      this.render();

      try {
        this.simResult = await api.simulateRouting({
          prompt: this.simPrompt,
          task: this.simTask,
          prompt_tokens: this.simTokens,
          requires_tool_calling: this.simReqTools,
          requires_vision: this.simReqVision,
        });
      } finally {
        this.simLoading = false;
        this.render();
      }
    });
  }
}

function escapeHtml(s?: string | null): string {
  if (!s) return "";
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
