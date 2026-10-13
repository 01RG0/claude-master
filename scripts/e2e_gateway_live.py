"""Live gateway E2E: real providers through the Anthropic-compatible API (rewrite).

Starts brain + gateway subprocesses, then runs real tasks. Prints per-task
PASS/FAIL with latency and provider (never prints keys or prompt secrets).
Exits non-zero if any task fails.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)


def load_env(path):
    vals = {}
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line[len("export "):].strip()
            k, v = line.split("=", 1)
            vals[k.strip()] = v.strip().strip("\"'")
    return vals


def wait_health(url, timeout=60):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        try:
            with urllib.request.urlopen(url, timeout=3) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.5)
    return False


def post(url, body, timeout=120, retries=3):
    data = json.dumps(body).encode()
    last = None
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, data=data,
                                     headers={"Content-Type": "application/json",
                                              "x-api-key": "dummy",
                                              "anthropic-version": "2023-06-01"},
                                     method="POST")
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, json.loads(r.read().decode()), (time.perf_counter() - t0) * 1000
        except urllib.error.HTTPError as e:
            last = e
            # Free-tier 429/502s are transient: back off and retry honestly.
            if e.code in (429, 502, 529) and attempt < retries:
                time.sleep(15)
                continue
            raise
    raise last


def post_stream(url, body, timeout=180):
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json",
                                          "x-api-key": "dummy",
                                          "anthropic-version": "2023-06-01"},
                                 method="POST")
    t0 = time.perf_counter()
    events = []
    text_parts = []
    with urllib.request.urlopen(req, timeout=timeout) as r:
        buf = b""
        while True:
            chunk = r.read(4096)
            if not chunk:
                break
            buf += chunk
            while b"\n\n" in buf:
                raw, buf = buf.split(b"\n\n", 1)
                for line in raw.decode(errors="replace").splitlines():
                    if line.startswith("data:"):
                        payload = line[5:].strip()
                        if payload == "[DONE]":
                            continue
                        try:
                            obj = json.loads(payload)
                        except json.JSONDecodeError:
                            continue
                        events.append(obj.get("type", "?"))
                        d = obj.get("delta", {})
                        if isinstance(d, dict) and d.get("text"):
                            text_parts.append(d["text"])
    return events, "".join(text_parts), (time.perf_counter() - t0) * 1000


BASE_MSG = [{"role": "user", "content": "Reply with exactly the five words: one two three four five"}]


def main():
    env_vals = load_env(os.path.join(REPO_ROOT, ".env"))
    tmp = tempfile.gettempdir()
    db = os.path.join(tmp, "e2e_live_brain.db")
    for f in (db, db + "-wal", db + "-shm"):
        try:
            os.remove(f)
        except OSError:
            pass
    tcp = "127.0.0.1:7781"
    bport, gport = 7786, 18080
    env = dict(os.environ, PYTHONPATH=REPO_ROOT, PYTHONUNBUFFERED="1",
               CLAUDE_BRAIN_TCP=tcp, **{k: v for k, v in env_vals.items()})
    brain = subprocess.Popen(
        [sys.executable, "-m", "brain.server", "--db", db, "--tcp", tcp,
         "--port", str(bport)], cwd=REPO_ROOT, env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    gw_exe = os.path.join(REPO_ROOT, "gateway", "gateway.exe")
    gateway = None
    results = []
    try:
        assert wait_health(f"http://127.0.0.1:{bport}/health"), "brain not healthy"
        gateway = subprocess.Popen(
            [gw_exe, "--config", os.path.join(REPO_ROOT, "gateway", "config.json")],
            cwd=REPO_ROOT, env={**env, "CLAUDE_BRAIN_TCP": tcp},
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # gateway listens on :8080 per config; health check
        assert wait_health("http://localhost:8080/health"), "gateway not healthy"
        G = "http://localhost:8080/v1/messages"

        def task(name, fn):
            try:
                detail = fn()
                print(f"PASS {name} {detail}", flush=True)
                results.append(True)
            except Exception as e:
                print(f"FAIL {name}: {type(e).__name__}: {str(e)[:200]}", flush=True)
                results.append(False)

        def t1():
            st, body, ms = post(G, {"model": "claude-test", "max_tokens": 64, "messages": BASE_MSG})
            assert st == 200, st
            txt = "".join(b.get("text", "") for b in body.get("content", []) if isinstance(b, dict))
            assert txt.strip(), "empty text"
            return f"lat={ms:.0f}ms text={txt.strip()[:60]!r}"

        def t2():
            evts, text, ms = post_stream(
                G, {"model": "claude-test", "max_tokens": 64, "messages": BASE_MSG, "stream": True})
            assert "message_start" in evts and "message_stop" in evts, evts[:8]
            assert text.strip(), "empty stream text"
            return f"lat={ms:.0f}ms events={len(evts)} text={text.strip()[:60]!r}"

        def t3():
            st, body, ms = post(G, {"model": "claude-test", "max_tokens": 128, "messages": [
                {"role": "user", "content": "What is 17 multiplied by 23? Use the calculator tool."}],
                "tools": [{"name": "calculator", "description": "Multiply two integers.",
                           "input_schema": {"type": "object",
                                            "properties": {"a": {"type": "integer"},
                                                           "b": {"type": "integer"}},
                                            "required": ["a", "b"]}}]})
            assert st == 200, st
            blocks = body.get("content", [])
            kinds = [b.get("type") for b in blocks if isinstance(b, dict)]
            assert "tool_use" in kinds or any("391" in json.dumps(b) for b in blocks), kinds
            return f"lat={ms:.0f}ms blocks={kinds}"

        def t4():
            st1, b1, ms1 = post(G, {"model": "claude-test", "max_tokens": 64,
                                    "messages": [{"role": "user", "content": "My project is called Aurora."}]})
            assert st1 == 200
            st2, b2, ms2 = post(G, {"model": "claude-test", "max_tokens": 64, "messages": [
                {"role": "user", "content": "My project is called Aurora."},
                {"role": "assistant", "content": "Noted."},
                {"role": "user", "content": "What is my project called? Answer in three words."}]})
            assert st2 == 200
            return f"lat={ms1:.0f}+{ms2:.0f}ms"

        def t5():
            # long streaming: 800-token essay exercises chunked SSE over time
            evts, text, ms = post_stream(
                G, {"model": "claude-test", "max_tokens": 800,
                    "messages": [{"role": "user", "content": "Write a 400-word essay on soil."}],
                    "stream": True})
            assert text.strip(), "empty long stream"
            return f"lat={ms:.0f}ms chars={len(text)} events={len(evts)}"

        def t6():
            st, body, ms = post("http://localhost:8080/v1/outcome",
                                {"model_id": "live/e2e", "success": True, "latency_ms": 1.0})
            assert st == 200 and body.get("ok"), (st, body)
            return f"lat={ms:.0f}ms ok"

        for name, fn in [("T1-chat", t1), ("T2-stream", t2), ("T3-tool-use", t3),
                         ("T4-multiturn", t4), ("T5-long-stream", t5), ("T6-outcome", t6)]:
            task(name, fn)
    finally:
        for p in (gateway, brain):
            if p is not None:
                try:
                    p.terminate()
                    p.wait(timeout=10)
                except Exception:
                    try:
                        p.kill()
                    except Exception:
                        pass
    print(f"E2E: {sum(results)}/{len(results)} passed", flush=True)
    sys.exit(0 if results and all(results) else 1)


if __name__ == "__main__":
    main()
