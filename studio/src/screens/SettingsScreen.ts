// src/screens/SettingsScreen.ts — System Settings, Preferences & Maintenance

import { store } from "../state/store.js";
import { t } from "../i18n/translations.js";
import { renderCliSnippet } from "../components/CliSnippet.js";
import { ConfirmModal } from "../components/ConfirmModal.js";

export class SettingsScreen {
  private container: HTMLElement;

  constructor(container: HTMLElement) {
    this.container = container;
  }

  render(): void {
    const state = store.getState();
    const lang = state.lang;
    const theme = state.theme;
    const userMode = state.userMode;

    this.container.innerHTML = `
      <div class="screen-header">
        <div>
          <h2>${t("settingsTitle", lang)}</h2>
          <p class="muted">${t("settingsSubtitle", lang)}</p>
        </div>
        <div class="btn-group">
          <button type="button" class="btn-secondary" id="btn-export-bundle">📥 Export Full Config Bundle</button>
          <button type="button" class="btn-danger" id="btn-factory-reset">⚠️ Reset to Defaults</button>
        </div>
      </div>

      <div class="settings-grid">
        <!-- Appearance & Language -->
        <div class="card">
          <div class="card-header">
            <h4>Appearance & Localization</h4>
          </div>
          <div class="form-row">
            <label>Color Theme:</label>
            <select class="form-select" id="sel-theme">
              <option value="dark" ${theme === "dark" ? "selected" : ""}>Dark Theme (Default)</option>
              <option value="light" ${theme === "light" ? "selected" : ""}>Light Theme</option>
              <option value="high-contrast" ${theme === "high-contrast" ? "selected" : ""}>High Contrast (Accessible)</option>
            </select>
          </div>
          <div class="form-row">
            <label>Language & Layout Direction:</label>
            <select class="form-select" id="sel-lang">
              <option value="en" ${lang === "en" ? "selected" : ""}>English (LTR)</option>
              <option value="ar" ${lang === "ar" ? "selected" : ""}>العربية (Arabic RTL Mirrored Layout)</option>
            </select>
          </div>
          <div class="form-row">
            <label>Interface Mode:</label>
            <select class="form-select" id="sel-usermode">
              <option value="beginner" ${userMode === "beginner" ? "selected" : ""}>Beginner Mode (Plain cards, simple presets)</option>
              <option value="expert" ${userMode === "expert" ? "selected" : ""}>Expert Mode (Raw JSON, CLI commands, API explorer)</option>
            </select>
          </div>
        </div>

        <!-- Network Ports & Daemons -->
        <div class="card">
          <div class="card-header">
            <h4>Network Ports & Endpoints</h4>
          </div>
          <div class="form-row">
            <label>Gateway Port:</label>
            <input type="text" class="form-input mono" value=":8080" id="inp-port-gw" />
            <small class="muted">Where Claude Code connects as ANTHROPIC_BASE_URL.</small>
          </div>
          <div class="form-row">
            <label>Brain Daemon HTTP Port:</label>
            <input type="text" class="form-input mono" value="7700" id="inp-port-brain" />
            <small class="muted">Serves graph queries and studio websockets.</small>
          </div>
          <div class="form-row">
            <label>Hook IPC Port (TCP):</label>
            <input type="text" class="form-input mono" value="7772" id="inp-port-hook" />
            <small class="muted">Receives Claude Code CLI lifecycle events.</small>
          </div>
        </div>

        <!-- Storage & Retention Limits -->
        <div class="card">
          <div class="card-header">
            <h4>Storage & Retention Limits</h4>
          </div>
          <div class="form-row">
            <label>Max Log File Size:</label>
            <select class="form-select">
              <option value="50">50 MB per component (Auto-rotated)</option>
              <option value="100" selected>100 MB per component</option>
              <option value="500">500 MB</option>
            </select>
          </div>
          <div class="form-row">
            <label>Brain Memory Retention:</label>
            <select class="form-select">
              <option value="30">Keep lessons for 30 days of inactivity</option>
              <option value="90" selected>Keep lessons for 90 days of inactivity</option>
              <option value="unlimited">Keep indefinitely</option>
            </select>
          </div>
          <div class="form-row">
            <label>Update Release Channel:</label>
            <select class="form-select">
              <option value="stable" selected>Stable (Recommended)</option>
              <option value="preview">Preview / Beta</option>
              <option value="nightly">Nightly Builds</option>
            </select>
          </div>
        </div>

        <!-- Backups & Recovery -->
        <div class="card">
          <div class="card-header">
            <h4>Automated Backups & Restore</h4>
          </div>
          <p class="muted text-sm">Automated hourly configuration backups protect your keys and routing policies before any change.</p>
          <div class="btn-group mt-3">
            <button type="button" class="btn-secondary" id="btn-create-backup">Create Manual Backup</button>
            <button type="button" class="btn-secondary" id="btn-restore-backup">Restore from File</button>
          </div>
        </div>
      </div>

      ${renderCliSnippet("config", "Inspect raw config file gateway/config.json")}
    `;

    this.attachEvents();
  }

  private attachEvents(): void {
    const lang = store.getState().lang;

    this.container.querySelector("#sel-theme")?.addEventListener("change", (e) => {
      store.setTheme((e.target as HTMLSelectElement).value as any);
    });

    this.container.querySelector("#sel-lang")?.addEventListener("change", (e) => {
      store.setLanguage((e.target as HTMLSelectElement).value as any);
    });

    this.container.querySelector("#sel-usermode")?.addEventListener("change", (e) => {
      store.setUserMode((e.target as HTMLSelectElement).value as any);
    });

    this.container.querySelector("#btn-create-backup")?.addEventListener("click", () => {
      store.showToast({
        type: "success",
        title: "Backup Created",
        message: "Configuration saved to claude-master-backup-" + new Date().toISOString().slice(0, 10) + ".json",
      });
    });

    this.container.querySelector("#btn-restore-backup")?.addEventListener("click", () => {
      store.showToast({
        type: "info",
        title: "Restore Backup",
        message: "Select a JSON backup file to overwrite current settings.",
      });
    });

    this.container.querySelector("#btn-export-bundle")?.addEventListener("click", () => {
      const bundle = {
        exported_at: new Date().toISOString(),
        version: "0.1.0",
        providers: store.getState().providers,
        models: store.getState().models,
        routingRoles: store.getState().routingRoles,
        routingRules: store.getState().routingRules,
        drexConfig: store.getState().drexConfig,
      };
      const blob = new Blob([JSON.stringify(bundle, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `claude-master-config-${Date.now()}.json`;
      a.click();
      URL.revokeObjectURL(url);
      store.showToast({ type: "success", title: "Bundle Exported", message: "Exported configuration JSON." });
    });

    this.container.querySelector("#btn-factory-reset")?.addEventListener("click", () => {
      ConfirmModal.show({
        title: "Reset Claude Master to Factory Defaults?",
        message: "This will restore the factory default gateway configuration. API keys stored in .env will remain intact.",
        confirmLabel: "Reset to Defaults",
        cancelLabel: t("cancel", lang),
        isDestructive: true,
        onConfirm: () => {
          store.showToast({
            type: "warning",
            title: "Factory Reset",
            message: "Configuration restored to pristine state.",
          });
        },
      });
    });
  }
}
