"""brain/api/services/privacy_service.py — Data rules, secret & PII redaction, and path guard policies.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
import sqlite3

from brain.api.database import get_setting, set_setting, log_audit_event
from brain.api.models import (
    PrivacyConfigResponse,
    PrivacyUpdateRequest,
    PrivacyPreviewResponse,
)
from brain.api.services.config_service import read_gateway_config, save_gateway_config


DEFAULT_SECRET_PATTERNS = [
    r"sk-[a-zA-Z0-9_\-]{20,}",
    r"Bearer\s+[a-zA-Z0-9_\-\.]{20,}",
    r"ghp_[a-zA-Z0-9]{36}",
    r"(?i)api[_-]?key\s*[:=]\s*['\"]?([a-zA-Z0-9_\-]{16,})['\"]?",
    r"(?i)token\s*[:=]\s*['\"]?([a-zA-Z0-9_\-]{20,})['\"]?",
]

DEFAULT_PII_PATTERNS = [
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",  # Email
    r"\b\d{3}-\d{2}-\d{4}\b",                                 # SSN
    r"\b(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b",  # Phone
]

DEFAULT_GUARD_PATHS = [
    ".env",
    ".env.*",
    "id_rsa",
    "id_ed25519",
    "*.pem",
    "*.key",
    ".cm_token",
    "keys.json",
    "credentials.json",
]


from brain.routing.privacy_policy import list_provider_policies


def get_privacy_config(conn: Optional[sqlite3.Connection] = None) -> PrivacyConfigResponse:
    config = read_gateway_config()
    prov_policies: Dict[str, str] = {}
    for p in config.get("providers", []):
        prov_policies[p.get("name", "")] = p.get("privacy_policy", "zero_retention")

    secrets_pat = get_setting(conn, "privacy_secret_patterns", default=DEFAULT_SECRET_PATTERNS) if conn else DEFAULT_SECRET_PATTERNS
    pii_pat = get_setting(conn, "privacy_pii_patterns", default=DEFAULT_PII_PATTERNS) if conn else DEFAULT_PII_PATTERNS
    guard_paths = get_setting(conn, "privacy_guard_paths", default=DEFAULT_GUARD_PATHS) if conn else DEFAULT_GUARD_PATHS

    return PrivacyConfigResponse(
        provider_policies=prov_policies,
        secret_redaction_patterns=secrets_pat,
        pii_redaction_patterns=pii_pat,
        guard_paths=guard_paths,
        retention_evidence=list_provider_policies(),
    )


def update_privacy_config(req: PrivacyUpdateRequest, conn: Optional[sqlite3.Connection] = None) -> PrivacyConfigResponse:
    if req.provider_policies:
        config = read_gateway_config()
        for p in config.get("providers", []):
            name = p.get("name")
            if name in req.provider_policies:
                p["privacy_policy"] = req.provider_policies[name]
        save_gateway_config(config, conn=conn, audit_action="update_privacy_policies")

    if conn:
        if req.secret_redaction_patterns is not None:
            set_setting(conn, "privacy_secret_patterns", req.secret_redaction_patterns)
        if req.pii_redaction_patterns is not None:
            set_setting(conn, "privacy_pii_patterns", req.pii_redaction_patterns)
        if req.guard_paths is not None:
            set_setting(conn, "privacy_guard_paths", req.guard_paths)
        log_audit_event(conn, action="update_privacy_config", details=req.model_dump())

    return get_privacy_config(conn)


def preview_redaction(text: str, conn: Optional[sqlite3.Connection] = None) -> PrivacyPreviewResponse:
    cfg = get_privacy_config(conn)
    redacted = text
    matches = []

    # Redact secrets
    for pat in cfg.secret_redaction_patterns:
        try:
            for m in re.finditer(pat, redacted):
                matched_str = m.group(0)
                matches.append({"type": "secret", "pattern": pat, "matched": matched_str[:8] + "..."})
            redacted = re.sub(pat, "[REDACTED_SECRET]", redacted)
        except Exception:
            pass

    # Redact PII
    for pat in cfg.pii_redaction_patterns:
        try:
            for m in re.finditer(pat, redacted):
                matched_str = m.group(0)
                matches.append({"type": "pii", "pattern": pat, "matched": matched_str[:4] + "***"})
            redacted = re.sub(pat, "[REDACTED_PII]", redacted)
        except Exception:
            pass

    return PrivacyPreviewResponse(
        original_text=text,
        redacted_text=redacted,
        matches_found=matches,
    )
