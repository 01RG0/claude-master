# License Audit

Audits every ported file for AGPL/GPL contamination. Companion to `NOTICE`.

## Audit Method

1. `git log --all --oneline` to enumerate every source commit.
2. For each file in `brain/`, `gateway/`, `hookshim/`, `watchdog/`, `studio/src/`,
   grep the header comment for an "Algorithm provenance" or license line.
3. Cross-reference provenance claims against `research/shortlist.md` and
   `research/risks.md`.
4. Confirm no file imports from a quarantined package.

## Results

| File | Provenance Claim | License | Verdict |
| :--- | :--- | :--- | :---: |
| `brain/learning/hebbian.py` | huawjcn/GHL; sss777999/Brain | MIT | CLEAN |
| `brain/learning/spreading.py` | nhadaututtheky/neural-memory; OSU-NLP-Group/HippoRAG | MIT | CLEAN |
| `brain/learning/fsrs.py` | open-spaced-repetition/py-fsrs | MIT | CLEAN |
| `brain/store/graph.py` | getzep/graphiti | Apache-2.0 | CLEAN |
| `brain/reflect/reflexion.py` | noahshinn/reflexion | MIT | CLEAN |
| `brain/reflect/skill_store.py` | MineDojo/Voyager | MIT | CLEAN |
| `brain/reflect/distiller.py` | LeapLabTHU/ExpeL | Apache-2.0 | CLEAN |
| `brain/sleep/consolidator.py` | sss777999/Brain sleep_inference | MIT | CLEAN |
| `brain/guard/stuck_detector.py` | OpenHands/software-agent-sdk | MIT | CLEAN |
| `gateway/bandit.py` | lm-sys/RouteLLM | Apache-2.0 | CLEAN |
| `gateway/cooldown.go` | BerriAI/litellm core (MIT) | MIT | CLEAN |
| `studio/src/shaders/*` | jacomyal/sigma.js | MIT | CLEAN |
| `studio/src/scrubber/*` | vasturiano/force-graph | MIT | CLEAN |

## Quarantine Confirmation

No file in the tree imports or copies from:
- `free-claude-code` (AGPL-3.0)
- `QuantumNous/new-api` (AGPL-3.0)
- `jakdot/pyactr` (GPL-3.0)
- `songquanpeng/one-api` (custom)
- `BerriAI/litellm/enterprise/` (proprietary)

## Audit Command

```bash
grep -rn 'import' brain gateway hookshim watchdog studio/src | grep -iE 'fcc|new.api|pyactr|one.api|litellm.enterprise'
# Expected: no output
```