/**
 * Mock WebSocket server for studio tests — in-process, no network.
 */

import type { BrainEvent, ClientAction } from "../types/events.js";

type MsgHandler = (data: string) => void;

export class MockWebSocket {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;

  readyState = MockWebSocket.CONNECTING;
  readonly url: string;
  private readonly server: MockWsServer;
  private readonly messageHandlers: MsgHandler[] = [];
  private readonly closeHandlers: Array<() => void> = [];

  constructor(url: string, server: MockWsServer) {
    this.url = url;
    this.server = server;
    queueMicrotask(() => {
      this.readyState = MockWebSocket.OPEN;
      server.attach(this);
    });
  }

  addEventListener(type: string, fn: EventListenerOrEventListenerObject): void {
    const handler = typeof fn === "function" ? fn : fn.handleEvent.bind(fn);
    if (type === "message") {
      this.messageHandlers.push((data) => {
        handler({ data } as MessageEvent);
      });
    } else if (type === "close") {
      this.closeHandlers.push(() => handler(new Event("close")));
    } else if (type === "open") {
      queueMicrotask(() => handler(new Event("open")));
    }
  }

  send(data: string): void {
    this.server.onClientMessage(this, data);
  }

  close(): void {
    this.readyState = MockWebSocket.CLOSED;
    this.server.detach(this);
    for (const h of this.closeHandlers) h();
  }

  /** Server → client push. */
  _receive(data: string): void {
    for (const h of this.messageHandlers) h(data);
  }
}

export class MockWsServer {
  private clients = new Set<MockWebSocket>();
  private actionHandlers: Array<(client: MockWebSocket, action: ClientAction) => void> = [];

  createWebSocketImpl(): typeof WebSocket {
    const server = this;
    return class extends MockWebSocket {
      constructor(url: string) {
        super(url, server);
      }
    } as unknown as typeof WebSocket;
  }

  attach(client: MockWebSocket): void {
    this.clients.add(client);
  }

  detach(client: MockWebSocket): void {
    this.clients.delete(client);
  }

  onAction(fn: (client: MockWebSocket, action: ClientAction) => void): void {
    this.actionHandlers.push(fn);
  }

  onClientMessage(client: MockWebSocket, raw: string): void {
    try {
      const action = JSON.parse(raw) as ClientAction;
      for (const h of this.actionHandlers) h(client, action);
    } catch {
      // ignore
    }
  }

  broadcast(event: BrainEvent): void {
    const raw = JSON.stringify(event);
    for (const c of this.clients) {
      if (c.readyState === MockWebSocket.OPEN) c._receive(raw);
    }
  }

  sendTo(client: MockWebSocket, event: BrainEvent): void {
    client._receive(JSON.stringify(event));
  }
}
