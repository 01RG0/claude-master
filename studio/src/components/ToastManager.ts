// src/components/ToastManager.ts — Toast alerts manager

import { store } from "../state/store.js";

export class ToastManager {
  private container: HTMLElement;

  constructor() {
    this.container = document.createElement("div");
    this.container.className = "toast-container";
    this.container.setAttribute("aria-live", "polite");
    document.body.appendChild(this.container);

    store.subscribe((state) => {
      this.render(state.toasts);
    });
  }

  private render(toasts: ReturnType<typeof store.getState>["toasts"]): void {
    this.container.innerHTML = toasts
      .map(
        (t) => `
        <div class="toast-item toast-${t.type}" data-id="${t.id}" role="alert">
          <div class="toast-content">
            <strong class="toast-title">${escapeHtml(t.title)}</strong>
            <p class="toast-message">${escapeHtml(t.message)}</p>
          </div>
          <button type="button" class="toast-dismiss" aria-label="Dismiss">&times;</button>
        </div>
      `,
      )
      .join("");

    this.container.querySelectorAll(".toast-dismiss").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        const item = (e.target as HTMLElement).closest(".toast-item");
        const id = item?.getAttribute("data-id");
        if (id) store.dismissToast(id);
      });
    });
  }
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
