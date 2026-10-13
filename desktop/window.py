"""
desktop/window.py — Native Windows desktop window powered by Microsoft Edge WebView2.

Embeds http://127.0.0.1:7700 (or custom URL) with native window controls,
resizable bounds, and seamless Windows 10/11 Evergreen WebView2 integration.
"""

from __future__ import annotations
import argparse
import os
import sys
import logging
from pathlib import Path

logger = logging.getLogger("desktop.window")


def detect_webview2_runtime() -> str | None:
    """Find installed WebView2 runtime path on native Windows."""
    candidates = [
        r"C:\Windows\System32\Microsoft-Edge-WebView",
        r"C:\Program Files (x86)\Microsoft\EdgeWebView\Application\155.0.4283.45",
    ]
    base_dir = r"C:\Program Files (x86)\Microsoft\EdgeWebView\Application"
    if os.path.exists(base_dir):
        try:
            for name in os.listdir(base_dir):
                full = os.path.join(base_dir, name)
                if os.path.isdir(full) and os.path.exists(os.path.join(full, "msedgewebview2.exe")):
                    candidates.append(full)
        except Exception:
            pass

    for c in candidates:
        if os.path.exists(os.path.join(c, "msedgewebview2.exe")):
            return c
    return None


def open_webview_window(url: str = "http://127.0.0.1:7700", title: str = "Claude Master — Synaptic Studio") -> None:
    """Initialize and run the native WebView2 desktop window."""
    import webview

    rt_path = detect_webview2_runtime()
    if rt_path:
        webview.settings["WEBVIEW2_RUNTIME_PATH"] = rt_path

    # Window configuration
    window = webview.create_window(
        title=title,
        url=url,
        width=1280,
        height=850,
        min_size=(900, 600),
        background_color="#09090b",
        text_select=True,
    )

    webview.start(debug=False)


def launch_window_process(url: str = "http://127.0.0.1:7700") -> None:
    """Spawn the WebView2 desktop window as a detached process."""
    import subprocess
    cmd = [sys.executable, "-m", "desktop.window", "--url", url]
    subprocess.Popen(
        cmd,
        cwd=str(Path(__file__).resolve().parent.parent),
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Claude Master Desktop WebView2 Window")
    parser.add_argument("--url", default="http://127.0.0.1:7700", help="URL to display")
    parser.add_argument("--title", default="Claude Master — Synaptic Studio", help="Window title")
    args = parser.parse_args()

    open_webview_window(url=args.url, title=args.title)


if __name__ == "__main__":
    main()
