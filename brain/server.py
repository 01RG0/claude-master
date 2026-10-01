"""
brain/server.py — brain daemon entrypoint.

Exposes a small HTTP API consumed by hookshim (via socket_server) and the
studio viewer (via WebSocket). The learning/guard/reflect/sleep modules are
wired in here; the SQLite store is the single source of truth.

Usage:
    python -m brain.server --db /tmp/claude_brain.db --socket /tmp/claude_brain.sock
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import signal
import sys
import threading
from collections import deque
from typing import Any

from brain.store.graph import GraphStore
from brain.guard.stuck_detector import StuckDetector, StuckResult
from brain.guard.context_builder import ContextBuilder
from brain.learning.hebbian import HebbianUpdater
from brain.learning.spreading import SpreadingActivation
from brain.reflect.reflexion import ReflexionHarness
from brain.reflect.skill_store import SkillStore
from brain.reflect.distiller import LessonDistiller
from brain.sleep.consolidator import SleepConsolidator
from brain.judge.client import DrexClient
from brain.judge.gating import GatingPolicy

logger = logging.getLogger("brain.server")


class BrainServer:
    """HTTP brain daemon wiring store + learning + guard + reflect + sleep."""

    def __init__(self, db_path: str, socket_path: str | None = None,
                 http_host: str = "127.0.0.1", http_port: int = 7700) -> None:
        self.db_path = db_path
        self.socket_path = socket_path
        self.http_host = http_host
        self.http_port = http_port
        self.store = GraphStore(db_path)
        self.stuck = StuckDetector()
        self.context = ContextBuilder()
        self.hebbian = HebbianUpdater()
        self.spreading = SpreadingActivation()
        self.reflexion = ReflexionHarness()
        self.skills = SkillStore(self.store)
        self.distiller = LessonDistiller(self.store)
        self.sleep = SleepConsolidator(self.store)
        self.drex = DrexClient()
        self.gating = GatingPolicy(self.drex)
        # Per-session event windows for stuck detection
        self._sessions: dict[str, deque[dict]] = {}

    # ------------------------------------------------------------------
    # Hook endpoint (called by socket_server)
    # ------------------------------------------------------------------

    def handle_hook(self, payload: dict) -> dict[str, Any]:
        """Evaluate a hook payload: stuck-check, gate, build context."""
        tool = payload.get("tool_name", "") or ""
        raw_input = payload.get("input")
        command = ""
        if isinstance(raw_input, dict):
            command = str(raw_input.get("command", "") or "")
        event = payload.get("hook_event_name", "PreToolUse")
        session_id = str(payload.get("session_id", "default"))

        # 1. Record event into the session window and check for stuck patterns
        evt = {
            "type": "action" if event == "PreToolUse" else "observation",
            "tool_name": tool,
            "command": command,
        }
        window = self._sessions.setdefault(session_id, deque(maxlen=20))
        window.append(evt)
        stuck: StuckResult = self.stuck.check() if False else self._check_window(window)

        if stuck.is_stuck:
            return {
                "allow": False,
                "block_reason": f"loop detected: {stuck.pattern}",
                "additional_context": stuck.nudge or "",
            }

        # 2. Drex gating for risky command classes
        gate = self.gating.gate(command_summary=command, tool_name=tool)
        if not gate.allow:
            return {
                "allow": False,
                "block_reason": gate.reason or "blocked by judge",
                "additional_context": "",
            }

        # 3. Inject working-memory context
        ctx = self._build_context(command)
        return {
            "allow": True,
            "block_reason": "",
            "additional_context": ctx,
        }

    def _check_window(self, window: deque[dict]) -> StuckResult:
        """Run the stuck detector over a session window."""
        # Mirror the window into the detector's internal deque
        detector = StuckDetector()
        detector._events = window
        detector._iteration = len(window)
        return detector.check()

    def _build_context(self, command: str) -> str:
        """Retrieve relevant lessons and format them as prompt context."""
        try:
            rows = self.store.conn.execute(
                "SELECT content FROM brain_nodes WHERE tags LIKE ? LIMIT 5",
                ("%lesson%",),
            ).fetchall()
            lessons = [r["content"] for r in rows if r["content"]]
        except Exception:
            lessons = []
        return self.context.build(
            activated_nodes={},
            lessons=lessons,
            reflections=list(self.reflexion.episodic_buffer[-3:]),
        )

    def record_outcome(self, model_id: str, success: bool, latency_ms: float) -> None:
        """Report a task outcome to the learning system."""
        self.hebbian.update(
            self.store,
            source_id=f"model:{model_id}",
            target_id="task:outcome",
            pre_activation=1.0,
            post_activation=1.0,
            reward=1.0 if success else -1.0,
        )

    def run_sleep(self) -> dict[str, Any]:
        """Run the nightly consolidation job."""
        return self.sleep.run()


def build_app(server: BrainServer):
    """Build a stdlib HTTP request handler bound to *server*."""
    from http.server import BaseHTTPRequestHandler

    class Handler(BaseHTTPRequestHandler):
        def _json(self, data: Any, status: int = 200) -> None:
            body = json.dumps(data).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b"{}"
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                self._json({"error": "bad json"}, 400)
                return

            if self.path == "/hook":
                self._json(server.handle_hook(payload))
            elif self.path == "/outcome":
                server.record_outcome(
                    payload.get("model_id", "unknown"),
                    bool(payload.get("success", False)),
                    float(payload.get("latency_ms", 0.0)),
                )
                self._json({"ok": True})
            elif self.path == "/sleep":
                self._json(server.run_sleep())
            else:
                self._json({"error": "not found"}, 404)

        def do_GET(self):
            if self.path == "/health":
                try:
                    n = server.store.conn.execute(
                        "SELECT COUNT(*) AS c FROM brain_nodes"
                    ).fetchone()["c"]
                except Exception:
                    n = -1
                self._json({"status": "ok", "db": server.db_path, "nodes": n})
            else:
                self._json({"error": "not found"}, 404)

        def log_message(self, fmt, *args):
            logger.debug("HTTP %s", fmt % args)

    return Handler


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="claude-master brain daemon")
    parser.add_argument("--db", default="/tmp/claude_brain.db")
    parser.add_argument("--socket", default="/tmp/claude_brain.sock")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7700)
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    server = BrainServer(args.db, args.socket, args.host, args.port)
    logger.info("Brain daemon starting on %s:%d", args.host, args.port)

    # Start Unix socket server in background thread with its own event loop
    from brain.guard.socket_server import BrainSocketServer
    import threading

    socket_server = BrainSocketServer(
        socket_path=args.socket,
        brain_api_url=f"http://{args.host}:{args.port}",
    )

    def _run_socket():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(socket_server.start())
        except Exception as exc:
            logger.error("Socket server error: %s", exc)

    t = threading.Thread(target=_run_socket, daemon=True)
    t.start()

    # HTTP server
    from http.server import HTTPServer
    httpd = HTTPServer((args.host, args.port), build_app(server))
    logger.info("HTTP API listening on http://%s:%d", args.host, args.port)

    def shutdown(*_):
        logger.info("Shutting down...")
        def _do_shutdown():
            try:
                loop = asyncio.new_event_loop()
                loop.run_until_complete(socket_server.stop())
                loop.close()
            except Exception:
                pass
            httpd.shutdown()
        threading.Thread(target=_do_shutdown, daemon=True).start()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.store.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())