/**
 * Pre-allocated TypedArray ring buffer for synaptic events (Shortlist §15).
 * Allocation-free circular store — capacity fixed at construction.
 *
 * Layout per slot:
 *   timestamps  Float64Array  — event ts (ms)
 *   sources     Uint32Array   — packed source node index
 *   targets     Uint32Array   — packed target node index
 *   deltas      Float32Array  — weight delta / activation
 *   kinds       Uint8Array    — event kind tag
 */

export const KIND_SYNAPSE = 1;
export const KIND_NODE_FIRE = 2;
export const KIND_INVALIDATE = 3;
export const KIND_OTHER = 0;

export interface RingSlot {
  ts: number;
  source: number;
  target: number;
  delta: number;
  kind: number;
}

export class EventRingBuffer {
  readonly capacity: number;
  readonly timestamps: Float64Array;
  readonly sources: Uint32Array;
  readonly targets: Uint32Array;
  readonly deltas: Float32Array;
  readonly kinds: Uint8Array;

  private head = 0;
  private count = 0;

  constructor(capacity = 250_000) {
    if (capacity < 1) throw new Error("capacity must be >= 1");
    this.capacity = capacity;
    this.timestamps = new Float64Array(capacity);
    this.sources = new Uint32Array(capacity);
    this.targets = new Uint32Array(capacity);
    this.deltas = new Float32Array(capacity);
    this.kinds = new Uint8Array(capacity);
  }

  get size(): number {
    return this.count;
  }

  get isFull(): boolean {
    return this.count === this.capacity;
  }

  /** Write one event without reallocating. Overwrites oldest when full. */
  push(ts: number, source: number, target: number, delta: number, kind = KIND_OTHER): void {
    const i = this.head;
    this.timestamps[i] = ts;
    this.sources[i] = source >>> 0;
    this.targets[i] = target >>> 0;
    this.deltas[i] = delta;
    this.kinds[i] = kind & 0xff;
    this.head = (i + 1) % this.capacity;
    if (this.count < this.capacity) this.count++;
  }

  /** Logical index 0 = oldest, size-1 = newest. */
  private physical(logical: number): number {
    if (logical < 0 || logical >= this.count) {
      throw new RangeError(`logical index ${logical} out of range [0, ${this.count})`);
    }
    if (this.count < this.capacity) return logical;
    return (this.head + logical) % this.capacity;
  }

  get(logical: number): RingSlot {
    const i = this.physical(logical);
    return {
      ts: this.timestamps[i]!,
      source: this.sources[i]!,
      target: this.targets[i]!,
      delta: this.deltas[i]!,
      kind: this.kinds[i]!,
    };
  }

  oldestTs(): number | null {
    if (this.count === 0) return null;
    return this.get(0).ts;
  }

  newestTs(): number | null {
    if (this.count === 0) return null;
    return this.get(this.count - 1).ts;
  }

  /**
   * Binary search for the rightmost slot with ts <= targetTs.
   * Returns logical index, or -1 if all events are after targetTs.
   * Target: seek latency << 16ms even at full capacity.
   */
  seekIndex(targetTs: number): number {
    let lo = 0;
    let hi = this.count - 1;
    let ans = -1;
    while (lo <= hi) {
      const mid = (lo + hi) >>> 1;
      const ts = this.timestamps[this.physical(mid)]!;
      if (ts <= targetTs) {
        ans = mid;
        lo = mid + 1;
      } else {
        hi = mid - 1;
      }
    }
    return ans;
  }

  /** Copy slots in [fromLogical, toLogical] into a pre-allocated dest (no alloc of ring). */
  copyRange(fromLogical: number, toLogical: number, dest: RingSlot[]): number {
    const start = Math.max(0, fromLogical);
    const end = Math.min(this.count - 1, toLogical);
    let n = 0;
    for (let i = start; i <= end; i++) {
      dest[n++] = this.get(i);
    }
    return n;
  }

  clear(): void {
    this.head = 0;
    this.count = 0;
  }
}
