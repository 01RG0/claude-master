# Card B2: Neuro-Inspired Learning & Spreading Activation

## Goal
Build `brain/learning`. Implement Three-Factor Neuromodulated Hebbian Learning (LTP on success, LTD on error), FSRS-5 power-law stability decay, and Priority-Queue BFS Spreading Activation for associative context retrieval.

## Owned Paths
- `brain/learning/`
- `tests/brain/test_learning.py`

## Forbidden Paths
- `gateway/`, `hookshim/`, `studio/`, `contracts/`

## Inputs
- `contracts/schema.sql`
- Shortlist Part 4: `open-spaced-repetition/py-fsrs`
- Shortlist Part 5: `HippoRAG` & `nhadaututtheky/neural-memory`
- Shortlist Part 6: `huawjcn/GHL` & `sss777999/Brain`

## Acceptance Tests
1. Hebbian update increases weight on positive reward ($R = 1.0$) and decreases weight on negative reward ($R = -0.8$).
2. FSRS-5 decay function matches power-law retention curve over simulated elapsed intervals.
3. Spreading activation starting from 2 seed nodes traverses causal/reinforcing edges and suppresses refractory loops.
4. Total execution time of spreading activation across 1,000 nodes is < 5ms.

## Performance Budget
- Spreading activation query < 5.0ms.
- Synaptic weight update < 2.0ms.

## Deliverables
- `brain/learning/hebbian.py`
- `brain/learning/fsrs.py`
- `brain/learning/spreading.py`
- `tests/brain/test_learning.py`

## Report Format
- At most 15 lines: algorithms implemented, mathematical verification, benchmark latency, test pass rate.
