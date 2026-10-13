"""Audit holdout label provenance without converting circular labels into scores.

The legacy holdout's labels were authored alongside a name-based heuristic. They
are not independent ground truth, so this audit deliberately does not run the
classifier or publish precision/recall. Metrics become available only after each
sample has independently reviewed labels and supporting evidence.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
HOLDOUT_PATH = ROOT / "data" / "catalog" / "holdout_dataset.json"
REPORT_PATH = ROOT / "data" / "catalog" / "holdout_audit_report.json"


def evaluate_holdout() -> dict[str, Any]:
    data = json.loads(HOLDOUT_PATH.read_text(encoding="utf-8"))
    samples = data.get("samples", [])
    independently_labeled = [
        sample for sample in samples
        if sample.get("label_status") == "independently_reviewed"
        and sample.get("label_evidence")
        and isinstance(sample.get("expected_agentic"), bool)
    ]
    report: dict[str, Any] = {
        "title": "Classifier holdout provenance audit",
        "dataset_path": "data/catalog/holdout_dataset.json",
        "holdout_rows": len(samples),
        "legacy_labels_not_independent": sum(
            1 for sample in samples
            if sample.get("label_status") != "independently_reviewed"
        ),
        "independently_labeled_rows": len(independently_labeled),
        "hard_cases_available": len(data.get("hard_cases", [])),
        "metrics": {
            "precision": "NOT MEASURED",
            "recall": "NOT MEASURED",
            "specificity": "NOT MEASURED",
            "f1": "NOT MEASURED",
        },
        "confusion_matrix": "NOT MEASURED",
        "reason": (
            "No independent labels with review evidence are present. The legacy "
            "labels were created alongside the name-based heuristic and cannot "
            "support a leakage-free estimate."
        ),
        "hard_cases_status": "UNLABELED; excluded from performance metrics",
    }
    if independently_labeled:
        report["reason"] = (
            "Independent labels exist, but classifier scoring is intentionally "
            "not implemented in this provenance-only audit."
        )
    REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    evaluate_holdout()
