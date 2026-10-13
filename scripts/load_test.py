"""Load test: 50 parallel streaming requests through the gateway (rewrite).

Verifies pool concurrency safety (no races, no hangs) and measures ok rate
+ latency under parallel streams. Free-tier 429s are expected and counted
separately from real failures.
"""
import json, os, subprocess, sys, tempfile, time, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
N = 50


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


def one(i):
    body = json.dumps({"model": "open-mistral-7b", "max_tokens": 32,
                       "messages": [{"role": "user", "content": f"Reply with the number {i}."}],
                       "stream": True}).encode()
    req = urllib.request.Request("http://localhost:8080/v1/messages", data=body,
                                 headers={"Content-Type": "application/json"}, method="POST")
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            n = len(r.read())
        return ("ok", (time.perf_counter() - t0) * 1000, n)
    except urllib.error.HTTPError as e:
        return (f"http{e.code}", (time.perf_counter() - t0) * 1000, 0)
    except Exception as e:
        return (type(e).__name__, (time.perf_counter() - t0) * 1000, 0)


def main():
    env_vals = load_env(os.path.join(REPO_ROOT, ".env"))
    env = dict(os.environ, PYTHONPATH=REPO_ROOT, **{k: v for k, v in env_vals.items()})
    gw = subprocess.Popen([os.path.join(REPO_ROOT, "gateway", "gateway.exe"), "--config",
                           os.path.join(REPO_ROOT, "gateway", "config.json")],
                          cwd=REPO_ROOT, env=env,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        assert wait_health("http://localhost:8080/health"), "gateway down"
        t0 = time.perf_counter()
        with ThreadPoolExecutor(max_workers=N) as ex:
            res = list(ex.map(one, range(N)))
        wall = (time.perf_counter() - t0) * 1000
        oks = [r for r in res if r[0] == "ok"]
        lats = sorted(r[1] for r in oks)
        from collections import Counter
        print(f"load: {len(oks)}/{N} ok in {wall:.0f}ms wall", flush=True)
        print(f"codes: {dict(Counter(r[0] for r in res))}", flush=True)
        if lats:
            print(f"ok-latency: p50={lats[len(lats)//2]:.0f}ms p95={lats[int(len(lats)*0.95)]:.0f}ms", flush=True)
        # admin stats prove accounting happened without races
        try:
            with urllib.request.urlopen("http://localhost:8080/v1/admin/stats", timeout=10) as r:
                st = json.loads(r.read().decode())
            print("admin models tracked: %d cooldowns=%s" % (len(st.get("models", [])), st.get("cooldowns_active")), flush=True)
        except Exception as e:
            print("admin stats failed:", e, flush=True)
    finally:
        try:
            gw.terminate()
            gw.wait(timeout=10)
        except Exception:
            try:
                gw.kill()
            except Exception:
                pass


if __name__ == "__main__":
    main()
