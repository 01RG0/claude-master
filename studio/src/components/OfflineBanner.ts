// src/components/OfflineBanner.ts — Real-time daemon status & repair banner

import { store } from "../state/store.js";
import { t } from "../i18n/translations.js";
import { api } from "../state/api.js";

export class OfflineBanner {
  private element: HTMLElement;

  constructor() {
    this.element = document.createElement("div");
    this.element.className = "offline-banner hidden";
    this.element.setAttribute("role", "alert");

    store.subscribe((state) => {
      this.update(state.daemonStatus, state.reconnectCountdown);
    });
  }

  getElement(): HTMLElement {
    return this.element;
  }

  private update(status: "connected" | "reconnecting" | "offline", countdown: number): void {
    if (status === "connected") {
      this.element.classList.add("hidden");
      return;
    }

    const lang = store.getState().lang;
    this.element.classList.remove("hidden");
    this.element.innerHTML = `
      <div class="offline-banner-content">
        <div class="offline-icon-pulse">!</div>
        <div class="offline-text">
          <strong>${t("offlineBannerTitle", lang)}</strong>
          <span>${t("offlineBannerDesc", lang)} ${countdown > 0 ? `(Auto-retry in ${countdown}s)` : ""}</span>
        </div>
        <div class="offline-actions">
          <button type="button" class="btn-repair" id="btn-banner-repair">
            ${t("startRepairBtn", lang)}
          </button>
        </div>
      </div>
    `;

    this.element.querySelector("#btn-banner-repair")?.addEventListener("click", async () => {
      const btn = this.element.querySelector("#btn-banner-repair") as HTMLButtonElement;
      if (btn) {
        btn.disabled = true;
        btn.innerText = "Starting...";
      }
      const res = await api.startSystem();
      store.showToast({
        type: "success",
        title: "Repair Signal Sent",
        message: res.message,
      });
      setTimeout(() => {
        if (btn) {
          btn.disabled = false;
          btn.innerText = t("startRepairBtn", store.getState().lang);
        }
      }, 3000);
    });
  }
}
