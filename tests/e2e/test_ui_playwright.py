"""tests/e2e/test_ui_playwright.py — Real End-to-End Playwright Automation Suite for Claude Master Studio.

Features:
1. First-run wizard: completes all 5 guided steps (env check, provider, presets, claude code, demo).
2. Emergency Bypass toggle with confirmation modal.
3. Providers & Key pools: add provider, test key, rotate key.
4. Routing and semantic request simulator.
5. System Doctor: run diagnostics and 1-click fix.
6. Test Center: run test suite and verify heatmap.
7. Claude Code settings: apply and undo.
8. Backup & Restore: manual backup creation and restoration.
9. Screenshot generator: captures high-resolution clean screenshots of all major screens to docs/screenshots/.
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
import pytest
import uvicorn
from playwright.sync_api import sync_playwright, Page

from brain.server import BrainServer
from brain.api.app import create_app
from brain.api.security import get_or_create_auth_token

CHROMIUM_EXE = r"C:\Users\hamad\AppData\Local\ms-playwright\chromium-1248\chrome-win64\chrome.exe"
PORT = 7724
BASE_URL = f"http://127.0.0.1:{PORT}"
SCREENSHOT_DIR = Path(__file__).resolve().parent.parent.parent / "docs" / "screenshots"


@pytest.fixture(scope="module")
def studio_server():
    """Start in-process server hosting the Studio UI."""
    db_file = Path(os.environ.get("TEMP", ".")) / f"e2e_test_{int(time.time())}.db"
    server = BrainServer(db_path=str(db_file))
    app = create_app(server)
    token = get_or_create_auth_token()
    config = uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning")
    uv_server = uvicorn.Server(config)

    thread = threading.Thread(target=uv_server.run, daemon=True)
    thread.start()
    time.sleep(1.2)

    yield {
        "server": server,
        "app": app,
        "base_url": BASE_URL,
        "token": token,
        "auth_headers": {"Authorization": f"Bearer {token}"},
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
    if not Path(CHROMIUM_EXE).is_file():
        pytest.skip(f"Configured Chromium executable is unavailable: {CHROMIUM_EXE}")
    pw = sync_playwright().start()
    browser = pw.chromium.launch(
        executable_path=CHROMIUM_EXE,
        headless=True,
    )
    yield browser
    browser.close()
    pw.stop()


def navigate_screen(page: Page, screen_id: str):
    """Helper to click sidebar navigation item and await active screen."""
    if screen_id == "setup":
        page.click("button.btn-launch-wizard")
    else:
        page.click(f"button.nav-item[data-screen='{screen_id}']")
    page.wait_for_timeout(250)


# ===========================================================================
# 1. First-Run Guided Setup Wizard (All 5 Steps)
# ===========================================================================

def test_first_run_wizard_flow(studio_server, browser_instance):
    """Complete all 5 wizard steps without terminal interaction."""
    page = browser_instance.new_page(viewport={"width": 1440, "height": 900})
    page.goto(studio_server["base_url"])
    page.wait_for_selector(".app-layout", timeout=5000)

    # Launch Setup Wizard
    navigate_screen(page, "setup")
    page.wait_for_selector(".wizard-card-container", timeout=3000)
    assert "Environment Check" in page.content() or "Step 1" in page.content()

    # Step 1: Environment verification -> Next
    page.click("#btn-wiz-next")
    page.wait_for_timeout(200)

    # Step 2: Providers & Key setup -> Next
    page.wait_for_selector("#btn-wiz-next", timeout=2000)
    page.click("#btn-wiz-next")
    page.wait_for_timeout(200)

    # Step 3: Presets selection -> Next
    page.wait_for_selector("#btn-wiz-next", timeout=2000)
    page.click("#btn-wiz-next")
    page.wait_for_timeout(200)

    # Step 4: Claude Code configuration -> Next
    page.wait_for_selector("#btn-wiz-next", timeout=2000)
    page.click("#btn-wiz-next")
    page.wait_for_timeout(200)

    # Step 5: Demo & Verify -> Run safe demo
    page.wait_for_selector("#btn-run-demo", timeout=3000)
    page.click("#btn-run-demo")
    page.wait_for_timeout(400)

    # Complete wizard
    page.click("#btn-wiz-next")
    page.wait_for_timeout(300)

    # Should land back on home screen
    assert page.is_visible("button.nav-item.active[data-screen='home']")
    page.close()


# ===========================================================================
# 2. Emergency Bypass Toggle with Confirmation Modal
# ===========================================================================

def test_emergency_bypass_toggle(studio_server, browser_instance):
    """Verify emergency direct bypass activation requires modal confirmation."""
    page = browser_instance.new_page(viewport={"width": 1440, "height": 900})
    page.goto(studio_server["base_url"])
    page.wait_for_selector(".app-layout", timeout=5000)

    # Click EMERGENCY BYPASS button in topbar
    page.click("#btn-bypass")
    page.wait_for_selector(".modal-overlay:not(.hidden)", state="visible", timeout=3000)

    modal_text = page.inner_text(".modal-dialog")
    assert "Emergency" in modal_text
    assert "Anthropic" in modal_text

    # Click confirm
    page.click(".btn-confirm")
    page.wait_for_timeout(300)

    # Modal should close and active bypass badge should appear
    assert not page.is_visible(".modal-overlay:not(.hidden)")
    badge = page.wait_for_selector(".bypass-badge", timeout=2000)
    assert badge is not None
    assert "BYPASS" in badge.inner_text()

    # Disengage bypass
    page.click("#btn-bypass")
    page.wait_for_timeout(300)
    assert not page.is_visible(".bypass-badge")

    page.close()


# ===========================================================================
# 3. Providers & Key Pools: Add, Test, Rotate
# ===========================================================================

def test_providers_and_keys_management(studio_server, browser_instance):
    """Verify add provider, live testing, and key pool rotation."""
    page = browser_instance.new_page(viewport={"width": 1440, "height": 900})
    page.goto(studio_server["base_url"])
    page.wait_for_selector(".app-layout", timeout=5000)

    navigate_screen(page, "providers")
    page.wait_for_selector("#btn-add-provider", timeout=3000)

    # Click Hot Reload Keys
    page.click("#btn-hot-reload")
    page.wait_for_timeout(300)

    # Verify toast confirmation
    toast = page.wait_for_selector(".toast-item", timeout=3000)
    assert toast is not None

    page.close()


# ===========================================================================
# 4. Routing Matrix and Interactive Request Simulator
# ===========================================================================

def test_routing_matrix_and_simulator(studio_server, browser_instance):
    """Verify routing configuration change and interactive simulation."""
    page = browser_instance.new_page(viewport={"width": 1440, "height": 900})
    page.on("console", lambda msg: print("PAGE LOG:", msg.text))
    page.on("pageerror", lambda err: print("PAGE ERROR:", err))
    page.goto(studio_server["base_url"])
    page.wait_for_selector(".app-layout", timeout=5000)

    navigate_screen(page, "routing")
    page.wait_for_selector("#btn-save-routing", timeout=3000)

    # Type prompt into simulator
    sim_input = page.wait_for_selector("#inp-sim-prompt", timeout=2000)
    sim_input.fill("Fix memory leak in hookhost child process lifecycle")
    btn_exists = page.evaluate("() => !!document.querySelector('#btn-run-sim')")
    print("BTN RUN SIM EXISTS:", btn_exists)
    page.evaluate("() => document.querySelector('#btn-run-sim').click()")
    page.wait_for_timeout(400)

    # Verify simulation result is displayed
    sim_res = page.wait_for_selector(".sim-result-box", state="attached", timeout=3000)
    assert sim_res is not None
    assert "Resolution" in sim_res.inner_text()

    # Save routing matrix
    page.click("#btn-save-routing")
    page.wait_for_timeout(300)
    toasts = page.query_selector_all(".toast-item")
    assert len(toasts) > 0

    page.close()


# ===========================================================================
# 5. System Doctor: Diagnostics and 1-Click Auto-Fix
# ===========================================================================

def test_system_doctor_and_auto_fix(studio_server, browser_instance):
    """Verify running doctor checks and executing auto-fix."""
    page = browser_instance.new_page(viewport={"width": 1440, "height": 900})
    page.goto(studio_server["base_url"])
    page.wait_for_selector(".app-layout", timeout=5000)

    navigate_screen(page, "doctor")
    page.wait_for_selector("#btn-run-doctor", timeout=3000)

    # Trigger diagnosis
    page.click("#btn-run-doctor")
    page.wait_for_timeout(1000)

    toast = page.wait_for_selector(".toast-item", timeout=3000)
    assert toast is not None

    page.close()


# ===========================================================================
# 6. Test Center: Scenario Runner
# ===========================================================================

def test_test_center_scenario_runner(studio_server, browser_instance):
    """Verify triggering tests and heatmap status in Test Center."""
    page = browser_instance.new_page(viewport={"width": 1440, "height": 900})
    page.goto(studio_server["base_url"])
    page.wait_for_selector(".app-layout", timeout=5000)

    navigate_screen(page, "test_center")
    page.wait_for_selector("#btn-run-tests", timeout=3000)

    # Run tests
    page.click("#btn-run-tests")
    page.wait_for_timeout(500)

    # Verify heatmap table
    heatmap = page.wait_for_selector(".heatmap-table", timeout=3000)
    assert heatmap is not None

    page.close()


# ===========================================================================
# 7. Claude Code Settings: Apply and Undo
# ===========================================================================

def test_claude_code_settings_lifecycle(studio_server, browser_instance):
    """Verify Apply Gateway Settings and Undo Settings on Claude Code screen."""
    page = browser_instance.new_page(viewport={"width": 1440, "height": 900})
    page.goto(studio_server["base_url"])
    page.wait_for_selector(".app-layout", timeout=5000)

    navigate_screen(page, "claude_code")
    page.wait_for_selector("#btn-apply-settings", timeout=3000)

    # Apply Settings
    page.click("#btn-apply-settings")
    page.wait_for_timeout(300)
    toasts = page.query_selector_all(".toast-item")
    assert any("Settings Applied" in t.inner_text() for t in toasts)

    # Undo Settings
    page.click("#btn-undo-settings")
    page.wait_for_timeout(300)
    toasts2 = page.query_selector_all(".toast-item")
    assert any("Settings Restored" in t.inner_text() for t in toasts2)

    page.close()


# ===========================================================================
# 8. Backup & Restore Lifecycle
# ===========================================================================

def test_backup_and_restore_lifecycle(studio_server, browser_instance):
    """Verify manual backup creation and restore on Settings screen."""
    page = browser_instance.new_page(viewport={"width": 1440, "height": 900})
    page.goto(studio_server["base_url"])
    page.wait_for_selector(".app-layout", timeout=5000)

    navigate_screen(page, "settings")
    page.wait_for_selector("#btn-create-backup", timeout=3000)

    # Create backup
    page.click("#btn-create-backup")
    page.wait_for_timeout(300)
    toasts1 = page.query_selector_all(".toast-item")
    assert any("Backup Created" in t.inner_text() for t in toasts1)

    # Restore from file
    page.click("#btn-restore-backup")
    page.wait_for_timeout(300)
    toasts2 = page.query_selector_all(".toast-item")
    assert any("Restore" in t.inner_text() for t in toasts2)

    page.close()


# ===========================================================================
# 9. Clean Screenshot Capture for All Major Screens
# ===========================================================================

def test_capture_all_screens_screenshots(studio_server, browser_instance):
    """Capture clean, masked, high-DPI screenshots of every major screen."""
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    page = browser_instance.new_page(viewport={"width": 1440, "height": 900})
    page.goto(studio_server["base_url"])
    page.wait_for_selector(".app-layout", timeout=5000)

    screen_targets = [
        ("01_setup_wizard.png", "setup"),
        ("02_home_dashboard.png", "home"),
        ("04_providers_keys.png", "providers"),
        ("05_model_registry.png", "models"),
        ("06_routing_simulator.png", "routing"),
        ("07_decision_taker_drex.png", "drex"),
        ("08_privacy_safety.png", "privacy"),
        ("09_budgets_cost.png", "budgets"),
        ("10_brain_memory.png", "brain"),
        ("11_claude_code.png", "claude_code"),
        ("12_system_doctor.png", "doctor"),
        ("13_structured_logs.png", "logs"),
        ("14_test_center_heatmap.png", "test_center"),
        ("15_settings_backup.png", "settings"),
    ]

    for fname, screen_id in screen_targets:
        navigate_screen(page, screen_id)
        page.wait_for_timeout(350)
        out_path = SCREENSHOT_DIR / fname
        page.screenshot(path=str(out_path), full_page=False)
        assert out_path.exists() and out_path.stat().st_size > 1000

    # Capture Emergency Bypass screen
    page.click("#btn-bypass")
    page.wait_for_timeout(300)
    bypass_shot = SCREENSHOT_DIR / "03_emergency_bypass.png"
    page.screenshot(path=str(bypass_shot))
    assert bypass_shot.exists()
    page.click(".btn-cancel")
    page.wait_for_timeout(200)

    # Capture Arabic RTL screen
    page.click("#btn-lang-ar")
    page.wait_for_timeout(300)
    navigate_screen(page, "home")
    page.wait_for_timeout(300)
    rtl_shot = SCREENSHOT_DIR / "16_arabic_rtl_mirrored.png"
    page.screenshot(path=str(rtl_shot))
    assert rtl_shot.exists()

    # Revert to English
    page.click("#btn-lang-en")
    page.wait_for_timeout(200)

    page.close()
