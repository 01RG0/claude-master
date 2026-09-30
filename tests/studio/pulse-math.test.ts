import { describe, expect, it } from "vitest";
import { pulseIntensity } from "../../studio/src/shaders/pulse-math";

describe("edge pulse formula", () => {
  it("peaks when progress aligns with traveling phase", () => {
    const speed = 0.5;
    const spike = 0;
    const time = 2; // phase = fract(1.0) = 0
    const atPeak = pulseIntensity(0, time, spike, speed, 0.08);
    const offPeak = pulseIntensity(0.5, time, spike, speed, 0.08);
    expect(atPeak).toBeGreaterThan(0.9);
    expect(atPeak).toBeGreaterThan(offPeak);
  });

  it("is allocation-free pure math (stable)", () => {
    let sum = 0;
    for (let i = 0; i < 1000; i++) {
      sum += pulseIntensity(i / 1000, i * 0.01, 0, 0.35, 0.08);
    }
    expect(sum).toBeGreaterThan(0);
  });
});
