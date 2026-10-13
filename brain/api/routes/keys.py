"""brain/api/routes/keys.py — Key management, rotation, DPAPI persistence, and masked retrieval.
"""

from __future__ import annotations

from typing import List
from fastapi import APIRouter, Depends, HTTPException, Query
import sqlite3

from brain.api.dependencies import get_db
from brain.api.models import (
    KeyItem,
    KeyAddRequest,
    KeyRotateRequest,
    KeyRevealRequest,
    KeyRevealResponse,
)
from brain.api.services.keystore_service import (
    get_all_keys,
    store_key,
    remove_key,
    reveal_key_plaintext,
    hot_reload_gateway,
)

router = APIRouter(prefix="/keys", tags=["Keys"])


@router.get("", response_model=List[KeyItem])
def list_keys_endpoint(conn: sqlite3.Connection = Depends(get_db)):
    return get_all_keys(conn)


@router.post("", response_model=KeyItem)
async def add_key_endpoint(req: KeyAddRequest, conn: sqlite3.Connection = Depends(get_db)):
    return await store_key(req, conn=conn)


@router.put("/rotate", response_model=KeyItem)
async def rotate_key_endpoint(req: KeyRotateRequest, conn: sqlite3.Connection = Depends(get_db)):
    add_req = KeyAddRequest(
        provider=req.provider,
        account_label="personal",
        env_var=req.env_var,
        key=req.new_key,
    )
    return await store_key(add_req, conn=conn)


@router.delete("")
async def remove_key_endpoint(
    provider: str = Query(...),
    account_label: str = Query("personal"),
    env_var: str = Query(""),
    conn: sqlite3.Connection = Depends(get_db),
):
    ev = env_var or f"{provider.upper()}_API_KEY"
    ok = await remove_key(provider, account_label, ev, conn=conn)
    return {"ok": ok, "provider": provider, "account_label": account_label}


@router.post("/reveal", response_model=KeyRevealResponse)
def reveal_key_endpoint(req: KeyRevealRequest):
    if not req.confirm:
        raise HTTPException(status_code=400, detail="Explicit confirmation required to reveal plaintext key")
    plain = reveal_key_plaintext(req.provider, req.account_label)
    if not plain:
        raise HTTPException(status_code=404, detail="Key not found in encrypted DPAPI store")
    return KeyRevealResponse(provider=req.provider, account_label=req.account_label, plaintext_key=plain)
