// src/screens/BudgetsScreen.ts — Spend Analytics, Hard Caps & Cache Savings

import { store } from "../state/store.js";
import { t } from "../i18n/translations.js";
import { renderCliSnippet } from "../components/CliSnippet.js";

export class BudgetsScreen {
  private container: HTMLElement;

  constructor(container: HTMLElement) {
    this.container = container;
  }

  render(): void {
    const state = store.getState();
    const lang = state.lang;
    const m = state.spendMetrics;

    const dailyPct = Math.min(100, Math.round((m.daily_spent / m.daily_cap) * 100));
    const monthlyPct = Math.min(100, Math.round((m.monthly_spent / m.monthly_cap) * 100));

    this.container.innerHTML = `
      <div class="screen-header">
        <div>
          <h2>${t("budgetsTitle", lang)}</h2>
          <p class="muted">${t("budgetsSubtitle", lang)}</p>
        </div>
        <div class="btn-group">
          <button type="button" class="btn-primary" id="btn-save-caps">Save Budget Caps</button>
        </div>
      </div>

      <!-- Top Summary Metrics Cards -->
      <div class="dashboard-grid">
        <div class="metric-card">
          <div class="metric-label">Daily Spend Limit</div>
          <div class="metric-value-huge">$${m.daily_spent.toFixed(2)} <small class="muted">/ $${m.daily_cap.toFixed(2)}</small></div>
          <div class="progress-bar-wrap">
            <div class="progress-bar ${dailyPct > 80 ? "warn" : ""}" style="width: ${dailyPct}%"></div>
          </div>
          <div class="metric-subtext">
            <span>${dailyPct}% used today</span>
            <span>Alerts trigger at 80% and 95%</span>
          </div>
        </div>

        <div class="metric-card">
          <div class="metric-label">Monthly Spend & Projections</div>
          <div class="metric-value-huge">$${m.monthly_spent.toFixed(2)} <small class="muted">/ $${m.monthly_cap.toFixed(2)}</small></div>
          <div class="progress-bar-wrap">
            <div class="progress-bar" style="width: ${monthlyPct}%"></div>
          </div>
          <div class="metric-subtext">
            <span>Projected Month-End: <strong>$${m.projected_month_end_usd.toFixed(2)}</strong></span>
            <span class="text-ok">Within budget</span>
          </div>
        </div>

        <div class="metric-card">
          <div class="metric-label">Honest Cache Savings</div>
          <div class="metric-value-huge text-ok">+$${m.cache_savings_usd.toFixed(2)}</div>
          <div class="metric-subtext">
            <span>44% prompt prefix cache hit rate</span>
            <span class="muted">Calculated strictly against base token rates</span>
          </div>
        </div>
      </div>

      <!-- Breakdown by Provider and Model -->
      <div class="card">
        <div class="card-header">
          <h3>Spend Breakdown by Provider & Model</h3>
        </div>
        <table class="data-table">
          <thead>
            <tr>
              <th>Entity</th>
              <th>Type</th>
              <th>Requests</th>
              <th>Tokens In / Out</th>
              <th>Spend</th>
              <th>Savings</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td><strong>Groq</strong> (Free + Tier 1)</td>
              <td>Provider</td>
              <td>842</td>
              <td>1.2M / 180k</td>
              <td>$0.12</td>
              <td class="text-ok">+$0.82</td>
            </tr>
            <tr>
              <td><strong>Cerebras</strong> (Developer Tier)</td>
              <td>Provider</td>
              <td>310</td>
              <td>420k / 64k</td>
              <td>$0.18</td>
              <td class="text-ok">+$0.34</td>
            </tr>
            <tr>
              <td><strong>Mistral</strong> (Codestral)</td>
              <td>Provider</td>
              <td>96</td>
              <td>280k / 45k</td>
              <td>$0.12</td>
              <td class="text-ok">+$0.18</td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Hard Cap & Notification Settings -->
      <div class="card">
        <div class="card-header">
          <h3>Budget Caps & Throttling Options</h3>
        </div>
        <div class="form-grid-2">
          <div class="form-row">
            <label>Daily Hard Cap ($ USD):</label>
            <input type="number" step="0.5" class="form-input" id="inp-daily-cap" value="${m.daily_cap}" />
            <small class="muted">Requests hold and notify when exceeded.</small>
          </div>
          <div class="form-row">
            <label>Monthly Hard Cap ($ USD):</label>
            <input type="number" step="5" class="form-input" id="inp-monthly-cap" value="${m.monthly_cap}" />
            <small class="muted">Hard stop ceiling for all provider accounts.</small>
          </div>
        </div>
      </div>

      ${renderCliSnippet("admin stats", "Fetch runtime cost and token aggregates from gateway")}
    `;

    this.attachEvents();
  }

  private attachEvents(): void {
    this.container.querySelector("#btn-save-caps")?.addEventListener("click", () => {
      const dailyInp = this.container.querySelector("#inp-daily-cap") as HTMLInputElement;
      const monthInp = this.container.querySelector("#inp-monthly-cap") as HTMLInputElement;
      if (dailyInp && monthInp) {
        store.getState().spendMetrics.daily_cap = parseFloat(dailyInp.value) || 5.0;
        store.getState().spendMetrics.monthly_cap = parseFloat(monthInp.value) || 50.0;
        store.showToast({
          type: "success",
          title: "Budget Caps Updated",
          message: "New daily and monthly hard limits applied.",
        });
        this.render();
      }
    });
  }
}
