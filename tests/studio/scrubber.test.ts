import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { EventRingBuffer } from "../../studio/src/scrubber/ring-buffer";
import { Scrubber } from "../../studio/src/scrubber/scrubber";

describe("Scrubber state machine", () => {
  let scrubber: Scrubber;

  beforeEach(() => {
    scrubber = new Scrubber(new EventRingBuffer(1024));
    vi.stubGlobal(
      "requestAnimationFrame",
      (cb: FrameRequestCallback) => {
        return setTimeout(() => cb(performance.now()), 16) as unknown as number;
      },
    );
    vi.stubGlobal("cancelAnimationFrame", (id: number) => clearTimeout(id));
  });

  afterEach(() => {
    scrubber.dispose();
    vi.unstubAllGlobals();
  });

  it("starts in LIVE and tracks newest on push", () => {
    expect(scrubber.getMode()).toBe("LIVE");
    scrubber.pushEvent(100, 1, 2, 0.5);
    scrubber.pushEvent(200, 3, 4, -0.1);
    const snap = scrubber.snapshot();
    expect(snap.mode).toBe("LIVE");
    expect(snap.cursorTs).toBe(200);
    expect(snap.bufferSize).toBe(2);
  });

  it("pause freezes cursor while buffer may grow", () => {
    scrubber.pushEvent(100, 0, 1, 1);
    scrubber.pause();
    expect(scrubber.getMode()).toBe("PAUSED");
    scrubber.pushEvent(300, 0, 1, 1);
    expect(scrubber.snapshot().cursorTs).toBe(100);
    expect(scrubber.snapshot().bufferSize).toBe(2);
  });

  it("seek in PAUSED is under 16ms and updates cursor", () => {
    const big = new Scrubber(new EventRingBuffer(8192));
    for (let i = 0; i < 5000; i++) big.pushEvent(i * 2, i, 0, 1);
    big.pause();
    const { index, elapsedMs } = big.seek(5000);
    expect(elapsedMs).toBeLessThan(16);
    expect(index).toBeGreaterThanOrEqual(0);
    expect(big.snapshot().cursorTs).toBeLessThanOrEqual(5000);
    expect(big.getMode()).toBe("PAUSED");
    big.dispose();
  });

  it("beginScrub / endScrub transitions", () => {
    scrubber.pushEvent(10, 0, 0, 0);
    scrubber.beginScrub();
    expect(scrubber.getMode()).toBe("SCRUBBING");
    scrubber.seek(10);
    scrubber.endScrub(true);
    expect(scrubber.getMode()).toBe("PAUSED");
  });

  it("live() returns to LIVE at newest", () => {
    scrubber.pushEvent(1, 0, 0, 0);
    scrubber.pause();
    scrubber.pushEvent(99, 0, 0, 0);
    scrubber.live();
    expect(scrubber.getMode()).toBe("LIVE");
    expect(scrubber.snapshot().cursorTs).toBe(99);
  });

  it("play enters REPLAYING", () => {
    for (let i = 0; i < 10; i++) scrubber.pushEvent(i * 100, 0, 0, 1);
    scrubber.pause();
    scrubber.seek(0);
    scrubber.play(2);
    expect(scrubber.getMode()).toBe("REPLAYING");
  });
});
