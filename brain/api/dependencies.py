"""brain/api/dependencies.py — FastAPI dependencies for database connection and BrainServer.
"""

from __future__ import annotations

import sqlite3
from typing import Generator
from fastapi import Request

from brain.paths import default_db_path
from brain.store.db import BrainDB
from brain.api.database import init_api_schema


def get_db(request: Request) -> Generator[sqlite3.Connection, None, None]:
    """Provide an active SQLite connection from BrainDB or request state."""
    if hasattr(request.app.state, "brain_db") and request.app.state.brain_db:
        conn = request.app.state.brain_db.conn
        init_api_schema(conn)
        yield conn
    elif hasattr(request.app.state, "brain_server") and request.app.state.brain_server:
        conn = request.app.state.brain_server.store.conn
        init_api_schema(conn)
        yield conn
    else:
        # Fallback standalone
        bdb = BrainDB(default_db_path())
        init_api_schema(bdb.conn)
        try:
            yield bdb.conn
        finally:
            pass


def get_brain_server(request: Request):
    """Retrieve BrainServer instance if attached to app."""
    return getattr(request.app.state, "brain_server", None)
