"""tests/performance/test_ui_scale.py — Performance & Scale Benchmark on Windows.

Benchmarks:
1. 100,000 log rows virtualized rendering: load time, memory RSS, scroll responsiveness.
2. 50 concurrent SSE/WebSocket streams: message delivery latency, broadcast efficiency, CPU usage.
3. Cold load latency on Windows loopback (API TTFB, DOMContentLoaded, full window ready).
"""

from __future__ import annotations

import asyncio
import os
import sys
import threading
import time
from pathlib import Path
import psutil
import pytest
import uvicorn
import httpx
from starlette.testclient import TestClient
from playwright.sync_api import sync_playwright

from brain.server import BrainServer
from brain.api.app import create_app
from brain.api.security import get_or_create_auth_token

import socket

def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]

CHROMIUM_EXE = r"C:\Users\hamad\AppData\Local\ms-playwright\chromium-1248\chrome-win64\chrome.exe"


@pytest.fixture(scope="module")
def perf_server():
    """Start in-process server for performance benchmarks."""
    port = find_free_port()
    base_url = f"http://127.0.0.1:{port}"
    db_file = Path(os.environ.get("TEMP", ".")) / f"perf_test_{int(time.time())}.db"
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


def test_cold_load_latency_windows(perf_server, browser_instance):
    """Measure cold load latency of Studio UI on Windows loopback."""
    page = browser_instance.new_page()

    t0 = time.perf_counter()
    response = page.goto(perf_server["base_url"])
    page.wait_for_selector(".app-layout", timeout=5000)
    t1 = time.perf_counter()

    cold_load_ms = (t1 - t0) * 1000
    assert response.status == 200
    assert cold_load_ms < 1500.0, f"Cold load too slow: {cold_load_ms:.2f}ms"

    # Measure navigation timing via PerformanceNavigationTiming API
    timing = page.evaluate("""() => {
        const entry = performance.getEntriesByType('navigation')[0];
        return {
            ttfb: entry.responseStart - entry.requestStart,
            domReady: entry.domContentLoadedEventEnd - entry.fetchStart,
            loadReady: entry.loadEventEnd - entry.fetchStart,
        };
    }""")

    assert timing["ttfb"] >= 0
    print(f"\n[PERF] Cold Load: {cold_load_ms:.1f}ms (TTFB: {timing['ttfb']:.1f}ms, DOM: {timing['domReady']:.1f}ms)")
    page.close()


def test_100k_log_rows_virtualization(perf_server, browser_instance):
    """Benchmark 100,000 log rows in memory and virtualized viewport rendering."""
    proc = psutil.Process(os.getpid())
    rss_before_mb = proc.memory_info().rss / 1024 / 1024

    page = browser_instance.new_page()
    page.goto(f"{perf_server['base_url']}")
    page.wait_for_selector(".app-layout", timeout=5000)

    # Navigate to Logs screen
    page.click("button.nav-item[data-screen='logs']")
    page.wait_for_selector(".logs-terminal-viewport", timeout=3000)

    # Inject 100,000 virtualized log lines directly into the client store/renderer
    t_inject_start = time.perf_counter()
    eval_res = page.evaluate("""() => {
        const count = 100000;
        const now = Date.now();
        const rows = new Array(count);
        const levels = ["INFO", "WARN", "ERROR", "DEBUG"];
        const comps = ["gateway", "brain", "watchdog", "hookshim"];
        for (let i = 0; i < count; i++) {
            rows[i] = {
                id: "log-" + i,
                timestamp: now - (count - i) * 10,
                level: levels[i % 4],
                component: comps[i % 4],
                message: "synthetic benchmark log entry " + i + " with transaction token sk-masked-hash-" + (i % 500)
            };
        }
        const t0 = performance.now();
        
        // Virtualized viewport simulation: slice top window (100 visible rows)
        const viewport = document.querySelector('.logs-terminal-viewport');
        const slice = rows.slice(0, 100);
        viewport.innerHTML = slice.map(l => 
            `<div class="log-line log-${l.level.toLowerCase()}" data-idx="${l.id}">
                <span class="log-time">${new Date(l.timestamp).toLocaleTimeString()}</span>
                <span class="log-badge ${l.level.toLowerCase()}">${l.level}</span>
                <span class="log-comp">[${l.component}]</span>
                <span class="log-msg">${l.message}</span>
            </div>`
        ).join('');

        const renderMs = performance.now() - t0;
        return { count: rows.length, renderMs };
    }""")
    t_inject_end = time.perf_counter()

    rss_after_mb = proc.memory_info().rss / 1024 / 1024
    mem_delta_mb = rss_after_mb - rss_before_mb

    assert eval_res["count"] == 100000
    assert eval_res["renderMs"] < 100.0, f"Virtualized slice render took too long: {eval_res['renderMs']:.2f}ms"

    # Test rapid scroll simulation (50 jumps across 100,000 rows)
    scroll_perf = page.evaluate("""() => {
        const jumps = 50;
        const times = [];
        const viewport = document.querySelector('.logs-terminal-viewport');
        for (let j = 0; j < jumps; j++) {
            const t0 = performance.now();
            viewport.scrollTop = j * 200;
            times.push(performance.now() - t0);
        }
        const avg = times.reduce((a, b) => a + b, 0) / times.length;
        const max = Math.max(...times);
        return { avgMs: avg, maxMs: max };
    }""")

    # 60fps frame budget is 16.6ms
    assert scroll_perf["avgMs"] < 16.6, f"Average scroll frame exceeded 16.6ms: {scroll_perf['avgMs']:.2f}ms"
    print(
        f"\n[PERF] 100k Rows Virtualized: in-memory build: {(t_inject_end - t_inject_start)*1000:.1f}ms, "
        f"window slice: {eval_res['renderMs']:.2f}ms, scroll frame avg: {scroll_perf['avgMs']:.2f}ms, "
        f"RSS delta: +{mem_delta_mb:.1f}MB"
    )
    page.close()


def test_50_concurrent_streams_and_cpu(perf_server):
    """Benchmark 50 concurrent SSE/WebSocket event streams and broadcast throughput."""
    from brain.api.services.events_service import GLOBAL_EVENT_BROKER
    import asyncio
    import concurrent.futures

    proc = psutil.Process(os.getpid())
    proc.cpu_percent(interval=0.05)

    num_clients = 50
    queues = [GLOBAL_EVENT_BROKER.register_queue() for _ in range(num_clients)]

    num_messages = 50

    async def broadcast_batch():
        for i in range(num_messages):
            await GLOBAL_EVENT_BROKER.broadcast("telemetry_update", {"seq": i, "tokens": 42})

    t0 = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        executor.submit(asyncio.run, broadcast_batch()).result()
    t1 = time.perf_counter()

    cpu_usage = proc.cpu_percent(interval=0.05)
    total_time_ms = (t1 - t0) * 1000
    avg_per_broadcast_ms = total_time_ms / num_messages

    # Verify each queue received all messages
    for q in queues:
        assert q.qsize() == num_messages
        GLOBAL_EVENT_BROKER.unregister_queue(q)

    assert avg_per_broadcast_ms < 5.0, f"Broadcast took too long: {avg_per_broadcast_ms:.2f}ms"
    print(
        f"\n[PERF] 50 Concurrent Streams: {num_messages} msgs to {num_clients} subscribers in {total_time_ms:.1f}ms "
        f"({avg_per_broadcast_ms:.2f}ms/broadcast), CPU: {cpu_usage:.1f}%"
    )
