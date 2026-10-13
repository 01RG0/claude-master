"""Count catalog records without treating capability probes as quality scores."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODELS_PATH = ROOT / "data" / "catalog" / "models.json"
REPORT_PATH = ROOT / "data" / "catalog" / "coverage_audit_report.json"


def audit() -> dict:
    models = json.loads(MODELS_PATH.read_text(encoding="utf-8"))
    records = list(models.values())
    agentic = [model for model in records if model.get("is_agentic") is True]
    probed = [
        model for model in records
        if (model.get("empirical_evidence") or {}).get("probes_evaluated", 0) > 0
    ]
    measured_quality = [
        model for model in records
        if isinstance(model.get("measured_quality"), (int, float))
        and model.get("measured_quality_source")
    ]
    result = {
        "catalog_path": "data/catalog/models.json",
        "catalog_model_ids": len(models),
        "agentic_flagged_by_existing_catalog": len(agentic),
        "agentic_filter_status": "EXISTING CATALOG FLAGS ONLY; fresh filter run NOT MEASURED",
        "models_with_capability_probe_evidence": len(probed),
        "agentic_models_with_capability_probe_evidence": sum(
            model.get("is_agentic") is True for model in probed
        ),
        "models_with_provenanced_quality_score": len(measured_quality),
        "quality_coverage": f"{len(measured_quality)}/{len(models)}",
        "unmeasured_model_policy": (
            "Quality is NOT MEASURED. Do not display a numeric quality estimate or "
            "treat capability probes, catalog metadata, or name heuristics as task quality. "
            "A model may be labeled agentic by catalog metadata, but remains unscored for quality."
        ),
        "limitations": [
            "Catalog is a snapshot and its agentic flags are not an independently audited filter result.",
            "Capability probes validate endpoint behavior only; they are not task-quality measurements.",
        ],
    }
    REPORT_PATH.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    audit()
