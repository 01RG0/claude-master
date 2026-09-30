/** Typed envelopes matching contracts/events.md (read-only). */

export interface EventEnvelope<T = unknown> {
  event: string;
  ts: number;
  data: T;
}

export interface GraphNode {
  id: string;
  name: string;
  node_type: string;
  weight_sum: number;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  weight: number;
  relation_type: string;
}

export interface SnapshotData {
  nodes: GraphNode[];
  edges: GraphEdge[];
  sleep_phase: string | null;
}

export interface NodeFiredData {
  node_id: string;
  activation_score: number;
  session_id: string;
}

export interface SynapseUpdatedData {
  edge_id: string;
  source_id: string;
  target_id: string;
  old_weight: number;
  new_weight: number;
  delta: number;
  reward: number;
}

export interface EdgeInvalidatedData {
  edge_id: string;
  replacement_edge_id: string;
}

export interface CircuitBreakerData {
  session_id: string;
  pattern: string;
  iteration: number;
  nudge_generated: boolean;
}

export interface SleepPhaseData {
  run_id: string;
  phase: string;
  state: string;
  edges_strengthened: number;
  edges_pruned: number;
  lessons_added: number;
}

export interface SkillLearnedData {
  skill_id: string;
  name: string;
  version: number;
  language: string;
}

export interface LessonExtractedData {
  lesson_id: string;
  rule_text: string;
  confidence: number;
}

export interface GatewayProviderHealth {
  name: string;
  active_keys: number;
  cooldown_keys: number;
  /** Optional masked key fingerprints from server — never raw secrets. */
  key_masks?: string[];
}

export interface GatewayHealthData {
  providers: GatewayProviderHealth[];
  requests_last_60s: number;
}

export interface ReplayFrameData {
  replay_ts: number;
  active_node_ids: string[];
  active_edge_ids: string[];
}

export type BrainEvent =
  | EventEnvelope<SnapshotData> & { event: "snapshot" }
  | EventEnvelope<NodeFiredData> & { event: "node_fired" }
  | EventEnvelope<SynapseUpdatedData> & { event: "synapse_updated" }
  | EventEnvelope<EdgeInvalidatedData> & { event: "edge_invalidated" }
  | EventEnvelope<CircuitBreakerData> & { event: "circuit_breaker_tripped" }
  | EventEnvelope<SleepPhaseData> & { event: "sleep_phase" }
  | EventEnvelope<SkillLearnedData> & { event: "skill_learned" }
  | EventEnvelope<LessonExtractedData> & { event: "lesson_extracted" }
  | EventEnvelope<GatewayHealthData> & { event: "gateway_health" }
  | EventEnvelope<ReplayFrameData> & { event: "replay_frame" };

export interface SubscribeAction {
  action: "subscribe";
  session_id: string;
}

export interface ReplayAction {
  action: "replay";
  from_ts: number;
  to_ts: number;
  speed: number;
}

export type ClientAction = SubscribeAction | ReplayAction;
