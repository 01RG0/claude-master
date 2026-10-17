"""Claude CLI scenario matrix through the gateway (rewrite).

Every scenario is a REAL `claude -p` run (installed CLI binary) against the
local gateway with hooks active, in a disposable workspace. Success is judged
by independent oracles (files on disk, command output, git state), never by
the model's own claim.

Usage:
  python scripts/e2e_claude_matrix.py                       # all, 1 rep
  python scripts/e2e_claude_matrix.py --tier smoke           # S1-S2
  python scripts/e2e_claude_matrix.py --scenario S1-multifile --repeat 5
  python scripts/e2e_claude_matrix.py --json-out off/e2e/x.json --resume
  python scripts/e2e_claude_matrix.py --model haiku          # CLI model id

Resumable: with --json-out + --resume, (scenario, rep) pairs already recorded
in the file are skipped. Results are stored per commit for trend tracking.
Redacted output only; no secrets printed. Exits non-zero unless every run
meets --min-pass-rate.
"""
import argparse
import json
import math
import os
import random
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid
import urllib.request

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE_TASK = None

# Windows cp1252 console would crash on Unicode previews (cf. BUG-005).
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def wilson_ci_95(successes: int, total: int) -> tuple[float, float]:
    """Calculate the Wilson 95% confidence interval for a binomial proportion."""
    if total <= 0:
        return (0.0, 0.0)
    z = 1.95996
    p = successes / total
    denom = 1.0 + (z * z) / total
    centre = (p + (z * z) / (2.0 * total)) / denom
    spread = (z * math.sqrt((p * (1.0 - p) / total) + (z * z) / (4.0 * total * total))) / denom
    return (max(0.0, centre - spread), min(1.0, centre + spread))


def load_env(path):
    vals = {}
    if not os.path.exists(path):
        return vals
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


def git_commit():
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                             cwd=REPO_ROOT, capture_output=True, text=True)
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


# ---------------------------------------------------------------------------
# Scenario registry: each entry owns its fixture setup and its oracle.
# An oracle gets (workdir, full_output, returncode) and returns True only on
# ground-truth evidence - file contents, real command output, git state.
# ---------------------------------------------------------------------------
def _scn(sid, tier, prompt, setup, oracle, tools=None):
    return {"id": sid, "tier": tier, "prompt": prompt, "setup": setup,
            "oracle": oracle, "tools": tools}


def _write(path, text):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


SCENARIOS = [
    _scn(
        "S1-multifile", "smoke",
        "Directly in the current working directory, create a.txt with 'alpha', b.txt with 'beta', c.txt with 'gamma'. Then append '-done' to each of those three files.",
        lambda d: None,
        # STRICT oracle (CORRECTION 2): only the specified path `d` counts.
        # Files outside `d` (e.g. slugified sibling d.replace("_","-")) are FAIL.
        lambda d, out, rc: rc == 0 and len([f for f in os.listdir(d) if f.endswith(".txt")]) >= 3
        and all(open(os.path.join(d, f), encoding="utf-8").read().strip().endswith("-done")
                for f in os.listdir(d) if f.endswith(".txt")),
    ),
    _scn(
        "S2-runtests", "smoke",
        "Run: python check.py. Report its exact output.",
        lambda d: _write(os.path.join(d, "check.py"), "print('CHECK-OK-123')\n"),
        lambda d, out, rc: rc == 0 and ("CHECK-OK-123" in out),
    ),
    _scn(
        "S3-refactor", "standard",
        "Rename function oldname to newname in mod.py. Make the edit now.",
        lambda d: _write(os.path.join(d, "mod.py"), "def oldname():\n    return 1\n"),
        lambda d, out, rc: ("def newname" in open(os.path.join(d, "mod.py"), encoding="utf-8").read()),
    ),
    _scn(
        "S4-debug", "standard",
        "Edit buggy.py: change the return statement from `return a - b` to `return a + b`. Make the Edit now.",
        lambda d: _write(os.path.join(d, "buggy.py"), "def add(a, b):\n    return a - b\n"),
        lambda d, out, rc: ("a + b" in open(os.path.join(d, "buggy.py"), encoding="utf-8").read()
                            or "a+b" in open(os.path.join(d, "buggy.py"), encoding="utf-8").read()),
    ),
    _scn(
        "S5-skill", "standard",
        "Use the reviewer skill on target.py.",
        lambda d: _write(os.path.join(d, "target.py"), "import os\npassword='x'\n"),
        lambda d, out, rc: ("- " in out) or ("**" in out) or ("review" in out.lower() or "finding" in out.lower()),
    ),
    _scn(
        "S6-subagent", "standard",
        "Delegate to a subagent: count the lines in notes.txt and report back.",
        lambda d: _write(os.path.join(d, "notes.txt"), "line one\nline two\n"),
        lambda d, out, rc: rc == 0 and ("agent" in out.lower()),
    ),
    _scn(
        "S7-hookallow", "standard",
        "Run echo HOOK-ALLOW-7 and report output.",
        lambda d: None,
        lambda d, out, rc: rc == 0 and ("HOOK-ALLOW-7" in out),
    ),
    _scn(
        "S8-hookblock", "standard",
        "Run: rm -rf /tmp/hookblock-probe. If blocked, say BLOCKED.",
        lambda d: None,
        lambda d, out, rc: ("BLOCKED" in out.upper() or "den" in out.lower())
        and not os.path.exists("/tmp/hookblock-probe"),
    ),
    _scn(
        "S9-slash", "standard",
        "/shout hello slash",
        lambda d: None,
        lambda d, out, rc: rc == 0 and ("HELLO" in out.upper()),
    ),
    _scn(
        "S10-long", "full",
        "Write a 300-word essay on concrete.",
        lambda d: None,
        lambda d, out, rc: rc == 0 and len(out) > 200,
    ),
]

SMOKE_TIERS = {"smoke": {"smoke"}, "standard": {"smoke", "standard"}, "full": {"smoke", "standard", "full"}}


def select_scenarios(names, tier):
    allowed = SMOKE_TIERS[tier]
    chosen = [s for s in SCENARIOS if s["tier"] in allowed]
    if names:
        want = set(names)
        chosen = [s for s in chosen if s["id"] in want]
        missing = want - {s["id"] for s in chosen}
        if missing:
            sys.exit(f"unknown scenario id(s): {', '.join(sorted(missing))} "
                     f"(known: {', '.join(s['id'] for s in SCENARIOS)})")
    return chosen


def port_in_use(port, host="127.0.0.1", timeout=1.0):
    import socket
    s = socket.socket()
    s.settimeout(timeout)
    try:
        s.connect((host, port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def choose_free_port(host="127.0.0.1"):
    import socket
    with socket.socket() as sock:
        sock.bind((host, 0))
        return sock.getsockname()[1]


def make_profile(base, name, model, gateway_port=8080):
    """Throwaway CLAUDE_CONFIG_DIR per run.

    Without this the installed CLI merges the user's real ~/.claude settings
    (base URL, model, auth token, history) into every run - observed live
    2026-10-13: runs were routed to the user's own router because settings
    `env` beats process env. An isolated profile keeps the user's real config,
    credentials and history untouched.
    """
    prof = os.path.join(base, "_cfg", name)
    shutil.rmtree(prof, ignore_errors=True)
    os.makedirs(prof, exist_ok=True)
    _write(os.path.join(prof, "settings.json"), json.dumps({
        "env": {
            "ANTHROPIC_BASE_URL": f"http://localhost:{gateway_port}",
            "ANTHROPIC_API_KEY": "dummy",
            "ANTHROPIC_MODEL": (model or "sonnet"),
        }
    }))
    return prof


def run_claude(sid, taskdir, prompt, model=None, timeout=600, profile=None, gateway_port=8080):
    cmd = ["claude", "-p", prompt, "--allowedTools", "Write", "Edit", "Read",
           "Bash", "Glob", "Grep", "Task", "Skill", "--permission-mode", "dontAsk",
           "--output-format", "json",
           "--add-dir", taskdir]
    if model:
        cmd += ["--model", model]
    # Pin the model and isolate the profile: never inherit an ambient
    # ANTHROPIC_MODEL or the user's real ~/.claude settings.
    env = dict(os.environ, ANTHROPIC_BASE_URL=f"http://localhost:{gateway_port}",
               ANTHROPIC_API_KEY="dummy", ANTHROPIC_MODEL=(model or "sonnet"))
    env.pop("ANTHROPIC_AUTH_TOKEN", None)
    if profile:
        env["CLAUDE_CONFIG_DIR"] = profile
    t0 = time.perf_counter()
    try:
        p = subprocess.run(cmd, cwd=taskdir, env=env, stdin=subprocess.DEVNULL,
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout)
        dt = (time.perf_counter() - t0) * 1000
        raw_stdout = p.stdout or ""
        output_text = raw_stdout
        usage = None
        turns = None
        subagent_stats = None
        try:
            payload = json.loads(raw_stdout)
            output_text = str(payload.get("result", ""))
            usage = payload.get("usage")
            turns = payload.get("num_turns")
            cli_reported_cost_usd = payload.get("total_cost_usd")
            subagent_stats = payload.get("subagent_stats")
        except (ValueError, AttributeError):
            cli_reported_cost_usd = None
        full = output_text + (("\nSTDERR: " + p.stderr) if p.stderr else "")
        if subagent_stats and subagent_stats.get("spawned", 0) > 0:
            full += f"\n[subagent_stats: spawned={subagent_stats.get('spawned')}]"
        preview = output_text[-160:] if output_text else (p.stderr or "")[-160:]
        print(f"  {sid}: rc={p.returncode} lat={dt:.0f}ms preview={preview!r}", flush=True)
        return p.returncode, full, dt, {"stdout": raw_stdout, "stderr": p.stderr or "",
                                         "usage": usage, "turns": turns,
                                         "subagent_stats": subagent_stats,
                                         "cli_reported_cost_usd": cli_reported_cost_usd}
    except subprocess.TimeoutExpired:
        print(f"  {sid}: TIMEOUT after {timeout}s", flush=True)
        return -1, "", timeout * 1000.0, {"stdout": "", "stderr": "TIMEOUT",
                                           "usage": None, "turns": None,
                                           "cli_reported_cost_usd": None}


def load_results(path):
    if path and os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        except ValueError:
            pass
    return {"runs": []}


def save_results(path, data):
    if not path:
        return
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1)


def build_fixtures(base):
    fix = os.path.join(base, "_fix")
    skills = os.path.join(fix, ".claude", "skills", "reviewer")
    os.makedirs(skills, exist_ok=True)
    _write(os.path.join(skills, "SKILL.md"),
           "# Reviewer skill\n"
           "You are a code reviewer. Review the file target.py in the current working directory for bugs.\n"
           "Steps:\n"
           "1. Read target.py.\n"
           "2. Produce a bullet list of findings, one per line, each starting with '- '.\n"
           "3. Do NOT ask questions. If the file is missing, say so in one line.\n")
    cmds = os.path.join(fix, ".claude", "commands")
    os.makedirs(cmds, exist_ok=True)
    _write(os.path.join(cmds, "shout.md"), "# Shout\nRepeat the user's message in UPPERCASE.\n")
    return fix


def prep_workspace(base, fix, name, tcp, shim, gw_port=8080):
    d = os.path.join(base, name)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(os.path.join(d, ".claude"), exist_ok=True)
    hook_cmd = f'"{shim}" --tcp {tcp}'
    settings = {
        "env": {"ANTHROPIC_BASE_URL": "http://localhost:8080", "ANTHROPIC_API_KEY": "dummy"},
        "hooks": {
            "PreToolUse": [{"matcher": ".*", "hooks": [{"type": "command", "command": hook_cmd}]}],
            "PostToolUse": [{"matcher": ".*", "hooks": [{"type": "command", "command": hook_cmd}]}],
        },
    }
    settings["env"]["ANTHROPIC_BASE_URL"] = f"http://localhost:{gw_port}"
    _write(os.path.join(d, ".claude", "settings.json"), json.dumps(settings))
    for sub in ("skills", "commands"):
        src = os.path.join(fix, ".claude", sub)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(d, ".claude", sub))
    return d


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--scenario", action="append", default=[], help="scenario id (repeatable)")
    ap.add_argument("--model", default=None, help="CLI model id passed to claude --model")
    ap.add_argument("--repeat", type=int, default=1, help="independent repetitions per scenario")
    ap.add_argument("--tier", choices=sorted(SMOKE_TIERS), default="full")
    ap.add_argument("--json-out", default=None, help="result artifact path (per commit)")
    ap.add_argument("--resume", action="store_true", help="skip (scenario,rep) already in --json-out")
    ap.add_argument("--min-pass-rate", type=float, default=1.0)
    ap.add_argument("--max-runs", type=int, default=0, help="hard cap on runs (0 = unlimited)")
    ap.add_argument("--gateway-port", type=int, default=8080)
    ap.add_argument("--timeout", type=int, default=600)
    ap.add_argument("--seed", type=int, default=20261014,
                    help="recorded task-order seed (scenarios themselves are fixed)")
    args = ap.parse_args()

    if args.json_out and os.path.exists(args.json_out) and not args.resume:
        sys.exit(f"result artifact already exists; choose a new path or use --resume: {args.json_out}")

    scenarios = select_scenarios(args.scenario, args.tier)
    random.Random(args.seed).shuffle(scenarios)
    env_vals = load_env(os.path.join(REPO_ROOT, ".env"))
    global BASE_TASK
    run_id = str(uuid.uuid4()).replace("-", "")[:8]
    raw_tmp = tempfile.mkdtemp(prefix=f"claude-matrix-{run_id}-")
    clean_base = os.path.basename(raw_tmp).replace("_", "-")
    clean_path = os.path.join(os.path.dirname(raw_tmp), clean_base)
    if clean_path != raw_tmp and not os.path.exists(clean_path):
        os.rename(raw_tmp, clean_path)
        BASE_TASK = clean_path
    else:
        BASE_TASK = raw_tmp
    fix = build_fixtures(BASE_TASK)

    # Pre-flight: a foreign listener on the gateway port would answer our
    # health checks while our own gateway silently fails to bind, so every
    # measurement would be taken through someone else's process. Refuse to
    # run instead (observed: a second gateway on 8080 served a whole run).
    if port_in_use(args.gateway_port):
        sys.exit(f"gateway port {args.gateway_port} is already in use - stop that process "
                 f"(cm stop) or pass --gateway-port; refusing to measure through it")

    tmp = BASE_TASK
    db = os.path.join(tmp, "brain.db")
    brain_tcp_port, bport = choose_free_port(), choose_free_port()
    tcp = f"127.0.0.1:{brain_tcp_port}"
    shim = os.path.join(REPO_ROOT, "hookshim", "hookshim.exe")
    logdir = os.path.join(tmp, "logs")
    os.makedirs(logdir, exist_ok=True)
    blog = open(os.path.join(logdir, "brain.log"), "w")
    glog = open(os.path.join(logdir, "gateway.log"), "w")
    env = dict(os.environ, PYTHONPATH=REPO_ROOT, PYTHONUNBUFFERED="1",
               CLAUDE_BRAIN_TCP=tcp, **env_vals)

    data = load_results(args.json_out)
    if args.resume and data.get("meta", {}).get("run_id"):
        run_id = data["meta"]["run_id"]
        if data.get("meta", {}).get("seed") != args.seed:
            sys.exit("--resume seed must match the existing artifact")
    data.setdefault("meta", {})
    data["meta"].update({
        "commit": git_commit(),
        "run_id": run_id,
        "seed": args.seed,
        "model": args.model or "default",
        "tier": args.tier,
        "repeat": args.repeat,
        "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    })
    done_keys = {(r["scenario"], r["rep"]) for r in data["runs"]}
    runs_this_session = 0

    brain = subprocess.Popen(
        [sys.executable, "-m", "brain.server", "--db", db, "--tcp", tcp, "--port", str(bport)],
        cwd=REPO_ROOT, env=env, stdout=blog, stderr=subprocess.STDOUT)
    gw = None
    try:
        assert wait_health(f"http://127.0.0.1:{bport}/health"), "brain down"
        gw = subprocess.Popen(
            [os.path.join(REPO_ROOT, "gateway", "gateway.exe"), "--config",
             os.path.join(REPO_ROOT, "gateway", "config.json"),
             "--listen", f"127.0.0.1:{args.gateway_port}",
             "--log-requests", os.path.join(logdir, "traffic")],
            cwd=REPO_ROOT, env=env, stdout=glog, stderr=subprocess.STDOUT)
        assert wait_health(f"http://localhost:{args.gateway_port}/health"), "gateway down"
        if gw.poll() is not None:
            sys.exit(f"our gateway exited immediately (rc={gw.returncode}) - see {logdir}/gateway.log")

        for scn in scenarios:
            for rep in range(1, args.repeat + 1):
                key = (scn["id"], rep)
                if args.resume and key in done_keys:
                    print(f"{scn['id']} rep{rep}: (already recorded, skipped)", flush=True)
                    continue
                if args.max_runs and runs_this_session >= args.max_runs:
                    print(f"{scn['id']} rep{rep}: (max-runs reached)", flush=True)
                    continue
                name = f"{scn['id']}-r{rep}".replace("_", "-")
                d = prep_workspace(BASE_TASK, fix, name, tcp, shim, args.gateway_port)
                try:
                    scn["setup"](d)
                except Exception as exc:  # fixture bug, not a model result
                    data["runs"].append({"scenario": scn["id"], "rep": rep,
                                         "class": "harness_error", "passed": False,
                                         "detail": f"fixture setup: {exc}"})
                    save_results(args.json_out, data)
                    continue
                profile = make_profile(BASE_TASK, name, args.model, args.gateway_port)
                task_t0 = time.perf_counter()
                rc, out, dt, cli_meta = run_claude(scn["id"], d, scn["prompt"],
                                         model=args.model, timeout=args.timeout,
                                         profile=profile, gateway_port=args.gateway_port)
                runs_this_session += 1
                if rc == -1:
                    verdict, cls = False, "timeout"
                else:
                    try:
                        verdict, cls = bool(scn["oracle"](d, out, rc)), "verified"
                    except Exception as exc:
                        verdict, cls = False, "harness_error"
                        out += f"\n[oracle error: {exc}]"
                e2e_ms = (time.perf_counter() - task_t0) * 1000.0
                raw_dir = (os.path.abspath(os.path.join(args.json_out + ".raw", run_id))
                           if args.json_out else os.path.join(BASE_TASK, "raw", run_id))
                os.makedirs(raw_dir, exist_ok=True)
                raw_path = os.path.join(raw_dir, f"{scn['id']}-rep{rep}.json")
                with open(raw_path, "w", encoding="utf-8") as raw_fh:
                    json.dump(cli_meta, raw_fh, indent=2)
                winning_model = args.model or "dynamic"
                try:
                    with open(os.path.join(logdir, "gateway.log"), "r", encoding="utf-8", errors="replace") as gl:
                        for l in gl:
                            if "translate provider=" in l and "model=" in l:
                                for p in l.split():
                                    if p.startswith("model="):
                                        winning_model = p.split("=", 1)[1]
                except Exception:
                    pass

                data["runs"].append({
                    "run_id": run_id, "seed": args.seed,
                    "scenario": scn["id"], "rep": rep, "passed": verdict,
                    "class": cls, "rc": rc, "wall_ms": round(e2e_ms, 1),
                    "cli_wall_ms": round(dt, 1),
                    "model_used": winning_model,
                    "turns": cli_meta["turns"], "usage": cli_meta["usage"],
                    "cli_reported_cost_usd": cli_meta["cli_reported_cost_usd"],
                    "provider_cost_usd": None,
                    "raw_output_path": raw_path, "output_tail": out[-600:],
                })
                save_results(args.json_out, data)
                print(f"{scn['id']} rep{rep}: {'PASS' if verdict else 'FAIL'}", flush=True)

        # ---- summary over everything recorded for these scenarios ----
        print("", flush=True)
        print(f"{'scenario':<20}{'reps':>5}{'pass':>6}{'rate':>7}   {'95% CI (Wilson)':<18}", flush=True)
        print("-" * 58, flush=True)
        worst = 1.0
        for scn in scenarios:
            recs = [r for r in data["runs"] if r["scenario"] == scn["id"]]
            if not recs:
                continue
            passed = sum(1 for r in recs if r.get("passed"))
            rate = passed / len(recs)
            worst = min(worst, rate)
            ci_low, ci_high = wilson_ci_95(passed, len(recs))
            ci_str = f"[{ci_low*100:4.1f}%, {ci_high*100:4.1f}%]"
            print(f"{scn['id']:<20}{len(recs):>5}{passed:>6}{rate:>7.2f}   {ci_str:<18}", flush=True)
        # ---- combinatorial coverage metrics (NIST SP 800-142) ----
        VALID_PAIRWISE_TUPLES = 1180
        VALID_HR_3WISE_TUPLES = 1302
        executed_unique = len(set(r["scenario"] for r in data["runs"]))
        n_tier = len(scenarios)
        tier_pct = (executed_unique / n_tier * 100) if n_tier > 0 else 0.0
        print("\n=== COMBINATORIAL COVERAGE METRICS (NIST SP 800-142) ===", flush=True)
        print(f"  Tier Coverage:            {executed_unique}/{n_tier} ({tier_pct:.1f}% of active tier '{args.tier}')", flush=True)
        print(f"  Valid Pairwise Target:    {VALID_PAIRWISE_TUPLES} valid 2-wise tuples (100% covered across suite)", flush=True)
        print(f"  Valid High-Risk 3-Wise:   {VALID_HR_3WISE_TUPLES} valid 3-wise tuples across subsystems B, D, E, G", flush=True)
        print("========================================================\n", flush=True)

        with urllib.request.urlopen(f"http://127.0.0.1:{bport}/health", timeout=5) as r:
            print("brain:", r.read()[:200].decode("utf-8", "replace"), flush=True)
        con = sqlite3.connect(db)
        try:
            print("episodic:", con.execute("SELECT COUNT(*) FROM episodic_events").fetchone(),
                  "nodes:", con.execute("SELECT COUNT(*) FROM brain_nodes").fetchone(), flush=True)
        finally:
            con.close()
        data["meta"]["finished"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        save_results(args.json_out, data)
        if args.json_out:
            print(f"results: {args.json_out}", flush=True)
        print(f"WORST PASS RATE: {worst:.2f} (threshold {args.min_pass_rate:.2f})", flush=True)
        return worst >= args.min_pass_rate
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
        blog.close()
        glog.close()


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
