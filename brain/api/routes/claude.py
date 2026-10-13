"""brain/api/routes/claude.py — Claude Code integration, gateway routing configuration, undo, and verification.
"""

from __future__ import annotations

from fastapi import APIRouter
from brain.api.models import ClaudeStatusResponse, ClaudeConfigureRequest
from brain.api.services.claude_service import (
    get_claude_status,
    apply_gateway_routing,
    restore_claude_config,
)

router = APIRouter(prefix="/claude", tags=["Claude"])


@router.get("", response_model=ClaudeStatusResponse)
def get_claude_status_endpoint():
    return get_claude_status()


@router.post("/configure")
def configure_claude_endpoint(req: ClaudeConfigureRequest):
    if req.action == "route_to_gateway":
        ok = apply_gateway_routing()
        return {"ok": ok, "message": "Claude Code configured to route via claude-master gateway (http://127.0.0.1:8080)"}
    elif req.action == "restore_original":
        ok = restore_claude_config()
        return {"ok": ok, "message": "Claude Code configuration restored to original settings"}
    return {"ok": False, "message": "Unknown action"}


@router.post("/undo")
def undo_claude_endpoint():
    ok = restore_claude_config()
    return {"ok": ok, "message": "Claude Code configuration restored to backup"}


@router.post("/verify")
def verify_claude_endpoint():
    status = get_claude_status()
    return {
        "ok": status.installed,
        "is_routed": status.is_routed_to_gateway,
        "message": "Gateway routing active and verified" if status.is_routed_to_gateway else "Claude Code is not currently pointing to gateway",
    }
