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
from brain.paths import default_db_path, default_socket_path, default_tcp_addr
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
        # Guard Drex budget: 1.0s covers measured p99 (783ms, 2026-10-13);
        # down/black-hole fails open without blocking the agent for 60s.
        # NOTE: gate itself is rule-only (use_drex=False): 2026-10-13 eval on
        # 40 labeled commands scored Drex 0.60 vs rules 0.70 — Drex stays
        # enabled for judge/route/store/sleep, disabled for guard blocking.
        self.drex = DrexClient(timeout_s=1.0, max_retries=0)
        self.gating = GatingPolicy(self.drex, use_drex=False)
        # Per-session event windows for stuck detection
        self._sessions: dict[str, deque[dict]] = {}
        self.hooks_handled = 0
        from brain.api_handlers import APIHandlerRegistry
        self.api_registry = APIHandlerRegistry(self)
        self.bypass_mode = False

    # ------------------------------------------------------------------
    # Hook endpoint (called by socket_server)
    # ------------------------------------------------------------------

    def handle_hook(self, payload: dict) -> dict[str, Any]:
        """Evaluate a hook payload: stuck-check, gate, build context."""
        tool_val = payload.get("tool_name", "")
        tool = tool_val if isinstance(tool_val, str) else ""
        raw_input = payload.get("tool_input", payload.get("input"))
        command = ""
        if isinstance(raw_input, dict):
            cmd_val = raw_input.get("command", "")
            # Non-string commands fail safe as "": never str() a list/dict into
            # a risky-looking repr (e.g. "['rm -rf /']" must not match rm -rf).
            command = cmd_val if isinstance(cmd_val, str) else ""
        event = payload.get("hook_event_name", "PreToolUse")
        session_id = str(payload.get("session_id", "default"))

        if getattr(self, "bypass_mode", False):
            return {"allow": True, "block_reason": "", "additional_context": ""}

        # 1. Record event into the session window and check for stuck patterns
        evt = {
            "type": "action" if event == "PreToolUse" else "observation",
            "tool_name": tool,
            "command": command,
        }
        window = self._sessions.setdefault(session_id, deque(maxlen=20))
        window.append(evt)
        self.hooks_handled += 1
        stuck: StuckResult = self._check_window(window)

        if stuck.is_stuck:
            return {
                "allow": False,
                "block_reason": f"loop detected: {stuck.pattern}",
                "additional_context": stuck.nudge or "",
            }

        # 2. Drex gating for risky command classes
        gate = self.gating.gate(command_summary=command, tool_name=tool)
        if not gate.allow:
            self._remember(session_id, event, tool, command, None)
            return {
                "allow": False,
                "block_reason": gate.reason or "blocked by judge",
                "additional_context": "",
            }

        # 3. Inject working-memory context
        ctx = self._build_context(command)
        self._remember(session_id, event, tool, command, ctx)
        return {
            "allow": True,
            "block_reason": "",
            "additional_context": ctx,
        }

    def _remember(
        self,
        session_id: str,
        event: str,
        tool: str,
        command: str,
        ctx: str | None,
    ) -> None:
        """Persist one episodic row + touch the tool node (best effort).

        Every hook — Pre and Post — leaves a trace: the brain provably learns
        from every action. Failures here must never break the hook path.
        """
        try:
            import time as _time

            now = int(_time.time() * 1000)
            etype = "pre_tool" if event == "PreToolUse" else (
                "post_tool" if event == "PostToolUse" else "hook")
            payload = json.dumps({"tool": tool, "command": (command or "")[:500],
                                  "context_chars": len(ctx or "")})
            self.store.conn.execute(
                "INSERT INTO episodic_events (session_id, event_type, tool_name, "
                "action_payload, outcome_reward, created_at) "
                "VALUES (?, ?, ?, ?, NULL, ?)",
                (session_id, etype, tool or "", payload, now),
            )
            if tool:
                self.store.upsert_node(f"tool:{tool}", "concept", tool, "")
            self.store.conn.commit()
        except Exception:
            pass

    def _check_window(self, window: deque[dict]) -> StuckResult:
        """Run the stuck detector over a session window."""
        # Mirror the window into the detector's internal deque
        detector = StuckDetector()
        detector._events = window
        detector._iteration = len(window)
        return detector.check()

    def _build_context(self, command: str) -> str:
        """Retrieve relevant lessons and format them as prompt context."""
        lessons: list[str] = []
        try:
            # Prefer the lessons table (and its FTS index) over brain_nodes tags.
            rows = self.store.conn.execute(
                "SELECT rule_text FROM lessons ORDER BY confidence DESC LIMIT 5"
            ).fetchall()
            lessons = [r["rule_text"] for r in rows if r["rule_text"]]
            if command:
                try:
                    fts = self.store.conn.execute(
                        "SELECT rule_text FROM lessons_fts WHERE lessons_fts MATCH ? LIMIT 5",
                        (command,),
                    ).fetchall()
                    for r in fts:
                        if r["rule_text"] and r["rule_text"] not in lessons:
                            lessons.append(r["rule_text"])
                except Exception:
                    pass
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
        try:
            import time as _time

            now = int(_time.time() * 1000)
            row = self.store.conn.execute(
                "SELECT successes, failures, total_latency_ms FROM model_stats WHERE model_id = ?",
                (model_id,),
            ).fetchone()
            if row:
                self.store.conn.execute(
                    "UPDATE model_stats SET successes = successes + ?, failures = failures + ?, "
                    "total_latency_ms = total_latency_ms + ?, last_used_at = ?, updated_at = ? "
                    "WHERE model_id = ?",
                    (1 if success else 0, 0 if success else 1, float(latency_ms or 0.0),
                     now, now, model_id),
                )
            else:
                self.store.conn.execute(
                    "INSERT INTO model_stats (model_id, provider, successes, failures, "
                    "total_latency_ms, total_tokens, last_used_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, 0, ?, ?)",
                    (model_id, model_id.split("/")[0] if "/" in model_id else "unknown",
                     1 if success else 0, 0 if success else 1,
                     float(latency_ms or 0.0), now, now),
                )
            self.store.conn.commit()
        except Exception:
            pass

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
                    ep = server.store.conn.execute(
                        "SELECT COUNT(*) AS c FROM episodic_events"
                    ).fetchone()["c"]
                except Exception:
                    n = -1
                    ep = -1
                self._json({"status": "ok", "db": server.db_path, "nodes": n,
                            "episodic_events": ep, "sessions": len(server._sessions),
                            "hooks_handled": server.hooks_handled})
            else:
                self._json({"error": "not found"}, 404)

        def log_message(self, fmt, *args):
            logger.debug("HTTP %s", fmt % args)

    return Handler


def main(argv: list[str] | None = None) -> int:
    import sys as _sys

    parser = argparse.ArgumentParser(description="claude-master brain daemon")
    parser.add_argument("--db", default=default_db_path())
    parser.add_argument("--socket", default=(None if _sys.platform == "win32" else default_socket_path()),
                        help="Unix socket path (POSIX only; ignored on Windows)")
    parser.add_argument("--tcp", default=default_tcp_addr(),
                        help="Hook IPC TCP address host:port (default 127.0.0.1:7772)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7700)
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    server = BrainServer(args.db, args.socket, args.host, args.port)
    logger.info("Brain daemon starting on %s:%d", args.host, args.port)

    # Start hook IPC server (TCP always + Unix socket on POSIX) in background
    from brain.guard.socket_server import BrainSocketServer
    import threading

    socket_server = BrainSocketServer(
        socket_path=args.socket,
        tcp_addr=args.tcp,
        brain_api_url=f"http://{args.host}:{args.port}",
        handle_hook=server.handle_hook,  # in-process: skip the HTTP hop
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

    # Prefer FastAPI admin API when the concurrent brain/api layer imports;
    # fall back to the stdlib health/hook app so e2e never hard-depends on WIP.
    use_uvicorn = False
    try:
        from brain.api.app import create_app
        import uvicorn  # noqa: F401
        app = create_app(server)
        use_uvicorn = True
    except Exception as exc:
        logger.warning("FastAPI admin API unavailable (%s); using stdlib HTTP", exc)

    logger.info("HTTP API listening on http://%s:%d", args.host, args.port)
    try:
        if use_uvicorn:
            import uvicorn
            uvicorn.run(app, host=args.host, port=args.port, log_level="info")
        else:
            from http.server import HTTPServer
            httpd = HTTPServer((args.host, args.port), build_app(server))

            def shutdown(*_):
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
            try:
                signal.signal(signal.SIGTERM, shutdown)
            except (AttributeError, ValueError, OSError):
                pass
            try:
                httpd.serve_forever()
            except KeyboardInterrupt:
                pass
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        try:
            loop = asyncio.new_event_loop()
            loop.run_until_complete(socket_server.stop())
            loop.close()
        except Exception:
            pass
        try:
            server.store.close()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())