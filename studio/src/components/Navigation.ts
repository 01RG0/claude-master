// src/components/Navigation.ts — Primary sidebar navigation component

import { store } from "../state/store.js";
import { t } from "../i18n/translations.js";
import type { ScreenId } from "../state/types.js";

interface NavItem {
  id: ScreenId;
  labelKey: Parameters<typeof t>[0];
  icon: string;
  badge?: () => string | number | null;
}

export class Navigation {
  private element: HTMLElement;

  constructor() {
    this.element = document.createElement("nav");
    this.element.className = "app-navigation";
    this.element.setAttribute("aria-label", "Main Navigation");
    this.render();

    store.subscribe(() => {
      this.render();
    });
  }

  getElement(): HTMLElement {
    return this.element;
  }

  private render(): void {
    const state = store.getState();
    const lang = state.lang;
    const current = state.currentScreen;

    const controlItems: NavItem[] = [
      { id: "home", labelKey: "navHome", icon: "🏠" },
      { id: "providers", labelKey: "navProviders", icon: "🔑" },
      { id: "models", labelKey: "navModels", icon: "🧠" },
      { id: "routing", labelKey: "navRouting", icon: "🔀" },
      { id: "drex", labelKey: "navDrex", icon: "🎯" },
      { id: "privacy", labelKey: "navPrivacy", icon: "🛡️" },
      { id: "budgets", labelKey: "navBudgets", icon: "💰" },
      { id: "brain", labelKey: "navBrain", icon: "🧬" },
      { id: "claude_code", labelKey: "navClaudeCode", icon: "💻" },
      { id: "settings", labelKey: "navSettings", icon: "⚙️" },
    ];

    const diagItems: NavItem[] = [
      { id: "live_requests", labelKey: "navLiveRequests", icon: "🌊", badge: () => state.liveRequests.length },
      { id: "sessions", labelKey: "navSessions", icon: "⏱️" },
      {
        id: "alerts",
        labelKey: "navAlerts",
        icon: "🔔",
        badge: () => {
          const count = state.alerts.filter((a) => !a.acknowledged).length;
          return count > 0 ? count : null;
        },
      },
      { id: "doctor", labelKey: "navDoctor", icon: "🩺" },
      { id: "logs", labelKey: "navLogs", icon: "📜" },
      { id: "detection", labelKey: "navDetection", icon: "🔍" },
      { id: "reports", labelKey: "navReports", icon: "📊" },
      { id: "test_center", labelKey: "navTestCenter", icon: "🧪" },
      { id: "version_update", labelKey: "navVersionUpdate", icon: "🚀" },
    ];

    const renderList = (items: NavItem[]) =>
      items
        .map((item) => {
          const active = current === item.id ? "active" : "";
          const badgeVal = item.badge ? item.badge() : null;
          return `
          <button type="button" class="nav-item ${active}" data-screen="${item.id}" role="tab" aria-selected="${current === item.id}">
            <span class="nav-icon">${item.icon}</span>
            <span class="nav-label">${t(item.labelKey, lang)}</span>
            ${badgeVal !== null ? `<span class="nav-badge">${badgeVal}</span>` : ""}
          </button>
        `;
        })
        .join("");

    this.element.innerHTML = `
      <div class="nav-wizard-card">
        <button type="button" class="btn-launch-wizard ${current === "setup" ? "active" : ""}" data-screen="setup">
          <span class="wizard-icon">🪄</span>
          <div class="wizard-text">
            <strong>${t("navSetup", lang)}</strong>
            <small>5-Step Guided Setup</small>
          </div>
        </button>
      </div>

      <div class="nav-section-title">CONTROL SCREENS</div>
      <div class="nav-section-group">
        ${renderList(controlItems)}
      </div>

      <div class="nav-section-title">TRACKING & DIAGNOSTICS</div>
      <div class="nav-section-group">
        ${renderList(diagItems)}
      </div>
    `;

    this.element.querySelectorAll("[data-screen]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const targetScreen = btn.getAttribute("data-screen") as ScreenId;
        if (targetScreen) {
          store.setScreen(targetScreen);
        }
      });
    });
  }
}
