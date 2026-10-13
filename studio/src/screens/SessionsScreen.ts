// src/screens/SessionsScreen.ts — Claude Code Sessions Replay & History

import { store } from "../state/store.js";
import { t } from "../i18n/translations.js";
import { renderCliSnippet } from "../components/CliSnippet.js";

export class SessionsScreen {
  private container: HTMLElement;

  constructor(container: HTMLElement) {
    this.container = container;
  }

  render(): void {
    const state = store.getState();
    const lang = state.lang;
    const sessions = state.sessions;

    this.container.innerHTML = `
      <div class="screen-header">
        <div>
          <h2>${t("sessionsTitle", lang)}</h2>
          <p class="muted">${t("sessionsSubtitle", lang)}</p>
        </div>
      </div>

      <!-- Sessions Table -->
      <div class="card">
        <div class="card-header">
          <h3>Claude Code Session Log</h3>
          <span class="badge info">${sessions.length} Recorded Sessions</span>
        </div>
        <table class="data-table">
          <thead>
            <tr>
              <th>Session ID</th>
              <th>Task / Goal</th>
              <th>Duration</th>
              <th>Turn Count</th>
              <th>Models Used</th>
              <th>Total Cost</th>
              <th>Failovers</th>
              <th>Outcome</th>
              <th>Replay</th>
            </tr>
          </thead>
          <tbody>
            ${sessions
              .map(
                (s) => `
              <tr>
                <td class="mono font-semibold">${s.id}</td>
                <td><strong>${escapeHtml(s.title)}</strong></td>
                <td>${Math.round(s.duration_s / 60)} min</td>
                <td>${s.request_count} turns</td>
                <td>
                  ${s.models_used.map((m) => `<span class="badge secondary">${escapeHtml(m)}</span>`).join(" ")}
                </td>
                <td class="mono font-semibold">$${s.total_cost_usd.toFixed(4)}</td>
                <td>
                  <span class="badge ${s.failovers > 0 ? "warn" : "ok"}">${s.failovers} failovers</span>
                </td>
                <td><span class="badge ok">${s.outcome.toUpperCase()}</span></td>
                <td>
                  <button type="button" class="btn-xs btn-primary btn-replay-session" data-id="${s.id}">Replay</button>
                </td>
              </tr>
            `,
              )
              .join("")}
          </tbody>
        </table>
      </div>

      <!-- Timeline Replay Box -->
      <div class="card replay-pane">
        <div class="card-header">
          <h4>Session Timeline Replay: <span class="mono">ses-991</span></h4>
        </div>
        <div class="session-replay-timeline">
          <div class="replay-step"><span class="badge ok">00:00</span> Prompt Inbound: "Build and verify Claude Master Studio UI"</div>
          <div class="replay-step"><span class="badge active">00:02</span> Hookshim pre-tool verification: npm test & npm run build</div>
          <div class="replay-step"><span class="badge secondary">00:15</span> Codestral 2501 generated UI components</div>
          <div class="replay-step"><span class="badge ok">30:00</span> Task Completed successfully with zero terminal errors</div>
        </div>
      </div>

      ${renderCliSnippet("sessions --list", "List past Claude Code sessions")}
    `;

    this.attachEvents();
  }

  private attachEvents(): void {
    this.container.querySelectorAll(".btn-replay-session").forEach((btn) => {
      btn.addEventListener("click", () => {
        const id = btn.getAttribute("data-id");
        store.showToast({
          type: "info",
          title: "Session Replay",
          message: `Replaying timeline events for session ${id}.`,
        });
      });
    });
  }
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
