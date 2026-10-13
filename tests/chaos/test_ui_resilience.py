"""tests/chaos/test_ui_resilience.py — Chaos and Resilience Verification for Claude Master UI & Services.

Verifies:
1. Daemon kill / disconnect while UI is active:
   - UI displays offline banner with role="alert".
   - Clear user guidance and countdown timer are displayed.
   - Start / Repair button is rendered and triggers system restart signal.
2. Config corruption and 1-click auto-repair:
   - Corrupted or missing configuration triggers fallback mode.
   - Doctor diagnostic suite flags config failure.
   - 1-click auto-repair endpoint restores default valid configuration and recovers system state.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
import time
from pathlib import Path
import pytest
import uvicorn
from starlette.testclient import TestClient
from playwright.sync_api import sync_playwright

from brain.server import BrainServer
from brain.api.app import create_app
from brain.api.security import get_or_create_auth_token
from brain.api.services.doctor_service import run_doctor_checks, execute_doctor_fix
from brain.api.services.config_service import get_gateway_config_path, read_gateway_config

import socket

def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]

CHROMIUM_EXE = r"C:\Users\hamad\AppData\Local\ms-playwright\chromium-1248\chrome-win64\chrome.exe"


@pytest.fixture(scope="module")
def resilience_server():
    """Start in-process server for resilience testing."""
    port = find_free_port()
    base_url = f"http://127.0.0.1:{port}"
    db_file = Path(os.environ.get("TEMP", ".")) / f"resilience_test_{int(time.time())}.db"
    server = BrainServer(db_path=str(db_file))
    app = create_app(server)
    token = get_or_create_auth_token()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    uv_server = uvicorn.Server(config)

    thread = threading.Thread(target=uv_server.run, daemon=True)
    thread.start()
    time.sleep(1.2)

    yield {
        "server": server,
        "app": app,
        "base_url": base_url,
        "token": token,
        "auth_headers": {"Authorization": f"Bearer {token}"},
        "db_file": db_file,
    }

    uv_server.should_exit = True
    thread.join(timeout=2.0)
    try:
        if hasattr(server, "store") and hasattr(server.store, "conn"):
            server.store.conn.close()
        if db_file.exists():
            db_file.unlink()
    except Exception:
        pass


@pytest.fixture(scope="module")
def browser_instance():
    pw = sync_playwright().start()
    browser = pw.chromium.launch(
        executable_path=CHROMIUM_EXE,
        headless=True,
    )
    yield browser
    browser.close()
    pw.stop()


def test_daemon_kill_and_offline_banner(resilience_server, browser_instance):
    """Verify that when daemon connection is lost, offline banner displays retry countdown and repair action."""
    page = browser_instance.new_page()
    page.goto(resilience_server["base_url"])
    page.wait_for_selector(".app-layout", timeout=5000)

    # Initially banner is hidden
    assert not page.is_visible(".offline-banner:not(.hidden)")

    # Simulate daemon loss / offline event via client store
    page.evaluate("""() => {
        if (window.__STORE__) {
            window.__STORE__.setDaemonStatus("reconnecting", 5);
        }
    }""")
    page.wait_for_timeout(300)

    # 1. Offline banner must be visible
    page.wait_for_selector(".offline-banner:not(.hidden)", state="visible", timeout=2000)
    assert page.is_visible(".offline-banner:not(.hidden)")

    # 2. Clear guidance text and countdown
    banner_text = page.inner_text(".offline-banner")
    assert "Backend Daemon Unreachable" in banner_text
    assert "Requests are currently held" in banner_text
    assert "Auto-retry in" in banner_text

    # 3. Start/Repair System button is rendered
    repair_btn = page.query_selector("#btn-banner-repair")
    assert repair_btn is not None
    assert "Start / Repair System" in repair_btn.inner_text()

    # 4. Click repair button and verify feedback toast
    repair_btn.click()
    page.wait_for_timeout(300)

    # Verify toast or button transition
    toast = page.wait_for_selector(".toast-item", timeout=3000)
    assert toast is not None
    assert "Repair Signal Sent" in toast.inner_text()

    page.close()


def test_corrupt_config_fallback_and_doctor_repair(resilience_server):
    """Verify doctor diagnoses corrupted config and 1-click auto-repair restores it."""
    client = TestClient(resilience_server["app"], base_url=resilience_server["base_url"])
    auth = resilience_server["auth_headers"]

    cfg_path = get_gateway_config_path()
    backup_path = cfg_path.with_suffix(".json.bak_test")

    # 1. Back up original config
    if cfg_path.exists():
        shutil.copy2(cfg_path, backup_path)

    try:
        # 2. Corrupt config with invalid JSON
        cfg_path.write_text("{ this is corrupted invalid json syntax !!!", encoding="utf-8")

        # 3. Safe fallback in read_gateway_config
        fallback_cfg = read_gateway_config()
        assert isinstance(fallback_cfg, dict)
        assert fallback_cfg.get("listen_addr") == ":8080"

        # 4. Run Doctor diagnosis via API
        doc_res = client.get("/api/doctor", headers=auth)
        assert doc_res.status_code == 200
        report = doc_res.json()
        assert "checks" in report

        # Find gateway_config check
        cfg_check = next((c for c in report["checks"] if c["check_id"] == "gateway_config"), None)
        assert cfg_check is not None
        # It must be flagged as warn or fail
        assert cfg_check["status"] in ("warn", "fail")
        assert cfg_check["can_auto_fix"] is True or cfg_check["status"] == "warn"

        # 5. Execute 1-click repair via API
        fix_res = client.post(
            "/api/doctor/fix",
            headers=auth,
            json={"check_id": "gateway_config"},
        )
        assert fix_res.status_code == 200
        fix_data = fix_res.json()
        assert fix_data["fixed"] is True
        assert fix_data["after_status"] == "pass"

        # 6. Verify config is now valid JSON on disk
        repaired_content = json.loads(cfg_path.read_text(encoding="utf-8"))
        assert repaired_content["listen_addr"] == ":8080"

    finally:
        # Restore original config
        if backup_path.exists():
            shutil.copy2(backup_path, cfg_path)
            backup_path.unlink()
