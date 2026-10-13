"""brain/api/services/keystore_service.py — DPAPI runtime keystore and gateway sync service.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
import httpx
import sqlite3

from brain.api.database import log_audit_event
from brain.api.models import KeyItem, KeyAddRequest
from brain.api.security import (
    dpapi_protect,
    dpapi_unprotect,
    mask_key,
    hash_key,
)
from brain.api.services.config_service import read_gateway_config, save_gateway_config


def get_keystore_path() -> Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        dir_path = Path(appdata) / "claude-master"
    else:
        dir_path = Path.home() / ".claude-master"
    dir_path.mkdir(parents=True, exist_ok=True)
    return dir_path / "keys.json"


def read_keystore_raw() -> Dict[str, Dict[str, str]]:
    """Read plaintext dictionary provider -> label -> plain_key."""
    path = get_keystore_path()
    if not path.exists():
        return {}
    try:
        content = json.loads(path.read_text(encoding="utf-8"))
        entries = content.get("entries", {})
        result: Dict[str, Dict[str, str]] = {}
        for prov, labels in entries.items():
            result[prov] = {}
            for label, b64_blob in labels.items():
                try:
                    blob = base64.b64decode(b64_blob)
                    plain = dpapi_unprotect(blob).decode("utf-8")
                    result[prov][label] = plain
                except Exception:
                    pass
        return result
    except Exception:
        return {}


def save_keystore_raw(entries: Dict[str, Dict[str, str]], conn: Optional[sqlite3.Connection] = None) -> None:
    path = get_keystore_path()
    out: Dict[str, Any] = {"version": 1, "entries": {}}
    for prov, labels in entries.items():
        out["entries"][prov] = {}
        for label, plain in labels.items():
            blob = dpapi_protect(plain.encode("utf-8"))
            out["entries"][prov][label] = base64.b64encode(blob).decode("ascii")

    path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    if conn:
        log_audit_event(conn, action="keystore_saved", details={"providers": list(entries.keys())})


async def hot_reload_gateway(
    action: str,
    provider: str,
    env_var: str,
    key: Optional[str] = None,
    models: Optional[List[str]] = None,
    gateway_url: str = "http://127.0.0.1:8080",
) -> bool:
    """Notify gateway of key changes via loopback /v1/admin/keys."""
    payload: Dict[str, Any] = {
        "action": action,
        "provider": provider,
        "env_var": env_var,
    }
    if key:
        payload["key"] = key
    if models:
        payload["models"] = models

    try:
        async with httpx.AsyncClient(timeout=1.5) as client:
            resp = await client.post(f"{gateway_url}/v1/admin/keys", json=payload)
            return resp.status_code == 200
    except Exception:
        return False  # Gateway may be offline, non-fatal since persisted to DPAPI


def get_all_keys(conn: Optional[sqlite3.Connection] = None) -> List[KeyItem]:
    """Return all keys with masked representations and metadata."""
    keystore = read_keystore_raw()
    config = read_gateway_config()

    # Query key_state table from DB if available
    db_state: Dict[str, Dict[str, Any]] = {}
    if conn:
        try:
            rows = conn.execute("SELECT * FROM key_state").fetchall()
            for r in rows:
                db_state[r["key_hash"]] = dict(r)
        except Exception:
            pass

    results: List[KeyItem] = []

    # 1. Keys in DPAPI keystore
    for prov, labels in keystore.items():
        for label, secret in labels.items():
            khash = hash_key(secret)
            state = db_state.get(khash, {})
            # Look up matching env_var in config
            env_var = f"{prov.upper()}_API_KEY"
            for p in config.get("providers", []):
                if p.get("name") == prov:
                    for kp in p.get("key_pools", []):
                        if kp.get("account_label") == label:
                            env_var = kp.get("env_var", env_var)

            results.append(
                KeyItem(
                    key_hash=khash,
                    provider=prov,
                    account_label=label,
                    env_var=env_var,
                    key_masked=mask_key(secret),
                    is_active=bool(state.get("is_active", 1)),
                    cooldown_until=state.get("cooldown_until"),
                    failure_count=int(state.get("failure_count", 0)),
                    budget_usd=None,
                    tags=["dpapi_persisted"],
                )
            )

    # 2. Configured key pools from config that might be purely from environment
    for p in config.get("providers", []):
        prov = p.get("name", "")
        for kp in p.get("key_pools", []):
            label = kp.get("account_label", "personal")
            env_var = kp.get("env_var", "")
            # If not already present from keystore
            if not any(k.provider == prov and k.account_label == label for k in results):
                secret = os.environ.get(env_var, "")
                masked = mask_key(secret) if secret else "(environment: unset)"
                khash = hash_key(secret) if secret else f"env:{env_var}"
                results.append(
                    KeyItem(
                        key_hash=khash,
                        provider=prov,
                        account_label=label,
                        env_var=env_var,
                        key_masked=masked,
                        is_active=bool(secret),
                        cooldown_until=None,
                        failure_count=0,
                        budget_usd=kp.get("budget_usd"),
                        tags=["env_var"],
                    )
                )

    return results


async def store_key(req: KeyAddRequest, conn: Optional[sqlite3.Connection] = None) -> KeyItem:
    """Store key in DPAPI keystore, register in gateway config, and hot-reload."""
    entries = read_keystore_raw()
    if req.provider not in entries:
        entries[req.provider] = {}
    entries[req.provider][req.account_label] = req.key
    save_keystore_raw(entries, conn=conn)

    # Also make sure config has provider and key pool
    config = read_gateway_config()
    prov_found = False
    for p in config.get("providers", []):
        if p.get("name") == req.provider:
            prov_found = True
            pools = p.setdefault("key_pools", [])
            pool_found = False
            for kp in pools:
                if kp.get("account_label") == req.account_label:
                    kp["env_var"] = req.env_var
                    kp["priority"] = req.priority
                    pool_found = True
                    break
            if not pool_found:
                pools.append({
                    "account_label": req.account_label,
                    "env_var": req.env_var,
                    "priority": req.priority,
                })
            break

    if not prov_found:
        config.setdefault("providers", []).append({
            "name": req.provider,
            "base_url": f"https://api.{req.provider}.com/v1",
            "privacy_policy": "zero_retention",
            "models": req.models or [],
            "key_pools": [{
                "account_label": req.account_label,
                "env_var": req.env_var,
                "priority": req.priority,
            }],
        })

    save_gateway_config(config, conn=conn, audit_action=f"add_key:{req.provider}/{req.account_label}")

    # Hot-reload to gateway
    await hot_reload_gateway(
        action="add",
        provider=req.provider,
        env_var=req.env_var,
        key=req.key,
        models=req.models,
    )

    khash = hash_key(req.key)
    # Update SQLite key_state table
    if conn:
        try:
            import time
            now = int(time.time() * 1000)
            conn.execute(
                "INSERT INTO key_state (key_hash, provider, account_label, is_active, failure_count, updated_at) "
                "VALUES (?, ?, ?, 1, 0, ?) ON CONFLICT(key_hash) DO UPDATE SET is_active = 1, updated_at = excluded.updated_at",
                (khash, req.provider, req.account_label, now),
            )
            conn.commit()
        except Exception:
            pass

    return KeyItem(
        key_hash=khash,
        provider=req.provider,
        account_label=req.account_label,
        env_var=req.env_var,
        key_masked=mask_key(req.key),
        is_active=True,
        cooldown_until=None,
        failure_count=0,
        budget_usd=req.budget_usd,
        tags=req.tags,
    )


async def remove_key(provider: str, account_label: str, env_var: str, conn: Optional[sqlite3.Connection] = None) -> bool:
    entries = read_keystore_raw()
    removed = False
    if provider in entries and account_label in entries[provider]:
        del entries[provider][account_label]
        if not entries[provider]:
            del entries[provider]
        save_keystore_raw(entries, conn=conn)
        removed = True

    await hot_reload_gateway(
        action="remove",
        provider=provider,
        env_var=env_var,
    )
    if conn:
        log_audit_event(conn, action=f"remove_key:{provider}/{account_label}")
    return removed


def reveal_key_plaintext(provider: str, account_label: str) -> Optional[str]:
    """Retrieve plaintext key only upon explicit user confirmation on loopback."""
    entries = read_keystore_raw()
    return entries.get(provider, {}).get(account_label)
