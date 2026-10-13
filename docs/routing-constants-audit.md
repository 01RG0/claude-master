# Routing constants audit

Audit status: operational values listed in `data/roles/hyperparameters.json` are **NOT MEASURED**. No calibration artifact or source log was found to substantiate the previous benchmark provenance labels. The numeric values remain active configuration for behavior compatibility; they are not empirical results.

The routing runtime reads configured thresholds from `data/roles/hyperparameters.json`. Missing keys now raise an explicit configuration error instead of silently using a second code-level default. The UI and API expose the current value, calibration status, source, and provenance. Runtime edits are also labeled **NOT MEASURED** until backed by calibration evidence.

## Remaining code-embedded policy values

These values still live in code. They are not calibration claims and were not changed in this cleanup because moving them changes separate policy behavior and requires a deliberate config migration.

| File | Active constant or behavior | Status |
| --- | --- | --- |
| `brain/routing/catalog.py` | Live probe cap `current_probes < 10` | NOT MEASURED; operational cap |
| `brain/routing/engine.py` | Default latency and cost weights `0.25` | NOT MEASURED; default objective weights |
| `brain/routing/learning.py` | Fixed quality component weights, drift delta, quality floor, calibration thresholds and step sizes | NOT MEASURED; learning policy constants |
| `brain/routing/profiles.py` | Role objective weights, fallback equal weights, and per-role budget defaults | NOT MEASURED; product policy presets |
| `brain/routing/scorer.py` | Static provider quality priors (including OpenAI `0.86`, Meta `0.80`), reliability fallback, and score clamps | NOT MEASURED; unsupported priors remain active |
| `brain/routing/scorer.py` | `CandidateMetrics` defaults: quality `0.70`, TTFT `400ms`, and `success_count=10` | NOT MEASURED; synthetic defaults still feed scoring |
| `brain/api/services/routing_service.py` | Empty-observation quality fallback `0.75` and latency fallback `350ms` | NOT MEASURED; synthetic fallback remains active |

These constants must not be described as learned, calibrated, or benchmark-derived. The synthetic candidate values specifically violate the intended "unknown quality remains NOT MEASURED" policy and still need a cold-start implementation change. Some other values are operational presets rather than thresholds; the inventory is intentionally explicit so future configuration work can migrate them without implying measured provenance.
