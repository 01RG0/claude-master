// src/components/ConfirmModal.ts — Safe-by-default destructive action modal

export interface ConfirmModalOptions {
  title: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  isDestructive?: boolean;
  onConfirm: () => void;
  onCancel?: () => void;
}

export class ConfirmModal {
  private static instance: ConfirmModal | null = null;
  private container: HTMLElement;

  constructor() {
    this.container = document.createElement("div");
    this.container.className = "modal-overlay hidden";
    this.container.setAttribute("role", "dialog");
    this.container.setAttribute("aria-modal", "true");
    document.body.appendChild(this.container);
  }

  static show(options: ConfirmModalOptions): void {
    if (!ConfirmModal.instance) {
      ConfirmModal.instance = new ConfirmModal();
    }
    ConfirmModal.instance.render(options);
  }

  private render(options: ConfirmModalOptions): void {
    const confirmClass = options.isDestructive ? "btn-danger" : "btn-primary";
    this.container.innerHTML = `
      <div class="modal-dialog">
        <div class="modal-header">
          <h3>${escapeHtml(options.title)}</h3>
          <button type="button" class="btn-close" aria-label="Close">&times;</button>
        </div>
        <div class="modal-body">
          <p>${escapeHtml(options.message)}</p>
        </div>
        <div class="modal-footer">
          <button type="button" class="btn-secondary btn-cancel">${escapeHtml(options.cancelLabel || "Cancel")}</button>
          <button type="button" class="${confirmClass} btn-confirm">${escapeHtml(options.confirmLabel || "Confirm")}</button>
        </div>
      </div>
    `;

    this.container.classList.remove("hidden");

    const close = () => {
      this.container.classList.add("hidden");
      if (options.onCancel) options.onCancel();
    };

    this.container.querySelector(".btn-close")?.addEventListener("click", close);
    this.container.querySelector(".btn-cancel")?.addEventListener("click", close);

    this.container.querySelector(".btn-confirm")?.addEventListener("click", () => {
      this.container.classList.add("hidden");
      options.onConfirm();
    });

    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        close();
        window.removeEventListener("keydown", handleKey);
      }
    };
    window.addEventListener("keydown", handleKey);
  }
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
