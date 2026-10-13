"""
brain/guard/socket_server.py — hook IPC server (rewrite: dual transport).

Receives newline-terminated JSON hook payloads from hookshim, forwards them
to the brain HTTP API, and returns newline-terminated JSON responses.

Transports (Windows-first):
  - TCP loopback (default on Windows, always on): 127.0.0.1:7772
    No file paths, no AF_UNIX, no spaces/backslash issues, Defender-safe.
  - Unix domain socket (POSIX only, backward compat): tempdir/claude_brain.sock

The daemon listens on TCP always + Unix socket on POSIX. hookshim dials TCP
on Windows (or when CLAUDE_BRAIN_TCP is set) and Unix socket on POSIX.

Fail-safe: any network/JSON error returns {'allow': True, 'additional_context': ''}.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from typing import Any, Optional

try:
    import aiohttp
    _AIOHTTP_AVAILABLE = True
except ImportError:
    _AIOHTTP_AVAILABLE = False

logger = logging.getLogger(__name__)

# Default fail-safe response — always allow, no context
_FAILSAFE: dict[str, Any] = {"allow": True, "additional_context": ""}

# Read timeout for calls into the brain HTTP API (seconds)
_BRAIN_TIMEOUT = 0.1


class BrainSocketServer:
    """Async hook IPC server bridging hookshim → brain HTTP API.

    Listens on TCP loopback always, plus a Unix domain socket on POSIX.

    Usage::

        server = BrainSocketServer()  # TCP 127.0.0.1:7772 + Unix socket (POSIX)
        await server.start()
        ...
        await server.stop()
    """

    def __init__(
        self,
        socket_path: str | None = None,
        brain_api_url: str = "http://localhost:7700",
        tcp_addr: str | None = None,
        handle_hook: Any | None = None,
    ) -> None:
        """If *handle_hook* is given, hook payloads are evaluated in-process
        (no extra HTTP hop). Otherwise they are POSTed to *brain_api_url*."""
        if socket_path is None and sys.platform != "win32":
            try:
                from brain.paths import default_socket_path

                socket_path = default_socket_path()
            except Exception:
                socket_path = os.path.join(os.path.expanduser("~"), "claude_brain.sock")
        # On Windows the default is TCP-only (socket_path stays None unless set).
        if tcp_addr is None:
            try:
                from brain.paths import default_tcp_addr

                tcp_addr = default_tcp_addr()
            except Exception:
                tcp_addr = "127.0.0.1:7772"
        self.socket_path = socket_path
        self.tcp_addr = tcp_addr
        self.brain_api_url = brain_api_url.rstrip("/")
        self._handle_hook = handle_hook
        self._servers: list[asyncio.AbstractServer] = []

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start TCP (always) + Unix socket (POSIX only) listeners."""
        self._servers = []
        # 1. TCP loopback — primary transport, works everywhere.
        host, port = self._split_tcp(self.tcp_addr or "127.0.0.1:7772")
        tcp_server = await asyncio.start_server(self._handle_client, host, port)
        self._servers.append(tcp_server)
        logger.info("BrainSocketServer listening on TCP %s:%d", host, port)
        # 2. Unix domain socket — POSIX backward compat only.
        if self.socket_path and sys.platform != "win32":
            parent = os.path.dirname(os.path.abspath(self.socket_path))
            if parent and not os.path.exists(parent):
                os.makedirs(parent, exist_ok=True)
            if os.path.exists(self.socket_path):
                try:
                    os.unlink(self.socket_path)
                except OSError:
                    pass
            try:
                unix_server = await asyncio.start_unix_server(
                    self._handle_client, path=self.socket_path
                )
                self._servers.append(unix_server)
                logger.info("BrainSocketServer listening on %s", self.socket_path)
            except OSError as exc:
                logger.warning("Unix socket unavailable (%s); TCP-only mode", exc)
        # Block forever serving all listeners (stop() closes them to unblock).
        await asyncio.gather(*(srv.serve_forever() for srv in self._servers))

    async def stop(self) -> None:
        """Gracefully stop all listeners."""
        for srv in self._servers:
            try:
                srv.close()
                await srv.wait_closed()
            except Exception:
                pass
        self._servers = []
        if self.socket_path and sys.platform != "win32" and os.path.exists(self.socket_path):
            try:
                os.unlink(self.socket_path)
            except OSError:
                pass
        logger.info("BrainSocketServer stopped")

    @staticmethod
    def _split_tcp(addr: str) -> tuple[str, int]:
        try:
            from brain.paths import split_tcp

            return split_tcp(addr)
        except Exception:
            return "127.0.0.1", 7772

    # ------------------------------------------------------------------
    # Connection handler
    # ------------------------------------------------------------------

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Read a newline-terminated JSON payload, call brain API, write JSON response."""
        try:
            raw = await asyncio.wait_for(reader.readline(), timeout=5.0)
        except (asyncio.TimeoutError, ConnectionResetError):
            await self._send_response(writer, _FAILSAFE)
            return

        # Parse JSON defensively
        try:
            payload: dict = json.loads(raw.decode("utf-8", errors="replace"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            logger.warning("BrainSocketServer: malformed JSON from hookshim — using failsafe")
            await self._send_response(writer, _FAILSAFE)
            return

        # Forward to brain API (in-process fast path preferred)
        if self._handle_hook is not None:
            try:
                response = await asyncio.get_running_loop().run_in_executor(
                    None, self._handle_hook, payload
                )
                if isinstance(response, dict):
                    await self._send_response(writer, response)
                    return
            except Exception:
                pass
            await self._send_response(writer, _FAILSAFE)
            return
        response = await self._call_brain(payload)
        await self._send_response(writer, response)

    # ------------------------------------------------------------------
    # Brain HTTP call
    # ------------------------------------------------------------------

    async def _call_brain(self, payload: dict) -> dict:
        """POST payload to /hook on the brain HTTP API.

        Returns _FAILSAFE on any error (timeout, connection refused, bad JSON).
        """
        url = f"{self.brain_api_url}/hook"

        if not _AIOHTTP_AVAILABLE:
            # Fallback: use asyncio streams for a basic HTTP POST (no aiohttp)
            return await self._call_brain_raw(payload)

        try:
            timeout = aiohttp.ClientTimeout(total=_BRAIN_TIMEOUT)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, json=payload) as resp:
                    data = await resp.json(content_type=None)
                    return data if isinstance(data, dict) else _FAILSAFE
        except Exception as exc:
            logger.debug("Brain API call failed (%s): %s", type(exc).__name__, exc)
            return _FAILSAFE

    async def _call_brain_raw(self, payload: dict) -> dict:
        """Minimal HTTP POST without aiohttp (stdlib only)."""
        import urllib.parse

        parsed = urllib.parse.urlparse(self.brain_api_url)
        host = parsed.hostname or "localhost"
        port = parsed.port or 7700
        body = json.dumps(payload).encode()
        request = (
            f"POST /hook HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\n"
            f"Connection: close\r\n"
            f"\r\n"
        ).encode() + body

        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=_BRAIN_TIMEOUT
            )
            writer.write(request)
            await writer.drain()
            chunks: list[bytes] = []
            while True:
                try:
                    part = await asyncio.wait_for(reader.read(65536), timeout=_BRAIN_TIMEOUT)
                except asyncio.TimeoutError:
                    break
                if not part:
                    break
                chunks.append(part)
            raw_response = b"".join(chunks)
            writer.close()

            # Naive HTTP response parse: find double CRLF, parse JSON body
            header_end = raw_response.find(b"\r\n\r\n")
            if header_end == -1:
                return _FAILSAFE
            json_body = raw_response[header_end + 4:]
            data = json.loads(json_body.decode("utf-8", errors="replace"))
            return data if isinstance(data, dict) else _FAILSAFE
        except Exception as exc:
            logger.debug("Brain raw HTTP call failed (%s): %s", type(exc).__name__, exc)
            return _FAILSAFE

    # ------------------------------------------------------------------
    # Helper
    # ------------------------------------------------------------------

    @staticmethod
    async def _send_response(writer: asyncio.StreamWriter, response: dict) -> None:
        try:
            writer.write(json.dumps(response).encode("utf-8") + b"\n")
            await writer.drain()
        except Exception:
            pass
        finally:
            try:
                writer.close()
            except Exception:
                pass
