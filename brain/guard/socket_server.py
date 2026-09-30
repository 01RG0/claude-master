"""
brain/guard/socket_server.py
Unix domain socket server: receives JSON hook payloads from hookshim,
forwards them to the brain HTTP API, and returns JSON responses.

Fail-safe: any network/JSON error returns {'allow': True, 'additional_context': ''}.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
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
    """Async Unix domain socket server that bridges hookshim → brain HTTP API.

    Usage::

        server = BrainSocketServer()
        await server.start()
        ...
        await server.stop()
    """

    def __init__(
        self,
        socket_path: str = "/tmp/claude_brain.sock",
        brain_api_url: str = "http://localhost:7700",
    ) -> None:
        self.socket_path = socket_path
        self.brain_api_url = brain_api_url.rstrip("/")
        self._server: Optional[asyncio.AbstractServer] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Create the Unix domain socket and start listening."""
        # Remove stale socket file if it exists
        if os.path.exists(self.socket_path):
            os.unlink(self.socket_path)

        self._server = await asyncio.start_unix_server(
            self._handle_client,
            path=self.socket_path,
        )
        logger.info("BrainSocketServer listening on %s", self.socket_path)
        async with self._server:
            await self._server.serve_forever()

    async def stop(self) -> None:
        """Gracefully stop the server."""
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        if os.path.exists(self.socket_path):
            try:
                os.unlink(self.socket_path)
            except OSError:
                pass
        logger.info("BrainSocketServer stopped")

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

        # Forward to brain API
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
            raw_response = await asyncio.wait_for(reader.read(65536), timeout=_BRAIN_TIMEOUT)
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
