/**
 * Human review queue for notable brain events (lessons, breakers, skills).
 */

export type ReviewKind =
  | "circuit_breaker_tripped"
  | "lesson_extracted"
  | "skill_learned"
  | "edge_invalidated";

export interface ReviewItem {
  id: string;
  kind: ReviewKind;
  ts: number;
  summary: string;
  status: "pending" | "accepted" | "rejected";
  payload: Record<string, unknown>;
}

export class ReviewQueue {
  private readonly root: HTMLElement;
  private items: ReviewItem[] = [];
  private seq = 0;

  constructor(root: HTMLElement) {
    this.root = root;
    this.render();
  }

  enqueue(kind: ReviewKind, ts: number, summary: string, payload: Record<string, unknown>): void {
    this.items.unshift({
      id: `rq-${++this.seq}`,
      kind,
      ts,
      summary,
      status: "pending",
      payload,
    });
    if (this.items.length > 200) this.items.length = 200;
    this.render();
  }

  decide(id: string, status: "accepted" | "rejected"): void {
    const item = this.items.find((i) => i.id === id);
    if (!item) return;
    item.status = status;
    this.render();
  }

  pendingCount(): number {
    return this.items.filter((i) => i.status === "pending").length;
  }

  private render(): void {
    const pending = this.pendingCount();
    const list = this.items
      .slice(0, 40)
      .map((item) => {
        const actions =
          item.status === "pending"
            ? `<button data-act="accepted" data-id="${item.id}">Accept</button>
               <button data-act="rejected" data-id="${item.id}" class="ghost">Reject</button>`
            : `<span class="badge">${item.status}</span>`;
        return `<li class="rq-item" data-status="${item.status}">
          <div class="rq-kind">${escape(item.kind)}</div>
          <div class="rq-sum">${escape(item.summary)}</div>
          <div class="rq-meta">${new Date(item.ts).toLocaleTimeString()} · ${actions}</div>
        </li>`;
      })
      .join("");

    this.root.innerHTML = `
      <header>Review queue <span class="badge">${pending}</span></header>
      <ul class="rq-list">${list || '<li class="muted">No items.</li>'}</ul>
    `;

    this.root.querySelectorAll("button[data-act]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const id = (btn as HTMLElement).dataset.id!;
        const act = (btn as HTMLElement).dataset.act as "accepted" | "rejected";
        this.decide(id, act);
      });
    });
  }
}

function escape(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
