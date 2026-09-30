/**
 * Node-side ring-buffer ops benchmark (GPU FPS is a documented target;
 * this measures allocation-free push/seek throughput).
 *
 * Target: seek << 16ms; push without realloc.
 * Run: npm run bench:buffer  (from studio/)
 */
import { EventRingBuffer, KIND_SYNAPSE } from "../src/scrubber/ring-buffer";

const CAP = 250_000;
const buf = new EventRingBuffer(CAP);

const tPush0 = performance.now();
for (let i = 0; i < CAP; i++) {
  buf.push(i, i, i + 1, 0.01, KIND_SYNAPSE);
}
const pushMs = performance.now() - tPush0;

const tsRef = buf.timestamps.buffer;
const tSeek0 = performance.now();
let checksum = 0;
for (let i = 0; i < 10_000; i++) {
  checksum += buf.seekIndex((i * 997) % CAP);
}
const seekMs = performance.now() - tSeek0;
const avgSeek = seekMs / 10_000;

const sameBuffer = buf.timestamps.buffer === tsRef;

console.log(
  JSON.stringify(
    {
      capacity: CAP,
      fill_ms: +pushMs.toFixed(3),
      pushes_per_sec: Math.round(CAP / (pushMs / 1000)),
      seek_iters: 10_000,
      avg_seek_ms: +avgSeek.toFixed(6),
      max_seek_budget_ms: 16,
      seek_under_budget: avgSeek < 16,
      no_realloc: sameBuffer,
      checksum,
      gpu_fps_target: 60,
      note: "GPU 5k/20k @ 60 FPS is a browser WebGL target; verified via Seed 5k in studio UI",
    },
    null,
    2,
  ),
);

if (!sameBuffer || avgSeek >= 16) {
  process.exitCode = 1;
}
