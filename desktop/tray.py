"""
desktop/tray.py — Native Windows System Tray Application for claude-master.

Provides real-time colored status tray icon (Green/Yellow/Red/Orange) and
quick context menu for lifecycle management, emergency bypass toggle,
doctor repairs, login startup, and desktop WebView2 window launching.
"""

from __future__ import annotations
import sys
import threading
import time
import logging
from pathlib import Path
import pystray
from PIL import Image

from desktop.icons import create_tray_icon_image, STATUS_NAMES
from desktop.status import get_current_status, SystemStatus
from desktop.window import launch_window_process
from desktop.service_manager import (
    start_system,
    stop_system,
    restart_system,
    toggle_bypass,
    run_doctor_repair,
)
from desktop.autostart import (
    is_autostart_enabled,
    set_autostart,
    create_desktop_shortcut,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("desktop.tray")


class ClaudeMasterTrayApp:
    def __init__(self, brain_port: int = 7700, gw_port: int = 8080) -> None:
        self.brain_port = brain_port
        self.gw_port = gw_port
        self.current_status: SystemStatus = get_current_status(brain_port, gw_port)
        self.autostart_active: bool = is_autostart_enabled()
        self.running: bool = False
        self._icon: pystray.Icon | None = None
        self._poll_thread: threading.Thread | None = None

    def _get_icon_image(self) -> Image.Image:
        return create_tray_icon_image(self.current_status.color)

    def _get_tooltip(self) -> str:
        return f"Claude Master — {self.current_status.label}\n{self.current_status.details}"

    # Action handlers
    def on_open_ui(self, icon=None, item=None):
        logger.info("Opening WebView2 Studio UI")
        launch_window_process(f"http://127.0.0.1:{self.brain_port}")

    def on_start_system(self, icon=None, item=None):
        logger.info("Starting claude-master system")
        start_system()
        time.sleep(1.0)
        self.update_status_now()

    def on_stop_system(self, icon=None, item=None):
        logger.info("Stopping claude-master system")
        stop_system()
        time.sleep(1.0)
        self.update_status_now()

    def on_restart_system(self, icon=None, item=None):
        logger.info("Restarting claude-master system")
        restart_system()
        time.sleep(1.5)
        self.update_status_now()

    def on_toggle_bypass(self, icon=None, item=None):
        logger.info("Toggling Emergency Bypass")
        toggle_bypass()
        time.sleep(0.5)
        self.update_status_now()

    def on_doctor_repair(self, icon=None, item=None):
        logger.info("Running Doctor diagnostics and repairs")
        res = run_doctor_repair()
        logger.info("Doctor result: %s", res)
        # Also launch UI to doctor view
        launch_window_process(f"http://127.0.0.1:{self.brain_port}/#doctor")
        self.update_status_now()

    def on_toggle_autostart(self, icon=None, item=None):
        new_val = not self.autostart_active
        if set_autostart(new_val):
            self.autostart_active = new_val
            logger.info("Autostart set to %s", new_val)
            if self._icon:
                self._icon.update_menu()

    def on_create_shortcut(self, icon=None, item=None):
        logger.info("Creating Desktop shortcut")
        path = create_desktop_shortcut()
        if path:
            logger.info("Desktop shortcut created successfully at %s", path)

    def on_quit(self, icon=None, item=None):
        logger.info("Quitting Claude Master Tray application")
        self.running = False
        if self._icon:
            self._icon.stop()

    def update_status_now(self):
        new_status = get_current_status(self.brain_port, self.gw_port)
        changed = (new_status.color != self.current_status.color or
                   new_status.bypass_active != self.current_status.bypass_active)
        self.current_status = new_status
        if self._icon:
            if changed:
                self._icon.icon = self._get_icon_image()
            self._icon.title = self._get_tooltip()
            self._icon.update_menu()

    def _poll_status_loop(self):
        while self.running:
            try:
                self.update_status_now()
            except Exception as exc:
                logger.debug("Error during status update: %s", exc)
            time.sleep(2.5)

    def build_menu(self) -> pystray.Menu:
        return pystray.Menu(
            pystray.MenuItem("Open UI", self.on_open_ui, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                lambda text: f"Status: {self.current_status.label} ({self.current_status.color.capitalize()})",
                action=None,
                enabled=False
            ),
            pystray.MenuItem("Start System", self.on_start_system),
            pystray.MenuItem("Stop System", self.on_stop_system),
            pystray.MenuItem("Restart System", self.on_restart_system),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Emergency Bypass",
                self.on_toggle_bypass,
                checked=lambda item: self.current_status.bypass_active
            ),
            pystray.MenuItem("Doctor / Repair", self.on_doctor_repair),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Launch at Login",
                self.on_toggle_autostart,
                checked=lambda item: self.autostart_active
            ),
            pystray.MenuItem("Create Desktop Shortcut", self.on_create_shortcut),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", self.on_quit),
        )

    def run(self):
        self.running = True
        self._poll_thread = threading.Thread(target=self._poll_status_loop, daemon=True)
        self._poll_thread.start()

        self._icon = pystray.Icon(
            name="claude_master_tray",
            icon=self._get_icon_image(),
            title=self._get_tooltip(),
            menu=self.build_menu(),
        )

        logger.info("Claude Master System Tray icon running. Double-click or right-click tray icon.")
        self._icon.run()


def main():
    app = ClaudeMasterTrayApp()
    app.run()


if __name__ == "__main__":
    main()
