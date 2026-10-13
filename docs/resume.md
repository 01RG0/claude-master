# Resume Point (2026-10-14, session 5 — Freebuff continuation)

Branch `rewrite`, HEAD moves with the clamp/pinban commits below. Nothing
pushed. Concurrent session still owns untracked `brain/api/`, `cli/`,
`desktop/`, studio components — leave untouched except the brain startup
fail-open so e2e can run.

## Done this continuation

1. **Committed** harness + gateway logging (`e177c3d`): port pre-flight,
   `--listen` threading, request `sha`, upstream 4xx `reason=`.
2. **Re-measured on clean port 18080** (S2 n=3): 73.5 / 114.5 / 12.7s,
   pass 3/3. Prior 13/88/170 + "0 provider failures" **invalid** (foreign
   :8080). Numbers in `docs/benchmarks.md` corrected.
3. **Root-caused the 400 storm** via `reason=`: Claude Code sends
   `max_tokens=128000`; free providers reject (groq/pooled/openrouter).
   Also `model="*"` 404, anyapi 403, alibaba 401.
4. **Fixed**: outbound max_tokens clamp (default 16384, adapter override);
   wildcard pickModel passthrough; disable apertis/anyapi/alibaba/pooled;
   `provider pin|ban` persists to capabilities.json and gateway loads it.
5. **Post-fix re-measure** (port 18082): 31.7 / 27.0 / 85.1s, pass 2/3,
   HTTP 401/403/404 = 0. Passing reps ~2–4× faster than clean median.
6. **Brain fail-open**: if concurrent `brain.api` import breaks, fall back
   to stdlib HTTP so matrix harness stays green.

## Still left (ordered)

1. Route tool-heavy turns off `ministral-8b-latest`; raise S2 pass rate
   back to 3/3 under clamp (N≥5).
2. Aux-call reduction (cache/dedupe) — re-measure after routing change;
   do not trust the old 45% figure.
3. E2E Part-2 matrix: PTY interactive, MCP, plugins, hooks, LSP, vision,
   failover/429/budget residency, trend storage, `cm e2e report` trends.
4. Part 5: studio drill-down, token/cost metrics, `cm report --trend`.
5. Part 6: pre-commit hook, coverage, dep/license audit, release process.
6. Docs: folder READMEs, architecture/troubleshooting/glossary, status.md,
   ROADMAP.md; CI-executed doc commands.
7. Part 3: startup/memory/binary-size baselines; storage retention/caps.
8. Coordination: admin-API tests must use `CLAUDE_MASTER_GATEWAY_CONFIG`
   (ADR-010) — they keep writing fixture providers into live config.json;
   root `cm.bat`/`cli`/`desktop` overlap `tools/cm`.

## Gotchas

- Build gateway with `go build -o gateway.exe ./cmd/gateway` (NOT `.` —
  that emits an `ar` archive named .exe → WinError 216).
- Never measure on a port that already has a listener; harness refuses.
- `gateway/config.json` is live state — treat concurrent admin tests as hostile.
