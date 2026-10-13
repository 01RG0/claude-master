// src/components/CommandPalette.ts — Quick navigation and action palette (Ctrl+K)

import { store } from "../state/store.js";
import { t } from "../i18n/translations.js";
import type { ScreenId } from "../state/types.js";
import { api } from "../state/api.js";

interface CommandItem {
  id: string;
  title: string;
  category: "Screens" | "Actions";
  shortcut?: string;
  run: () => void;
}

export class CommandPalette {
  private container: HTMLElement;
  private input: HTMLInputElement | null = null;
  private selectedIndex = 0;
  private filteredItems: CommandItem[] = [];

  constructor() {
    this.container = document.createElement("div");
    this.container.className = "command-palette-overlay hidden";
    document.body.appendChild(this.container);

    window.addEventListener("keydown", (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        this.toggle();
      } else if (!this.container.classList.contains("hidden")) {
        if (e.key === "Escape") {
          e.preventDefault();
          this.close();
        } else if (e.key === "Enter") {
          e.preventDefault();
          if (this.filteredItems[this.selectedIndex]) {
            this.filteredItems[this.selectedIndex].run();
            this.close();
          }
        }
      }
    });

    store.subscribe((state) => {
      if (state.commandPaletteOpen && this.container.classList.contains("hidden")) {
        this.open();
      } else if (!state.commandPaletteOpen && !this.container.classList.contains("hidden")) {
        this.close();
      }
    });
  }

  private getItems(): CommandItem[] {
    const lang = store.getState().lang;
    const screens: { id: ScreenId; nameKey: Parameters<typeof t>[0] }[] = [
      { id: "setup", nameKey: "navSetup" },
      { id: "home", nameKey: "navHome" },
      { id: "providers", nameKey: "navProviders" },
      { id: "models", nameKey: "navModels" },
      { id: "routing", nameKey: "navRouting" },
      { id: "drex", nameKey: "navDrex" },
      { id: "privacy", nameKey: "navPrivacy" },
      { id: "budgets", nameKey: "navBudgets" },
      { id: "brain", nameKey: "navBrain" },
      { id: "claude_code", nameKey: "navClaudeCode" },
      { id: "settings", nameKey: "navSettings" },
      { id: "live_requests", nameKey: "navLiveRequests" },
      { id: "sessions", nameKey: "navSessions" },
      { id: "alerts", nameKey: "navAlerts" },
      { id: "doctor", nameKey: "navDoctor" },
      { id: "logs", nameKey: "navLogs" },
      { id: "detection", nameKey: "navDetection" },
      { id: "reports", nameKey: "navReports" },
      { id: "test_center", nameKey: "navTestCenter" },
      { id: "version_update", nameKey: "navVersionUpdate" },
    ];

    const screenCommands: CommandItem[] = screens.map((s) => ({
      id: "screen-" + s.id,
      title: `${t(s.nameKey, lang)} [Screen]`,
      category: "Screens",
      run: () => store.setScreen(s.id),
    }));

    const actionCommands: CommandItem[] = [
      {
        id: "act-doctor",
        title: "Run System Doctor Diagnostics",
        category: "Actions",
        run: () => store.setScreen("doctor"),
      },
      {
        id: "act-bypass",
        title: "Toggle Emergency Bypass Direct Mode",
        category: "Actions",
        run: () => store.setEmergencyBypass(!store.getState().emergencyBypass),
      },
      {
        id: "act-start",
        title: "Start System Daemons (Gateway + Brain)",
        category: "Actions",
        run: async () => {
          const res = await api.startSystem();
          store.showToast({ type: "info", title: "System Start", message: res.message });
        },
      },
      {
        id: "act-stop",
        title: "Stop System Daemons",
        category: "Actions",
        run: async () => {
          const res = await api.stopSystem();
          store.showToast({ type: "warning", title: "System Stop", message: res.message });
        },
      },
      {
        id: "act-mode",
        title: "Toggle Beginner / Expert Mode",
        category: "Actions",
        run: () => store.setUserMode(store.getState().userMode === "beginner" ? "expert" : "beginner"),
      },
    ];

    return [...screenCommands, ...actionCommands];
  }

  toggle(): void {
    if (this.container.classList.contains("hidden")) {
      this.open();
    } else {
      this.close();
    }
  }

  open(): void {
    this.container.classList.remove("hidden");
    store.getState().commandPaletteOpen = true;
    this.selectedIndex = 0;
    this.filteredItems = this.getItems();
    this.render();
    setTimeout(() => this.input?.focus(), 50);
  }

  close(): void {
    this.container.classList.add("hidden");
    store.getState().commandPaletteOpen = false;
  }

  private render(): void {
    const lang = store.getState().lang;
    this.container.innerHTML = `
      <div class="palette-dialog" role="dialog" aria-modal="true">
        <div class="palette-search-wrap">
          <input type="text" class="palette-input" placeholder="${t("searchPlaceholder", lang)}" autocomplete="off" />
          <span class="palette-esc-hint">ESC to close</span>
        </div>
        <div class="palette-results" role="listbox">
          ${this.renderResultList()}
        </div>
      </div>
    `;

    this.input = this.container.querySelector(".palette-input");
    this.input?.addEventListener("input", (e) => {
      const q = (e.target as HTMLInputElement).value.toLowerCase().trim();
      const all = this.getItems();
      this.filteredItems = q ? all.filter((item) => item.title.toLowerCase().includes(q)) : all;
      this.selectedIndex = 0;
      this.updateResultList();
    });

    this.input?.addEventListener("keydown", (e) => {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        this.selectedIndex = Math.min(this.selectedIndex + 1, this.filteredItems.length - 1);
        this.updateResultList();
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        this.selectedIndex = Math.max(this.selectedIndex - 1, 0);
        this.updateResultList();
      } else if (e.key === "Enter") {
        e.preventDefault();
        if (this.filteredItems[this.selectedIndex]) {
          this.filteredItems[this.selectedIndex].run();
          this.close();
        }
      } else if (e.key === "Escape") {
        e.preventDefault();
        this.close();
      }
    });

    this.container.addEventListener("click", (e) => {
      if (e.target === this.container) this.close();
    });
  }

  private updateResultList(): void {
    const listEl = this.container.querySelector(".palette-results");
    if (listEl) {
      listEl.innerHTML = this.renderResultList();
      this.attachResultListeners();
    }
  }

  private renderResultList(): string {
    if (this.filteredItems.length === 0) {
      return `<div class="palette-empty">No matching screens or actions found</div>`;
    }
    return this.filteredItems
      .map(
        (item, idx) => `
        <div class="palette-item ${idx === this.selectedIndex ? "selected" : ""}" data-idx="${idx}" role="option">
          <span class="palette-item-title">${escapeHtml(item.title)}</span>
          <span class="palette-item-cat">${escapeHtml(item.category)}</span>
        </div>
      `,
      )
      .join("");
  }

  private attachResultListeners(): void {
    const items = this.container.querySelectorAll(".palette-item");
    items.forEach((el) => {
      el.addEventListener("click", () => {
        const idx = parseInt(el.getAttribute("data-idx") || "0", 10);
        if (this.filteredItems[idx]) {
          this.filteredItems[idx].run();
          this.close();
        }
      });
    });
  }
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
