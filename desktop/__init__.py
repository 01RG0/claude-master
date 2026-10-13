"""
desktop — Claude Master Windows native desktop shell and system tray integration.
"""

from desktop.icons import create_tray_icon_image, STATUS_COLORS
from desktop.status import get_current_status, SystemStatus
from desktop.window import open_webview_window, launch_window_process

__all__ = [
    "create_tray_icon_image",
    "STATUS_COLORS",
    "get_current_status",
    "SystemStatus",
    "open_webview_window",
    "launch_window_process",
]
