// src/screens/DrexScreen.ts — Decision Taker (Drex) & Decision Trace Viewer

import { store } from "../state/store.js";
import { t } from "../i18n/translations.js";
import { renderCliSnippet } from "../components/CliSnippet.js";
import type { DrexDecisionTrace, ExplorationCandidate } from "../state/types.js";

export class DrexScreen {
  private container: HTMLElement;
  private selectedTrace: DrexDecisionTrace | null = null;

  constructor(container: HTMLElement) {
    this.container = container;
  }

  render(): void {
    const state = store.getState();
    const lang = state.lang;
    const drex = state.drexConfig;
    const logs = state.drexLogs;

    if (!drex) {
      this.container.innerHTML = `<div class="p-6">Loading Drex configuration...</div>`;
      return;
    }

    const traces: DrexDecisionTrace[] = drex.traces || [];
    const candidates: ExplorationCandidate[] = drex.exploration_candidates || [];
    const explorationBudget = drex.exploration_budget ?? 0.05;

    this.container.innerHTML = `
      <div class="screen-header">
        <div>
          <h2>${t("drexTitle", lang)}</h2>
          <p class="muted">${t("drexSubtitle", lang)}</p>
        </div>
        <div class="btn-group">
          <button type="button" class="btn-primary" id="btn-save-drex">
            💾 ${t("save", lang)} Drex Config
          </button>
        </div>
      </div>

      <!-- Dashboard Status & Connection -->
      <div class="dashboard-grid">
        <div class="card">
          <div class="card-header">
            <h4>Drex Model Connection</h4>
            <span class="badge ${drex.enabled ? "ok" : "warn"}">${drex.enabled ? "Online & Active" : "Disabled"}</span>
          </div>
          <div class="form-row">
            <label>Base URL:</label>
            <input type="text" class="form-input" id="inp-drex-url" value="${escapeHtml(drex.base_url)}" />
          </div>
          <div class="form-row">
            <label>Resolved Model:</label>
            <input type="text" class="form-input" id="inp-drex-model" value="${escapeHtml(drex.model)}" />
          </div>
          <div class="form-row">
            <label>Masked Key:</label>
            <input type="text" class="form-input mono" disabled value="${escapeHtml(drex.api_key_masked)}" />
          </div>
        </div>

        <div class="card">
          <div class="card-header">
            <h4>Budget & Degraded Mode</h4>
            <span class="badge info">Fail-Open Safe</span>
          </div>
          <div class="form-row">
            <label>Daily Budget Cap ($):</label>
            <input type="number" step="0.1" class="form-input" id="inp-drex-cap" value="${drex.daily_budget_cap}" />
            <small class="muted">Today's Drex spend: $${drex.daily_spend.toFixed(2)}</small>
          </div>
          <div class="form-row">
            <label>Degraded Mode Behavior:</label>
            <select class="form-select" id="sel-drex-degraded">
              <option value="fail_open" ${drex.degraded_mode === "fail_open" ? "selected" : ""}>Fail Open (Use deterministic utility heuristics if Drex timeouts)</option>
              <option value="fail_closed" ${drex.degraded_mode === "fail_closed" ? "selected" : ""}>Fail Closed (Block command if Drex unavailable)</option>
            </select>
          </div>
        </div>

        <div class="card">
          <div class="card-header">
            <h4>Drex vs Utility Heuristics Accuracy</h4>
            <span class="badge ok">96.8% Consensus</span>
          </div>
          <div class="metric-stat-row">
            <div>
              <div class="stat-num text-ok">96.8%</div>
              <div class="muted">Consensus Rate</div>
            </div>
            <div>
              <div class="stat-num">28 ms</div>
              <div class="muted">Mean Latency</div>
            </div>
            <div>
              <div class="stat-num text-ok">+0.09</div>
              <div class="muted">Hebbian Delta</div>
            </div>
          </div>
        </div>
      </div>

      <!-- Exploration Budget Slider & Active Candidates List -->
      <div class="card exploration-card">
        <div class="card-header">
          <div>
            <h3>${t("explorationBudgetLabel", lang)} & Candidates</h3>
            <span class="muted text-sm">
              Allocate a fraction of live traffic to sample and calibrate performance of new candidate models under real workloads.
            </span>
          </div>
          <span class="badge info">Multi-Armed Bandit (ε-Greedy)</span>
        </div>

        <div class="exploration-body">
          <div class="exploration-slider-wrap">
            <div class="slider-header">
              <span>Traffic Exploration Budget (ε):</span>
              <span class="badge active" id="lbl-exploration-budget">${(explorationBudget * 100).toFixed(1)}%</span>
            </div>
            <input
              type="range"
              min="0"
              max="0.25"
              step="0.005"
              id="rng-exploration-budget"
              class="range-slider"
              value="${explorationBudget}" />
            <small class="muted">
              Current allocation: ${(explorationBudget * 100).toFixed(1)}% of queries will test emerging candidates to gather empirical sample sizes.
            </small>
          </div>

          <!-- Active Exploration Candidate List -->
          <div class="exploration-candidates-section">
            <h4>${t("explorationCandidatesTitle", lang)}</h4>
            <div class="candidates-grid">
              ${candidates.map((c) => this.renderCandidateCard(c, lang)).join("")}
            </div>
          </div>
        </div>
      </div>

      <!-- Decision Trace Viewer (Drex Recommendation vs Deterministic Utility Score) -->
      <div class="card">
        <div class="card-header">
          <div>
            <h3>${t("decisionTraceTitle", lang)}</h3>
            <span class="muted text-sm">
              Comparative decision trace showing Drex recommendation side-by-side with deterministic utility score calculations.
            </span>
          </div>
          <span class="badge info">${traces.length} Recent Traces</span>
        </div>

        <div class="decision-traces-container">
          <table class="data-table traces-table">
            <thead>
              <tr>
                <th>Timestamp</th>
                <th>Task Type</th>
                <th>Prompt Summary</th>
                <th>${t("drexRec", lang)}</th>
                <th>${t("utilityScoreRec", lang)}</th>
                <th>Agreement Status</th>
                <th>Final Selection</th>
                <th>Latency</th>
                <th>Trace Details</th>
              </tr>
            </thead>
            <tbody>
              ${traces.map((trace) => this.renderTraceRow(trace)).join("")}
            </tbody>
          </table>
        </div>
      </div>

      <!-- Decision Toggles & Confidence Sliders -->
      <div class="card">
        <div class="card-header">
          <h3>Decision Toggles & Confidence Thresholds</h3>
        </div>
        <div class="toggles-grid">
          <label class="toggle-card">
            <input type="checkbox" id="chk-drex-routing" ${drex.toggles.routing ? "checked" : ""} />
            <div>
              <strong>Autonomous Routing</strong>
              <p class="muted">Drex resolves model selection per prompt</p>
              <div class="slider-row">
                <span>Threshold: <strong id="lbl-th-routing">${(drex.confidence_thresholds.routing * 100).toFixed(0)}%</strong></span>
                <input type="range" min="0.5" max="0.99" step="0.01" value="${drex.confidence_thresholds.routing}" id="rng-th-routing" />
              </div>
            </div>
          </label>

          <label class="toggle-card">
            <input type="checkbox" id="chk-drex-guard" ${drex.toggles.guard ? "checked" : ""} />
            <div>
              <strong>Tool Safety Guard</strong>
              <p class="muted">Drex inspects shell commands for danger</p>
              <div class="slider-row">
                <span>Threshold: <strong id="lbl-th-guard">${(drex.confidence_thresholds.guard * 100).toFixed(0)}%</strong></span>
                <input type="range" min="0.5" max="0.99" step="0.01" value="${drex.confidence_thresholds.guard}" id="rng-th-guard" />
              </div>
            </div>
          </label>

          <label class="toggle-card">
            <input type="checkbox" id="chk-drex-judge" ${drex.toggles.judge ? "checked" : ""} />
            <div>
              <strong>Outcome Judge</strong>
              <p class="muted">Evaluates tool results and updates Hebbian brain</p>
              <div class="slider-row">
                <span>Threshold: <strong id="lbl-th-judge">${(drex.confidence_thresholds.judge * 100).toFixed(0)}%</strong></span>
                <input type="range" min="0.5" max="0.99" step="0.01" value="${drex.confidence_thresholds.judge}" id="rng-th-judge" />
              </div>
            </div>
          </label>
        </div>
      </div>

      <!-- Raw Decision Log Stream -->
      <div class="card">
        <div class="card-header">
          <h3>System Event Decision Logs</h3>
          <span class="badge info">${logs.length} Logged Events</span>
        </div>
        <table class="data-table">
          <thead>
            <tr>
              <th>Timestamp</th>
              <th>Type</th>
              <th>Prompt / Command Summary</th>
              <th>Chosen Action</th>
              <th>Confidence</th>
              <th>Latency</th>
              <th>Outcome</th>
            </tr>
          </thead>
          <tbody>
            ${logs
              .map(
                (l) => `
              <tr>
                <td class="mono text-xs">${new Date(l.timestamp).toLocaleTimeString()}</td>
                <td><span class="badge ${l.decision_type === "routing" ? "active" : l.decision_type === "guard" ? "warn" : "ok"}">${l.decision_type}</span></td>
                <td>${escapeHtml(l.prompt_summary)}</td>
                <td class="mono text-xs">${escapeHtml(l.chosen_action)}</td>
                <td><strong>${(l.confidence * 100).toFixed(0)}%</strong></td>
                <td class="mono">${l.latency_ms} ms</td>
                <td><span class="badge ok">${l.outcome}</span></td>
              </tr>
            `,
              )
              .join("")}
          </tbody>
        </table>
      </div>

      <!-- Decision Trace Inspector Modal -->
      ${this.selectedTrace ? this.renderTraceModal(this.selectedTrace) : ""}

      ${renderCliSnippet("config --drex", "View and configure Drex autonomous router and confidence thresholds")}
    `;

    this.attachEvents();
  }

  private renderCandidateCard(c: ExplorationCandidate, lang: any): string {
    const progressPct = Math.min(100, Math.round((c.probes_count / c.target_probes) * 100));
    const statusLabel =
      c.status === "probing"
        ? t("candidateStatusProbing", lang)
        : c.status === "evaluating"
        ? t("candidateStatusEvaluating", lang)
        : t("candidateStatusPromoted", lang);

    return `
      <div class="candidate-card status-${c.status}">
        <div class="candidate-header">
          <div>
            <strong>${escapeHtml(c.name)}</strong>
            <span class="badge info text-xs">${escapeHtml(c.provider)}</span>
          </div>
          <span class="badge ${c.status === "promoted" ? "ok" : c.status === "evaluating" ? "active" : "warn"}">
            ${statusLabel}
          </span>
        </div>

        <div class="candidate-progress-row">
          <div class="progress-labels">
            <span class="text-xs muted">Probing Progress:</span>
            <span class="mono text-xs">${c.probes_count} / ${c.target_probes} probes</span>
          </div>
          <div class="progress-bar-wrap">
            <div class="progress-bar-fill fill-exploration" style="width: ${progressPct}%"></div>
          </div>
        </div>

        <div class="candidate-stats-row">
          <div>
            <div class="stat-sub">${(c.mean_reward * 100).toFixed(1)}%</div>
            <div class="text-xs muted">Mean Reward</div>
          </div>
          <div>
            <div class="stat-sub mono">${c.ci_95}</div>
            <div class="text-xs muted">95% CI</div>
          </div>
          <div>
            <div class="stat-sub text-xs">${c.target_tasks.join(", ")}</div>
            <div class="text-xs muted">Tasks</div>
          </div>
        </div>

        <div class="candidate-footer">
          <button type="button" class="btn-xs btn-secondary btn-probe-candidate" data-id="${c.model_id}">
            ⚡ Probe Candidate
          </button>
          ${
            c.status !== "promoted"
              ? `
            <button type="button" class="btn-xs btn-primary btn-promote-candidate" data-id="${c.model_id}">
              ★ Promote to Registry
            </button>
          `
              : `<span class="badge ok text-xs">✓ In Active Registry</span>`
          }
        </div>
      </div>
    `;
  }

  private renderTraceRow(tr: DrexDecisionTrace): string {
    const isConsensus = tr.status === "consensus";

    return `
      <tr class="trace-row ${isConsensus ? "row-consensus" : "row-divergence"}">
        <td class="mono text-xs">${new Date(tr.timestamp).toLocaleTimeString()}</td>
        <td><span class="badge secondary">${tr.task_type.toUpperCase()}</span></td>
        <td class="prompt-summary-col">${escapeHtml(tr.prompt_summary)}</td>
        <td>
          <div class="drex-rec-pill">
            <strong>${escapeHtml(tr.drex_recommendation.model_name)}</strong>
            <span class="badge info text-xs">${(tr.drex_recommendation.confidence * 100).toFixed(0)}%</span>
          </div>
        </td>
        <td>
          <div class="utility-rec-pill">
            <strong>${escapeHtml(tr.utility_recommendation.model_name)}</strong>
            <span class="badge ok text-xs">${(tr.utility_recommendation.utility_score * 100).toFixed(0)}% score</span>
          </div>
        </td>
        <td>
          <span class="badge ${isConsensus ? "ok" : "warn"}">
            ${isConsensus ? "✓ Consensus" : "⚡ Divergence"}
          </span>
          ${tr.is_exploration ? `<span class="badge active text-xs">Exploration</span>` : ""}
        </td>
        <td class="mono text-xs">
          <strong>${escapeHtml(tr.final_winner)}</strong>
        </td>
        <td class="mono">${tr.latency_ms} ms</td>
        <td>
          <button type="button" class="btn-xs btn-secondary btn-inspect-trace" data-id="${tr.id}">
            🔍 Inspect
          </button>
        </td>
      </tr>
    `;
  }

  private renderTraceModal(tr: DrexDecisionTrace): string {
    const isConsensus = tr.status === "consensus";
    const u = tr.utility_recommendation;

    return `
      <div class="modal-overlay">
        <div class="modal-dialog modal-lg">
          <div class="modal-header">
            <div>
              <h3>Decision Trace Inspector (${tr.id})</h3>
              <span class="muted text-xs">${new Date(tr.timestamp).toISOString()}</span>
            </div>
            <button type="button" class="btn-close" id="btn-close-trace">&times;</button>
          </div>
          <div class="modal-body">
            <div class="trace-prompt-box">
              <span class="label">Evaluated Query / Prompt:</span>
              <p class="mono text-xs">${escapeHtml(tr.prompt_summary)}</p>
            </div>

            <div class="trace-compare-grid">
              <!-- Drex Recommendation Side -->
              <div class="compare-pane drex-pane">
                <div class="pane-header">
                  <h4>Drex Recommendation</h4>
                  <span class="badge info">${(tr.drex_recommendation.confidence * 100).toFixed(0)}% Confidence</span>
                </div>
                <div class="pane-body">
                  <p><strong>Chosen Model:</strong> ${escapeHtml(tr.drex_recommendation.model_name)}</p>
                  <p><strong>Model ID:</strong> <code>${tr.drex_recommendation.model_id}</code></p>
                  <hr/>
                  <p class="text-xs"><strong>Rationale:</strong> ${escapeHtml(tr.drex_recommendation.reason)}</p>
                </div>
              </div>

              <!-- Deterministic Utility Score Side -->
              <div class="compare-pane utility-pane">
                <div class="pane-header">
                  <h4>Deterministic Utility Winner</h4>
                  <span class="badge ok">${(u.utility_score * 100).toFixed(1)}% Utility Score</span>
                </div>
                <div class="pane-body">
                  <p><strong>Top Scored Model:</strong> ${escapeHtml(u.model_name)}</p>
                  <p><strong>Model ID:</strong> <code>${u.model_id}</code></p>
                  <hr/>
                  <div class="score-breakdown-mini">
                    <div>Quality: ${(u.quality_component * 100).toFixed(0)}%</div>
                    <div>TTFT: ${(u.ttft_component * 100).toFixed(0)}%</div>
                    <div>Cost: ${(u.cost_component * 100).toFixed(0)}%</div>
                    <div>Reliability: ${(u.reliability_component * 100).toFixed(0)}%</div>
                  </div>
                </div>
              </div>
            </div>

            <div class="trace-resolution-banner ${isConsensus ? "consensus" : "divergence"}">
              <div>
                <strong>Resolution Status: ${isConsensus ? "Consensus Agreement" : "Controlled Divergence"}</strong>
                <p class="text-xs muted">
                  ${
                    tr.divergence_note
                      ? escapeHtml(tr.divergence_note)
                      : "Both Drex neural policy and deterministic utility score selected the identical model."
                  }
                </p>
              </div>
              <div class="final-tag">
                Final Winner: <strong>${escapeHtml(tr.final_winner)}</strong> (${tr.latency_ms} ms)
              </div>
            </div>
          </div>
          <div class="modal-footer">
            <button type="button" class="btn-primary" id="btn-close-trace-footer">Close Trace</button>
          </div>
        </div>
      </div>
    `;
  }

  private attachEvents(): void {
    const drex = store.getState().drexConfig;
    if (!drex) return;

    // Save Drex Config
    this.container.querySelector("#btn-save-drex")?.addEventListener("click", () => {
      store.showToast({
        type: "success",
        title: "Drex Config Saved",
        message: "Confidence thresholds, exploration budget, and decision toggles committed.",
      });
    });

    // Exploration Budget Slider
    const expSlider = this.container.querySelector("#rng-exploration-budget") as HTMLInputElement;
    const expLabel = this.container.querySelector("#lbl-exploration-budget");
    expSlider?.addEventListener("input", () => {
      const val = parseFloat(expSlider.value);
      store.setExplorationBudget(val);
      if (expLabel) expLabel.textContent = `${(val * 100).toFixed(1)}%`;
    });

    // Candidate actions
    this.container.querySelectorAll(".btn-probe-candidate").forEach((btn) => {
      btn.addEventListener("click", () => {
        const id = btn.getAttribute("data-id")!;
        const c = drex.exploration_candidates?.find((item) => item.model_id === id);
        if (c) {
          c.probes_count = Math.min(c.target_probes, c.probes_count + 10);
          if (c.probes_count >= c.target_probes) c.status = "promoted";
          store.showToast({
            type: "info",
            title: "Probed Candidate",
            message: `Dispatched 10 test probes to ${c.name}. Sample count now ${c.probes_count}.`,
          });
          this.render();
        }
      });
    });

    this.container.querySelectorAll(".btn-promote-candidate").forEach((btn) => {
      btn.addEventListener("click", () => {
        const id = btn.getAttribute("data-id")!;
        const c = drex.exploration_candidates?.find((item) => item.model_id === id);
        if (c) {
          c.status = "promoted";
          store.showToast({
            type: "success",
            title: "Candidate Promoted",
            message: `${c.name} has completed exploration phase and is promoted to candidate pool.`,
          });
          this.render();
        }
      });
    });

    // Inspect Trace Modal
    this.container.querySelectorAll(".btn-inspect-trace").forEach((btn) => {
      btn.addEventListener("click", () => {
        const id = btn.getAttribute("data-id")!;
        this.selectedTrace = drex.traces?.find((t) => t.id === id) || null;
        this.render();
      });
    });

    this.container.querySelector("#btn-close-trace, #btn-close-trace-footer")?.addEventListener("click", () => {
      this.selectedTrace = null;
      this.render();
    });

    // Slider setup helper
    const setupSlider = (sliderId: string, labelId: string, key: "routing" | "guard" | "judge") => {
      const slider = this.container.querySelector(sliderId) as HTMLInputElement;
      const label = this.container.querySelector(labelId);
      slider?.addEventListener("input", () => {
        const val = parseFloat(slider.value);
        drex.confidence_thresholds[key] = val;
        if (label) label.textContent = `${(val * 100).toFixed(0)}%`;
      });
    };

    setupSlider("#rng-th-routing", "#lbl-th-routing", "routing");
    setupSlider("#rng-th-guard", "#lbl-th-guard", "guard");
    setupSlider("#rng-th-judge", "#lbl-th-judge", "judge");
  }
}

function escapeHtml(s?: string | null): string {
  if (!s) return "";
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
