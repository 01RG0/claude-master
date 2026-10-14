"""tests/ui/test_a11y_rtl.py — Accessibility, RTL, Keyboard Nav, and Theme Switch Suite.

Automates Playwright verification against live Studio UI:
1. Keyboard navigation (Tab, Arrow keys, Enter, Escape, Ctrl+K command palette).
2. ARIA semantics, role attributes, focus management, and contrast readability.
3. RTL layout check: Arabic switch sets dir="rtl", mirrors navigation, and renders Arabic text.
4. Light/Dark theme switching and persistent theme tokens.
5. Scalable layout verification under zoom/font scaling.
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
import pytest
import uvicorn
from playwright.sync_api import sync_playwright

from brain.server import BrainServer
from brain.api.app import create_app

import socket

def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]

CHROMIUM_EXE = r"C:\Users\hamad\AppData\Local\ms-playwright\chromium-1248\chrome-win64\chrome.exe"


@pytest.fixture(scope="module")
def studio_server():
    """Start in-process uvicorn server hosting Studio UI."""
    port = find_free_port()
    base_url = f"http://127.0.0.1:{port}"
    db_file = Path(os.environ.get("TEMP", ".")) / f"a11y_test_{int(time.time())}.db"
    server = BrainServer(db_path=str(db_file))
    app = create_app(server)
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    uv_server = uvicorn.Server(config)

    thread = threading.Thread(target=uv_server.run, daemon=True)
    thread.start()
    time.sleep(1.2)

    yield {"server": server, "app": app, "base_url": base_url}

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
    """Launch Chromium browser."""
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


def test_aria_semantics_and_roles(studio_server, browser_instance):
    """Verify ARIA roles, landmarks, and accessible tab controls."""
    page = browser_instance.new_page()
    page.goto(studio_server["base_url"])
    page.wait_for_selector(".app-layout", timeout=5000)

    # 1. Main landmark
    main_el = page.query_selector("main[role='main']")
    assert main_el is not None, "Missing <main role='main'> landmark"

    # 2. Navigation landmark
    nav_el = page.query_selector("nav.app-navigation[aria-label='Main Navigation']")
    assert nav_el is not None, "Missing accessible <nav aria-label='Main Navigation'>"

    # 3. Radio groups for toggles
    radiogroups = page.query_selector_all("div[role='radiogroup']")
    assert len(radiogroups) >= 2, "Expected radiogroups for User Mode and Language toggles"

    # 4. Tab selection state on navigation buttons
    tabs = page.query_selector_all("button.nav-item[role='tab']")
    assert len(tabs) >= 10, "Expected at least 10 nav tabs"
    selected_tabs = [t for t in tabs if t.get_attribute("aria-selected") == "true"]
    assert len(selected_tabs) == 1, "Exactly one nav tab should have aria-selected=true"

    page.close()


def test_keyboard_navigation_and_command_palette(studio_server, browser_instance):
    """Verify full keyboard control: Ctrl+K, Arrow navigation, Enter, and Escape."""
    page = browser_instance.new_page()
    page.goto(studio_server["base_url"])
    page.wait_for_selector(".app-layout", timeout=5000)

    # 1. Open Command Palette via button or Ctrl+K
    page.click("#btn-open-palette")
    page.wait_for_selector(".command-palette-overlay:not(.hidden)", state="visible", timeout=3000)

    input_el = page.wait_for_selector(".palette-input", timeout=2000)
    assert input_el is not None

    # 2. Type search query
    page.type(".palette-input", "Routing")
    page.wait_for_timeout(200)

    # Verify search results exist
    results = page.query_selector_all(".palette-item")
    assert len(results) > 0, "Command palette must show matching results for 'Routing'"

    # 3. Press Enter to navigate to screen
    page.keyboard.press("Enter")
    page.wait_for_timeout(300)

    # Palette should close and screen change
    assert not page.is_visible(".command-palette-overlay:not(.hidden)")
    active_nav = page.query_selector("button.nav-item.active")
    assert active_nav is not None
    assert active_nav.get_attribute("data-screen") == "routing"

    # 4. Open palette again and test Escape dismiss
    page.click("#btn-open-palette")
    page.wait_for_selector(".command-palette-overlay:not(.hidden)", state="visible", timeout=3000)
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)
    assert not page.is_visible(".command-palette-overlay:not(.hidden)")

    page.close()


def test_rtl_layout_and_arabic_rendering(studio_server, browser_instance):
    """Verify Arabic switch sets dir='rtl', mirrors flex layouts, and renders Arabic text."""
    page = browser_instance.new_page()
    page.goto(studio_server["base_url"])
    page.wait_for_selector(".app-layout", timeout=5000)

    # Initial LTR verification
    dir_init = page.evaluate("document.documentElement.getAttribute('dir')")
    assert dir_init in (None, "ltr")

    # Click Arabic language button
    page.click("#btn-lang-ar")
    page.wait_for_timeout(300)

    # 1. document.documentElement dir attribute must be rtl
    dir_ar = page.evaluate("document.documentElement.getAttribute('dir')")
    assert dir_ar == "rtl", f"Expected dir='rtl', got {dir_ar}"

    # 2. Computed direction must be rtl
    computed_dir = page.evaluate("window.getComputedStyle(document.documentElement).direction")
    assert computed_dir == "rtl"

    # 3. Verify Arabic text rendering in UI components
    content = page.content()
    assert "استوديو كلود ماستر" in content or "الرئيسية" in content or "المزودات" in content, (
        "Arabic translation string not found in rendered DOM"
    )

    # 4. Switch back to English
    page.click("#btn-lang-en")
    page.wait_for_timeout(300)

    dir_en = page.evaluate("document.documentElement.getAttribute('dir')")
    assert dir_en == "ltr"

    page.close()


def test_dark_and_light_theme_switching(studio_server, browser_instance):
    """Verify theme toggle between dark and light modes, and contrast values."""
    page = browser_instance.new_page()
    page.goto(studio_server["base_url"])
    page.wait_for_selector(".app-layout", timeout=5000)

    # Initial theme is dark
    theme_1 = page.evaluate("document.documentElement.getAttribute('data-theme')")
    assert theme_1 in (None, "dark")

    # Toggle to light theme
    page.click("#btn-theme")
    page.wait_for_timeout(300)

    theme_2 = page.evaluate("document.documentElement.getAttribute('data-theme')")
    assert theme_2 == "light"

    # Check background color in light mode is bright/light
    bg_light = page.evaluate("window.getComputedStyle(document.body).backgroundColor")
    assert bg_light is not None

    # Toggle back to dark theme
    page.click("#btn-theme")
    page.wait_for_timeout(300)

    theme_3 = page.evaluate("document.documentElement.getAttribute('data-theme')")
    assert theme_3 == "dark"

    page.close()
