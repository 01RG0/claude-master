import { describe, expect, it } from "vitest";
import { MockWsServer } from "../../studio/src/graph/mock-ws";
import { BrainWebSocket } from "../../studio/src/graph/ws-client";

describe("Mock WebSocket server", () => {
  it("delivers snapshot to client", async () => {
    const server = new MockWsServer();
    const client = new BrainWebSocket({
      url: "ws://mock/ws",
      WebSocketImpl: server.createWebSocketImpl(),
      reconnectMs: 60_000,
    });

    const events: string[] = [];
    client.onEvent((ev) => events.push(ev.event));
    client.connect();

    await new Promise((r) => setTimeout(r, 10));
    server.broadcast({
      event: "snapshot",
      ts: Date.now(),
      data: { nodes: [], edges: [], sleep_phase: null },
    });
    await new Promise((r) => setTimeout(r, 10));

    expect(events).toContain("snapshot");
    client.close();
  });

  it("forwards subscribe actions to server", async () => {
    const server = new MockWsServer();
    const seen: string[] = [];
    server.onAction((_c, action) => {
      if (action.action === "subscribe") seen.push(action.session_id);
    });
    const client = new BrainWebSocket({
      url: "ws://mock/ws",
      WebSocketImpl: server.createWebSocketImpl(),
      reconnectMs: 60_000,
    });
    client.connect();
    await new Promise((r) => setTimeout(r, 10));
    client.subscribe("sess-1");
    await new Promise((r) => setTimeout(r, 10));
    expect(seen).toEqual(["sess-1"]);
    client.close();
  });
});
