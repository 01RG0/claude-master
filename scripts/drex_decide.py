#!/usr/bin/env python3
import os
import sys
import json
import urllib.request
import urllib.error

def get_api_key():
    key = os.environ.get("DREX_API_KEY")
    if key:
        return key
    env_paths = [
        "/home/rootuser/claude-master/.env",
        "/home/rootuser/.env"
    ]
    for p in env_paths:
        if os.path.exists(p):
            with open(p) as f:
                for line in f:
                    if line.startswith("DREX_API_KEY="):
                        return line.strip().split("=", 1)[1].strip("\"'")
    raise RuntimeError("DREX_API_KEY not found in environment or .env files")

def drex_evaluate(state: str, questions: dict, model: str = "drex-v1.5"):
    key = get_api_key()
    url = "https://drex.nace.ai/v1/systemone"
    payload = {
        "model": model,
        "state": state,
        "questions": questions
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json"
        },
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        sys.stderr.write(f"Drex HTTP Error {e.code}: {body}\n")
        raise

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
                        "flat_vector": "Standard vector embeddings database with top-k cosine similarity"
                    }
                }
            }
        )
        print(json.dumps(res, indent=2))
