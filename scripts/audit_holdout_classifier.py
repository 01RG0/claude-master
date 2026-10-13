"""audit_holdout_classifier.py — Evaluates classifier against holdout dataset.

Computes:
- Confusion Matrix (TP, TN, FP, FN)
- Precision, Recall, Specificity, F1-Score
- Error analysis on adversarial and novel hard cases
- Exports results to data/catalog/holdout_audit_report.json
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List

from brain.routing.classifier import classify_model_capabilities

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOLDOUT_PATH = os.path.join(REPO_ROOT, "data", "catalog", "holdout_dataset.json")
REPORT_PATH = os.path.join(REPO_ROOT, "data", "catalog", "holdout_audit_report.json")


def evaluate_holdout() -> Dict[str, Any]:
    with open(HOLDOUT_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    samples = data["samples"]

    tp = 0  # True Positive: Agentic correctly predicted as Agentic
    tn = 0  # True Negative: Non-agentic correctly predicted as Non-agentic
    fp = 0  # False Positive: Non-agentic wrongly predicted as Agentic
    fn = 0  # False Negative: Agentic wrongly predicted as Non-agentic

    misclassified = []
    eval_details = []

    for s in samples:
        model_id = s["model_id"]
        expected_agentic = s["expected_agentic"]

        cls = classify_model_capabilities(model_id, provider="holdout_eval")
        pred_agentic = cls.is_agentic

        is_correct = (pred_agentic == expected_agentic)

        if expected_agentic and pred_agentic:
            tp += 1
        elif not expected_agentic and not pred_agentic:
            tn += 1
        elif not expected_agentic and pred_agentic:
            fp += 1
            misclassified.append({
                "model_id": model_id,
                "expected": "Non-Agentic",
                "predicted": "Agentic",
                "predicted_modalities": cls.modalities
            })
        else:
            fn += 1
            misclassified.append({
                "model_id": model_id,
                "expected": "Agentic",
                "predicted": "Non-Agentic",
                "predicted_modalities": cls.modalities
            })

        eval_details.append({
            "model_id": model_id,
            "category": s.get("category"),
            "expected_agentic": expected_agentic,
            "predicted_agentic": pred_agentic,
            "predicted_modalities": cls.modalities,
            "correct": is_correct
        })

    total = len(samples)
    accuracy = (tp + tn) / total if total > 0 else 0.0
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    specificity = tn / (tn + fp) if (tn + fp) > 0 else 0.0
    f1 = (2.0 * precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0

    report = {
        "title": "Classification Holdout Audit & Hard Cases Evaluation",
        "dataset_path": HOLDOUT_PATH,
        "total_samples": total,
        "metrics": {
            "accuracy": round(accuracy, 4),
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "specificity": round(specificity, 4),
            "f1_score": round(f1, 4)
        },
        "confusion_matrix": {
            "true_positive_agentic": tp,
            "true_negative_non_agentic": tn,
            "false_positive": fp,
            "false_negative": fn
        },
        "misclassified_count": len(misclassified),
        "misclassified_models": misclassified,
        "details": eval_details
    }

    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print("=== Holdout Classification Audit Completed ===")
    print(f"Total Samples: {total}")
    print(f"Confusion Matrix: TP={tp}, TN={tn}, FP={fp}, FN={fn}")
    print(f"Precision: {precision:.4f} | Recall: {recall:.4f} | F1: {f1:.4f}")
    if misclassified:
        print(f"Misclassified: {len(misclassified)}")
        for m in misclassified:
            print(f"  - {m['model_id']}: expected {m['expected']}, got {m['predicted']}")
    else:
        print("ZERO MISCLASSIFICATIONS (100% Precision, Recall, and F1 on Holdout Suite)!")

    return report


if __name__ == "__main__":
    evaluate_holdout()
