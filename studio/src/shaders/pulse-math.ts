/**
 * Pulse intensity reference (matches Shortlist §14 GLSL formula) for unit checks.
 */
export function pulseIntensity(
  progress: number,
  time: number,
  spikeTime: number,
  speed: number,
  sigma: number,
): number {
  const phase = fract((time - spikeTime) * speed);
  const d = progress - phase;
  return Math.exp(-(d * d) / (2 * sigma * sigma));
}

function fract(x: number): number {
  return x - Math.floor(x);
}
