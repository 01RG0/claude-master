import { describe, expect, it } from "vitest";
import {
  EventRingBuffer,
  KIND_SYNAPSE,
  KIND_NODE_FIRE,
} from "../../studio/src/scrubber/ring-buffer";

describe("EventRingBuffer", () => {
  it("pushes without growing TypedArrays", () => {
    const buf = new EventRingBuffer(8);
    const tsRef = buf.timestamps;
    const srcRef = buf.sources;
    for (let i = 0; i < 20; i++) {
      buf.push(1000 + i, i, i + 1, 0.1 * i, KIND_SYNAPSE);
    }
    expect(buf.timestamps).toBe(tsRef);
    expect(buf.sources).toBe(srcRef);
    expect(buf.size).toBe(8);
    expect(buf.isFull).toBe(true);
    expect(buf.oldestTs()).toBe(1000 + 12);
    expect(buf.newestTs()).toBe(1000 + 19);
  });

  it("seekIndex finds rightmost ts <= target", () => {
    const buf = new EventRingBuffer(100);
    for (let i = 0; i < 50; i++) buf.push(i * 10, i, 0, 1, KIND_NODE_FIRE);
    expect(buf.seekIndex(0)).toBe(0);
    expect(buf.seekIndex(25)).toBe(2); // ts 20
    expect(buf.seekIndex(250)).toBe(25);
    expect(buf.seekIndex(10_000)).toBe(49);
    expect(buf.seekIndex(-1)).toBe(-1);
  });

  it("seek over full 250k buffer stays under 16ms", () => {
    const buf = new EventRingBuffer(250_000);
    for (let i = 0; i < 250_000; i++) {
      buf.push(i, i, i + 1, 1, KIND_SYNAPSE);
    }
    const t0 = performance.now();
    for (let k = 0; k < 100; k++) {
      buf.seekIndex(Math.floor(Math.random() * 250_000));
    }
    const elapsed = performance.now() - t0;
    expect(elapsed / 100).toBeLessThan(16);
  });

  it("get returns correct slot after wrap", () => {
    const buf = new EventRingBuffer(4);
    for (let i = 0; i < 6; i++) buf.push(i, i, 0, i, KIND_SYNAPSE);
    // logical 0 = oldest = ts 2
    expect(buf.get(0).ts).toBe(2);
    expect(buf.get(3).ts).toBe(5);
    expect(buf.get(3).delta).toBe(5);
  });
});
