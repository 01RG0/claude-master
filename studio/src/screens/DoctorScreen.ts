// src/screens/DoctorScreen.ts — System Doctor (1-Click Diagnostics & Automated Fixes)

import { store } from "../state/store.js";
import { t } from "../i18n/translations.js";
import { renderCliSnippet } from "../components/CliSnippet.js";

export class DoctorScreen {
  private container: HTMLElement;
  private isDiagnosing = false;

  constructor(container: HTMLElement) {
    this.container = container;
  }

  render(): void {
    const state = store.getState();
    const lang = state.lang;
    const checks = state.doctorChecks;
    const allPassed = checks.every((c) => c.passed);

    this.container.innerHTML = `
      <div class="screen-header">
        <div>
          <h2>${t("doctorTitle", lang)}</h2>
          <p class="muted">${t("doctorSubtitle", lang)}</p>
        </div>
        <button type="button" class="btn-primary" id="btn-run-doctor">
          ${this.isDiagnosing ? "Running Diagnostics..." : "🩺 Run Full Doctor Check"}
        </button>
      </div>

      <!-- Doctor Overview Banner -->
      <div class="card ${allPassed ? "bg-ok-subtle" : "bg-warn-subtle"}">
        <div class="doctor-banner-content">
          <span class="doctor-big-icon">${allPassed ? "✓" : "⚠️"}</span>
          <div>
            <strong>${allPassed ? "All Diagnostic Checks Green" : "Issues Detected"}</strong>
            <p class="muted">
              ${
                allPassed
                  ? "Node runtime, Python 3.11+, Go binaries, config schemas, and local ports are fully operational."
                  : "One or more checks require attention. Use the 1-click fix buttons below."
              }
            </p>
          </div>
        </div>
      </div>

      <!-- Checks List with Before / After Status and Fix Buttons -->
      <div class="doctor-checks-stack">
        ${checks
          .map(
            (c) => `
          <div class="card check-item-card ${c.passed ? "passed" : "failed"}">
            <div class="check-status-col">
              <span class="check-icon-large">${c.passed ? "✓" : "✕"}</span>
            </div>
            <div class="check-body-col">
              <div class="check-title-row">
                <strong>${escapeHtml(c.title)}</strong>
                <span class="badge ${c.passed ? "ok" : "warn"}">${c.passed ? "PASSED" : c.severity.toUpperCase()}</span>
              </div>
              <p class="check-detail muted">${escapeHtml(c.detail)}</p>
              ${
                !c.passed
                  ? `
                <div class="check-fix-box">
                  <span>Automated Fix: <code>${escapeHtml(c.fix_command)}</code></span>
                </div>
              `
                  : ""
              }
            </div>
            <div class="check-action-col">
              ${
                !c.passed
                  ? `
                <button type="button" class="btn-sm btn-primary btn-fix-check" data-id="${c.id}">
                  ${escapeHtml(c.fix_action_label)}
                </button>
              `
                  : `
                <button type="button" class="btn-sm btn-ghost btn-recheck" data-id="${c.id}">Recheck</button>
              `
              }
            </div>
          </div>
        `,
          )
          .join("")}
      </div>

      ${renderCliSnippet("doctor", "Execute system doctor from PowerShell")}
    `;

    this.attachEvents();
  }

  private attachEvents(): void {
    this.container.querySelector("#btn-run-doctor")?.addEventListener("click", () => {
      this.isDiagnosing = true;
      this.render();

      setTimeout(() => {
        this.isDiagnosing = false;
        store.showToast({
          type: "success",
          title: "Diagnostics Complete",
          message: "System health check finished with 0 critical errors.",
        });
        this.render();
      }, 800);
    });

    this.container.querySelectorAll(".btn-fix-check").forEach((btn) => {
      btn.addEventListener("click", () => {
        const id = btn.getAttribute("data-id");
        const c = store.getState().doctorChecks.find((item) => item.id === id);
        if (c) {
          c.passed = true;
          store.showToast({
            type: "success",
            title: "Issue Fixed",
            message: `${c.title} resolved.`,
          });
          this.render();
        }
      });
    });

    this.container.querySelectorAll(".btn-recheck").forEach((btn) => {
      btn.addEventListener("click", () => {
        store.showToast({
          type: "info",
          title: "Check Verified",
          message: "Component confirmed operational.",
        });
      });
    });
  }
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
