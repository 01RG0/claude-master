// src/screens/LiveRequestsScreen.ts — Live Requests Stream, Waterfall Timeline & Plain Explanations

import { store } from "../state/store.js";
import { t } from "../i18n/translations.js";
import { renderCliSnippet } from "../components/CliSnippet.js";
import type { LiveRequestEvent } from "../state/types.js";

export class LiveRequestsScreen {
  private container: HTMLElement;
  private selectedRequestId: string | null = null;
  private filterProvider = "all";
  private filterStatus = "all";

  constructor(container: HTMLElement) {
    this.container = container;
  }

  render(): void {
    const state = store.getState();
    const lang = state.lang;
    let requests = state.liveRequests;

    if (this.filterProvider !== "all") {
      requests = requests.filter((r) => r.provider === this.filterProvider);
    }
    if (this.filterStatus !== "all") {
      requests = requests.filter((r) => String(r.status_code) === this.filterStatus);
    }

    const selected = requests.find((r) => r.id === this.selectedRequestId) || requests[0] || null;

    this.container.innerHTML = `
      <div class="screen-header">
        <div>
          <h2>${t("liveRequestsTitle", lang)}</h2>
          <p class="muted">${t("liveRequestsSubtitle", lang)}</p>
        </div>
        <div class="btn-group">
          <button type="button" class="btn-primary" id="btn-stream-live">● Live Streaming Active</button>
        </div>
      </div>

      <!-- Filter Bar -->
      <div class="card filter-bar">
        <div class="filter-group">
          <label>Provider:</label>
          <select class="form-select form-select-sm" id="sel-filter-prov">
            <option value="all">All Providers</option>
            <option value="groq" ${this.filterProvider === "groq" ? "selected" : ""}>Groq</option>
            <option value="cerebras" ${this.filterProvider === "cerebras" ? "selected" : ""}>Cerebras</option>
            <option value="mistral" ${this.filterProvider === "mistral" ? "selected" : ""}>Mistral</option>
          </select>
        </div>
        <div class="filter-group">
          <label>Status Code:</label>
          <select class="form-select form-select-sm" id="sel-filter-status">
            <option value="all">All Codes</option>
            <option value="200" ${this.filterStatus === "200" ? "selected" : ""}>200 OK</option>
            <option value="429" ${this.filterStatus === "429" ? "selected" : ""}>429 Rate Limit</option>
            <option value="500" ${this.filterStatus === "500" ? "selected" : ""}>500 Error</option>
          </select>
        </div>
        <span class="muted text-sm ml-auto">Showing ${requests.length} events</span>
      </div>

      <!-- Two-Column Layout: Virtualized Requests Table + Waterfall Drilldown -->
      <div class="requests-split-view">
        <!-- Requests List -->
        <div class="card requests-table-pane">
          <table class="data-table">
            <thead>
              <tr>
                <th>Time</th>
                <th>Status</th>
                <th>Model</th>
                <th>Tokens</th>
                <th>TTFT</th>
                <th>Cost</th>
              </tr>
            </thead>
            <tbody>
              ${requests
                .map(
                  (r) => `
                <tr class="clickable-row ${selected?.id === r.id ? "row-selected" : ""}" data-id="${r.id}">
                  <td class="mono text-xs">${new Date(r.timestamp).toLocaleTimeString()}</td>
                  <td><span class="badge ${r.status_code === 200 ? "ok" : "warn"}">${r.status_code}</span></td>
                  <td>
                    <strong>${escapeHtml(r.model)}</strong>
                    <div class="muted text-xs">${escapeHtml(r.provider)}</div>
                  </td>
                  <td class="mono">${r.total_tokens} ${r.cached ? '<span class="text-ok">⚡</span>' : ""}</td>
                  <td class="mono">${r.duration_ms}ms</td>
                  <td class="mono text-xs">$${r.cost_usd.toFixed(5)}</td>
                </tr>
              `,
                )
                .join("")}
            </tbody>
          </table>
        </div>

        <!-- Waterfall Timeline & Explain This Pane -->
        <div class="card request-detail-pane">
          ${selected ? this.renderRequestDetail(selected) : `<div class="p-6 muted">Select a request to inspect timeline</div>`}
        </div>
      </div>

      ${renderCliSnippet("logs --follow", "Follow live request stream in terminal")}
    `;

    this.attachEvents();
  }

  private renderRequestDetail(r: LiveRequestEvent): string {
    return `
      <div class="detail-header">
        <h4>Request Trace: <span class="mono">${r.id}</span></h4>
        <span class="badge ${r.status_code === 200 ? "ok" : "warn"}">${r.status_code} OK</span>
      </div>

      <!-- Plain Language Explain This -->
      <div class="explain-box">
        <div class="explain-title">💡 Plain-Language Summary ("Explain This"):</div>
        <p class="explain-text">${escapeHtml(r.explanation)}</p>
      </div>

      <!-- Full Timeline Waterfall -->
      <div class="waterfall-section">
        <h5>Execution Waterfall Breakdown:</h5>
        <div class="waterfall-timeline">
          ${r.timeline
            .map(
              (step) => `
            <div class="waterfall-step">
              <div class="waterfall-step-info">
                <strong>${escapeHtml(step.step)}</strong>
                <span class="muted text-xs">${escapeHtml(step.detail)}</span>
              </div>
              <span class="waterfall-duration mono">${step.duration_ms} ms</span>
            </div>
          `,
            )
            .join("")}
        </div>
      </div>

      <!-- Token & Cost Breakdown -->
      <div class="token-cost-grid">
        <div class="stat-box">
          <div class="muted text-xs">Prompt Tokens</div>
          <strong>${r.prompt_tokens}</strong>
        </div>
        <div class="stat-box">
          <div class="muted text-xs">Completion Tokens</div>
          <strong>${r.completion_tokens}</strong>
        </div>
        <div class="stat-box">
          <div class="muted text-xs">Cache Status</div>
          <strong class="${r.cached ? "text-ok" : ""}">${r.cached ? "HIT (Saved Tokens)" : "MISS"}</strong>
        </div>
        <div class="stat-box">
          <div class="muted text-xs">Calculated Cost</div>
          <strong>$${r.cost_usd.toFixed(5)}</strong>
        </div>
      </div>
    `;
  }

  private attachEvents(): void {
    this.container.querySelectorAll(".clickable-row").forEach((row) => {
      row.addEventListener("click", () => {
        this.selectedRequestId = row.getAttribute("data-id");
        this.render();
      });
    });

    this.container.querySelector("#sel-filter-prov")?.addEventListener("change", (e) => {
      this.filterProvider = (e.target as HTMLSelectElement).value;
      this.render();
    });

    this.container.querySelector("#sel-filter-status")?.addEventListener("change", (e) => {
      this.filterStatus = (e.target as HTMLSelectElement).value;
      this.render();
    });

    this.container.querySelector("#btn-stream-live")?.addEventListener("click", () => {
      store.showToast({
        type: "info",
        title: "Streaming Active",
        message: "Listening for real-time WebSocket requests.",
      });
    });
  }
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
