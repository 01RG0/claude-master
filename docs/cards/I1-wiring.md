# Card I1: End-to-End System Wiring & Interconnection

## Goal
Integrate all subsystems into a unified operational pipeline. Connect Claude Code -> Go Gateway -> Free Upstream Providers, Claude Code Hooks -> Hookshim -> Brain Daemon Socket, and Brain Daemon -> WebSocket -> Studio Viewer.

## Owned Paths
- `integration/`
- `scripts/start_brain.sh`
- `scripts/run_session.sh`

## Forbidden Paths
- Core algorithms in `brain/`, `gateway/`, `hookshim/`, `studio/`

## Inputs
- Outputs from all Wave 1 builder cards (B1 to B8)

## Acceptance Tests
1. Single launch script starts Gateway, Brain Daemon, Watchdog, and Studio.
2. Simulated Claude Code session runs commands through hooks and receives working memory context.
3. Real-time synaptic firing pulses appear in Studio viewer over WebSocket during session.
4. Complete session log records Hebbian weight changes in SQLite database.

## Performance Budget
- End-to-end hook overhead < 15ms.

## Deliverables
- `scripts/start_brain.sh`
- `scripts/run_session.sh`
- `integration/test_full_pipeline.py`

## Report Format
- At most 15 lines: pipeline connectivity verified, end-to-end dataflow confirmed, launch script tested.
