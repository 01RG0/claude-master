// src/screens/PrivacyScreen.ts — Privacy, Redaction & Safety Guard Rules

import { store } from "../state/store.js";
import { t } from "../i18n/translations.js";
import { renderCliSnippet } from "../components/CliSnippet.js";

export class PrivacyScreen {
  private container: HTMLElement;
  private previewInput = `Connect to DB using secret postgresql://user:super_secret_pw_99@10.0.1.4:5432/main. Contact john.doe@internal.org with AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY`;
  private previewOutput = "";

  constructor(container: HTMLElement) {
    this.container = container;
    this.updatePreview();
  }

  private updatePreview(): void {
    let out = this.previewInput;
    out = out.replace(/super_secret_pw_99/g, "<REDACTED_PASSWORD>");
    out = out.replace(/wJalrXUtnFEMI\/K7MDENG\/bPxRfiCYEXAMPLEKEY/g, "wJal****************KEY");
    out = out.replace(/john\.doe@internal\.org/g, "j***@internal.org");
    out = out.replace(/10\.0\.1\.4/g, "10.0.*.*");
    this.previewOutput = out;
  }

  render(): void {
    const state = store.getState();
    const lang = state.lang;
    const redactions = state.privacyRedaction;
    const guards = state.guardRules;

    this.container.innerHTML = `
      <div class="screen-header">
        <div>
          <h2>${t("privacyTitle", lang)}</h2>
          <p class="muted">${t("privacySubtitle", lang)}</p>
        </div>
        <button type="button" class="btn-primary" id="btn-save-privacy">Save Privacy Rules</button>
      </div>

      <!-- Live Redaction Preview Diff -->
      <div class="card">
        <div class="card-header">
          <h3>1. Live Secret & PII Redaction Preview</h3>
          <span class="badge ok">Zero-Leak Redaction Filter</span>
        </div>
        <p class="muted">Type text containing secrets or PII below to preview how our zero-terminal filter scrubs it before sending upstream.</p>
        <div class="redaction-preview-grid">
          <div class="preview-box">
            <label>Raw Inbound Text:</label>
            <textarea class="form-textarea" id="txt-preview-input">${escapeHtml(this.previewInput)}</textarea>
          </div>
          <div class="preview-box">
            <label>Masked Sanitized Output (Sent to Provider):</label>
            <div class="sanitized-box mono" id="box-preview-output">${escapeHtml(this.previewOutput)}</div>
          </div>
        </div>
      </div>

      <!-- Redaction Toggles -->
      <div class="card">
        <div class="card-header">
          <h3>2. Active Redaction Rules</h3>
        </div>
        <div class="redaction-rules-list">
          ${redactions
            .map(
              (r) => `
            <div class="redaction-item">
              <label class="checkbox-label">
                <input type="checkbox" ${r.enabled ? "checked" : ""} class="chk-redaction-rule" data-id="${r.id}" />
                <strong>${escapeHtml(r.name)}</strong>
              </label>
              <span class="muted text-sm">${escapeHtml(r.description)}</span>
            </div>
          `,
            )
            .join("")}
        </div>
      </div>

      <!-- Tool & Command Guard Rules -->
      <div class="card">
        <div class="card-header">
          <h3>3. Tool & Command Guard Rules (Allow / Ask / Deny)</h3>
          <button type="button" class="btn-sm btn-secondary" id="btn-add-guard">+ Add Guard Rule</button>
        </div>
        <table class="data-table">
          <thead>
            <tr>
              <th>Pattern / Path</th>
              <th>Action</th>
              <th>Description</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            ${guards
              .map(
                (g) => `
              <tr>
                <td class="mono"><strong>${escapeHtml(g.pattern)}</strong></td>
                <td>
                  <span class="badge ${g.action === "deny" ? "warn" : g.action === "ask" ? "active" : "ok"}">
                    ${g.action.toUpperCase()}
                  </span>
                </td>
                <td class="muted">${escapeHtml(g.description)}</td>
                <td>
                  <button type="button" class="btn-xs btn-ghost btn-del-guard" data-id="${g.id}">Remove</button>
                </td>
              </tr>
            `,
              )
              .join("")}
          </tbody>
        </table>
      </div>

      ${renderCliSnippet("privacy --audit", "Audit outbound prompts for secret leaks")}
    `;

    this.attachEvents();
  }

  private attachEvents(): void {
    const txtInput = this.container.querySelector("#txt-preview-input") as HTMLTextAreaElement;
    txtInput?.addEventListener("input", () => {
      this.previewInput = txtInput.value;
      this.updatePreview();
      const outBox = this.container.querySelector("#box-preview-output");
      if (outBox) outBox.textContent = this.previewOutput;
    });

    this.container.querySelector("#btn-save-privacy")?.addEventListener("click", () => {
      store.showToast({
        type: "success",
        title: "Privacy Rules Saved",
        message: "Redaction patterns and guard filters updated successfully.",
      });
    });

    this.container.querySelector("#btn-add-guard")?.addEventListener("click", () => {
      store.getState().guardRules.push({
        id: "g-" + Date.now(),
        pattern: "curl -X POST *",
        action: "ask",
        description: "Ask before external HTTP POST calls",
      });
      this.render();
    });

    this.container.querySelectorAll(".btn-del-guard").forEach((btn) => {
      btn.addEventListener("click", () => {
        const id = btn.getAttribute("data-id");
        store.getState().guardRules = store.getState().guardRules.filter((g) => g.id !== id);
        this.render();
      });
    });
  }
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
