/**
 * Graphology + Sigma synaptic graph controller.
 */

import Graph from "graphology";
import forceAtlas2 from "graphology-layout-forceatlas2";
import Sigma from "sigma";
import EdgePulseProgram, {
  advancePulseTime,
  type PulseEdgeDisplayData,
} from "../shaders/edge-pulse.js";
import type {
  BrainEvent,
  GraphEdge,
  GraphNode,
  SnapshotData,
  SynapseUpdatedData,
} from "../types/events.js";
import { KIND_NODE_FIRE, KIND_SYNAPSE, Scrubber } from "../scrubber/index.js";

export interface BrainGraphOptions {
  container: HTMLElement;
  scrubber: Scrubber;
  maxNodes?: number;
}

export class BrainGraph {
  readonly graph: Graph;
  readonly sigma: Sigma;
  readonly scrubber: Scrubber;
  private readonly idToIndex = new Map<string, number>();
  private readonly indexToId: string[] = [];
  private selectedId: string | null = null;
  private onSelect: ((id: string | null, kind: "node" | "edge" | null) => void) | null = null;
  private raf = 0;
  private lastTs = 0;
  private fa2Running = false;

  constructor(opts: BrainGraphOptions) {
    this.scrubber = opts.scrubber;
    this.graph = new Graph({ multi: false, type: "directed" });
    this.sigma = new Sigma(this.graph, opts.container, {
      allowInvalidContainer: true,
      defaultEdgeType: "pulse",
      edgeProgramClasses: {
        pulse: EdgePulseProgram,
      },
      renderEdgeLabels: false,
      labelDensity: 0.07,
    });

    this.sigma.on("clickNode", ({ node }) => {
      this.selectedId = node;
      this.onSelect?.(node, "node");
    });
    this.sigma.on("clickEdge", ({ edge }) => {
      this.selectedId = edge;
      this.onSelect?.(edge, "edge");
    });
    this.sigma.on("clickStage", () => {
      this.selectedId = null;
      this.onSelect?.(null, null);
    });

    this.lastTs = performance.now();
    const loop = (now: number) => {
      const dt = (now - this.lastTs) / 1000;
      this.lastTs = now;
      advancePulseTime(dt);
      this.sigma.refresh();
      this.raf = requestAnimationFrame(loop);
    };
    this.raf = requestAnimationFrame(loop);
  }

  setSelectionHandler(fn: (id: string | null, kind: "node" | "edge" | null) => void): void {
    this.onSelect = fn;
  }

  private indexOf(id: string): number {
    let idx = this.idToIndex.get(id);
    if (idx == null) {
      idx = this.indexToId.length;
      this.idToIndex.set(id, idx);
      this.indexToId.push(id);
    }
    return idx;
  }

  applySnapshot(data: SnapshotData): void {
    this.graph.clear();
    this.idToIndex.clear();
    this.indexToId.length = 0;

    for (const n of data.nodes) this.addNode(n);
    for (const e of data.edges) this.addEdge(e);
    this.runLayout(true);
  }

  private addNode(n: GraphNode): void {
    if (this.graph.hasNode(n.id)) return;
    this.indexOf(n.id);
    const angle = Math.random() * Math.PI * 2;
    const r = 50 + Math.random() * 400;
    this.graph.addNode(n.id, {
      label: n.name,
      node_type: n.node_type,
      weight_sum: n.weight_sum,
      x: Math.cos(angle) * r,
      y: Math.sin(angle) * r,
      size: 2 + Math.min(12, n.weight_sum),
      color: colorForType(n.node_type),
    });
  }

  private addEdge(e: GraphEdge): void {
    if (!this.graph.hasNode(e.source) || !this.graph.hasNode(e.target)) return;
    if (this.graph.hasEdge(e.id)) {
      this.graph.setEdgeAttribute(e.id, "weight", e.weight);
      this.graph.setEdgeAttribute(e.id, "size", 0.5 + e.weight * 3);
      return;
    }
    if (this.graph.hasEdge(e.source, e.target)) return;
    this.graph.addEdgeWithKey(e.id, e.source, e.target, {
      weight: e.weight,
      relation_type: e.relation_type,
      size: 0.5 + e.weight * 3,
      color: "#4b5563",
      type: "pulse",
      spikeTime: -1e9,
      pulseSpeed: 0.35,
    } satisfies Partial<PulseEdgeDisplayData> & Record<string, unknown>);
  }

  handleEvent(ev: BrainEvent): void {
    switch (ev.event) {
      case "snapshot":
        this.applySnapshot(ev.data);
        break;
      case "node_fired": {
        const { node_id, activation_score } = ev.data;
        if (this.graph.hasNode(node_id)) {
          this.graph.setNodeAttribute(node_id, "color", "#fbbf24");
          this.graph.setNodeAttribute(
            node_id,
            "size",
            3 + activation_score * 10,
          );
        }
        this.scrubber.pushEvent(
          ev.ts,
          this.indexOf(node_id),
          0,
          activation_score,
          KIND_NODE_FIRE,
        );
        break;
      }
      case "synapse_updated":
        this.onSynapse(ev.ts, ev.data);
        break;
      case "edge_invalidated": {
        const { edge_id } = ev.data;
        if (this.graph.hasEdge(edge_id)) {
          this.graph.setEdgeAttribute(edge_id, "color", "#7f1d1d");
          this.graph.setEdgeAttribute(edge_id, "hidden", true);
        }
        break;
      }
      case "replay_frame": {
        for (const id of ev.data.active_edge_ids) {
          if (this.graph.hasEdge(id)) {
            this.graph.setEdgeAttribute(id, "spikeTime", performance.now() / 1000);
            this.graph.setEdgeAttribute(id, "color", "#5eead4");
          }
        }
        for (const id of ev.data.active_node_ids) {
          if (this.graph.hasNode(id)) {
            this.graph.setNodeAttribute(id, "color", "#fbbf24");
          }
        }
        break;
      }
      default:
        break;
    }
  }

  private onSynapse(ts: number, data: SynapseUpdatedData): void {
    const { edge_id, source_id, target_id, new_weight, delta } = data;
    if (!this.graph.hasNode(source_id)) {
      this.addNode({
        id: source_id,
        name: source_id.slice(0, 8),
        node_type: "unknown",
        weight_sum: 0,
      });
    }
    if (!this.graph.hasNode(target_id)) {
      this.addNode({
        id: target_id,
        name: target_id.slice(0, 8),
        node_type: "unknown",
        weight_sum: 0,
      });
    }
    if (this.graph.hasEdge(edge_id)) {
      this.graph.setEdgeAttribute(edge_id, "weight", new_weight);
      this.graph.setEdgeAttribute(edge_id, "size", 0.5 + new_weight * 3);
      this.graph.setEdgeAttribute(edge_id, "spikeTime", performance.now() / 1000);
      this.graph.setEdgeAttribute(edge_id, "color", delta >= 0 ? "#34d399" : "#f87171");
    } else {
      this.addEdge({
        id: edge_id,
        source: source_id,
        target: target_id,
        weight: new_weight,
        relation_type: "synapse",
      });
      if (this.graph.hasEdge(edge_id)) {
        this.graph.setEdgeAttribute(edge_id, "spikeTime", performance.now() / 1000);
      }
    }
    this.scrubber.pushEvent(
      ts,
      this.indexOf(source_id),
      this.indexOf(target_id),
      delta,
      KIND_SYNAPSE,
    );
  }

  /** Seed a demo graph sized for perf targets (5k nodes / 20k edges). */
  seedBenchmarkGraph(nodes = 5000, edges = 20_000): void {
    this.graph.clear();
    this.idToIndex.clear();
    this.indexToId.length = 0;
    for (let i = 0; i < nodes; i++) {
      const id = `n${i}`;
      this.addNode({
        id,
        name: id,
        node_type: i % 5 === 0 ? "concept" : "file",
        weight_sum: Math.random() * 3,
      });
    }
    let added = 0;
    while (added < edges) {
      const s = Math.floor(Math.random() * nodes);
      const t = Math.floor(Math.random() * nodes);
      if (s === t) continue;
      const id = `e${added}`;
      const source = `n${s}`;
      const target = `n${t}`;
      if (this.graph.hasEdge(source, target)) continue;
      this.addEdge({
        id,
        source,
        target,
        weight: Math.random(),
        relation_type: "causes",
      });
      added++;
    }
    this.runLayout(true);
  }

  runLayout(assign = false): void {
    if (this.fa2Running) return;
    this.fa2Running = true;
    const settings = forceAtlas2.inferSettings(this.graph);
    forceAtlas2.assign(this.graph, {
      iterations: assign ? 50 : 10,
      settings: { ...settings, barnesHutOptimize: true },
    });
    this.fa2Running = false;
    this.sigma.refresh();
  }

  getNodeAttrs(id: string): Record<string, unknown> | null {
    if (!this.graph.hasNode(id)) return null;
    return this.graph.getNodeAttributes(id);
  }

  getEdgeAttrs(id: string): Record<string, unknown> | null {
    if (!this.graph.hasEdge(id)) return null;
    return this.graph.getEdgeAttributes(id);
  }

  dispose(): void {
    cancelAnimationFrame(this.raf);
    this.sigma.kill();
    this.graph.clear();
  }
}

function colorForType(t: string): string {
  switch (t) {
    case "concept":
      return "#60a5fa";
    case "file":
      return "#a78bfa";
    case "skill":
      return "#34d399";
    case "lesson":
      return "#fbbf24";
    default:
      return "#94a3b8";
  }
}
