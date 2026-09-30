/**
 * Brain WebSocket client — read-only consumer of contracts/events.md.
 */

import type { BrainEvent, ClientAction, EventEnvelope } from "../types/events.js";

export type EventHandler = (ev: BrainEvent) => void;

export interface BrainWsOptions {
  url?: string;
  WebSocketImpl?: typeof WebSocket;
  reconnectMs?: number;
}

export class BrainWebSocket {
  private ws: WebSocket | null = null;
  private readonly url: string;
  private readonly WebSocketImpl: typeof WebSocket;
  private readonly reconnectMs: number;
  private readonly handlers = new Set<EventHandler>();
  private closed = false;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;

  constructor(opts: BrainWsOptions = {}) {
    this.url = opts.url ?? "ws://localhost:7700/ws";
    this.WebSocketImpl = opts.WebSocketImpl ?? WebSocket;
    this.reconnectMs = opts.reconnectMs ?? 2000;
  }

  onEvent(fn: EventHandler): () => void {
    this.handlers.add(fn);
    return () => this.handlers.delete(fn);
  }

  connect(): void {
    this.closed = false;
    this.open();
  }

  private open(): void {
    if (this.closed) return;
    const ws = new this.WebSocketImpl(this.url);
    this.ws = ws;
    ws.addEventListener("message", (msg) => {
      const raw = typeof msg.data === "string" ? msg.data : String(msg.data);
      try {
        const parsed = JSON.parse(raw) as EventEnvelope;
        if (!parsed || typeof parsed.event !== "string") return;
        for (const h of this.handlers) h(parsed as BrainEvent);
      } catch {
        // ignore malformed
      }
    });
    ws.addEventListener("close", () => {
      this.ws = null;
      if (!this.closed) {
        this.reconnectTimer = setTimeout(() => this.open(), this.reconnectMs);
      }
    });
  }

  send(action: ClientAction): void {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
    this.ws.send(JSON.stringify(action));
  }

  subscribe(sessionId: string): void {
    this.send({ action: "subscribe", session_id: sessionId });
  }

  replay(fromTs: number, toTs: number, speed = 1): void {
    this.send({ action: "replay", from_ts: fromTs, to_ts: toTs, speed });
  }

  close(): void {
    this.closed = true;
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.ws?.close();
    this.ws = null;
  }
}
