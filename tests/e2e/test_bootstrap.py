"""
tests/e2e/test_bootstrap.py
End-to-end bootstrap test for claude-master.

Exercises the full hook path against a real brain daemon subprocess:

    1. POST /hook    PreToolUse payload -> {"allow": true}
    2. POST /outcome model outcome      -> 200
    3. GET  /health                    -> {"status": "ok"}
    4. Stuck/loop detection: a repeated command in one session is blocked
    5. Gateway config validation (gateway/config.toml) + Go module build

The gateway package (gateway/) has no `main` entrypoint, so `go run .` is not
possible; the gateway is instead validated in-process against the same config
file the Go side reads.

Run from the repo root:
    python -m pytest tests/e2e/test_bootstrap.py -v

Note on stuck detection
-----------------------
`handle_hook` maps hook_event_name to window event types: PreToolUse becomes
"action", anything else becomes "observation". The StuckDetector's
repeating_action_observation rule needs >= 4 identical action/observation
pairs and pingpong needs >= 6 alternating events -- so a run of *bare*
PreToolUse hooks with no observations never trips the detector. A real tool
loop emits Pre->Post->Pre->Post, so these tests interleave PostToolUse
observations between the repeated PreToolUse calls, which is exactly what the
hook stream looks like for an agent stuck retrying the same command.
"""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from shutil import which

import pytest

# ---------------------------------------------------------------------------
# Paths / constants
# ---------------------------------------------------------------------------

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GATEWAY_CONFIG = os.path.join(REPO_ROOT, "gateway", "config.toml")

PREFERRED_PORT = 7798
SOCKET_PATH = "/tmp/e2e_brain.sock"
DB_PATH = "/tmp/e2e_brain.db"
DAEMON_LOG = "/tmp/e2e_brain.log"

HTTP_TIMEOUT_S = 10.0
BOOT_TIMEOUT_S = 30.0
SHUTDOWN_GRACE_S = 3.0

# A command that is clearly not risky, so the Drex gate does not interfere.
SAFE_COMMAND = "pytest tests/brain -q"

# /outcome and record_outcome are fully supported: GraphStore exposes
# get_edge_weight / set_edge_weight (duck-typed interface for HebbianUpdater).
OUTCOME_ENDPOINT_OK = True


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------


def _port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def _free_port() -> int:
    """Return an ephemeral port that is currently bindable."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _pick_port() -> int:
    """Prefer the documented port, fall back to an ephemeral one if taken."""
    if _port_is_free(PREFERRED_PORT):
        return PREFERRED_PORT
    return _free_port()


def _http(method: str, url: str, payload: dict | None = None) -> tuple[int, dict]:
    """Issue an HTTP request and return (status_code, decoded_json_body)."""
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"} if data is not None else {}
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:
            body = resp.read().decode("utf-8")
            return resp.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        try:
            return exc.code, json.loads(body) if body else {}
        except json.JSONDecodeError:
            return exc.code, {"raw": body}


def _hook(base_url: str, event: str, session_id: str, command: str = SAFE_COMMAND) -> dict:
    """POST a Claude Code hook payload to the brain and return the decision."""
    payload = {
        "hook_event_name": event,
        "tool_name": "Bash",
        "session_id": session_id,
        "input": {"command": command},
    }
    status, body = _http("POST", f"{base_url}/hook", payload)
    assert status == 200, f"/hook returned {status}: {body}"
    return body


def _terminate(proc: subprocess.Popen) -> None:
    """Stop a subprocess, escalating to SIGKILL.

    brain/server.py installs a SIGTERM handler that calls httpd.shutdown()
    from the same thread that is inside serve_forever(), which deadlocks
    (shutdown() waits for the serve loop that the handler is blocking). So a
    SIGTERM grace period is attempted but SIGKILL is the reliable stop.
    """
    if proc.poll() is not None:
        return
    try:
        proc.send_signal(signal.SIGTERM)
    except (ProcessLookupError, OSError):
        pass
    deadline = time.monotonic() + SHUTDOWN_GRACE_S
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return
        time.sleep(0.1)
    try:
        proc.kill()
        proc.wait(timeout=SHUTDOWN_GRACE_S)
    except (ProcessLookupError, OSError, subprocess.TimeoutExpired):
        pass


def _remove_if_exists(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def daemon():
    """Start the brain daemon subprocess for the duration of the session.

    Yields the base URL of the running daemon. Always tears the subprocess
    down and removes temp artifacts, even if startup or a test fails.
    """
    port = _pick_port()
    base_url = f"http://127.0.0.1:{port}"

    _remove_if_exists(DB_PATH)
    _remove_if_exists(SOCKET_PATH)
    _remove_if_exists(DAEMON_LOG)

    cmd = [
        sys.executable, "-m", "brain.server",
        "--db", DB_PATH,
        "--socket", SOCKET_PATH,
        "--port", str(port),
    ]
    env = dict(os.environ, PYTHONPATH=REPO_ROOT, PYTHONUNBUFFERED="1")

    log_handle = open(DAEMON_LOG, "w", encoding="utf-8")
    proc = subprocess.Popen(
        cmd,
        cwd=REPO_ROOT,
        env=env,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )

    try:
        deadline = time.monotonic() + BOOT_TIMEOUT_S
        ready = False
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                raise RuntimeError(
                    f"brain daemon exited early with code {proc.returncode}\n"
                    f"--- log ---\n{_read_log()}"
                )
            try:
                status, body = _http("GET", f"{base_url}/health")
                if status == 200 and body.get("status") == "ok":
                    ready = True
                    break
            except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
                last_error = exc
            time.sleep(0.2)

        if not ready:
            raise RuntimeError(
                f"brain daemon not healthy within {BOOT_TIMEOUT_S}s "
                f"(last error: {last_error!r})\n--- log ---\n{_read_log()}"
            )

        yield base_url
    finally:
        _terminate(proc)
        log_handle.close()
        _remove_if_exists(DB_PATH)
        _remove_if_exists(SOCKET_PATH)
        _remove_if_exists(DAEMON_LOG)


def _read_log() -> str:
    try:
        with open(DAEMON_LOG, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return "<no daemon log>"


@pytest.fixture
def in_process_server(tmp_path):
    """A BrainServer used directly, bypassing HTTP/subprocess entirely.

    This exercises the identical handle_hook() code path the daemon serves,
    so it stays a valid end-to-end demonstration of hook handling even when a
    subprocess cannot be started.
    """
    sys.path.insert(0, REPO_ROOT)
    from brain.server import BrainServer

    server = BrainServer(str(tmp_path / "brain.db"), None, "127.0.0.1", 0)
    try:
        yield server
    finally:
        try:
            server.store.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# 1-3. Core daemon endpoints
# ---------------------------------------------------------------------------


class TestDaemonEndpoints:
    def test_health_reports_ok(self, daemon):
        """GET /health returns {"status": "ok"}."""
        status, body = _http("GET", f"{daemon}/health")
        assert status == 200
        assert body["status"] == "ok"

    def test_hook_allows_safe_command(self, daemon):
        """POST /hook with a PreToolUse payload allows the tool call."""
        result = _hook(daemon, "PreToolUse", "e2e-session-allow")
        assert result["allow"] is True, f"expected allow=True, got {result}"
        assert result["block_reason"] == ""

    def test_hook_returns_context_key(self, daemon):
        """An allowed hook response carries the brain context field."""
        result = _hook(daemon, "PreToolUse", "e2e-session-ctx")
        assert "additional_context" in result

    @pytest.mark.skipif(not OUTCOME_ENDPOINT_OK, reason="outcome endpoint not wired")
    def test_outcome_endpoint_accepts_model_outcome(self, daemon):
        """POST /outcome records a model outcome and returns 200."""
        payload = {
            "model_id": "groq/llama-3.3-70b-versatile",
            "success": True,
            "latency_ms": 812.5,
        }
        status, body = _http("POST", f"{daemon}/outcome", payload)
        assert status == 200, f"expected 200, got {status}: {body}"
        assert body.get("ok") is True

    @pytest.mark.skipif(not OUTCOME_ENDPOINT_OK, reason="outcome endpoint not wired")
    def test_outcome_failure_path(self, daemon):
        """A failed outcome is accepted just as a successful one."""
        status, body = _http("POST", f"{daemon}/outcome", {
            "model_id": "cerebras/llama3.1-70b",
            "success": False,
            "latency_ms": 12000.0,
        })
        assert status == 200
        assert body.get("ok") is True

    def test_unknown_route_returns_404(self, daemon):
        """Unrouted paths 404 rather than crashing the daemon."""
        status, _ = _http("GET", f"{daemon}/does-not-exist")
        assert status == 404


# ---------------------------------------------------------------------------
# 4. Stuck / loop detection
# ---------------------------------------------------------------------------


class TestStuckDetection:
    def test_fifth_repeated_hook_is_blocked(self, daemon):
        """Repeating one command in one session trips the loop detector.

        A real stuck agent emits Pre->Post->Pre->Post for the same command.
        The 5th PreToolUse must be denied with a "loop detected" reason.
        """
        session = "e2e-session-loop"
        results = []

        for attempt in range(1, 6):
            results.append(_hook(daemon, "PreToolUse", session))
            if attempt < 5:
                # The tool ran and reported back -- same output every time.
                _hook(daemon, "PostToolUse", session)

        first = results[0]
        last = results[-1]

        assert first["allow"] is True, f"first call should be allowed, got {first}"
        assert last["allow"] is False, f"5th repeated call should be blocked, got {last}"
        assert "loop detected" in last["block_reason"]
        assert last["additional_context"], "blocked hook should carry a corrective nudge"

    def test_distinct_sessions_do_not_share_windows(self, daemon):
        """Stuck windows are per-session, so a fresh session starts clean."""
        # Saturate one session into the stuck state.
        stuck_session = "e2e-session-saturated"
        for attempt in range(1, 5):
            _hook(daemon, "PreToolUse", stuck_session)
            if attempt < 4:
                _hook(daemon, "PostToolUse", stuck_session)

        # A different session running the same command must still be allowed.
        fresh = _hook(daemon, "PreToolUse", "e2e-session-fresh")
        assert fresh["allow"] is True

    def test_varied_commands_are_not_flagged(self, daemon):
        """Distinct commands in one session do not trip loop detection."""
        session = "e2e-session-varied"
        for i in range(5):
            result = _hook(daemon, "PreToolUse", session, command=f"ls /tmp/dir{i}")
            assert result["allow"] is True, f"varied command {i} blocked: {result}"


# ---------------------------------------------------------------------------
# 4b. Same hook path, in-process (no subprocess)
# ---------------------------------------------------------------------------


class TestHandleHookInProcess:
    def test_single_hook_allowed(self, in_process_server):
        result = in_process_server.handle_hook({
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "session_id": "inproc",
            "input": {"command": SAFE_COMMAND},
        })
        assert result["allow"] is True

    def test_fifth_repeated_hook_blocked(self, in_process_server):
        """handle_hook() directly: 5th repeated PreToolUse is blocked."""
        payload = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "session_id": "inproc-loop",
            "input": {"command": SAFE_COMMAND},
        }
        post = dict(payload, hook_event_name="PostToolUse")

        results = []
        for attempt in range(1, 6):
            results.append(in_process_server.handle_hook(dict(payload)))
            if attempt < 5:
                in_process_server.handle_hook(dict(post))

        assert results[0]["allow"] is True
        assert results[-1]["allow"] is False
        assert "loop detected" in results[-1]["block_reason"]

    @pytest.mark.skipif(not OUTCOME_ENDPOINT_OK, reason="outcome endpoint not wired")
    def test_record_outcome(self, in_process_server):
        in_process_server.record_outcome("groq/llama-3.3-70b-versatile", True, 500.0)
        in_process_server.record_outcome("gemini/gemini-2.0-flash-exp", False, 9000.0)


# ---------------------------------------------------------------------------
# 5. Gateway config + module
# ---------------------------------------------------------------------------


class TestGatewayConfig:
    def test_config_file_exists(self):
        assert os.path.isfile(GATEWAY_CONFIG), f"missing {GATEWAY_CONFIG}"

    def test_config_matches_contract(self):
        """gateway/config.toml carries the documented server/provider/routing values."""
        tomllib = pytest.importorskip("tomllib")
        with open(GATEWAY_CONFIG, "rb") as fh:
            cfg = tomllib.load(fh)

        assert cfg["server"]["listen_addr"] == ":8080"
        assert cfg["server"]["brain_socket"] == "/tmp/claude_brain.sock"

        expected = {
            "groq": (
                "https://api.groq.com/openai/v1",
                "zero_retention",
                ["llama-3.3-70b-versatile"],
                "GROQ_API_KEY",
                10,
            ),
            "cerebras": (
                "https://api.cerebras.ai/v1",
                "zero_retention",
                ["llama3.1-70b"],
                "CEREASRAS_API_KEY",
                20,
            ),
            "gemini": (
                "https://generativelanguage.googleapis.com/v1beta/openai",
                "public_data_only",
                ["gemini-2.0-flash-exp"],
                "GEMINI_API_KEY",
                100,
            ),
        }
        providers = cfg["providers"]
        assert set(providers) == set(expected)

        for name, (base_url, policy, models, env_var, priority) in expected.items():
            prov = providers[name]
            assert prov["base_url"] == base_url
            assert prov["privacy_policy"] == policy
            assert prov["models"] == models
            assert len(prov["key_pools"]) == 1
            pool = prov["key_pools"][0]
            assert pool["env_var"] == env_var
            assert pool["account_label"] == "personal"
            assert pool["priority"] == priority

        routing = cfg["routing"]
        assert routing["strategy"] == "thompson_sampling"
        assert routing["cooldown_base_s"] == 60
        assert routing["cooldown_max_s"] == 3600
        assert routing["github_models_fallback"] is True

    def test_gateway_module_builds(self):
        """The gateway Go module compiles (there is no main package to run)."""
        go = which("go")
        if go is None:
            pytest.skip("go toolchain not installed")
        proc = subprocess.run(
            [go, "build", "./..."],
            cwd=os.path.join(REPO_ROOT, "gateway"),
            capture_output=True,
            text=True,
            timeout=180,
        )
        assert proc.returncode == 0, f"go build failed:\n{proc.stderr}"
