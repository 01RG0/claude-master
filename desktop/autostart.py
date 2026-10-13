"""
desktop/autostart.py — Windows login autostart registry and Desktop shortcut management.
"""

from __future__ import annotations
import os
import sys
import winreg
import logging
from pathlib import Path

logger = logging.getLogger("desktop.autostart")

RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_NAME = "ClaudeMaster"
REPO_ROOT = Path(__file__).resolve().parent.parent


def get_desktop_launcher_command() -> str:
    """Return the Windows execution command for the tray application."""
    # Use pythonw.exe if available to avoid pop-up console window
    python_dir = Path(sys.executable).parent
    pythonw = python_dir / "pythonw.exe"
    exe = str(pythonw) if pythonw.exists() else sys.executable
    tray_script = REPO_ROOT / "desktop" / "tray.py"
    return f'"{exe}" "{tray_script}"'


def is_autostart_enabled() -> bool:
    """Check if Claude Master is registered to start at Windows login."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_READ) as key:
            val, _ = winreg.QueryValueEx(key, APP_NAME)
            return bool(val)
    except FileNotFoundError:
        return False
    except Exception as exc:
        logger.debug("Failed to read autostart registry key: %s", exc)
        return False


def set_autostart(enable: bool) -> bool:
    """Enable or disable startup at Windows login via HKCU Run registry key."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE) as key:
            if enable:
                cmd = get_desktop_launcher_command()
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, cmd)
                logger.info("Enabled autostart at login: %s", cmd)
            else:
                try:
                    winreg.DeleteValue(key, APP_NAME)
                    logger.info("Disabled autostart at login")
                except FileNotFoundError:
                    pass
        return True
    except Exception as exc:
        logger.error("Failed to update autostart key: %s", exc)
        return False


def create_desktop_shortcut(target_path: Path | None = None, shortcut_name: str = "Claude Master") -> Path | None:
    """Create a Windows desktop shortcut (.lnk) pointing to the desktop launcher."""
    import win32com.client  # from pywin32
    from desktop.icons import get_icon_bytes

    try:
        desktop_dir = Path(os.environ["USERPROFILE"]) / "Desktop"
        if not desktop_dir.exists():
            desktop_dir = Path(os.path.expanduser("~")) / "Desktop"
        
        shortcut_file = desktop_dir / f"{shortcut_name}.lnk"

        # Generate icon file if not present
        icon_file = REPO_ROOT / "desktop" / "claude_master.ico"
        if not icon_file.exists():
            icon_file.write_bytes(get_icon_bytes(status="green", format="ICO"))

        python_dir = Path(sys.executable).parent
        pythonw = python_dir / "pythonw.exe"
        exe = str(pythonw) if pythonw.exists() else sys.executable
        tray_script = REPO_ROOT / "desktop" / "tray.py"

        shell = win32com.client.Dispatch("WScript.Shell")
        shortcut = shell.CreateShortcut(str(shortcut_file))
        shortcut.TargetPath = exe
        shortcut.Arguments = f'"{tray_script}"'
        shortcut.WorkingDirectory = str(REPO_ROOT)
        shortcut.Description = "Claude Master — Synaptic Gateway & Desktop Shell"
        if icon_file.exists():
            shortcut.IconLocation = str(icon_file)
        shortcut.Save()

        logger.info("Created desktop shortcut at %s", shortcut_file)
        return shortcut_file
    except Exception as exc:
        logger.error("Failed to create desktop shortcut: %s", exc)
        return None
