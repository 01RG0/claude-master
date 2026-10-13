#!/usr/bin/env python3
"""Legacy thin wrapper kept for compat; delegates to brain.judge.client (rewrite).

Resolves repo root dynamically (no hardcoded home paths), uses
https://console.nace.ai, supports NACE_API_KEY/DREX_API_KEY, 60s timeout.
Prefer `python scripts/drex_client.py --test` or DecisionTaker for new code.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from brain.judge.client import DrexClient


def drex_evaluate(state: str, questions: dict, model: str | None = None):
    return DrexClient(model=model).evaluate(state, questions)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        res = drex_evaluate(
            state="Evaluating graph memory engines for autonomous coding agents.",
            questions={
                "pick_engine": {
                    "type": "choice",
                    "instructions": "Which memory model best enables persistent, associative reflection?",
                    "criteria": {
                        "hebbian_graph": "Synaptic weight graph with spreading activation and decay",
                        "flat_vector": "Standard vector embeddings database with top-k cosine similarity",
                    },
                }
            },
        )
        print(json.dumps(res, indent=2))
