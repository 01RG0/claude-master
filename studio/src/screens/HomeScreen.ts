// src/screens/HomeScreen.ts — Main Control Screen (Home Dashboard)

import { store } from "../state/store.js";
import { t } from "../i18n/translations.js";
import { renderCliSnippet } from "../components/CliSnippet.js";
import { ConfirmModal } from "../components/ConfirmModal.js";
import { api } from "../state/api.js";

export class HomeScreen {
  private container: HTMLElement;

  constructor(container: HTMLElement) {
    this.container = container;
  }

  render(): void {
    const state = store.getState();
    const lang = state.lang;
    const m = state.spendMetrics;
    const isBypass = state.emergencyBypass;
    const spendPct = Math.min(100, Math.round((m.daily_spent / m.daily_cap) * 100));

    this.container.innerHTML = `
      <div class="screen-header">
        <div>
          <h2>${t("homeTitle", lang)}</h2>
          <p class="muted">${t("homeSubtitle", lang)}</p>
        </div>
        <div class="btn-group">
          <button type="button" class="btn-primary" id="btn-home-start">
            ▶ ${t("startAll", lang)}
          </button>
          <button type="button" class="btn-secondary" id="btn-home-restart">
            🔄 ${t("restartAll", lang)}
          </button>
          <button type="button" class="btn-danger" id="btn-home-stop">
            ⏹ ${t("stopAll", lang)}
          </button>
        </div>
      </div>

      <!-- Emergency Bypass Banner Card -->
      <div class="card emergency-bypass-card ${isBypass ? "active" : ""}">
        <div class="bypass-left">
          <span class="bypass-icon">⚠️</span>
          <div>
            <strong>${isBypass ? "EMERGENCY BYPASS IS CURRENTLY ENGAGED" : "Direct Provider Bypass (Fallback Switch)"}</strong>
            <p class="muted">
              ${
                isBypass
                  ? "Local routing, caching, and redaction are suspended. All requests pass directly to the Anthropic API."
                  : "If anything goes wrong with local routing, toggle this to immediately fall back to standard Anthropic Claude."
              }
            </p>
          </div>
        </div>
        <button type="button" class="btn-bypass-toggle ${isBypass ? "active" : ""}" id="btn-home-bypass">
          ${isBypass ? "DISENGAGE BYPASS" : "ENGAGE EMERGENCY BYPASS"}
        </button>
      </div>

      <!-- System Health & Spend Metrics Grid -->
      <div class="dashboard-grid">
        <div class="metric-card">
          <div class="metric-label">System Daemons</div>
          <div class="component-status-rows">
            <div class="status-row"><span class="status-dot ok"></span> <strong>Gateway</strong> (port 8080)</div>
            <div class="status-row"><span class="status-dot ok"></span> <strong>Brain Daemon</strong> (port 7700)</div>
            <div class="status-row"><span class="status-dot ok"></span> <strong>Watchdog</strong> (PID alive)</div>
            <div class="status-row"><span class="status-dot ok"></span> <strong>Hookshim</strong> (port 7772)</div>
          </div>
        </div>

        <div class="metric-card">
          <div class="metric-label">Daily Spend vs Hard Cap</div>
          <div class="metric-value-huge">$${m.daily_spent.toFixed(2)} <small class="muted">/ $${m.daily_cap.toFixed(2)}</small></div>
          <div class="progress-bar-wrap">
            <div class="progress-bar" style="width: ${spendPct}%"></div>
          </div>
          <div class="metric-subtext">
            <span>${spendPct}% of daily budget used</span>
            <span class="text-ok">Honest Savings: +$${m.cache_savings_usd.toFixed(2)}</span>
          </div>
        </div>

        <div class="metric-card">
          <div class="metric-label">Proxy Reliability & Speed</div>
          <div class="metric-stat-row">
            <div>
              <div class="stat-num text-ok">${(m.error_rate * 100).toFixed(1)}%</div>
              <div class="muted">Error Rate</div>
            </div>
            <div>
              <div class="stat-num">${m.total_requests}</div>
              <div class="muted">Total Turns</div>
            </div>
            <div>
              <div class="stat-num text-ok">${(m.cache_hit_rate * 100).toFixed(0)}%</div>
              <div class="muted">Cache Hits</div>
            </div>
          </div>
        </div>
      </div>

      <!-- Attention List with 1-Click Fixes -->
      <div class="card attention-card">
        <div class="card-header">
          <h3>⚡ What Needs Attention (Actionable Items)</h3>
          <span class="badge info">2 Recommendations</span>
        </div>
        <div class="attention-list">
          <div class="attention-item">
            <span class="attn-badge warn">Quota Headroom</span>
            <div class="attn-content">
              <strong>Groq API Key 'personal-01' reached 86% of minute capacity</strong>
              <p class="muted">Heavy bursts may result in rate-limit cooldowns. Adding a secondary key pool will spread load.</p>
            </div>
            <button type="button" class="btn-sm btn-primary" id="btn-attn-add-key">
              + Add Backup Key to Pool
            </button>
          </div>

          <div class="attention-item">
            <span class="attn-badge info">Role Coverage</span>
            <div class="attn-content">
              <strong>Dedicated Vision Model Not Bound</strong>
              <p class="muted">Screenshot inspections currently fall back to general text model. Assigning a vision-tuned model improves image parsing accuracy.</p>
            </div>
            <button type="button" class="btn-sm btn-secondary" id="btn-attn-assign-vision">
              Assign Vision Role
            </button>
          </div>
        </div>
      </div>

      ${renderCliSnippet("status", "Check full component health from the command line")}
    `;

    this.attachEvents();
  }

  private attachEvents(): void {
    const lang = store.getState().lang;

    this.container.querySelector("#btn-home-start")?.addEventListener("click", async () => {
      const res = await api.startSystem();
      store.showToast({ type: "success", title: "Start Request", message: res.message });
    });

    this.container.querySelector("#btn-home-restart")?.addEventListener("click", async () => {
      const res = await api.restartSystem();
      store.showToast({ type: "info", title: "Restart Request", message: res.message });
    });

    this.container.querySelector("#btn-home-stop")?.addEventListener("click", () => {
      ConfirmModal.show({
        title: "Stop Claude Master Daemons?",
        message: "This will stop the Gateway, Brain, and Watchdog background services.",
        confirmLabel: "Stop Services",
        cancelLabel: t("cancel", lang),
        isDestructive: true,
        onConfirm: async () => {
          const res = await api.stopSystem();
          store.showToast({ type: "warning", title: "Services Stopped", message: res.message });
        },
      });
    });

    this.container.querySelector("#btn-home-bypass")?.addEventListener("click", () => {
      const isBypass = store.getState().emergencyBypass;
      if (!isBypass) {
        ConfirmModal.show({
          title: t("confirmBypassTitle", lang),
          message: t("confirmBypassBody", lang),
          confirmLabel: "Engage Emergency Bypass",
          cancelLabel: t("cancel", lang),
          isDestructive: true,
          onConfirm: () => {
            store.setEmergencyBypass(true);
            this.render();
          },
        });
      } else {
        store.setEmergencyBypass(false);
        this.render();
      }
    });

    this.container.querySelector("#btn-attn-add-key")?.addEventListener("click", () => {
      store.setScreen("providers");
    });

    this.container.querySelector("#btn-attn-assign-vision")?.addEventListener("click", () => {
      store.setScreen("routing");
    });
  }
}
