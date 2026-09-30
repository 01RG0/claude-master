# Card B4: Reflexion, Skill Store & Nightly Sleep Consolidation

## Goal
Build `brain/reflect` and `brain/sleep`. Implement Reflexion test execution harness with episodic verbal failure reflection, Voyager-style docstring skill library, ExpeL cross-trajectory lesson distiller, and the 4-phase nightly sleep consolidation worker.

## Owned Paths
- `brain/reflect/`
- `brain/sleep/`
- `tests/brain/test_reflect.py`

## Forbidden Paths
- `gateway/`, `hookshim/`, `studio/`, `contracts/`

## Inputs
- Shortlist Part 11: `noahshinn/reflexion` (`reflexion.py`)
- Shortlist Part 12: `MineDojo/Voyager` (`skill.py`)
- Shortlist Part 13: `LeapLabTHU/ExpeL` (`expel.py`)
- Track 2 Sleep Consolidation specifications

## Acceptance Tests
1. Reflexion harness captures failed assertions and formats episodic verbal memory snippet.
2. Skill store saves verified code snippets indexed by synthesized docstrings.
3. ExpeL distiller extracts operational guidelines from paired success/failure traces.
4. Nightly sleep job executes: replay, transitive closure, community abstraction, and multiplicative downscaling ($w \leftarrow w \cdot 0.95$).

## Performance Budget
- Sleep consolidation runs in background with zero disruption to active sessions.

## Deliverables
- `brain/reflect/reflexion.py`
- `brain/reflect/skill_store.py`
- `brain/sleep/consolidator.py`
- `tests/brain/test_reflect.py`

## Report Format
- At most 15 lines: components built, sleep cycle stages verified, test results.
