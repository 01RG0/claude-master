// src/screens/DetectionScreen.ts — Detection and Capability History Timeline with Diffs

import { store } from "../state/store.js";
import { t } from "../i18n/translations.js";
import { renderCliSnippet } from "../components/CliSnippet.js";

export class DetectionScreen {
  private container: HTMLElement;

  constructor(container: HTMLElement) {
    this.container = container;
  }

  render(): void {
    const state = store.getState();
    const lang = state.lang;
    const history = state.detectionHistory;

    this.container.innerHTML = `
      <div class="screen-header">
        <div>
          <h2>${t("detectionTitle", lang)}</h2>
          <p class="muted">${t("detectionSubtitle", lang)}</p>
        </div>
        <button type="button" class="btn-primary" id="btn-run-detect-all">
          🔍 Run detect_all.py Probe
        </button>
      </div>

      <!-- Timeline of Changes with Diffs -->
      <div class="timeline-container">
        ${history
          .map(
            (item) => `
          <div class="timeline-card">
            <div class="timeline-meta">
              <span class="badge ${item.change_type === "added" ? "ok" : "info"}">
                ${item.change_type.toUpperCase()}
              </span>
              <strong>${escapeHtml(item.model)}</strong> (${escapeHtml(item.provider)})
              <span class="muted text-xs ml-auto">${new Date(item.timestamp).toLocaleString()}</span>
            </div>
            <p class="timeline-detail">${escapeHtml(item.details)}</p>
            <div class="diff-viewer">
              <div class="diff-pane before">
                <span class="diff-label">Previous State:</span>
                <pre><code>${escapeHtml(item.diff.before)}</code></pre>
              </div>
              <div class="diff-pane after">
                <span class="diff-label">Detected / New State:</span>
                <pre><code>${escapeHtml(item.diff.after)}</code></pre>
              </div>
            </div>
          </div>
        `,
          )
          .join("")}
      </div>

      ${renderCliSnippet("detect", "Execute full detector scripts/detect_all.py")}
    `;

    this.attachEvents();
  }

  private attachEvents(): void {
    this.container.querySelector("#btn-run-detect-all")?.addEventListener("click", () => {
      store.showToast({
        type: "info",
        title: "Detector Running",
        message: "Scraping endpoints, reading context limits and model catalogs.",
      });
    });
  }
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
