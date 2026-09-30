import "./styles.css";
import { BrainGraph, BrainWebSocket } from "./graph/index.js";
import { CanvasScrubber, Scrubber } from "./scrubber/index.js";
import { GatewayAdmin, InspectorPanel, ReviewQueue } from "./ui/index.js";
import type { BrainEvent } from "./types/events.js";

function mount(): void {
  const app = document.getElementById("app");
  if (!app) throw new Error("#app missing");

  app.innerHTML = `
    <div class="app-shell">
      <div class="topbar">
        <h1>Synaptic Studio</h1>
        <span class="muted" id="conn-status">connecting…</span>
        <div class="spacer"></div>
        <button type="button" id="btn-live">Live</button>
        <button type="button" id="btn-pause">Pause</button>
        <button type="button" id="btn-play">Replay</button>
        <button type="button" id="btn-seed" class="ghost">Seed 5k</button>
      </div>
      <div class="viewport"><div class="sigma-root" id="graph"></div></div>
      <aside class="sidebar">
        <section id="inspector"></section>
        <section id="review-queue"></section>
        <section id="gateway-admin"></section>
      </aside>
      <div class="scrubber-bar">
        <canvas id="scrubber-canvas" width="1200" height="48"></canvas>
      </div>
    </div>
  `;

  const scrubber = new Scrubber();
  const graphEl = document.getElementById("graph")!;
  const brain = new BrainGraph({ container: graphEl, scrubber });
  const inspector = new InspectorPanel(document.getElementById("inspector")!);
  const review = new ReviewQueue(document.getElementById("review-queue")!);
  const gateway = new GatewayAdmin(document.getElementById("gateway-admin")!);
  const canvas = document.getElementById("scrubber-canvas") as HTMLCanvasElement;
  const canvasScrubber = new CanvasScrubber(canvas, scrubber);

  brain.setSelectionHandler((id, kind) => {
    if (!id || !kind) {
      inspector.setSelection(null, null, null);
      return;
    }
    const attrs = kind === "node" ? brain.getNodeAttrs(id) : brain.getEdgeAttrs(id);
    inspector.setSelection(kind, id, attrs);
  });

  const status = document.getElementById("conn-status")!;
  const wsUrl = (import.meta as ImportMeta & { env?: { VITE_WS_URL?: string } }).env?.VITE_WS_URL
    ?? "ws://localhost:7700/ws";
  const ws = new BrainWebSocket({ url: wsUrl });

  ws.onEvent((ev: BrainEvent) => {
    brain.handleEvent(ev);
    routeSideEffects(ev, review, gateway);
  });

  try {
    ws.connect();
    status.textContent = `ws → ${wsUrl}`;
  } catch {
    status.textContent = "ws offline (seed locally)";
  }

  document.getElementById("btn-live")!.onclick = () => scrubber.live();
  document.getElementById("btn-pause")!.onclick = () => scrubber.pause();
  document.getElementById("btn-play")!.onclick = () => scrubber.play(2);
  document.getElementById("btn-seed")!.onclick = () => {
    brain.seedBenchmarkGraph(5000, 20_000);
    status.textContent = "seeded 5k/20k (GPU target 60 FPS)";
  };

  window.addEventListener("beforeunload", () => {
    canvasScrubber.dispose();
    brain.dispose();
    scrubber.dispose();
    ws.close();
  });
}

function routeSideEffects(
  ev: BrainEvent,
  review: ReviewQueue,
  gateway: GatewayAdmin,
): void {
  switch (ev.event) {
    case "circuit_breaker_tripped":
      review.enqueue(
        "circuit_breaker_tripped",
        ev.ts,
        `${ev.data.pattern} ×${ev.data.iteration} (${ev.data.session_id})`,
        ev.data as unknown as Record<string, unknown>,
      );
      break;
    case "lesson_extracted":
      review.enqueue(
        "lesson_extracted",
        ev.ts,
        ev.data.rule_text,
        ev.data as unknown as Record<string, unknown>,
      );
      break;
    case "skill_learned":
      review.enqueue(
        "skill_learned",
        ev.ts,
        `${ev.data.name}@v${ev.data.version} (${ev.data.language})`,
        ev.data as unknown as Record<string, unknown>,
      );
      break;
    case "edge_invalidated":
      review.enqueue(
        "edge_invalidated",
        ev.ts,
        `${ev.data.edge_id} → ${ev.data.replacement_edge_id}`,
        ev.data as unknown as Record<string, unknown>,
      );
      break;
    case "gateway_health":
      gateway.updateHealth(ev.data);
      break;
    default:
      break;
  }
}

mount();
