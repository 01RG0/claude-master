export interface InspectorState {
  kind: "node" | "edge" | null;
  id: string | null;
  attrs: Record<string, unknown> | null;
}

export class InspectorPanel {
  private readonly root: HTMLElement;
  private state: InspectorState = { kind: null, id: null, attrs: null };

  constructor(root: HTMLElement) {
    this.root = root;
    this.render();
  }

  setSelection(kind: "node" | "edge" | null, id: string | null, attrs: Record<string, unknown> | null): void {
    this.state = { kind, id, attrs };
    this.render();
  }

  private render(): void {
    const { kind, id, attrs } = this.state;
    if (!kind || !id) {
      this.root.innerHTML = `<header>Inspector</header><p class="muted">Select a node or edge.</p>`;
      return;
    }
    const rows = Object.entries(attrs ?? {})
      .filter(([k]) => !["x", "y"].includes(k))
      .map(
        ([k, v]) =>
          `<tr><th>${escapeHtml(k)}</th><td>${escapeHtml(formatVal(v))}</td></tr>`,
      )
      .join("");
    this.root.innerHTML = `
      <header>Inspector · ${escapeHtml(kind)}</header>
      <div class="id">${escapeHtml(id)}</div>
      <table>${rows}</table>
    `;
  }
}

function formatVal(v: unknown): string {
  if (v == null) return "—";
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : v.toFixed(4);
  return String(v);
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
