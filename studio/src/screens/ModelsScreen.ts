// src/screens/ModelsScreen.ts — Unified Model Matrix, Capabilities & Measured Leaderboards

import { store } from "../state/store.js";
import { t } from "../i18n/translations.js";
import { renderCliSnippet } from "../components/CliSnippet.js";
import type { ModelItem, TaskType } from "../state/types.js";

export class ModelsScreen {
  private container: HTMLElement;
  private selectedTaskType: TaskType = "coding";
  private viewMode: "leaderboard" | "matrix" = "leaderboard";
  private compareModalOpen = false;
  private selectedForCompare: string[] = [];

  constructor(container: HTMLElement) {
    this.container = container;
  }

  render(): void {
    const state = store.getState();
    const lang = state.lang;
    const models = state.models;

    this.container.innerHTML = `
      <div class="screen-header">
        <div>
          <h2>${t("modelsTitle", lang)}</h2>
          <p class="muted">${t("modelsSubtitle", lang)}</p>
        </div>
        <div class="btn-group">
          <div class="toggle-group">
            <button type="button" class="btn-toggle ${this.viewMode === "leaderboard" ? "active" : ""}" id="btn-view-leaderboard">
              🏆 ${t("leaderboardTitle", lang)}
            </button>
            <button type="button" class="btn-toggle ${this.viewMode === "matrix" ? "active" : ""}" id="btn-view-matrix">
              📋 Capability Matrix
            </button>
          </div>
          <button type="button" class="btn-secondary" id="btn-compare-models">
            ⚖️ ${t("compareModels", lang)} (${this.selectedForCompare.length})
          </button>
          <button type="button" class="btn-primary" id="btn-probe-all">
            ⚡ Probe All Models
          </button>
        </div>
      </div>

      <!-- Provenance Legend -->
      <div class="provenance-legend-bar">
        <span class="legend-title">Capability Provenance:</span>
        <span class="prov-badge declared">Declared (Vendor)</span>
        <span class="prov-badge measured">Measured (Benchmarked)</span>
        <span class="prov-badge learned">Learned (Adaptive)</span>
        <span class="prov-badge override">Override (Manual Always Wins)</span>
      </div>

      ${this.viewMode === "leaderboard" ? this.renderLeaderboardSection(models, lang) : this.renderMatrixSection(models, lang)}

      <!-- Compare Modal -->
      ${this.compareModalOpen ? this.renderCompareModal() : ""}

      ${renderCliSnippet("doctor --models", "Audit and inspect measured benchmark distributions for candidate models")}
    `;

    this.attachEvents();
  }

  private renderLeaderboardSection(models: ModelItem[], lang: any): string {
    const taskTabs: { type: TaskType; label: string; icon: string }[] = [
      { type: "coding", label: t("taskCoding", lang), icon: "💻" },
      { type: "tool_calling", label: t("taskToolCalling", lang), icon: "🛠️" },
      { type: "reasoning", label: t("taskReasoning", lang), icon: "🧠" },
      { type: "vision", label: t("taskVision", lang), icon: "👁️" },
      { type: "arabic", label: t("taskArabic", lang), icon: "🌍" },
      { type: "english", label: t("taskEnglish", lang), icon: "🔤" },
    ];

    // Rank models for the selected task type
    const rankedModels = [...models].sort((a, b) => {
      // Force-routed always floats to the top
      if (a.force_routed && !b.force_routed) return -1;
      if (!a.force_routed && b.force_routed) return 1;

      // Pinned comes next
      if (a.status === "pinned" && b.status !== "pinned") return -1;
      if (a.status !== "pinned" && b.status === "pinned") return 1;

      // Then by score for current task
      const scoreA = a.benchmarks?.[this.selectedTaskType]?.score ?? a.quality_score;
      const scoreB = b.benchmarks?.[this.selectedTaskType]?.score ?? b.quality_score;
      if (scoreA == null && scoreB != null) return 1;
      if (scoreB == null && scoreA != null) return -1;
      return (scoreB ?? 0) - (scoreA ?? 0);
    });

    return `
      <!-- Task Type Tab Selector -->
      <div class="leaderboard-tabs-bar">
        <span class="tab-label">Task Benchmark:</span>
        <div class="tabs-group">
          ${taskTabs
            .map(
              (tab) => `
            <button
              type="button"
              class="tab-btn ${this.selectedTaskType === tab.type ? "active" : ""}"
              data-task="${tab.type}">
              ${tab.icon} ${tab.label}
            </button>
          `,
            )
            .join("")}
        </div>
      </div>

      <!-- Leaderboard Table -->
      <div class="card table-card">
        <div class="card-header">
          <div>
            <h3>Task Leaderboard: ${this.getTaskTitle(this.selectedTaskType, lang)}</h3>
            <span class="muted text-sm">
              Empirical evaluation based on sample size N with 95% confidence intervals and latency measurements.
            </span>
          </div>
          <span class="badge info">Task Type: ${this.selectedTaskType.toUpperCase()}</span>
        </div>

        <table class="data-table leaderboard-table">
          <thead>
            <tr>
              <th width="40"><input type="checkbox" id="chk-select-all" /></th>
              <th width="50">Rank</th>
              <th>Model Identifier</th>
              <th>Provider</th>
              <th>Task Benchmark Score</th>
              <th>${t("sampleSizeN", lang)}</th>
              <th>${t("confidenceInterval", lang)}</th>
              <th>${t("measuredTtft", lang)}</th>
              <th>${t("tokensPerSec", lang)}</th>
              <th>Provenance</th>
              <th>Status</th>
              <th>Manual Overrides</th>
            </tr>
          </thead>
          <tbody>
            ${rankedModels.map((m, idx) => this.renderLeaderboardRow(m, idx + 1)).join("")}
          </tbody>
        </table>
      </div>
    `;
  }

  private renderLeaderboardRow(m: ModelItem, rank: number): string {
    const isSelected = this.selectedForCompare.includes(m.id);
    const bm = m.benchmarks?.[this.selectedTaskType];
    const score = bm?.score ?? m.quality_score;
    const sampleN = bm?.sample_size_n ?? m.sample_size_n;
    const ciLow = bm?.ci_95_low;
    const ciHigh = bm?.ci_95_high;
    const ttft = bm?.measured_ttft_ms ?? m.latency_ms;
    const tps = bm?.tokens_per_sec ?? m.tokens_per_sec;
    const prov = m.overridden ? "override" : (bm?.provenance ?? m.capabilities.provenance ?? "NOT MEASURED");
    const scoreMeasured = typeof score === "number" && Number.isFinite(score);

    const isPinned = m.status === "pinned";
    const isBanned = m.status === "banned";
    const isForced = m.force_routed ?? false;

    return `
      <tr class="${isBanned ? "row-banned" : isForced ? "row-forced" : isPinned ? "row-pinned" : ""}">
        <td>
          <input type="checkbox" class="chk-model-compare" data-id="${m.id}" ${isSelected ? "checked" : ""} />
        </td>
        <td class="rank-col">
          ${isForced ? `<span class="rank-badge forced" title="Force-routed override winner">⚡</span>` : `<span class="rank-badge r-${rank}">#${rank}</span>`}
        </td>
        <td>
          <strong>${escapeHtml(m.name)}</strong>
          <div class="mono text-xs muted">${escapeHtml(m.id)}</div>
          ${isForced ? `<div class="force-route-badge">FORCE-ROUTED WINNER</div>` : ""}
        </td>
        <td><span class="badge info">${escapeHtml(m.provider)}</span></td>
        <td>
          <div class="score-pill-wrap">
            <div class="score-pill ${scoreMeasured ? (score! >= 90 ? "high" : score! >= 75 ? "mid" : "low") : "unknown"}">
              ${scoreMeasured ? `${score!.toFixed(1)}%` : "NOT MEASURED"}
            </div>
            ${scoreMeasured ? `<div class="score-bar-mini"><div class="score-bar-fill" style="width: ${Math.min(score!, 100)}%"></div></div>` : ""}
          </div>
        </td>
        <td class="mono">
          <span class="sample-size-pill">${typeof sampleN === "number" ? `N = ${sampleN.toLocaleString()}` : "NOT MEASURED"}</span>
        </td>
        <td class="mono text-xs">
          <span class="ci-badge">${typeof ciLow === "number" && typeof ciHigh === "number" ? `[${ciLow.toFixed(1)}% – ${ciHigh.toFixed(1)}%]` : "NOT MEASURED"}</span>
        </td>
        <td class="mono">${typeof ttft === "number" && ttft > 0 ? `${ttft} ms` : "NOT MEASURED"}</td>
        <td class="mono">
          <span class="tps-badge">${typeof tps === "number" && tps > 0 ? `${tps} t/s` : "NOT MEASURED"}</span>
        </td>
        <td>
          <span class="prov-badge ${prov}">${prov}</span>
        </td>
        <td>
          <span class="badge ${isBanned ? "warn" : isForced ? "active" : isPinned ? "active" : "ok"}">
            ${isForced ? "FORCED" : isPinned ? "PINNED" : isBanned ? "BANNED" : "ACTIVE"}
          </span>
        </td>
        <td>
          <div class="btn-group-xs">
            <button
              type="button"
              class="btn-xs ${isForced ? "btn-primary active" : "btn-secondary"} btn-force-route"
              data-id="${m.id}"
              data-task="${this.selectedTaskType}"
              title="Force route this model as winner override for this task">
              ${isForced ? "★ Forced" : "Force"}
            </button>
            <button
              type="button"
              class="btn-xs ${isPinned ? "btn-primary" : "btn-secondary"} btn-pin-model"
              data-id="${m.id}"
              title="Pin to prioritize in candidate rankings">
              ${isPinned ? "📌 Pinned" : "Pin"}
            </button>
            <button
              type="button"
              class="btn-xs ${isBanned ? "btn-danger" : "btn-ghost"} btn-ban-model"
              data-id="${m.id}"
              title="Ban model from router candidate pool">
              ${isBanned ? "🚫 Banned" : "Ban"}
            </button>
          </div>
        </td>
      </tr>
    `;
  }

  private renderMatrixSection(models: ModelItem[], _lang: any): string {
    return `
      <!-- Full Capabilities Matrix Table -->
      <div class="card table-card">
        <table class="data-table">
          <thead>
            <tr>
              <th width="40"><input type="checkbox" id="chk-select-all" /></th>
              <th>Model Identifier</th>
              <th>Provider</th>
              <th>Agentic IQ</th>
              <th>Latency (TTFT)</th>
              <th>Price (1M in / out)</th>
              <th>Capabilities Matrix</th>
              <th>Assigned Roles</th>
              <th>Status</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            ${models.map((m) => this.renderMatrixRow(m)).join("")}
          </tbody>
        </table>
      </div>
    `;
  }

  private renderMatrixRow(m: ModelItem): string {
    const isSelected = this.selectedForCompare.includes(m.id);
    const prov = m.capabilities.provenance;
    const isPinned = m.status === "pinned";
    const isBanned = m.status === "banned";
    const isForced = m.force_routed ?? false;

    return `
      <tr class="${isBanned ? "row-banned" : isForced ? "row-forced" : isPinned ? "row-pinned" : ""}">
        <td><input type="checkbox" class="chk-model-compare" data-id="${m.id}" ${isSelected ? "checked" : ""} /></td>
        <td>
          <strong>${escapeHtml(m.name)}</strong>
          <div class="mono text-xs muted">${escapeHtml(m.id)}</div>
          ${isForced ? `<div class="force-route-badge">FORCE-ROUTED</div>` : ""}
        </td>
        <td><span class="badge info">${escapeHtml(m.provider)}</span></td>
        <td>
          <div class="score-pill ${m.quality_score == null ? "unknown" : m.quality_score >= 85 ? "high" : m.quality_score >= 70 ? "mid" : "low"}">
            ${m.quality_score == null ? "NOT MEASURED" : `${m.quality_score}/100`}
          </div>
        </td>
        <td class="mono">${m.latency_ms == null ? "NOT MEASURED" : `${m.latency_ms} ms`}</td>
        <td class="mono text-xs">$${m.cost_input_1m.toFixed(2)} / $${m.cost_output_1m.toFixed(2)}</td>
        <td>
          <div class="caps-tags-group">
            <span class="cap-tag ${m.capabilities.tool_calling ? "yes" : "no"}" title="Tool Calling">Tools</span>
            <span class="cap-tag ${m.capabilities.streaming ? "yes" : "no"}" title="Streaming">Stream</span>
            <span class="cap-tag ${m.capabilities.vision ? "yes" : "no"}" title="Vision Multimodal">Vision</span>
            <span class="cap-tag ${m.capabilities.reasoning ? "yes" : "no"}" title="Deep Reasoning">CoT</span>
            <span class="prov-badge ${prov}">${prov}</span>
            ${m.overridden ? `<span class="prov-badge override" title="Manual override active">OVERRIDE WINS</span>` : ""}
          </div>
        </td>
        <td>
          <div class="roles-tags-group">
            ${m.roles.map((r) => `<span class="badge ${r === "main" ? "active" : "secondary"}">${escapeHtml(r)}</span>`).join(" ")}
          </div>
        </td>
        <td>
          <span class="badge ${m.status === "active" ? "ok" : m.status === "pinned" ? "active" : "warn"}">
            ${m.status.toUpperCase()}
          </span>
        </td>
        <td>
          <div class="btn-group-xs">
            <button type="button" class="btn-xs ${isForced ? "btn-primary active" : "btn-secondary"} btn-force-route" data-id="${m.id}">
              ${isForced ? "★ Forced" : "Force"}
            </button>
            <button type="button" class="btn-xs ${isPinned ? "btn-primary" : "btn-secondary"} btn-pin-model" data-id="${m.id}">
              ${isPinned ? "Pinned" : "Pin"}
            </button>
            <button type="button" class="btn-xs ${isBanned ? "btn-danger" : "btn-ghost"} btn-ban-model" data-id="${m.id}">
              ${isBanned ? "Banned" : "Ban"}
            </button>
          </div>
        </td>
      </tr>
    `;
  }

  private renderCompareModal(): string {
    const state = store.getState();
    const selected = state.models.filter((m) => this.selectedForCompare.includes(m.id));

    return `
      <div class="modal-overlay">
        <div class="modal-dialog modal-lg">
          <div class="modal-header">
            <h3>Side-by-Side Model Comparison</h3>
            <button type="button" class="btn-close" id="btn-close-compare">&times;</button>
          </div>
          <div class="modal-body">
            <div class="compare-columns-grid">
              ${selected
                .map(
                  (m) => `
                <div class="compare-col">
                  <h4>${escapeHtml(m.name)}</h4>
                  <div class="mono text-xs muted">${escapeHtml(m.id)}</div>
                  <hr/>
                  <p><strong>Provider:</strong> ${m.provider}</p>
                  <p><strong>Agentic IQ Score:</strong> ${m.quality_score == null ? "NOT MEASURED" : `${m.quality_score}/100`}</p>
                  <p><strong>Latency TTFT:</strong> ${m.latency_ms == null ? "NOT MEASURED" : `${m.latency_ms} ms`}</p>
                  <p><strong>Context Window:</strong> ${m.capabilities.context_window.toLocaleString()} tokens</p>
                  <p><strong>Input Price / 1M:</strong> $${m.cost_input_1m.toFixed(2)}</p>
                  <p><strong>Output Price / 1M:</strong> $${m.cost_output_1m.toFixed(2)}</p>
                  <p><strong>Tool Calling:</strong> ${m.capabilities.tool_calling ? "✓ Supported" : "✗ No"}</p>
                  <p><strong>Vision:</strong> ${m.capabilities.vision ? "✓ Supported" : "✗ No"}</p>
                  <p><strong>Measured TTFT:</strong> ${(m.benchmarks?.[this.selectedTaskType]?.measured_ttft_ms ?? m.latency_ms) ?? "NOT MEASURED"} ms</p>
                  <p><strong>Throughput:</strong> ${(m.benchmarks?.[this.selectedTaskType]?.tokens_per_sec ?? m.tokens_per_sec) ?? "NOT MEASURED"} t/s</p>
                  <p><strong>Provenance:</strong> <span class="prov-badge ${m.capabilities.provenance}">${m.capabilities.provenance}</span></p>
                </div>
              `,
                )
                .join("")}
            </div>
          </div>
          <div class="modal-footer">
            <button type="button" class="btn-primary" id="btn-close-compare-footer">Close</button>
          </div>
        </div>
      </div>
    `;
  }

  private getTaskTitle(task: TaskType, lang: any): string {
    switch (task) {
      case "coding":
        return t("taskCoding", lang);
      case "tool_calling":
        return t("taskToolCalling", lang);
      case "reasoning":
        return t("taskReasoning", lang);
      case "vision":
        return t("taskVision", lang);
      case "arabic":
        return t("taskArabic", lang);
      case "english":
        return t("taskEnglish", lang);
    }
  }

  private attachEvents(): void {
    // View Toggle
    this.container.querySelector("#btn-view-leaderboard")?.addEventListener("click", () => {
      this.viewMode = "leaderboard";
      this.render();
    });

    this.container.querySelector("#btn-view-matrix")?.addEventListener("click", () => {
      this.viewMode = "matrix";
      this.render();
    });

    // Task Tab Click
    this.container.querySelectorAll(".tab-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const task = btn.getAttribute("data-task") as TaskType;
        if (task) {
          this.selectedTaskType = task;
          this.render();
        }
      });
    });

    // Compare checkbox selection
    this.container.querySelectorAll(".chk-model-compare").forEach((chk) => {
      chk.addEventListener("change", (e) => {
        const id = (e.target as HTMLElement).getAttribute("data-id")!;
        if ((e.target as HTMLInputElement).checked) {
          if (!this.selectedForCompare.includes(id)) this.selectedForCompare.push(id);
        } else {
          this.selectedForCompare = this.selectedForCompare.filter((item) => item !== id);
        }
        this.render();
      });
    });

    // Compare Modal Open / Close
    this.container.querySelector("#btn-compare-models")?.addEventListener("click", () => {
      if (this.selectedForCompare.length < 2) {
        store.showToast({
          type: "warning",
          title: "Select Models",
          message: "Please check at least 2 models to compare side-by-side.",
        });
        return;
      }
      this.compareModalOpen = true;
      this.render();
    });

    this.container.querySelector("#btn-close-compare, #btn-close-compare-footer")?.addEventListener("click", () => {
      this.compareModalOpen = false;
      this.render();
    });

    this.container.querySelector("#btn-probe-all")?.addEventListener("click", () => {
      store.showToast({
        type: "info",
        title: "Probing Underway",
        message: "Measuring tool calling latency and context limits across active models.",
      });
    });

    // Manual Overrides: Force Route
    this.container.querySelectorAll(".btn-force-route").forEach((btn) => {
      btn.addEventListener("click", () => {
        const id = btn.getAttribute("data-id")!;
        const task = btn.getAttribute("data-task") || this.selectedTaskType;
        store.forceRouteModel(id, task);
        this.render();
      });
    });

    // Manual Overrides: Pin
    this.container.querySelectorAll(".btn-pin-model").forEach((btn) => {
      btn.addEventListener("click", () => {
        const id = btn.getAttribute("data-id")!;
        store.pinModel(id);
        this.render();
      });
    });

    // Manual Overrides: Ban
    this.container.querySelectorAll(".btn-ban-model").forEach((btn) => {
      btn.addEventListener("click", () => {
        const id = btn.getAttribute("data-id")!;
        store.banModel(id);
        this.render();
      });
    });
  }
}

function escapeHtml(s?: string | null): string {
  if (!s) return "";
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
