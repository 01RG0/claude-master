"""Real Claude Code run through the gateway with hooks + memory check (rewrite).

Starts brain + gateway, runs `claude -p` tasks with ANTHROPIC_BASE_URL,
hookshim.exe hooks active, then verifies hook sessions + memory writes.
Redacted output only.
"""
import json, os, shutil, sqlite3, subprocess, sys, tempfile, time, urllib.request

REPO_ROOT = r"D:\pRoG\claude-master"
TASKDIR = r"C:\Users\hamad\AppData\Local\Temp\opencode\claudetask"


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


def main():
    env_vals = load_env(os.path.join(REPO_ROOT, ".env"))
    shutil.rmtree(TASKDIR, ignore_errors=True)
    os.makedirs(TASKDIR, exist_ok=True)
    tmp = tempfile.gettempdir()
    db = os.path.join(tmp, "claude_live_brain.db")
    for f in (db, db + "-wal", db + "-shm"):
        try:
            os.remove(f)
        except OSError:
            pass
    tcp, bport = "127.0.0.1:7783", 7788
    shim = os.path.join(REPO_ROOT, "hookshim", "hookshim.exe")
    hook_cmd = f'"{shim}" --tcp {tcp}'
    logdir = os.path.join(tmp, "claude-live-logs")
    os.makedirs(logdir, exist_ok=True)
    blog = open(os.path.join(logdir, "brain.log"), "w")
    glog = open(os.path.join(logdir, "gateway.log"), "w")
    # project settings: hooks fire hookshim.exe for every tool + prompt.
    # NOTE: ~/.claude/settings.json on this host pins ANTHROPIC_BASE_URL to a
    # LiteLLM router; project env overrides user env, so pin ours here.
    settings = {
        "env": {
            "ANTHROPIC_BASE_URL": "http://localhost:8080",
            "ANTHROPIC_API_KEY": "dummy",
            "ANTHROPIC_MODEL": "sonnet",
        },
        "hooks": {
            "PreToolUse": [{"matcher": ".*", "hooks": [{"type": "command",
                                                        "command": hook_cmd}]}],
            "PostToolUse": [{"matcher": ".*", "hooks": [{"type": "command",
                                                         "command": hook_cmd}]}],
        },
    }
    claude_dir = os.path.join(TASKDIR, ".claude")
    os.makedirs(claude_dir, exist_ok=True)
    json.dump(settings, open(os.path.join(claude_dir, "settings.json"), "w"))
    env = dict(os.environ, PYTHONPATH=REPO_ROOT, PYTHONUNBUFFERED="1",
               CLAUDE_BRAIN_TCP=tcp, ANTHROPIC_BASE_URL="http://localhost:8080",
               ANTHROPIC_API_KEY="dummy",
               **{k: v for k, v in env_vals.items()
                  if "KEY" in k or k.endswith("_URL") or k == "PORT"})
    brain = subprocess.Popen(
        [sys.executable, "-m", "brain.server", "--db", db, "--tcp", tcp,
         "--port", str(bport)], cwd=REPO_ROOT, env=env,
        stdout=blog, stderr=subprocess.STDOUT)
    gw = None
    try:
        assert wait_health(f"http://127.0.0.1:{bport}/health"), "brain down"
        gw = subprocess.Popen(
            [os.path.join(REPO_ROOT, "gateway", "gateway.exe"), "--config",
             os.path.join(REPO_ROOT, "gateway", "config.json"),
             "--log-requests", os.path.join(logdir, "traffic")],
            cwd=REPO_ROOT, env=env, stdout=glog, stderr=subprocess.STDOUT)
        assert wait_health("http://localhost:8080/health"), "gateway down"

        tasks = [
            ("T1-haiku", ["claude", "-p", "Write a haiku about rivers to haiku.txt in the current directory.",
                          "--allowedTools", "Write", "Edit", "Bash", "--add-dir", TASKDIR]),
            ("T2-edit", ["claude", "-p", "Append a second verse to haiku.txt, then list directory contents with ls.",
                         "--allowedTools", "Write", "Edit", "Read", "Bash", "--add-dir", TASKDIR]),
            ("T3-shell", ["claude", "-p", "Run pwd and echo HELLO-WORLD-42 via shell, report outputs.",
                          "--allowedTools", "Bash", "--add-dir", TASKDIR]),
        ]
        results = []
        for name, cmd in tasks:
            t0 = time.perf_counter()
            try:
                p = subprocess.run(cmd, cwd=TASKDIR, env=env, capture_output=True,
                                   text=True, timeout=600)
                dt = (time.perf_counter() - t0) * 1000
                out = (p.stdout or "")[-300:].replace("\n", " | ")
                print(f"{name}: rc={p.returncode} lat={dt:.0f}ms out={out[:200]!r}", flush=True)
                results.append(p.returncode == 0)
            except subprocess.TimeoutExpired:
                print(f"{name}: TIMEOUT after 600s", flush=True)
                results.append(False)
        print(f"files: {sorted(os.listdir(TASKDIR))}", flush=True)

        # hooks fired? (daemon sessions live in-process; query health nodes + hook endpoint)
        with urllib.request.urlopen(f"http://127.0.0.1:{bport}/health", timeout=5) as r:
            print("brain health:", r.read()[:160], flush=True)
        con = sqlite3.connect(db)
        try:
            print("model_stats:", con.execute("SELECT model_id, successes, failures FROM model_stats").fetchall(), flush=True)
            print("edges:", con.execute("SELECT COUNT(*) FROM brain_edges WHERE invalid_at IS NULL").fetchone(), flush=True)
            print("sleep_log:", con.execute("SELECT COUNT(*) FROM sleep_log").fetchone(), flush=True)
        finally:
            con.close()
        print(f"CLAUDE: {sum(results)}/{len(results)} tasks rc=0", flush=True)
        return all(results)
    finally:
        for p in (gw, brain):
            if p is not None:
                try:
                    p.terminate()
                    p.wait(timeout=10)
                except Exception:
                    try:
                        p.kill()
                    except Exception:
                        pass


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
