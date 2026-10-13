// src/components/Topbar.ts — Application header bar with toggles and status

import { store } from "../state/store.js";
import { t } from "../i18n/translations.js";
import { ConfirmModal } from "./ConfirmModal.js";

export class Topbar {
  private element: HTMLElement;

  constructor() {
    this.element = document.createElement("header");
    this.element.className = "topbar-shell";
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
    const isBypass = state.emergencyBypass;
    const isExpert = state.userMode === "expert";
    const isLight = state.theme === "light";

    this.element.innerHTML = `
      <div class="topbar-left">
        <div class="brand-title">
          <span class="brand-icon">⚡</span>
          <strong>${t("appName", lang)}</strong>
        </div>
        <div class="status-indicator-badge ${state.daemonStatus}">
          <span class="status-dot"></span>
          <span>${state.daemonStatus === "connected" ? t("statusConnected", lang) : state.daemonStatus === "reconnecting" ? t("statusReconnecting", lang) : t("statusOffline", lang)}</span>
        </div>
        ${
          isBypass
            ? `<div class="bypass-badge pulse">
                 <span>⚠️ ${t("emergencyBypassActive", lang)}</span>
               </div>`
            : ""
        }
      </div>

      <div class="topbar-center">
        <button type="button" class="search-command-btn" id="btn-open-palette" title="Ctrl+K">
          <span>🔍</span>
          <span class="search-placeholder-text">${t("searchPlaceholder", lang)}</span>
          <kbd>Ctrl+K</kbd>
        </button>
      </div>

      <div class="topbar-right">
        <!-- Emergency Bypass Switch -->
        <button type="button" class="btn-bypass-toggle ${isBypass ? "active" : ""}" id="btn-bypass" title="${t("emergencyBypassDesc", lang)}">
          ${isBypass ? "DISABLE BYPASS" : "EMERGENCY BYPASS"}
        </button>

        <!-- Beginner vs Expert Mode Toggle -->
        <div class="toggle-group" role="radiogroup" aria-label="User Mode">
          <button type="button" class="btn-toggle ${!isExpert ? "active" : ""}" id="btn-mode-beginner">
            ${t("beginnerMode", lang)}
          </button>
          <button type="button" class="btn-toggle ${isExpert ? "active" : ""}" id="btn-mode-expert">
            ${t("expertMode", lang)}
          </button>
        </div>

        <!-- Language Switcher -->
        <div class="toggle-group" role="radiogroup" aria-label="Language">
          <button type="button" class="btn-toggle ${lang === "en" ? "active" : ""}" id="btn-lang-en">EN</button>
          <button type="button" class="btn-toggle ${lang === "ar" ? "active" : ""}" id="btn-lang-ar">عربي</button>
        </div>

        <!-- Theme Toggle -->
        <button type="button" class="btn-icon-toggle" id="btn-theme" title="Toggle Dark/Light Mode">
          ${isLight ? "🌙" : "☀️"}
        </button>
      </div>
    `;

    // Event listeners
    this.element.querySelector("#btn-open-palette")?.addEventListener("click", () => {
      store.setCommandPaletteOpen(true);
    });

    this.element.querySelector("#btn-bypass")?.addEventListener("click", () => {
      if (!isBypass) {
        ConfirmModal.show({
          title: t("confirmBypassTitle", lang),
          message: t("confirmBypassBody", lang),
          confirmLabel: "Engage Direct Bypass",
          cancelLabel: t("cancel", lang),
          isDestructive: true,
          onConfirm: () => {
            store.setEmergencyBypass(true);
          },
        });
      } else {
        store.setEmergencyBypass(false);
      }
    });

    this.element.querySelector("#btn-mode-beginner")?.addEventListener("click", () => {
      store.setUserMode("beginner");
    });

    this.element.querySelector("#btn-mode-expert")?.addEventListener("click", () => {
      store.setUserMode("expert");
    });

    this.element.querySelector("#btn-lang-en")?.addEventListener("click", () => {
      store.setLanguage("en");
    });

    this.element.querySelector("#btn-lang-ar")?.addEventListener("click", () => {
      store.setLanguage("ar");
    });

    this.element.querySelector("#btn-theme")?.addEventListener("click", () => {
      store.setTheme(isLight ? "dark" : "light");
    });
  }
}
