"""
tests/parity/test_cli_parity.py — automated CLI-to-UI parity test suite.

Discovers all API endpoints from the backend OpenAPI schema and route table,
invokes each `cm` CLI command, asserts that it maps 1:1 to the corresponding
API endpoint, and produces the exact same state changes as direct API calls.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest
import uvicorn
import yaml

from brain.api.app import create_app
from brain.api.security import get_or_create_auth_token
from brain.server import BrainServer

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CLI_PATH = REPO_ROOT / "cli" / "cm.py"


@pytest.fixture(scope="module")
def api_server(tmp_path_factory):
    """Start an authenticated BrainServer daemon on an ephemeral port."""
    tmp_dir = tmp_path_factory.mktemp("parity_test")
    db_path = str(tmp_dir / "parity_brain.db")
    server = BrainServer(db_path=db_path, http_host="127.0.0.1", http_port=0)

    # Find free port
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    server.http_port = port
    base_url = f"http://127.0.0.1:{port}"

    app = create_app(server)
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    uv_server = uvicorn.Server(config)
    th = threading.Thread(target=uv_server.run, daemon=True)
    th.start()

    # Wait for server to come up
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        if uv_server.started:
            break
        time.sleep(0.05)

    token = get_or_create_auth_token()

    yield {
        "server": server,
        "base_url": base_url,
        "token": token,
        "port": port,
        "uv_server": uv_server,
    }

    try:
        uv_server.should_exit = True
        server.store.close()
    except Exception:
        pass


def make_api_call(
    base_url: str,
    token: str | None,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    timeout: float = 5.0,
) -> tuple[int, Any]:
    """Simulate a UI client call directly to the backend API."""
    url = f"{base_url}{path}"
    req = urllib.request.Request(url, method=method.upper())
    if token:
        req.add_header("Authorization", f"Bearer {token}")
        req.add_header("X-CM-Token", token)
    req.add_header("Content-Type", "application/json")

    data_bytes = json.dumps(body).encode("utf-8") if body is not None else None
    try:
        with urllib.request.urlopen(req, data=data_bytes, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            try:
                return resp.status, json.loads(raw)
            except json.JSONDecodeError:
                return resp.status, raw
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            return exc.code, json.loads(raw)
        except Exception:
            return exc.code, {"error": exc.reason}


def run_cli(api_server: dict, *args: str) -> subprocess.CompletedProcess:
    """Run cm CLI command against the test api_server."""
    env = dict(os.environ)
    env["BRAIN_API_URL"] = api_server["base_url"]
    env["CM_TOKEN"] = api_server["token"]
    cmd = [sys.executable, str(CLI_PATH)] + list(args)
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=env,
        cwd=str(REPO_ROOT),
    )


# =============================================================================
# 1. OPENAPI SCHEMA DISCOVERY & ENDPOINT COVERAGE TESTS
# =============================================================================

class TestOpenAPIDiscovery:
    def test_openapi_schema_endpoint(self, api_server):
        """Verify GET /openapi.json returns valid OpenAPI 3.0 schema."""
        code, data = make_api_call(api_server["base_url"], None, "GET", "/openapi.json")
        assert code == 200
        assert data.get("openapi") == "3.0.3" or data.get("openapi", "").startswith("3.")
        assert "paths" in data
        assert len(data["paths"]) >= 20

    def test_openapi_yaml_sync(self):
        """Verify contracts/brain.openapi.yaml exists and is valid YAML."""
        yaml_path = REPO_ROOT / "contracts" / "brain.openapi.yaml"
        assert yaml_path.is_file()
        content = yaml_path.read_text(encoding="utf-8")
        parsed = yaml.safe_load(content)
        assert "openapi" in parsed
        assert len(parsed.get("paths", {})) >= 20

    def test_all_routes_discovered(self, api_server):
        """Assert that backend OpenAPI schema discovers endpoints for all CLI commands."""
        code, data = make_api_call(api_server["base_url"], None, "GET", "/openapi.json")
        assert code == 200
        paths = set(data.get("paths", {}).keys())

        expected_patterns = [
            "/api/v1/status",
            "/api/v1/bypass",
            "/api/v1/control/{action}",
            "/api/v1/doctor",
            "/api/v1/explain/{request_id}",
            "/api/v1/providers",
            "/api/v1/keys",
            "/api/v1/models",
            "/api/v1/routing",
            "/api/v1/drex",
            "/api/v1/privacy",
            "/api/v1/budgets",
            "/api/v1/brain/memory",
            "/api/v1/claude",
            "/api/v1/test-center/run",
            "/api/v1/backup",
            "/api/v1/update",
            "/api/v1/schema",
            "/api/v1/logs",
        ]
        for exp in expected_patterns:
            assert exp in paths, f"Expected endpoint {exp} missing from OpenAPI schema"


# =============================================================================
# 2. AUTHENTICATION PARITY TESTS
# =============================================================================

class TestAuthenticationParity:
    def test_unauthenticated_request_rejected(self, api_server):
        """Unauthenticated calls to /api/ endpoints must return 401 Unauthorized."""
        code, data = make_api_call(api_server["base_url"], None, "GET", "/api/v1/status")
        assert code == 401
        assert "error" in data or "detail" in data

    def test_invalid_token_rejected(self, api_server):
        """Calls with invalid token must return 401."""
        code, data = make_api_call(api_server["base_url"], "invalid-bogus-token", "GET", "/api/v1/status")
        assert code == 401

    def test_authenticated_request_succeeds(self, api_server):
        """Calls with correct token succeed."""
        code, data = make_api_call(api_server["base_url"], api_server["token"], "GET", "/api/v1/status")
        assert code == 200
        assert "brain" in data or "status" in data

    def test_cli_authenticates_automatically(self, api_server):
        """CLI automatically passes the local token and receives 200."""
        res = run_cli(api_server, "status", "--json")
        assert res.returncode == 0
        data = json.loads(res.stdout)
        assert "brain" in data


# =============================================================================
# 3. 1:1 ENDPOINT MAPPING & STATE PARITY TESTS
# =============================================================================

class TestCommandParity:
    """Test every CLI command against its direct UI API counterpart."""

    def test_status_parity(self, api_server):
        res_api = run_cli(api_server, "status", "--api")
        assert res_api.returncode == 0
        assert "/api/v1/status" in res_api.stdout

        code, api_data = make_api_call(api_server["base_url"], api_server["token"], "GET", "/api/v1/status")
        assert code == 200

        res_json = run_cli(api_server, "status", "--json")
        assert res_json.returncode == 0
        cli_data = json.loads(res_json.stdout)

        assert cli_data["brain"]["status"] == api_data["brain"]["status"]

    def test_bypass_parity(self, api_server):
        # 1. CLI turns bypass ON
        res_on = run_cli(api_server, "bypass", "on", "--json")
        assert res_on.returncode == 0
        cli_on_data = json.loads(res_on.stdout)
        assert cli_on_data["enabled"] is True

        # Assert direct API reflects bypass ON
        code, api_data = make_api_call(api_server["base_url"], api_server["token"], "GET", "/api/v1/bypass")
        assert code == 200
        assert api_data["enabled"] is True

        # 2. Direct API turns bypass OFF (simulating UI action)
        code_off, api_off = make_api_call(api_server["base_url"], api_server["token"], "POST", "/api/v1/bypass", {"enabled": False})
        assert code_off == 200
        assert api_off["enabled"] is False

        # CLI reads status and matches
        res_status = run_cli(api_server, "bypass", "status", "--json")
        assert res_status.returncode == 0
        assert json.loads(res_status.stdout)["enabled"] is False

    def test_lifecycle_parity(self, api_server):
        for action in ["start", "stop", "restart"]:
            res_api = run_cli(api_server, action, "--api")
            assert res_api.returncode == 0
            assert f"/api/v1/control/{action}" in res_api.stdout

            res_cli = run_cli(api_server, action, "--json")
            assert res_cli.returncode == 0
            cli_data = json.loads(res_cli.stdout)

            code, api_data = make_api_call(
                api_server["base_url"],
                api_server["token"],
                "POST",
                f"/api/v1/control/{action}",
                {"action": action, "component": "all"},
                timeout=15.0,
            )
            assert code == 200
            assert cli_data["ok"] == api_data["ok"]

    def test_doctor_parity(self, api_server):
        res_diag = run_cli(api_server, "doctor", "--json")
        assert res_diag.returncode == 0
        cli_diag = json.loads(res_diag.stdout)

        code, api_diag = make_api_call(api_server["base_url"], api_server["token"], "GET", "/api/v1/doctor")
        assert code == 200
        assert len(cli_diag["checks"]) == len(api_diag["checks"])

        res_fix = run_cli(api_server, "doctor", "--fix", "--json")
        assert res_fix.returncode == 0

    def test_explain_parity(self, api_server):
        req_id = "req-parity-test-42"
        now_ms = int(time.time() * 1000)
        api_server["server"].store.conn.execute(
            "INSERT OR REPLACE INTO request_log (request_id, model_id, provider, key_hash, http_status, outcome, latency_ms, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (req_id, "claude-3-7-sonnet", "anthropic", "hash123", 200, "success", 120.0, now_ms)
        )
        api_server["server"].store.conn.commit()

        res_api = run_cli(api_server, "explain", req_id, "--api")
        assert res_api.returncode == 0
        assert f"/api/v1/explain/{req_id}" in res_api.stdout

        res_cli = run_cli(api_server, "explain", req_id, "--json")
        assert res_cli.returncode == 0
        cli_data = json.loads(res_cli.stdout)
        assert cli_data.get("request_id") == req_id

    def test_provider_parity(self, api_server):
        # List
        res_list = run_cli(api_server, "provider", "list", "--json")
        assert res_list.returncode == 0

        # Add
        prov_name = "test-provider-parity"
        res_add = run_cli(api_server, "provider", "add", prov_name, "--url", "https://api.test.com/v1", "--json")
        assert res_add.returncode == 0

        # Verify through direct API that state has the new provider
        code, api_list = make_api_call(api_server["base_url"], api_server["token"], "GET", "/api/v1/providers")
        assert code == 200
        found = any((p.get("name") == prov_name or p.get("Name") == prov_name) for p in api_list)
        assert found, f"Provider {prov_name} was not persisted"

        # Test
        res_test = run_cli(api_server, "provider", "test", prov_name, "--json")
        assert res_test.returncode == 0

        # Remove
        res_rem = run_cli(api_server, "provider", "remove", prov_name, "--json")
        assert res_rem.returncode == 0

    def test_key_parity(self, api_server):
        res_add = run_cli(api_server, "key", "add", "anthropic", "sk-parity-key-12345", "--env", "ANTHROPIC_KEY_TEST", "--json")
        assert res_add.returncode == 0

        code, api_keys = make_api_call(api_server["base_url"], api_server["token"], "GET", "/api/v1/keys")
        assert code == 200

        res_rot = run_cli(api_server, "key", "rotate", "anthropic", "sk-parity-key-67890", "--env", "ANTHROPIC_KEY_TEST", "--json")
        assert res_rot.returncode == 0

        res_test = run_cli(api_server, "key", "test", "anthropic", "--json")
        assert res_test.returncode == 0

        res_rem = run_cli(api_server, "key", "remove", "ANTHROPIC_KEY_TEST", "--json")
        assert res_rem.returncode == 0

    def test_model_parity(self, api_server):
        # Pin model
        res_pin = run_cli(api_server, "model", "pin", "claude-3-7-sonnet", "--json")
        assert res_pin.returncode == 0

        # Ban model
        res_ban = run_cli(api_server, "model", "ban", "claude-3-5-haiku", "--json")
        assert res_ban.returncode == 0

        # Override model
        res_ovr = run_cli(api_server, "model", "override", "--alias", "fast", "--target", "gemini-2.0-flash", "--json")
        assert res_ovr.returncode == 0

        # Compare models
        res_cmp = run_cli(api_server, "model", "compare", "--json")
        assert res_cmp.returncode == 0

    def test_route_parity(self, api_server):
        res_get = run_cli(api_server, "route", "get", "--json")
        assert res_get.returncode == 0

        res_set = run_cli(api_server, "route", "set", "latency", "--json")
        assert res_set.returncode == 0

        res_sim = run_cli(api_server, "route", "simulate", "--model", "claude-3-7-sonnet", "--json")
        assert res_sim.returncode == 0

    def test_drex_parity(self, api_server):
        res_st = run_cli(api_server, "drex", "status", "--json")
        assert res_st.returncode == 0

        res_cfg = run_cli(api_server, "drex", "config", "--timeout", "1.5", "--guard-drex", "off", "--json")
        assert res_cfg.returncode == 0

    def test_privacy_parity(self, api_server):
        res_rules = run_cli(api_server, "privacy", "rules", "--json")
        assert res_rules.returncode == 0

        sample = "Secret key sk-abcdefghijklmnopqrstuvwxyz should be redacted"
        res_red = run_cli(api_server, "privacy", "redact", sample, "--json")
        assert res_red.returncode == 0

    def test_budget_parity(self, api_server):
        res_sum = run_cli(api_server, "budget", "summary", "--json")
        assert res_sum.returncode == 0

        res_caps = run_cli(api_server, "budget", "caps", "--daily", "25.0", "--monthly", "250.0", "--json")
        assert res_caps.returncode == 0

    def test_brain_parity(self, api_server):
        for sub in ["lessons", "decay"]:
            res_sub = run_cli(api_server, "brain", sub, "--json")
            assert res_sub.returncode == 0

    def test_claude_parity(self, api_server):
        for sub in ["status", "apply", "undo", "verify"]:
            res_sub = run_cli(api_server, "claude", sub, "--json")
            assert res_sub.returncode == 0

    def test_test_parity(self, api_server):
        for sub in ["smoke", "run", "status"]:
            res_sub = run_cli(api_server, "test", sub, "--json")
            assert res_sub.returncode == 0

    def test_backup_parity(self, api_server):
        # Create
        res_cr = run_cli(api_server, "backup", "create", "parity-snap", "--json")
        assert res_cr.returncode == 0

        # List
        res_ls = run_cli(api_server, "backup", "list", "--json")
        assert res_ls.returncode == 0
        backups = json.loads(res_ls.stdout)
        assert len(backups) >= 1

        # Restore
        backup_id = backups[0]["backup_id"]
        res_rst = run_cli(api_server, "backup", "restore", backup_id, "--json")
        assert res_rst.returncode == 0

    def test_update_parity(self, api_server):
        for sub in ["check", "apply"]:
            res_sub = run_cli(api_server, "update", sub, "--json")
            assert res_sub.returncode == 0

    def test_config_parity(self, api_server):
        res_exp = run_cli(api_server, "config", "export", "--json")
        assert res_exp.returncode == 0

    def test_logs_parity(self, api_server):
        res_logs = run_cli(api_server, "logs", "--json")
        assert res_logs.returncode == 0


# =============================================================================
# 4. CURL & API FLAG VERIFICATION
# =============================================================================

class TestTraceFlags:
    @pytest.mark.parametrize("cmd_args", [
        ("status",),
        ("bypass", "status"),
        ("start",),
        ("stop",),
        ("restart",),
        ("doctor",),
        ("explain", "req-test"),
        ("provider", "list"),
        ("key", "list"),
        ("model", "list"),
        ("route", "get"),
        ("drex", "status"),
        ("privacy", "rules"),
        ("budget", "summary"),
        ("brain", "lessons"),
        ("claude", "status"),
        ("test", "smoke"),
        ("backup", "list"),
        ("update", "check"),
        ("config", "export"),
        ("logs",),
    ])
    def test_curl_and_api_flags(self, api_server, cmd_args):
        # 1. Test --curl flag
        res_curl = run_cli(api_server, *cmd_args, "--curl")
        assert res_curl.returncode == 0
        assert "curl -s -X" in res_curl.stdout
        assert "Authorization: Bearer" in res_curl.stdout

        # 2. Test --api flag
        res_api = run_cli(api_server, *cmd_args, "--api")
        assert res_api.returncode == 0
        assert ("GET " in res_api.stdout or "POST " in res_api.stdout or "PUT " in res_api.stdout)
        assert "/api/v1/" in res_api.stdout
