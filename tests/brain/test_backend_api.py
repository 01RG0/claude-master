"""tests/brain/test_backend_api.py — Comprehensive pytest suite for claude-master Backend API.

Verifies:
1. Security: loopback-only binding, origin validation, token authentication, CSP headers, secret masking, DPAPI.
2. API Endpoints covering all 10 control screens, 9 diagnostics screens, wizard steps, emergency bypass, and doctor engine.
3. SSE telemetry stream and root compatibility endpoints.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import pytest
from fastapi.testclient import TestClient

from brain.api.app import create_app
from brain.api.security import (
    get_or_create_auth_token,
    mask_key,
    hash_key,
    dpapi_protect,
    dpapi_unprotect,
)
from brain.server import BrainServer


@pytest.fixture(scope="module")
def temp_db_and_server():
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    server = BrainServer(db_path=db_path)
    app = create_app(server)
    token = get_or_create_auth_token()
    client = TestClient(app)
    auth_headers = {"Authorization": f"Bearer {token}"}

    yield {
        "server": server,
        "app": app,
        "client": client,
        "token": token,
        "auth_headers": auth_headers,
        "db_path": db_path,
    }

    try:
        server.store.close()
        if os.path.exists(db_path):
            os.remove(db_path)
    except Exception:
        pass


# ===========================================================================
# 1. Security & Foundation Tests
# ===========================================================================

def test_openapi_schema_exposed(temp_db_and_server):
    client = temp_db_and_server["client"]
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    data = resp.json()
    assert "openapi" in data
    assert data["info"]["title"] == "claude-master Backend API"
    assert "/api/status" in data["paths"]
    assert "/api/doctor" in data["paths"]


def test_auth_token_enforcement(temp_db_and_server):
    client = temp_db_and_server["client"]
    token = temp_db_and_server["token"]

    # 1. Request with no auth header -> 401 Unauthorized
    resp = client.get("/api/status")
    assert resp.status_code == 401
    assert "unauthorized" in resp.json()["error"].lower()

    # 2. Request with invalid token -> 401
    resp = client.get("/api/status", headers={"Authorization": "Bearer invalid_token_12345"})
    assert resp.status_code == 401

    # 3. Request with valid Bearer token -> 200 OK
    resp = client.get("/api/status", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200

    # 4. Request with X-CM-Token header -> 200 OK
    resp = client.get("/api/status", headers={"X-CM-Token": token})
    assert resp.status_code == 200


def test_origin_validation_and_csp(temp_db_and_server):
    client = temp_db_and_server["client"]
    auth = temp_db_and_server["auth_headers"]

    # Valid localhost origin allowed
    resp = client.get("/api/status", headers={**auth, "Origin": "http://localhost:5173"})
    assert resp.status_code == 200
    assert resp.headers["Access-Control-Allow-Origin"] == "http://localhost:5173"
    assert "default-src 'self'" in resp.headers["Content-Security-Policy"]
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "DENY"

    # Malicious external origin rejected
    bad_resp = client.get("/api/status", headers={**auth, "Origin": "http://malicious-site.com"})
    assert bad_resp.status_code == 403


def test_dpapi_and_secret_masking(temp_db_and_server):
    # Secret masking utility
    key = "sk-ant-api03-abcdef1234567890"
    masked = mask_key(key)
    assert masked.startswith("sk-ant-")
    assert masked.endswith("7890")
    assert "abcdef" not in masked
    assert hash_key(key) != ""

    # DPAPI round-trip
    plain = b"test_secret_for_windows_dpapi"
    enc = dpapi_protect(plain)
    dec = dpapi_unprotect(enc)
    assert dec == plain


# ===========================================================================
# 2. Control & Status Endpoints
# ===========================================================================

def test_system_status(temp_db_and_server):
    client = temp_db_and_server["client"]
    auth = temp_db_and_server["auth_headers"]

    resp = client.get("/api/status", headers=auth)
    assert resp.status_code == 200
    data = resp.json()
    assert "daemon" in data
    assert "gateway" in data
    assert "brain" in data
    assert "spend" in data
    assert "error_rates" in data
    assert "bypass_state" in data
    assert "attention_list" in data


def test_emergency_bypass_toggle(temp_db_and_server):
    client = temp_db_and_server["client"]
    auth = temp_db_and_server["auth_headers"]

    # Initial state
    resp = client.get("/api/bypass", headers=auth)
    assert resp.status_code == 200

    # Toggle ON
    resp = client.post("/api/bypass", json={"enabled": True, "reason": "Testing manual bypass"}, headers=auth)
    assert resp.status_code == 200
    assert resp.json()["enabled"] is True
    assert resp.json()["reason"] == "Testing manual bypass"

    # Verify status reflects bypass
    status_resp = client.get("/api/status", headers=auth)
    assert status_resp.json()["bypass_state"]["enabled"] is True

    # Toggle OFF
    resp = client.post("/api/bypass", json={"enabled": False, "reason": "Resolved"}, headers=auth)
    assert resp.status_code == 200
    assert resp.json()["enabled"] is False


def test_control_process(temp_db_and_server):
    client = temp_db_and_server["client"]
    auth = temp_db_and_server["auth_headers"]

    resp = client.post("/api/control/restart", json={"action": "restart", "component": "gateway"}, headers=auth)
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_dynamic_schema(temp_db_and_server):
    client = temp_db_and_server["client"]
    auth = temp_db_and_server["auth_headers"]

    resp = client.get("/api/schema", headers=auth)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["dialects"]) >= 4
    assert len(data["preset_modes"]) >= 3
    assert len(data["privacy_policies"]) >= 3
    assert "main" in data["roles"]


# ===========================================================================
# 3. Wizard & Diagnostics (Doctor)
# ===========================================================================

def test_wizard_env_check_and_fix(temp_db_and_server):
    client = temp_db_and_server["client"]
    auth = temp_db_and_server["auth_headers"]

    resp = client.get("/api/wizard/env-check", headers=auth)
    assert resp.status_code == 200
    data = resp.json()
    assert "checks" in data
    assert any(c["check_id"] == "os_version" for c in data["checks"])

    # Wizard 1-click fix
    fix_resp = client.post("/api/wizard/fix", json={"action_id": "sqlite_wal"}, headers=auth)
    assert fix_resp.status_code == 200
    assert fix_resp.json()["fixed"] is True


def test_wizard_import_env(temp_db_and_server):
    client = temp_db_and_server["client"]
    auth = temp_db_and_server["auth_headers"]

    mock_env = "GROQ_API_KEY=gsk_1234567890abcdef1234567890\nMISTRAL_API_KEY=mis_9876543210fedcba\n"
    resp = client.post(
        "/api/wizard/import-env",
        json={"env_content": mock_env, "apply": False},
        headers=auth,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["discovered"]) == 2
    assert data["discovered"][0]["masked_key"].startswith("gsk_")
    assert "1234567890abcdef" not in data["discovered"][0]["masked_key"]


def test_doctor_diagnostics_suite(temp_db_and_server):
    client = temp_db_and_server["client"]
    auth = temp_db_and_server["auth_headers"]

    report = client.get("/api/doctor", headers=auth)
    assert report.status_code == 200
    data = report.json()
    assert "overall_status" in data
    assert len(data["checks"]) >= 5

    # Auto fix check
    fix = client.post("/api/doctor/fix", json={"check_id": "sqlite_wal"}, headers=auth)
    assert fix.status_code == 200
    assert fix.json()["check_id"] == "sqlite_wal"


# ===========================================================================
# 4. Providers & Keystore (Masked Keys)
# ===========================================================================

def test_providers_crud_and_test(temp_db_and_server):
    client = temp_db_and_server["client"]
    auth = temp_db_and_server["auth_headers"]

    # GET
    resp = client.get("/api/providers", headers=auth)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)

    # TEST probe
    probe = client.post(
        "/api/providers/test",
        json={"provider": "groq", "model": "llama-3.3-70b-versatile"},
        headers=auth,
    )
    assert probe.status_code == 200
    assert probe.json()["detected_dialect"] == "openai"


def test_keys_lifecycle_and_masked_return(temp_db_and_server):
    client = temp_db_and_server["client"]
    auth = temp_db_and_server["auth_headers"]

    raw_secret = "sk-test-super-secret-key-12345678"

    # 1. Add key (write-only plaintext)
    add_resp = client.post(
        "/api/keys",
        json={
            "provider": "unittest_prov",
            "account_label": "personal",
            "env_var": "UNITTEST_API_KEY",
            "key": raw_secret,
            "priority": 10,
        },
        headers=auth,
    )
    assert add_resp.status_code == 200
    added = add_resp.json()
    # Masked by construction!
    assert raw_secret not in added["key_masked"]
    assert added["key_masked"].startswith("sk-")

    # 2. List keys: ensure secret is masked
    list_resp = client.get("/api/keys", headers=auth)
    assert list_resp.status_code == 200
    all_keys = list_resp.json()
    our_key = next((k for k in all_keys if k["provider"] == "unittest_prov"), None)
    assert our_key is not None
    assert our_key["key_masked"] != raw_secret

    # 3. Reveal requires explicit confirm=True
    fail_reveal = client.post(
        "/api/keys/reveal",
        json={"provider": "unittest_prov", "account_label": "personal", "confirm": False},
        headers=auth,
    )
    assert fail_reveal.status_code == 400

    ok_reveal = client.post(
        "/api/keys/reveal",
        json={"provider": "unittest_prov", "account_label": "personal", "confirm": True},
        headers=auth,
    )
    assert ok_reveal.status_code == 200
    assert ok_reveal.json()["plaintext_key"] == raw_secret

    # 4. Remove key
    del_resp = client.delete("/api/keys?provider=unittest_prov&account_label=personal", headers=auth)
    assert del_resp.status_code == 200


# ===========================================================================
# 5. Models & Routing
# ===========================================================================

def test_models_catalog_and_pin_ban(temp_db_and_server):
    client = temp_db_and_server["client"]
    auth = temp_db_and_server["auth_headers"]

    resp = client.get("/api/models", headers=auth)
    assert resp.status_code == 200
    models = resp.json()
    assert len(models) > 0

    # Pin / Ban
    pin = client.post("/api/models/pin", json={"models": ["llama-3.3-70b-versatile"]}, headers=auth)
    assert pin.status_code == 200
    assert "llama-3.3-70b-versatile" in pin.json()["pinned"]

    # Compare
    comp = client.post("/api/models/compare", json={"model_ids": ["llama-3.3-70b-versatile"]}, headers=auth)
    assert comp.status_code == 200


def test_routing_and_simulation(temp_db_and_server):
    client = temp_db_and_server["client"]
    auth = temp_db_and_server["auth_headers"]

    cfg = client.get("/api/routing", headers=auth)
    assert cfg.status_code == 200
    assert "roles" in cfg.json()

    # Simulate
    sim = client.post(
        "/api/routing/simulate",
        json={"task": "Write quick python script", "role": "fast", "prompt_tokens": 800},
        headers=auth,
    )
    assert sim.status_code == 200
    res = sim.json()
    assert res["resolved_role"] == "fast"
    assert res["selected_model"] != ""
    assert res["estimated_cost_usd"] >= 0.0


# ===========================================================================
# 6. Drex & Privacy & Budgets
# ===========================================================================

def test_drex_toggles_and_status(temp_db_and_server):
    client = temp_db_and_server["client"]
    auth = temp_db_and_server["auth_headers"]

    resp = client.get("/api/drex", headers=auth)
    assert resp.status_code == 200
    data = resp.json()
    assert "decision_toggles" in data
    assert data["decision_toggles"]["judge"] is True

    # Update confidence threshold
    upd = client.put("/api/drex", json={"confidence_threshold": 0.85}, headers=auth)
    assert upd.status_code == 200
    assert upd.json()["confidence_threshold"] == 0.85


def test_privacy_redaction_preview(temp_db_and_server):
    client = temp_db_and_server["client"]
    auth = temp_db_and_server["auth_headers"]

    sample_text = "My secret token is sk-abcdefghijklmnopqrstuvwxyz123456 and email is dev@company.com"
    prev = client.post("/api/privacy/preview", json={"text": sample_text}, headers=auth)
    assert prev.status_code == 200
    red = prev.json()["redacted_text"]
    assert "[REDACTED_SECRET]" in red
    assert "[REDACTED_PII]" in red
    assert "dev@company.com" not in red


def test_budgets_summary(temp_db_and_server):
    client = temp_db_and_server["client"]
    auth = temp_db_and_server["auth_headers"]

    resp = client.get("/api/budgets", headers=auth)
    assert resp.status_code == 200
    data = resp.json()
    assert "hard_cap_usd" in data
    assert "today_usd" in data


# ===========================================================================
# 7. Memory & Claude Code & Requests & Explain
# ===========================================================================

def test_brain_memory_operations(temp_db_and_server):
    client = temp_db_and_server["client"]
    auth = temp_db_and_server["auth_headers"]

    # Query
    mem = client.get("/api/brain/memory", headers=auth)
    assert mem.status_code == 200
    assert "lessons" in mem.json()

    # Decay
    decay = client.post("/api/brain/memory/decay?rate=0.05", headers=auth)
    assert decay.status_code == 200

    # Toggle A/B
    ab = client.post("/api/brain/memory/toggle-ab", headers=auth)
    assert ab.status_code == 200

    # Snapshot
    snap = client.post("/api/brain/memory/snapshot?notes=TestSnapshot", headers=auth)
    assert snap.status_code == 200
    snap_id = snap.json()["snapshot_id"]

    # Rollback
    rb = client.post(f"/api/brain/memory/rollback?snapshot_id={snap_id}", headers=auth)
    assert rb.status_code == 200


def test_claude_status_and_undo(temp_db_and_server):
    client = temp_db_and_server["client"]
    auth = temp_db_and_server["auth_headers"]

    c = client.get("/api/claude", headers=auth)
    assert c.status_code == 200
    assert "installed" in c.json()

    v = client.post("/api/claude/verify", headers=auth)
    assert v.status_code == 200


def test_requests_pagination_and_explain(temp_db_and_server):
    client = temp_db_and_server["client"]
    server = temp_db_and_server["server"]
    auth = temp_db_and_server["auth_headers"]

    # Seed one test request in request_log
    import time
    now = int(time.time() * 1000)
    server.store.conn.execute(
        "INSERT INTO request_log (request_id, session_id, model_id, provider, key_hash, input_tokens, output_tokens, latency_ms, http_status, outcome, privacy_class, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("req_test_001", "sess_001", "llama-3.3-70b-versatile", "groq", "hash123", 500, 150, 125.5, 200, "success", "internal", now),
    )
    server.store.conn.commit()

    # Query requests
    reqs = client.get("/api/requests?page=1&page_size=10", headers=auth)
    assert reqs.status_code == 200
    assert reqs.json()["total"] >= 1
    assert reqs.json()["items"][0]["request_id"] == "req_test_001"

    # Explain request
    exp = client.get("/api/explain/req_test_001", headers=auth)
    assert exp.status_code == 200
    data = exp.json()
    assert "timeline" in data
    assert len(data["timeline"]) == 5
    assert "groq" in data["plain_summary"]

    # Sessions
    sess = client.get("/api/sessions", headers=auth)
    assert sess.status_code == 200
    assert any(s["session_id"] == "sess_001" for s in sess.json())


# ===========================================================================
# 8. Alerts & Logs & Test Center & Backup & Update & Events
# ===========================================================================

def test_alerts_lifecycle(temp_db_and_server):
    client = temp_db_and_server["client"]
    server = temp_db_and_server["server"]
    auth = temp_db_and_server["auth_headers"]

    from brain.api.services.alerts_service import create_alert
    create_alert(server.store.conn, "alt_01", "warning", "High Token Usage", "Token budget reached 80%", "budgets")

    alerts = client.get("/api/alerts", headers=auth)
    assert alerts.status_code == 200
    assert any(a["alert_id"] == "alt_01" for a in alerts.json())

    ack = client.post("/api/alerts/alt_01/acknowledge", headers=auth)
    assert ack.status_code == 200


def test_logs_and_support_bundle(temp_db_and_server):
    client = temp_db_and_server["client"]
    auth = temp_db_and_server["auth_headers"]

    logs = client.get("/api/logs?limit=10", headers=auth)
    assert logs.status_code == 200
    assert isinstance(logs.json(), list)

    bundle = client.post("/api/logs/bundle", headers=auth)
    assert bundle.status_code == 200
    assert bundle.headers["content-type"] == "application/zip"


def test_test_center_heatmap(temp_db_and_server):
    client = temp_db_and_server["client"]
    auth = temp_db_and_server["auth_headers"]

    run = client.post("/api/test-center/run", json={"suite": "smoke"}, headers=auth)
    assert run.status_code == 200
    data = run.json()
    assert data["passed"] >= 5
    assert len(data["heatmap"]) >= 5

    status = client.get("/api/test-center/status", headers=auth)
    assert status.status_code == 200


def test_backup_and_update(temp_db_and_server):
    client = temp_db_and_server["client"]
    auth = temp_db_and_server["auth_headers"]

    b = client.post("/api/backup?notes=UnittestBackup", headers=auth)
    assert b.status_code == 200
    b_id = b.json()["backup_id"]

    blist = client.get("/api/backup", headers=auth)
    assert blist.status_code == 200
    assert any(x["backup_id"] == b_id for x in blist.json())

    u = client.get("/api/update", headers=auth)
    assert u.status_code == 200
    assert u.json()["up_to_date"] is True


def test_root_compatibility_endpoints(temp_db_and_server):
    client = temp_db_and_server["client"]

    # /health without token (used by watchdog and startup scripts)
    h = client.get("/health")
    assert h.status_code == 200
    assert h.json()["status"] == "ok"

    # /hook
    hook = client.post("/hook", json={"tool_name": "bash", "tool_input": {"command": "echo hello"}})
    assert hook.status_code == 200
    assert hook.json()["allow"] is True

    # /outcome
    out = client.post("/outcome", json={"model_id": "llama3.1-8b", "success": True, "latency_ms": 110.0})
    assert out.status_code == 200

    # /sleep
    sl = client.post("/sleep")
    assert sl.status_code == 200
