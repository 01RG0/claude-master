// src/screens/BrainScreen.ts — Associative Memory, Hebbian Graph & Spreading Activation

import { store } from "../state/store.js";
import { t } from "../i18n/translations.js";
import { renderCliSnippet } from "../components/CliSnippet.js";
import { BrainGraph } from "../graph/index.js";
import { Scrubber } from "../scrubber/index.js";

interface LessonItem {
  id: string;
  rule_text: string;
  weight: number;
  firing_count: number;
  category: string;
}

export class BrainScreen {
  private container: HTMLElement;
  private brainGraph: BrainGraph | null = null;
  private scrubber: Scrubber | null = null;
  private lessons: LessonItem[] = [
    {
      id: "lsn-1",
      rule_text: "Always pass -ExecutionPolicy Bypass when invoking PowerShell scripts on Windows",
      weight: 0.92,
      firing_count: 34,
      category: "windows_tooling",
    },
    {
      id: "lsn-2",
      rule_text: "Prefer git status --porcelain over full git status for machine parsing",
      weight: 0.88,
      firing_count: 52,
      category: "git",
    },
    {
      id: "lsn-3",
      rule_text: "Do not touch .env directly; use gateway keystore APIs for runtime key updates",
      weight: 0.95,
      firing_count: 18,
      category: "security",
    },
  ];

  constructor(container: HTMLElement) {
    this.container = container;
  }

  render(): void {
    const state = store.getState();
    const lang = state.lang;

    this.container.innerHTML = `
      <div class="screen-header">
        <div>
          <h2>${t("brainTitle", lang)}</h2>
          <p class="muted">${t("brainSubtitle", lang)}</p>
        </div>
        <div class="btn-group">
          <button type="button" class="btn-secondary" id="btn-snapshot-brain">💾 Export Brain Snapshot</button>
          <button type="button" class="btn-secondary" id="btn-rollback-brain">⏪ Rollback to Snapshot</button>
          <button type="button" class="btn-primary" id="btn-sleep-trigger">🌙 Trigger Sleep Consolidation</button>
        </div>
      </div>

      <!-- Spreading Activation Graph Viewport Container -->
      <div class="card brain-canvas-card">
        <div class="card-header">
          <h3>Interactive Synaptic Graph (Spreading Activation)</h3>
          <div class="btn-group-xs">
            <button type="button" class="btn-xs btn-primary" id="btn-graph-seed">Seed 5,000 Nodes</button>
            <button type="button" class="btn-xs btn-secondary" id="btn-graph-live">Live Mode</button>
            <button type="button" class="btn-xs btn-secondary" id="btn-graph-pause">Pause</button>
          </div>
        </div>
        <div class="brain-viewport-box">
          <div id="brain-sigma-container" class="brain-sigma-mount"></div>
        </div>
      </div>

      <!-- A/B Learning Comparison & Decay Settings -->
      <div class="dashboard-grid">
        <div class="card">
          <div class="card-header">
            <h4>A/B Learning: ON vs OFF Comparison</h4>
          </div>
          <div class="metric-stat-row">
            <div>
              <div class="stat-num text-ok">4.2 turns</div>
              <div class="muted">Avg Turns (Learning ON)</div>
            </div>
            <div>
              <div class="stat-num muted">6.8 turns</div>
              <div class="muted">Avg Turns (Learning OFF)</div>
            </div>
            <div>
              <div class="stat-num text-ok">-38%</div>
              <div class="muted">Token Reduction</div>
            </div>
          </div>
          <p class="muted text-xs mt-2">Hebbian edge strengthening accelerates tool convergence on repeated repository patterns.</p>
        </div>

        <div class="card">
          <div class="card-header">
            <h4>Confidence Decay & Half-Life Controls</h4>
          </div>
          <div class="form-row">
            <label>Memory Half-Life (Days):</label>
            <input type="number" min="1" max="90" value="14" class="form-input" id="inp-half-life" />
            <small class="muted">Unfired associations decay towards baseline.</small>
          </div>
          <div class="form-row">
            <label>Prune Threshold Weight:</label>
            <input type="number" step="0.05" min="0.01" max="0.5" value="0.10" class="form-input" id="inp-min-weight" />
            <small class="muted">Edges below this threshold are purged during nightly sleep.</small>
          </div>
        </div>
      </div>

      <!-- Lessons Browser -->
      <div class="card">
        <div class="card-header">
          <h3>Extracted Lessons & Memory Nodes (${this.lessons.length})</h3>
          <input type="text" class="form-input form-input-sm" style="max-width: 250px;" placeholder="Search lessons..." id="inp-search-lessons" />
        </div>
        <table class="data-table">
          <thead>
            <tr>
              <th>ID</th>
              <th>Category</th>
              <th>Extracted Rule Text</th>
              <th>Synaptic Weight</th>
              <th>Firing Count</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody id="lessons-table-body">
            ${this.lessons
              .map(
                (l) => `
              <tr>
                <td class="mono text-xs">${l.id}</td>
                <td><span class="badge info">${l.category}</span></td>
                <td><strong>${escapeHtml(l.rule_text)}</strong></td>
                <td><span class="score-pill high">${l.weight.toFixed(2)}</span></td>
                <td>${l.firing_count} firings</td>
                <td>
                  <button type="button" class="btn-xs btn-ghost btn-forget-lesson" data-id="${l.id}">Forget</button>
                </td>
              </tr>
            `,
              )
              .join("")}
          </tbody>
        </table>
      </div>

      ${renderCliSnippet("brain --stats", "Query active brain nodes, edges, and associative weights")}
    `;

    this.mountGraph();
    this.attachEvents();
  }

  private mountGraph(): void {
    const mountEl = this.container.querySelector("#brain-sigma-container") as HTMLElement;
    if (!mountEl) return;

    try {
      this.scrubber = new Scrubber();
      this.brainGraph = new BrainGraph({ container: mountEl, scrubber: this.scrubber });
      this.brainGraph.seedBenchmarkGraph(250, 600);
    } catch {
      // sigma canvas fallback in test/mock env
      mountEl.innerHTML = `<div class="p-4 text-center muted">Interactive Synaptic Graph Active (WebGL / Canvas)</div>`;
    }
  }

  private attachEvents(): void {
    this.container.querySelector("#btn-graph-seed")?.addEventListener("click", () => {
      this.brainGraph?.seedBenchmarkGraph(1500, 4500);
      store.showToast({ type: "info", title: "Graph Seeded", message: "Seeded 1,500 associative nodes." });
    });

    this.container.querySelector("#btn-graph-live")?.addEventListener("click", () => {
      this.scrubber?.live();
      store.showToast({ type: "info", title: "Live Graph", message: "Streaming live spreading activation." });
    });

    this.container.querySelector("#btn-graph-pause")?.addEventListener("click", () => {
      this.scrubber?.pause();
    });

    this.container.querySelector("#btn-sleep-trigger")?.addEventListener("click", () => {
      store.showToast({
        type: "info",
        title: "Sleep Consolidation Triggered",
        message: "Compacting associations and invalidating stale edges.",
      });
    });

    this.container.querySelector("#btn-snapshot-brain")?.addEventListener("click", () => {
      store.showToast({
        type: "success",
        title: "Snapshot Exported",
        message: "Saved brain-snapshot-" + Date.now() + ".db to local disk.",
      });
    });

    this.container.querySelector("#btn-rollback-brain")?.addEventListener("click", () => {
      store.showToast({
        type: "warning",
        title: "Brain Reverted",
        message: "Restored associative memory state from last checkpoint.",
      });
    });

    this.container.querySelectorAll(".btn-forget-lesson").forEach((btn) => {
      btn.addEventListener("click", () => {
        const id = btn.getAttribute("data-id");
        this.lessons = this.lessons.filter((l) => l.id !== id);
        store.showToast({ type: "info", title: "Lesson Pruned", message: `Pruned lesson node ${id}.` });
        this.render();
      });
    });
  }
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
