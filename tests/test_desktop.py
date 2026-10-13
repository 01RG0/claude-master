"""
tests/test_desktop.py — Unit and integration tests for native Windows desktop shell.
"""

import os
import sys
import pytest
from PIL import Image

from desktop.icons import create_tray_icon_image, get_icon_bytes, STATUS_COLORS, STATUS_NAMES
from desktop.status import get_current_status, check_brain_health, check_gateway_health, SystemStatus
from desktop.service_manager import get_repo_root, toggle_bypass, run_doctor_repair
from desktop.autostart import (
    is_autostart_enabled,
    set_autostart,
    get_desktop_launcher_command,
    create_desktop_shortcut,
)
from desktop.window import detect_webview2_runtime
from desktop.tray import ClaudeMasterTrayApp


def test_icons_generation():
    """Verify all 4 status color icons generate valid RGBA images."""
    for color in ["green", "yellow", "red", "orange"]:
        img = create_tray_icon_image(color, size=64)
        assert isinstance(img, Image.Image)
        assert img.size == (64, 64)
        assert img.mode == "RGBA"

    # Test byte generation
    ico_bytes = get_icon_bytes("green", "ICO")
    assert len(ico_bytes) > 100
    png_bytes = get_icon_bytes("orange", "PNG")
    assert len(png_bytes) > 100


def test_status_classification(monkeypatch):
    """Verify status calculation correctly maps states to colors."""
    # When all down -> red (Stopped)
    monkeypatch.setattr("desktop.status.check_brain_health", lambda *a, **k: None)
    monkeypatch.setattr("desktop.status.check_gateway_health", lambda *a, **k: False)
    monkeypatch.setattr("desktop.status.check_bypass_active", lambda *a, **k: False)
    st = get_current_status()
    assert st.color == "red"
    assert st.label == "Stopped"

    # When brain up, gateway down -> yellow (Degraded)
    monkeypatch.setattr("desktop.status.check_brain_health", lambda *a, **k: {"status": "ok"})
    st = get_current_status()
    assert st.color == "yellow"
    assert st.label == "Degraded"

    # When both up, bypass off -> green (Normal)
    monkeypatch.setattr("desktop.status.check_gateway_health", lambda *a, **k: True)
    st = get_current_status()
    assert st.color == "green"
    assert st.label == "Normal"

    # When bypass active -> orange (Emergency Bypass)
    monkeypatch.setattr("desktop.status.check_bypass_active", lambda *a, **k: True)
    st = get_current_status()
    assert st.color == "orange"
    assert st.label == "Emergency Bypass"


def test_webview2_detection():
    """Verify Evergreen WebView2 runtime detection on Windows."""
    rt_path = detect_webview2_runtime()
    assert rt_path is not None
    assert os.path.exists(rt_path)
    assert os.path.exists(os.path.join(rt_path, "msedgewebview2.exe"))


def test_autostart_and_shortcuts():
    """Verify autostart command string, registry toggling and shortcut creation."""
    cmd = get_desktop_launcher_command()
    assert "tray.py" in cmd

    # Test toggling autostart in registry
    init_val = is_autostart_enabled()
    # Test setting to True and reading
    res = set_autostart(True)
    assert res is True
    assert is_autostart_enabled() is True
    # Restore or set False
    set_autostart(init_val)
    assert is_autostart_enabled() == init_val

    # Test creating shortcut
    lnk = create_desktop_shortcut(shortcut_name="Claude Master Test")
    assert lnk is not None
    assert lnk.exists()
    # Clean up test shortcut
    try:
        lnk.unlink()
    except Exception:
        pass


def test_tray_app_initialization():
    """Verify tray application object, menu items, and tooltip generation."""
    app = ClaudeMasterTrayApp()
    assert app.current_status is not None
    tooltip = app._get_tooltip()
    assert "Claude Master" in tooltip
    img = app._get_icon_image()
    assert img.size == (64, 64)

    menu = app.build_menu()
    items = list(menu.items)
    # Ensure expected actions are present
    labels = [str(item.text) if callable(item.text) else item.text for item in items]
    assert any("Open UI" in str(l) for l in labels)
    assert any("Start System" in str(l) for l in labels)
    assert any("Stop System" in str(l) for l in labels)
    assert any("Emergency Bypass" in str(l) for l in labels)
    assert any("Doctor" in str(l) for l in labels)
    assert any("Quit" in str(l) for l in labels)
