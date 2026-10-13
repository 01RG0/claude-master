"""
scripts/bench_desktop.py — Benchmark desktop shell startup latency, disk footprint, and RSS memory.
"""

import os
import sys
import time
import psutil

def detect_webview2_path() -> str | None:
    candidates = [
        r"C:\Windows\System32\Microsoft-Edge-WebView",
        r"C:\Program Files (x86)\Microsoft\EdgeWebView\Application\155.0.4283.45",
    ]
    for c in candidates:
        if os.path.exists(os.path.join(c, "msedgewebview2.exe")):
            return c
    return None

def benchmark_webview2():
    import webview
    rt_path = detect_webview2_path()
    if rt_path:
        webview.settings["WEBVIEW2_RUNTIME_PATH"] = rt_path

    proc = psutil.Process()
    rss_before = proc.memory_info().rss / (1024 * 1024)

    t_start = time.perf_counter()
    w = webview.create_window(
        "Claude Master Benchmark",
        html="<html><body style='background:#111;color:#eee'><h1>claude-master desktop benchmark</h1></body></html>",
        width=800,
        height=600
    )

    t_loaded = None
    total_rss = 0.0

    def on_loaded():
        nonlocal t_loaded, total_rss
        t_loaded = time.perf_counter()
        time.sleep(0.5)
        # Measure RSS of main python process and all child WebView2 processes
        children = proc.children(recursive=True)
        child_rss = sum(c.memory_info().rss for c in children if c.is_running()) / (1024 * 1024)
        main_rss = proc.memory_info().rss / (1024 * 1024)
        total_rss = main_rss + child_rss
        time.sleep(0.5)
        w.destroy()

    w.events.loaded += on_loaded
    webview.start()

    load_latency_ms = (t_loaded - t_start) * 1000 if t_loaded else 0.0
    print(f"WebView2 runtime path: {rt_path}")
    print(f"Base Python RSS (before window): {rss_before:.2f} MB")
    print(f"Cold startup to loaded: {load_latency_ms:.2f} ms")
    print(f"Total RSS with WebView2 renderer: {total_rss:.2f} MB")
    return load_latency_ms, total_rss

def benchmark_tray():
    t0 = time.perf_counter()
    import pystray
    from PIL import Image, ImageDraw
    t_import_ms = (time.perf_counter() - t0) * 1000

    t1 = time.perf_counter()
    img = Image.new("RGBA", (64, 64), color=(0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((4, 4, 60, 60), fill=(34, 197, 94))
    icon = pystray.Icon("claude_master_tray", img, "Claude Master Tray")
    t_icon_ms = (time.perf_counter() - t1) * 1000

    proc = psutil.Process()
    tray_rss = proc.memory_info().rss / (1024 * 1024)
    print(f"Tray import latency: {t_import_ms:.2f} ms")
    print(f"Tray icon render latency: {t_icon_ms:.2f} ms")
    print(f"Tray-only RSS: {tray_rss:.2f} MB")
    return t_import_ms + t_icon_ms, tray_rss

if __name__ == "__main__":
    print("=== Claude Master Desktop Shell Benchmark ===")
    t_tray, rss_tray = benchmark_tray()
    print("---")
    t_wv, rss_wv = benchmark_webview2()
    print("==============================================")
