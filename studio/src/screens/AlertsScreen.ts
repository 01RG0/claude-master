// src/screens/AlertsScreen.ts — Health and Alerts Center

import { store } from "../state/store.js";
import { t } from "../i18n/translations.js";
import { renderCliSnippet } from "../components/CliSnippet.js";

export class AlertsScreen {
  private container: HTMLElement;
  private enableToastNotifications = true;

  constructor(container: HTMLElement) {
    this.container = container;
  }

  render(): void {
    const state = store.getState();
    const lang = state.lang;
    const alerts = state.alerts;

    this.container.innerHTML = `
      <div class="screen-header">
        <div>
          <h2>${t("alertsTitle", lang)}</h2>
          <p class="muted">${t("alertsSubtitle", lang)}</p>
        </div>
        <div class="btn-group">
          <label class="checkbox-label mr-3">
            <input type="checkbox" id="chk-desktop-toasts" ${this.enableToastNotifications ? "checked" : ""} />
            <span>Windows Desktop Toast Notifications</span>
          </label>
          <button type="button" class="btn-secondary" id="btn-ack-all">Acknowledge All</button>
        </div>
      </div>

      <!-- Alerts List -->
      <div class="alerts-stack">
        ${alerts
          .map(
            (a) => `
          <div class="card alert-card ${a.acknowledged ? "acknowledged" : ""}" data-id="${a.id}">
            <div class="alert-header">
              <span class="badge ${a.level === "critical" ? "warn" : a.level === "warning" ? "warn" : "info"}">
                ${a.level.toUpperCase()}
              </span>
              <strong>${escapeHtml(a.title)}</strong>
              <span class="muted text-xs ml-auto">${new Date(a.timestamp).toLocaleTimeString()}</span>
            </div>
            <p class="alert-message">${escapeHtml(a.message)}</p>
            ${
              a.fix_action
                ? `
              <div class="alert-fix-hint">
                <strong>Recommended Fix:</strong> ${escapeHtml(a.fix_action)}
              </div>
            `
                : ""
            }
            <div class="alert-actions">
              <button type="button" class="btn-xs btn-secondary btn-snooze" data-id="${a.id}" data-mins="15">Snooze 15m</button>
              <button type="button" class="btn-xs btn-secondary btn-snooze" data-id="${a.id}" data-mins="60">Snooze 1h</button>
              <button type="button" class="btn-xs btn-primary btn-ack" data-id="${a.id}">
                ${a.acknowledged ? "Acknowledged" : "Acknowledge / Dismiss"}
              </button>
            </div>
          </div>
        `,
          )
          .join("")}
      </div>

      ${renderCliSnippet("status --alerts", "Display active alert queue")}
    `;

    this.attachEvents();
  }

  private attachEvents(): void {
    this.container.querySelector("#btn-ack-all")?.addEventListener("click", () => {
      store.getState().alerts.forEach((a) => (a.acknowledged = true));
      store.showToast({ type: "info", title: "All Acknowledged", message: "Alerts cleared." });
      this.render();
    });

    this.container.querySelectorAll(".btn-snooze").forEach((btn) => {
      btn.addEventListener("click", () => {
        const id = btn.getAttribute("data-id")!;
        const mins = parseInt(btn.getAttribute("data-mins") || "60", 10);
        store.snoozeAlert(id, mins);
        this.render();
      });
    });

    this.container.querySelectorAll(".btn-ack").forEach((btn) => {
      btn.addEventListener("click", () => {
        const id = btn.getAttribute("data-id")!;
        store.acknowledgeAlert(id);
        this.render();
      });
    });

    this.container.querySelector("#chk-desktop-toasts")?.addEventListener("change", (e) => {
      this.enableToastNotifications = (e.target as HTMLInputElement).checked;
      store.showToast({
        type: "info",
        title: "Toast Setting",
        message: this.enableToastNotifications ? "Desktop toast notifications enabled." : "Desktop toasts disabled.",
      });
    });
  }
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
