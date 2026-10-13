"""brain/api/app.py — Unified FastAPI Backend Application for claude-master.

Features loopback binding, origin validation, random per-install token auth,
CSP headers, full /api endpoint coverage, and root compatibility endpoints.
"""

from __future__ import annotations

import logging
from typing import Any, Optional
from fastapi import FastAPI, Request, Response, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from brain.api.security import (
    is_loopback,
    is_valid_origin,
    verify_token,
    get_or_create_auth_token,
)
from brain.api.routes import (
    status as status_route,
    bypass as bypass_route,
    control as control_route,
    schema as schema_route,
    wizard as wizard_route,
    providers as providers_route,
    keys as keys_route,
    models as models_route,
    routing as routing_route,
    drex as drex_route,
    privacy as privacy_route,
    budgets as budgets_route,
    memory as memory_route,
    claude as claude_route,
    doctor as doctor_route,
    requests as requests_route,
    sessions as sessions_route,
    alerts as alerts_route,
    logs as logs_route,
    test_center as test_center_route,
    backup as backup_route,
    update as update_route,
    events as events_route,
)

logger = logging.getLogger("brain.api")


def create_app(brain_server: Optional[Any] = None) -> FastAPI:
    """Create and configure the unified FastAPI application."""
    app = FastAPI(
        title="claude-master Backend API",
        version="0.1.0",
        description="Unified, typed, versioned, documented backend serving CLI and Studio.",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # Attach brain_server to state
    app.state.brain_server = brain_server
    if brain_server and hasattr(brain_server, "store"):
        app.state.brain_db = brain_server.store

    # ------------------------------------------------------------------
    # Security Middleware: Loopback, Origin, CSP, Auth Token
    # ------------------------------------------------------------------
    @app.middleware("http")
    async def security_middleware(request: Request, call_next):
        # 1. Loopback Verification
        client_host = request.client.host if request.client else ""
        if not is_loopback(client_host):
            logger.warning("Rejected non-loopback request from %s", client_host)
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={"error": "Forbidden: claude-master is loopback-only (127.0.0.1)"},
            )

        # 2. Strict Origin Validation
        origin = request.headers.get("origin")
        if origin and not is_valid_origin(origin):
            logger.warning("Rejected invalid origin: %s", origin)
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={"error": f"Forbidden: Origin '{origin}' is not an authorized localhost origin"},
            )

        # 3. Auth Token Enforcement on /api/* (Exempt docs, openapi, /health, /hook, /sleep, /outcome)
        path = request.url.path
        if path.startswith("/api"):
            # Check Bearer or X-CM-Token header or query param for SSE
            auth_header = request.headers.get("authorization", "")
            token_candidate = None
            if auth_header.startswith("Bearer "):
                token_candidate = auth_header[len("Bearer "):].strip()
            if not token_candidate:
                token_candidate = request.headers.get("x-cm-token", "").strip()
            if not token_candidate:
                token_candidate = request.cookies.get("cm_token", "").strip()
            if not token_candidate:
                token_candidate = request.query_params.get("token", "").strip()

            if not verify_token(token_candidate):
                return JSONResponse(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    content={"error": "unauthorized", "message": "Valid session token required in Authorization: Bearer <token> or X-CM-Token header"},
                    headers={"WWW-Authenticate": "Bearer"},
                )

        response: Response = await call_next(request)

        # 4. Strict CSP and Security Headers
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "connect-src 'self' ws://127.0.0.1:* ws://localhost:* http://127.0.0.1:* http://localhost:*; "
            "frame-ancestors 'none';"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"

        if origin and is_valid_origin(origin):
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = "true"
            response.headers["Access-Control-Allow-Headers"] = "Authorization, X-CM-Token, Content-Type, Accept"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS, PATCH"

        return response

    # ------------------------------------------------------------------
    # Root Compatibility Endpoints (for hookshim, watchdog, and tests)
    # ------------------------------------------------------------------
    @app.get("/health", tags=["System"])
    def health_endpoint():
        bs = app.state.brain_server
        nodes = -1
        ep = -1
        sessions = 0
        hooks = 0
        db_path = "default"
        if bs:
            db_path = getattr(bs, "db_path", "default")
            hooks = getattr(bs, "hooks_handled", 0)
            sessions = len(getattr(bs, "_sessions", {}))
            try:
                nodes = bs.store.conn.execute("SELECT COUNT(*) AS c FROM brain_nodes").fetchone()["c"]
                ep = bs.store.conn.execute("SELECT COUNT(*) AS c FROM episodic_events").fetchone()["c"]
            except Exception:
                pass
        return {
            "status": "ok",
            "db": db_path,
            "nodes": nodes,
            "episodic_events": ep,
            "sessions": sessions,
            "hooks_handled": hooks,
        }

    @app.post("/hook", tags=["System"])
    async def hook_endpoint(request: Request):
        bs = app.state.brain_server
        if not bs:
            return {"allow": True, "additional_context": ""}
        payload = await request.json()
        return bs.handle_hook(payload)

    @app.post("/outcome", tags=["System"])
    async def outcome_endpoint(request: Request):
        bs = app.state.brain_server
        if bs:
            payload = await request.json()
            bs.record_outcome(
                payload.get("model_id", "unknown"),
                bool(payload.get("success", False)),
                float(payload.get("latency_ms", 0.0)),
            )
        return {"ok": True}

    @app.post("/sleep", tags=["System"])
    def sleep_endpoint():
        bs = app.state.brain_server
        if bs:
            return bs.run_sleep()
        return {"ok": True, "phase": "sleep_noop"}

    # ------------------------------------------------------------------
    # Mount all routers under both /api and /api/v1 for version compatibility
    # ------------------------------------------------------------------
    routers = [
        status_route.router,
        bypass_route.router,
        control_route.router,
        schema_route.router,
        wizard_route.router,
        providers_route.router,
        keys_route.router,
        models_route.router,
        routing_route.router,
        drex_route.router,
        privacy_route.router,
        budgets_route.router,
        memory_route.router,
        claude_route.router,
        doctor_route.router,
        requests_route.router,
        sessions_route.router,
        alerts_route.router,
        logs_route.router,
        test_center_route.router,
        backup_route.router,
        update_route.router,
        events_route.router,
    ]

    for r in routers:
        app.include_router(r, prefix="/api")
        app.include_router(r, prefix="/api/v1")

    # Mount APIHandlerRegistry fallback for complete 1:1 cm CLI parity
    try:
        from brain.api_handlers import APIHandlerRegistry
        registry = APIHandlerRegistry(brain_server)

        @app.api_route("/api/v1/{full_path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
        async def v1_api_handlers_fallback(full_path: str, request: Request):
            method = request.method
            path = f"/api/v1/{full_path}"
            query_params = dict(request.query_params)
            body = {}
            if method in ("POST", "PUT", "PATCH"):
                try:
                    body = await request.json()
                except Exception:
                    pass
            code, res = registry.match_and_handle(method, path, query_params, body)
            return JSONResponse(status_code=code, content=res)
    except Exception as exc:
        logger.warning("Could not mount api_handlers fallback: %s", exc)

    # Serve Studio UI static distribution if available
    from pathlib import Path
    from fastapi.responses import FileResponse
    repo_root = Path(__file__).resolve().parent.parent.parent
    studio_dist = (repo_root / "studio" / "dist").resolve()
    if studio_dist.is_dir():
        from fastapi.staticfiles import StaticFiles
        assets_dir = studio_dist / "assets"
        if assets_dir.is_dir():
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

        @app.get("/", include_in_schema=False)
        def serve_studio_index():
            resp = FileResponse(str(studio_dist / "index.html"))
            tok = get_or_create_auth_token()
            resp.set_cookie("cm_token", tok, httponly=False, samesite="strict")
            return resp

    return app
