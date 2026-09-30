# Card B7: WebGL Synaptic Studio & Scrubber

## Goal
Build `studio/` in TypeScript. Implement the live force-directed synaptic graph viewer using Sigma.js v3, off-thread Graphology ForceAtlas2 worker, custom WebGL traveling pulse shaders, and a 60 FPS HTML5 Canvas replay scrubber with a TypedArray ring buffer.

## Owned Paths
- `studio/`
- `tests/studio/`

## Forbidden Paths
- `brain/`, `gateway/`, `hookshim/`, `contracts/`

## Inputs
- `contracts/events.md`
- Shortlist Part 14: `jacomyal/sigma.js` (WebGL instanced shaders)
- Shortlist Part 15: Custom TypedArray Ring Buffer & Canvas Scrubber

## Acceptance Tests
1. WebGL viewport renders 5,000 nodes and 20,000 edges at steady 60 FPS.
2. GPU traveling wave pulse shader animates synaptic firing along edges without CPU memory reallocations.
3. Canvas time scrubber accurately scrubs through past event ring buffer in `PAUSED` and `REPLAYING` modes.
4. Studio connects to brain WebSocket and updates edge weights in real time.

## Performance Budget
- Rendering: 60 FPS under active physics simulation.
- Replay scrubber seek latency < 16ms (within one frame).

## Deliverables
- `studio/src/graph/`
- `studio/src/shaders/`
- `studio/src/scrubber/`
- `studio/src/ui/`

## Report Format
- At most 15 lines: WebGL FPS benchmarks, pulse shader verification, scrubber state machine tests.
