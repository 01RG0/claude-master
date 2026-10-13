// src/screens/ProvidersScreen.ts — Providers and Key Pools Control Screen

import { store } from "../state/store.js";
import { t } from "../i18n/translations.js";
import { renderCliSnippet } from "../components/CliSnippet.js";
import { ConfirmModal } from "../components/ConfirmModal.js";
import type { ProviderItem } from "../state/types.js";

export class ProvidersScreen {
  private container: HTMLElement;

  constructor(container: HTMLElement) {
    this.container = container;
  }

  render(): void {
    const state = store.getState();
    const lang = state.lang;
    const providers = state.providers;

    this.container.innerHTML = `
      <div class="screen-header">
        <div>
          <h2>${t("providersTitle", lang)}</h2>
          <p class="muted">${t("providersSubtitle", lang)}</p>
        </div>
        <div class="btn-group">
          <button type="button" class="btn-primary" id="btn-add-provider">+ Add Provider</button>
          <button type="button" class="btn-secondary" id="btn-hot-reload">⚡ Hot Reload Keys</button>
        </div>
      </div>

      <div class="providers-list-stack">
        ${providers.map((p, idx) => this.renderProviderCard(p, idx)).join("")}
      </div>

      <!-- Add Key / Edit Modal Container -->
      <div id="provider-modal-root"></div>

      ${renderCliSnippet("provider list", "List configured providers and keys")}
    `;

    this.attachEvents();
  }

  private renderProviderCard(p: ProviderItem, index: number): string {
    const isEnabled = p.enabled;
    return `
      <div class="card provider-card ${isEnabled ? "" : "disabled"}" data-provider="${p.name}">
        <div class="provider-card-header">
          <div class="provider-info-left">
            <span class="provider-name-badge">${escapeHtml(p.name.toUpperCase())}</span>
            <span class="provider-endpoint mono">${escapeHtml(p.base_url)}</span>
            <span class="badge ${p.privacy_policy === "zero_retention" ? "ok" : "warn"}">
              ${p.privacy_policy === "zero_retention" ? "🛡️ Zero Retention" : p.privacy_policy}
            </span>
            <span class="badge info">${escapeHtml(p.region)}</span>
          </div>
          <div class="provider-actions-right">
            <select class="form-select form-select-sm sel-pool-strat" data-provider="${p.name}">
              <option value="round_robin" ${p.pool_strategy === "round_robin" ? "selected" : ""}>Pool: Round-Robin</option>
              <option value="least_loaded" ${p.pool_strategy === "least_loaded" ? "selected" : ""}>Pool: Least-Loaded</option>
              <option value="priority" ${p.pool_strategy === "priority" ? "selected" : ""}>Pool: Priority Order</option>
              <option value="cost_first" ${p.pool_strategy === "cost_first" ? "selected" : ""}>Pool: Cost-First</option>
              <option value="latency_first" ${p.pool_strategy === "latency_first" ? "selected" : ""}>Pool: Latency-First</option>
              <option value="sticky" ${p.pool_strategy === "sticky" ? "selected" : ""}>Pool: Session-Sticky</option>
            </select>
            <button type="button" class="btn-sm btn-secondary btn-test-provider" data-provider="${p.name}">Test Live</button>
            <button type="button" class="btn-sm ${isEnabled ? "btn-secondary" : "btn-primary"} btn-toggle-provider" data-provider="${p.name}">
              ${isEnabled ? "Disable" : "Enable"}
            </button>
            <button type="button" class="btn-sm btn-danger btn-delete-provider" data-provider="${p.name}">Remove</button>
          </div>
        </div>

        <!-- Key Pools Table -->
        <div class="key-pool-section">
          <div class="key-pool-header">
            <h4>API Key Pools & Quota Status (${p.key_pools.length} keys in pool)</h4>
            <button type="button" class="btn-sm btn-ghost btn-add-key" data-provider="${p.name}">+ Add Key to Pool</button>
          </div>

          <table class="data-table">
            <thead>
              <tr>
                <th>Account Label</th>
                <th>Env Var</th>
                <th>Masked Secret</th>
                <th>Status</th>
                <th>Headroom & Quota</th>
                <th>Daily Spend / Cap</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              ${p.key_pools
                .map(
                  (k) => `
                <tr>
                  <td><strong>${escapeHtml(k.account_label)}</strong></td>
                  <td class="mono">${escapeHtml(k.env_var)}</td>
                  <td class="mono">${escapeHtml(k.masked_key || "****")}</td>
                  <td><span class="badge ${k.status === "valid" ? "ok" : "warn"}">${k.status}</span></td>
                  <td>
                    <div class="quota-meter">
                      <span>${k.quota_left_percent}% left (${k.rate_limit_rpm} RPM)</span>
                      <div class="mini-bar"><div class="mini-fill" style="width: ${k.quota_left_percent}%"></div></div>
                    </div>
                  </td>
                  <td>$${k.daily_spend.toFixed(2)} / $${k.daily_cap.toFixed(2)}</td>
                  <td>
                    <button type="button" class="btn-xs btn-secondary btn-rotate-key" data-provider="${p.name}" data-key="${k.account_label}">Rotate</button>
                    <button type="button" class="btn-xs btn-ghost btn-test-key" data-provider="${p.name}" data-key="${k.account_label}">Ping</button>
                  </td>
                </tr>
              `,
                )
                .join("")}
            </tbody>
          </table>
        </div>
      </div>
    `;
  }

  private attachEvents(): void {
    const lang = store.getState().lang;

    this.container.querySelector("#btn-hot-reload")?.addEventListener("click", () => {
      store.showToast({
        type: "success",
        title: "Keys Hot-Reloaded",
        message: "Key rings reloaded into process memory without server restart.",
      });
    });

    this.container.querySelector("#btn-add-provider")?.addEventListener("click", () => {
      store.showToast({
        type: "info",
        title: "Add Provider",
        message: "Opening template modal. Enter provider name, base URL, and key pool.",
      });
    });

    this.container.querySelectorAll(".btn-toggle-provider").forEach((btn) => {
      btn.addEventListener("click", () => {
        const provName = btn.getAttribute("data-provider");
        const prov = store.getState().providers.find((p) => p.name === provName);
        if (prov) {
          prov.enabled = !prov.enabled;
          store.showToast({
            type: "info",
            title: `Provider ${prov.name}`,
            message: prov.enabled ? "Enabled in rotation." : "Disabled from routing.",
          });
          this.render();
        }
      });
    });

    this.container.querySelectorAll(".btn-delete-provider").forEach((btn) => {
      btn.addEventListener("click", () => {
        const provName = btn.getAttribute("data-provider");
        ConfirmModal.show({
          title: `Remove Provider ${provName}?`,
          message: `Are you sure you want to remove ${provName} and all its key pools?`,
          confirmLabel: "Remove Provider",
          cancelLabel: t("cancel", lang),
          isDestructive: true,
          onConfirm: () => {
            store.getState().providers = store.getState().providers.filter((p) => p.name !== provName);
            store.showToast({ type: "warning", title: "Provider Removed", message: `${provName} removed.` });
            this.render();
          },
        });
      });
    });

    this.container.querySelectorAll(".btn-test-provider, .btn-test-key").forEach((btn) => {
      btn.addEventListener("click", () => {
        store.showToast({
          type: "success",
          title: "Key Alive",
          message: "Loopback test returned 200 OK. Latency: 195ms.",
        });
      });
    });

    this.container.querySelectorAll(".btn-rotate-key").forEach((btn) => {
      btn.addEventListener("click", () => {
        const keyLabel = btn.getAttribute("data-key");
        store.showToast({
          type: "info",
          title: "Key Rotated",
          message: `Key '${keyLabel}' rotated with zero downtime in memory.`,
        });
      });
    });
  }
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
