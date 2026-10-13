#!/usr/bin/env python3
"""Run real empirical catalog audit across all active providers.

Outputs:
- data/catalog/models.json
- data/catalog/routes.json
- data/catalog/non_agentic_evidence.json
"""

import json
import logging
import sys
from pathlib import Path

# Add project root to path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from brain.routing.catalog import CatalogAuditor

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

def main():
    print("=" * 70)
    print("CATALOG & MODEL IDENTITY AUDITOR -- EMPIRICAL PROBING RUN")
    print("=" * 70)

    auditor = CatalogAuditor(root_dir=ROOT)
    print("Running audit with real empirical probing...")
    summary = auditor.audit_catalog(live_probing=True)

    print("\nAudit completed:")
    print(f"  Total Canonical Models: {summary['total_canonical_models']}")
    print(f"  Total Active Routes:    {summary['total_routes']}")
    print(f"  Agentic Models:         {summary['agentic_models_count']}")
    print(f"  Non-Agentic Filtered:   {summary['non_agentic_models_filtered']}")
    print(f"  Misclassified Evidence: {summary['misclassified_evidence_count']}")

    models_path, routes_path = auditor.export_catalog()
    print(f"\nSaved catalog:")
    print(f"  Models: {models_path}")
    print(f"  Routes: {routes_path}")

    # Display multi-route resolution highlights
    print("\n" + "=" * 70)
    print("MULTI-ROUTE CANONICAL RESOLUTION HIGHLIGHTS (Aggregator Grouping):")
    print("=" * 70)
    multi_route_models = [m for m in auditor.models.values() if len(m.routes) > 1]
    for m in multi_route_models[:10]:
        print(f"\nCanonical ID: {m.canonical_id} ({m.display_name})")
        print(f"  Type: {m.type} | Agentic: {m.is_agentic} | Context: {m.context_window}")
        print(f"  Routes ({len(m.routes)}):")
        for r_id in m.routes:
            r = auditor.routes[r_id]
            print(f"    - [{r.provider}] model={r.provider_model_id} | latency={r.measured_latency_ms}ms | cost in/out=${r.pricing.get('prompt_per_m')}/${r.pricing.get('completion_per_m')}")

    # Display non-agentic filtered models
    print("\n" + "=" * 70)
    print("FILTERED NON-AGENTIC MODELS WITH EMPIRICAL EVIDENCE:")
    print("=" * 70)
    for rec in auditor.misclassified_non_agentic[:15]:
        print(f"\nProvider: {rec['provider']} | Model: {rec['model_id']}")
        print(f"  Canonical: {rec['canonical_id']}")
        print(f"  Modalities: {rec['modalities']}")
        print(f"  Reason: {rec['reason']}")
        evidence = rec.get("evidence", {})
        details = evidence.get("details", [])
        if details:
            print(f"  Evidence: {details[0].get('evidence')}")

if __name__ == "__main__":
    main()
