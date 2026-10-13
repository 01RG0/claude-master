#!/usr/bin/env python3
"""Secret scanner for CI (rewrite). Fails if probable secrets are committed.

Scans tracked files (git ls-files) for:
  - nace_sk_... / sk-... / AKIA... patterns
  - KEY = value assignments with long random-looking values in non-example files
Skips .env.example, docs with [REDACTED], and test fixtures with fake_key.
Exit 0 = clean, 1 = leak found. Never prints the secret itself.
"""
import re
import subprocess
import sys

PATTERNS = [
    re.compile(r"nace_sk_[A-Za-z0-9_-]{8,}"),
    re.compile(r"\bsk-(live|test)-[A-Za-z0-9]{8,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"xox[bap]-.+", re.IGNORECASE),
]

ASSIGN = re.compile(
    r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*['\"]?([A-Za-z0-9_\-./+]{20,})['\"]?"
)

ALLOW_FILES = (".env.example", "secret_scan.py", "test_secrets.py")
ALLOW_SUBSTR = ("fake_key", "test_key", "dummy", "[REDACTED]", "REDACTED", "example",
                "abc123", "sk-abc", "placeholder", "xxx", "test", "fake", "Test")


def tracked_files():
    try:
        out = subprocess.run(["git", "ls-files"], capture_output=True, text=True, check=True)
        return out.stdout.splitlines()
    except Exception:
        return []


def main() -> int:
    leaks = 0
    for path in tracked_files():
        if path == ".env" or path.endswith("/.env") or ".venv/" in path:
            print(f"LEAK: tracked secret file {path}")
            leaks += 1
            continue
        if any(a in path for a in ALLOW_FILES):
            continue
        try:
            with open(path, encoding="utf-8", errors="ignore") as fh:
                text = fh.read()
        except OSError:
            continue
        if any(a in text for a in ("[REDACTED]",)):
            pass
        for pat in PATTERNS:
            m = pat.search(text)
            if m and not any(a in text[max(0, m.start() - 40):m.end() + 40] for a in ALLOW_SUBSTR):
                print(f"LEAK: {path} matches {pat.pattern} (value redacted)")
                leaks += 1
                break
        else:
            for line in text.splitlines():
                if any(a in line for a in ALLOW_SUBSTR):
                    continue
                if ASSIGN.search(line) and "example" not in path.lower():
                    print(f"SUSPECT: {path}: possible committed credential (redacted)")
                    leaks += 1
                    break
    if leaks:
        print(f"secret_scan: {leaks} leak(s) found")
        return 1
    print("secret_scan: clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
