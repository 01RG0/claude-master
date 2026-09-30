/**
 * Scrubber state machine: LIVE / PAUSED / REPLAYING (+ transient SCRUBBING).
 * Seek uses the ring buffer binary search; budget < 16ms per seek.
 */

import { EventRingBuffer, type RingSlot } from "./ring-buffer.js";

export type ScrubberMode = "LIVE" | "PAUSED" | "REPLAYING" | "SCRUBBING";

export interface ScrubberSnapshot {
  mode: ScrubberMode;
  cursorTs: number;
  speed: number;
  oldestTs: number | null;
  newestTs: number | null;
  bufferSize: number;
  cursorIndex: number;
}

export type ScrubberListener = (snap: ScrubberSnapshot) => void;

export class Scrubber {
  readonly buffer: EventRingBuffer;
  private mode: ScrubberMode = "LIVE";
  private cursorTs = 0;
  private cursorIndex = -1;
  private speed = 1;
  private replayRaf: number | null = null;
  private lastFrameWall = 0;
  private readonly listeners = new Set<ScrubberListener>();

  constructor(buffer?: EventRingBuffer) {
    this.buffer = buffer ?? new EventRingBuffer();
  }

  getMode(): ScrubberMode {
    return this.mode;
  }

  subscribe(fn: ScrubberListener): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  private emit(): void {
    const snap = this.snapshot();
    for (const fn of this.listeners) fn(snap);
  }

  snapshot(): ScrubberSnapshot {
    return {
      mode: this.mode,
      cursorTs: this.cursorTs,
      speed: this.speed,
      oldestTs: this.buffer.oldestTs(),
      newestTs: this.buffer.newestTs(),
      bufferSize: this.buffer.size,
      cursorIndex: this.cursorIndex,
    };
  }

  /** Ingest a live event. When LIVE, cursor tracks newest. */
  pushEvent(ts: number, source: number, target: number, delta: number, kind?: number): void {
    this.buffer.push(ts, source, target, delta, kind);
    if (this.mode === "LIVE") {
      this.cursorTs = ts;
      this.cursorIndex = this.buffer.size - 1;
      this.emit();
    }
  }

  pause(): void {
    this.stopReplayLoop();
    this.mode = "PAUSED";
    this.emit();
  }

  live(): void {
    this.stopReplayLoop();
    this.mode = "LIVE";
    const newest = this.buffer.newestTs();
    if (newest != null) {
      this.cursorTs = newest;
      this.cursorIndex = this.buffer.size - 1;
    }
    this.emit();
  }

  /**
   * Seek to a timestamp. Returns elapsed ms for budget checks.
   * Valid in PAUSED / REPLAYING / SCRUBBING.
   */
  seek(targetTs: number): { index: number; elapsedMs: number } {
    const t0 = performance.now();
    if (this.mode === "LIVE") {
      this.mode = "SCRUBBING";
    } else if (this.mode === "REPLAYING") {
      // keep REPLAYING; just reposition
    } else {
      this.mode = this.mode === "PAUSED" ? "PAUSED" : "SCRUBBING";
    }
    const index = this.buffer.seekIndex(targetTs);
    this.cursorIndex = index;
    if (index >= 0) {
      this.cursorTs = this.buffer.get(index).ts;
    } else {
      this.cursorTs = targetTs;
    }
    const elapsedMs = performance.now() - t0;
    this.emit();
    return { index, elapsedMs };
  }

  /** Enter explicit scrubbing gesture (drag). */
  beginScrub(): void {
    this.stopReplayLoop();
    this.mode = "SCRUBBING";
    this.emit();
  }

  endScrub(keepPaused = true): void {
    this.mode = keepPaused ? "PAUSED" : "LIVE";
    if (!keepPaused) this.live();
    else this.emit();
  }

  play(speed = 1): void {
    this.speed = speed;
    this.mode = "REPLAYING";
    this.lastFrameWall = performance.now();
    this.startReplayLoop();
    this.emit();
  }

  setSpeed(speed: number): void {
    this.speed = Math.max(0.1, speed);
    this.emit();
  }

  /** Slots from previous cursor..current for applying a replay frame. */
  slotsAtCursor(): RingSlot | null {
    if (this.cursorIndex < 0 || this.cursorIndex >= this.buffer.size) return null;
    return this.buffer.get(this.cursorIndex);
  }

  private startReplayLoop(): void {
    this.stopReplayLoop();
    const tick = (now: number) => {
      if (this.mode !== "REPLAYING") return;
      const dt = (now - this.lastFrameWall) * this.speed;
      this.lastFrameWall = now;
      const newest = this.buffer.newestTs();
      if (newest == null) {
        this.pause();
        return;
      }
      const nextTs = this.cursorTs + dt;
      if (nextTs >= newest) {
        this.seek(newest);
        this.pause();
        return;
      }
      this.seek(nextTs);
      this.mode = "REPLAYING";
      this.replayRaf = requestAnimationFrame(tick);
    };
    this.replayRaf = requestAnimationFrame(tick);
  }

  private stopReplayLoop(): void {
    if (this.replayRaf != null) {
      cancelAnimationFrame(this.replayRaf);
      this.replayRaf = null;
    }
  }

  dispose(): void {
    this.stopReplayLoop();
    this.listeners.clear();
  }
}
