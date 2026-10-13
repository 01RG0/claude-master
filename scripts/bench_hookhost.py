"""Hook-host benchmark: persistent keep-alive host vs cold spawn (Windows).

Starts a real brain daemon subprocess + a real hookhost subprocess, measures:
  (a) hookshim.exe cold spawn per call, direct TCP to brain (N=100)
  (b) persistent downstream conn to hookhost, sequential calls (N=100)
  (c) hookshim.exe cold spawn per call via host (CLAUDE_HOOK_HOST set, N=100)
Reports min/p50/p95/p99 for each + verdict whether host path hits <10ms.
No secrets printed.
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRAIN_TCP = "127.0.0.1:7781"
HOST_ADDR = "127.0.0.1:7783"
HTTP_PORT = 7792
N = 100

PAYLOAD_TMPL = {
    "hook_event_name": "PreToolUse",
    "tool_name": "Bash",
    "input": {"command": "git status"},
}

SHIM = os.path.join(REPO_ROOT, "hookshim", "hookshim.exe")
GO_BIN = r"C:\Program Files\Go\bin"


def pct(data, q):
    s = sorted(data)
    return s[min(len(s) - 1, int(len(s) * q / 100))]


def wait_health(url, timeout=30):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.2)
    return False


def wait_port(addr, timeout=15):
    host, port = addr.split(":")
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        try:
            with socket.create_connection((host, int(port)), timeout=2):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def build_shim():
    env = dict(os.environ, PATH=GO_BIN + os.pathsep + os.environ.get("PATH", ""))
    subprocess.run(["go", "build", "-o", SHIM, "."],
                   cwd=os.path.join(REPO_ROOT, "hookshim"),
                   env=env, check=True, capture_output=True, timeout=300)


def rpc(sock, payload):
    t0 = time.perf_counter()
    sock.sendall(payload + b"\n")
    buf = b""
    while not buf.endswith(b"\n"):
        chunk = sock.recv(65536)
        if not chunk:
            break
        buf += chunk
    return (time.perf_counter() - t0) * 1000, buf


def main():
    build_shim()
    tmp = tempfile.gettempdir()
    db = os.path.join(tmp, "bench_hookhost.db")
    for f in (db, db + "-wal", db + "-shm"):
        try:
            os.remove(f)
        except OSError:
            pass
    base_env = dict(os.environ, PYTHONPATH=REPO_ROOT, PYTHONUNBUFFERED="1")
    daemon = subprocess.Popen(
        [sys.executable, "-m", "brain.server", "--db", db, "--tcp", BRAIN_TCP,
         "--port", str(HTTP_PORT)],
        cwd=REPO_ROOT, env=base_env, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    host = None
    try:
        assert wait_health(f"http://127.0.0.1:{HTTP_PORT}/health"), "daemon not healthy"
        host = subprocess.Popen(
            [SHIM, "--serve", "--host", HOST_ADDR],
            env={**base_env, "CLAUDE_BRAIN_TCP": BRAIN_TCP},
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        assert wait_port(HOST_ADDR), "hookhost never listened"

        spawn_env = {**os.environ, "CLAUDE_BRAIN_TCP": BRAIN_TCP,
                     "CLAUDE_BRAIN_TIMEOUT_MS": "2000"}
        spawn_env.pop("CLAUDE_HOOK_HOST", None)
        via_env = {**spawn_env, "CLAUDE_HOOK_HOST": HOST_ADDR}

        def spawn_once(env, i):
            payload = json.dumps({**PAYLOAD_TMPL, "session_id": f"bench-{i}"}).encode()
            t0 = time.perf_counter()
            p = subprocess.run([SHIM], input=payload, capture_output=True,
                               timeout=15, env=env)
            dt = (time.perf_counter() - t0) * 1000
            assert p.returncode in (0, 2), (p.returncode, p.stderr[:200])
            return dt

        spawn_times = [spawn_once(spawn_env, i) for i in range(N)]
        via_times = [spawn_once(via_env, i) for i in range(N)]

        hh, hp = HOST_ADDR.split(":")
        host_times = []
        with socket.create_connection((hh, int(hp)), timeout=5) as sock:
            for i in range(5):  # warmup (excluded): fills host upstream conn
                rpc(sock, json.dumps({**PAYLOAD_TMPL, "session_id": f"warm-{i}"}).encode())
            for i in range(N):
                dt, line = rpc(sock, json.dumps(
                    {**PAYLOAD_TMPL, "session_id": f"bench-host-{i}"}).encode())
                assert b"allow" in line, line[:120]
                host_times.append(dt)

        def row(name, xs):
            return (f"{name}: min={min(xs):.2f}ms p50={pct(xs,50):.2f}ms "
                    f"p95={pct(xs,95):.2f}ms p99={pct(xs,99):.2f}ms max={max(xs):.2f}ms (n={len(xs)})")

        print(row("spawn direct to brain", spawn_times))
        print(row("spawn via hookhost", via_times))
        print(row("persistent via hookhost (1 conn)", host_times))
        p50, p95 = pct(host_times, 50), pct(host_times, 95)
        if p50 < 10:
            print(f"VERDICT: <10ms budget MET on host path (p50={p50:.2f}ms p95={p95:.2f}ms)")
        else:
            print(f"VERDICT: <10ms budget NOT met on host path (p50={p50:.2f}ms p95={p95:.2f}ms)")
    finally:
        for proc in (host, daemon):
            if proc is None:
                continue
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except Exception:
                proc.kill()


if __name__ == "__main__":
    main()
