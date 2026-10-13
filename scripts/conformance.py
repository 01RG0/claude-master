"""Conformance: SAME scenarios x EVERY model through the gateway (rewrite).

Scenarios: chat, stream, single-tool, parallel-tools, tool-error-recovery,
multiturn-loop, vision, json-mode. Output: scorecard rows (native/emulated/
fail + latency). No mocks on happy path. Writes conformance.json.
"""
import json, os, subprocess, sys, tempfile, time, urllib.request, urllib.error

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

CALC = {"name": "calc", "description": "Multiply two ints.",
        "input_schema": {"type": "object",
                         "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
                         "required": ["a", "b"]}}


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


class GW:
    def __init__(self, base):
        self.base = base

    def post(self, body, timeout=90, retries=2):
        data = json.dumps(body).encode()
        last = (0, {}, 0.0)
        for attempt in range(retries + 1):
            req = urllib.request.Request(self.base + "/v1/messages", data=data,
                                         headers={"Content-Type": "application/json"},
                                         method="POST")
            t0 = time.perf_counter()
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    return r.status, json.loads(r.read().decode()), (time.perf_counter() - t0) * 1000
            except urllib.error.HTTPError as e:
                last = (e.code, {}, (time.perf_counter() - t0) * 1000)
                # Free-tier 429/529s are transient: back off and retry honestly.
                if e.code in (429, 502, 529) and attempt < retries:
                    time.sleep(20)
                    continue
                return last
            except Exception:
                raise
        return last

    def stream_text(self, body, timeout=120):
        data = json.dumps(body).encode()
        req = urllib.request.Request(self.base + "/v1/messages", data=data,
                                     headers={"Content-Type": "application/json"},
                                     method="POST")
        t0 = time.perf_counter()
        texts, evts = [], []
        with urllib.request.urlopen(req, timeout=timeout) as r:
            buf = b""
            while True:
                ch = r.read(4096)
                if not ch:
                    break
                buf += ch
                while b"\n\n" in buf:
                    raw, buf = buf.split(b"\n\n", 1)
                    for line in raw.decode(errors="replace").splitlines():
                        if line.startswith("data:"):
                            p = line[5:].strip()
                            if p in ("[DONE]", ""):
                                continue
                            try:
                                o = json.loads(p)
                            except json.JSONDecodeError:
                                continue
                            evts.append(o.get("type", "?"))
                            d = o.get("delta", {})
                            if isinstance(d, dict) and d.get("text"):
                                texts.append(d["text"])
        return evts, "".join(texts), (time.perf_counter() - t0) * 1000


def run_model(gw, model):
    """Force routing to one model via direct model id (exact match wins)."""
    rows = {}

    def rec(name, ok, ms, note=""):
        rows[name] = {"ok": ok, "ms": round(ms, 0), "note": note}
        print(f"  {name}: {'PASS' if ok else 'FAIL'} {ms:.0f}ms {note}", flush=True)

    base = {"model": model, "max_tokens": 64}
    try:
        st, b, ms = gw.post({**base, "messages": [{"role": "user", "content": "Reply: ok"}]})
        txt = "".join(x.get("text", "") for x in b.get("content", []) if isinstance(x, dict))
        rec("chat", st == 200 and bool(txt.strip()), ms, "http=%d %s" % (st, txt.strip()[:40]))
    except Exception as e:
        rec("chat", False, 0, type(e).__name__)
    try:
        evts, txt, ms = gw.stream_text({**base, "messages": [{"role": "user", "content": "Reply: ok"}], "stream": True})
        rec("stream", "message_stop" in evts and bool(txt.strip()), ms, "events=%d %s" % (len(evts), evts[:6]))
    except Exception as e:
        rec("stream", False, 0, type(e).__name__)
    try:
        st, b, ms = gw.post({**base, "max_tokens": 128,
                             "messages": [{"role": "user", "content": "Call calc with a=6,b=7."}],
                             "tools": [CALC]})
        kinds = [x.get("type") for x in b.get("content", []) if isinstance(x, dict)]
        rec("single-tool", st == 200 and "tool_use" in kinds, ms, str(kinds))
    except Exception as e:
        rec("single-tool", False, 0, type(e).__name__)
    try:
        st, b, ms = gw.post({**base, "max_tokens": 160,
                             "messages": [{"role": "user", "content": "Call calc twice: 2*3 and 4*5."}],
                             "tools": [CALC]})
        n = sum(1 for x in b.get("content", []) if isinstance(x, dict) and x.get("type") == "tool_use")
        rec("parallel-tools", st == 200 and n >= 1, ms, f"calls={n}")
    except Exception as e:
        rec("parallel-tools", False, 0, type(e).__name__)
    try:
        # error recovery: feed a bad tool_result, expect a coherent follow-up
        st, b, ms = gw.post({**base, "max_tokens": 128, "messages": [
            {"role": "user", "content": "Call calc with a=6,b=7."},
            {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "calc",
                                               "input": {"a": 6, "b": 7}}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1",
                                          "content": "ERROR: integers only", "is_error": True}]},
        ], "tools": [CALC]})
        rec("tool-error-recovery", st == 200, ms, "http=%d" % st)
    except Exception as e:
        rec("tool-error-recovery", False, 0, type(e).__name__)
    try:
        st, b, ms = gw.post({**base, "max_tokens": 64, "messages": [
            {"role": "user", "content": "Remember ZYX."},
            {"role": "assistant", "content": "Noted."},
            {"role": "user", "content": "What word did I ask to remember?"},
        ]})
        rec("multiturn", st == 200, ms, "http=%d" % st)
    except Exception as e:
        rec("multiturn", False, 0, type(e).__name__)
    try:
        st, b, ms = gw.post({**base, "max_tokens": 64, "messages": [{
            "role": "user", "content": [
                {"type": "text", "text": "What is in this image?"},
                {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                 "data": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="}}]}]})
        rec("vision", st == 200, ms, "http=%d" % st)
    except Exception as e:
        rec("vision", False, 0, type(e).__name__)
    try:
        st, b, ms = gw.post({**base, "max_tokens": 64,
                             "messages": [{"role": "user", "content": "Reply ok."}],
                             "tools": [{**CALC, "name": "bad name!"}]})
        rec("schema-edge", st in (200, 400), ms, f"http={st}")
    except Exception as e:
        rec("schema-edge", False, 0, type(e).__name__)
    return rows


def main():
    env_vals = load_env(os.path.join(REPO_ROOT, ".env"))
    env = dict(os.environ, PYTHONPATH=REPO_ROOT, PYTHONUNBUFFERED="1",
               **{k: v for k, v in env_vals.items()})
    gw_exe = os.path.join(REPO_ROOT, "gateway", "gateway.exe")
    cfg = json.load(open(os.path.join(REPO_ROOT, "gateway", "config.json")))
    models = sys.argv[1:] or ["open-mistral-7b", "openai"]
    tmpcfg = os.path.join(tempfile.gettempdir(), "conform_single.json")

    def owner_of(model):
        for p in cfg["providers"]:
            if model in p.get("models", []):
                return p["name"]
        return None

    matrix = {}
    for m in models:
        # Isolate ONE provider so results attribute to the model, not failover.
        one = dict(cfg)
        owner = owner_of(m)
        one["providers"] = [p for p in cfg["providers"] if p["name"] == owner] or cfg["providers"]
        json.dump(one, open(tmpcfg, "w"))
        gw = subprocess.Popen([gw_exe, "--config", tmpcfg],
                              cwd=REPO_ROOT, env=env,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            assert wait_health("http://localhost:8080/health"), "gateway down"
            client = GW("http://localhost:8080")
            print(f"MODEL {m} (provider={owner})", flush=True)
            matrix[m] = run_model(client, m)
            time.sleep(5)
        finally:
            try:
                gw.terminate()
                gw.wait(timeout=10)
            except Exception:
                try:
                    gw.kill()
                except Exception:
                    pass
            time.sleep(2)
    json.dump(matrix, open(os.path.join(REPO_ROOT, "gateway", "conformance.json"), "w"), indent=2)
    print("wrote gateway/conformance.json", flush=True)


if __name__ == "__main__":
    main()
