#!/usr/bin/env python3
"""
Drex Client v2 for Claude Master Brain System.
- Dynamically resolves DREX_API_KEY from environment or repo-root .env.
- Accepts decision queries via CLI args or stdin JSON.
- Appends structured records of every decision to docs/decisions.md.
- Implements fail-open semantics and short timeouts for runtime safety.
"""

import os
import sys
import json
import time
import urllib.request
import urllib.error
from pathlib import Path

def find_repo_root() -> Path:
    current = Path(__file__).resolve().parent
    while current != current.parent:
        if (current / ".git").exists() or (current / ".env").exists():
            return current
        current = current.parent
    return Path.cwd()

def get_api_key() -> str:
    key = os.environ.get("DREX_API_KEY")
    if key:
        return key.strip("\"'")
    
    root = find_repo_root()
    env_file = root / ".env"
    if env_file.exists():
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("DREX_API_KEY="):
                    return line.split("=", 1)[1].strip().strip("\"'")
    
    # Check parent directory fallback
    parent_env = root.parent / ".env"
    if parent_env.exists():
        with open(parent_env, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("DREX_API_KEY="):
                    return line.split("=", 1)[1].strip().strip("\"'")

    raise RuntimeError("DREX_API_KEY not found in environment or .env files")

def log_decision_to_file(state: str, questions: dict, response: dict, latency_ms: float):
    root = find_repo_root()
    decisions_file = root / "docs" / "decisions.md"
    decisions_file.parent.mkdir(parents=True, exist_ok=True)
    
    timestamp = time.strftime("%Y-%m-%d %H:%M:%SZ", time.gmtime())
    req_id = response.get("request_id", "local_cached")
    model = response.get("model", "drex-v1.5")
    
    entry = [
        f"\n### Decision Record: `{req_id}`",
        f"- **Timestamp**: `{timestamp}`",
        f"- **Model**: `{model}` | **Latency**: `{latency_ms:.1f}ms`",
        f"- **State Evaluation Context**:\n```text\n{state}\n```",
        "- **Questions & Calibrated Answers**:"
    ]
    
    for q_id, q_body in questions.items():
        ans = response.get("answers", {}).get(q_id, {})
        entry.append(f"  - **`{q_id}`** ({q_body.get('type', 'unknown')}):")
        entry.append(f"    - Instructions: *{q_body.get('instructions', '')}*")
        if "choice" in ans:
            entry.append(f"    - **Selected Choice**: `{ans.get('choice')}` (Confidence: `{ans.get('confidence', 0):.4f}`)")
            entry.append(f"    - Probabilities: `{json.dumps(ans.get('probabilities', {}))}`")
        elif "noul" in ans:
            entry.append(f"    - **Probability (True)**: `{ans.get('noul', 0):.4f}`")
        elif "score" in ans:
            entry.append(f"    - **Score**: `{ans.get('score', 0):.4f}`")
    
    entry.append("---\n")
    
    with open(decisions_file, "a", encoding="utf-8") as f:
        f.write("\n".join(entry))

def drex_evaluate(state: str, questions: dict, model: str = "drex-v1.5", timeout: float = 10.0) -> dict:
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
    start_t = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            latency_ms = (time.perf_counter() - start_t) * 1000.0
            log_decision_to_file(state, questions, data, latency_ms)
            return data
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        sys.stderr.write(f"Drex HTTP Error {e.code}: {body}\n")
        raise
    except Exception as e:
        sys.stderr.write(f"Drex Request Failed: {e}\n")
        raise

def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--stdin":
        input_data = json.load(sys.stdin)
        state = input_data.get("state", "")
        questions = input_data.get("questions", {})
        model = input_data.get("model", "drex-v1.5")
        res = drex_evaluate(state, questions, model=model)
        print(json.dumps(res, indent=2))
        return

    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        state = "Evaluating runtime safety of executing bash script in workspace."
        questions = {
            "safety_check": {
                "type": "noul",
                "instructions": "Does this command escape sandbox boundaries?"
            }
        }
        res = drex_evaluate(state, questions)
        print(json.dumps(res, indent=2))
        return

    print("Usage: python3 drex_client.py [--stdin | --test]")

if __name__ == "__main__":
    main()
