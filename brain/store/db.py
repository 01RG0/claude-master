"""
brain/store/db.py
-----------------
BrainDB: SQLite connection manager for the claude-master neocortical store.

Design notes:
- WAL journal mode for concurrent reads alongside writer.
- sqlite-vec extension loaded dynamically; absence is non-fatal (graceful degradation).
- Schema is authoritative in contracts/schema.sql — never duplicated here.
"""

import logging
import os
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

# Resolve the schema path relative to the repo root (two levels up from this file).
_THIS_DIR = Path(__file__).resolve().parent          # brain/store/
_REPO_ROOT = _THIS_DIR.parent.parent                  # claude-master/
_SCHEMA_PATH = _REPO_ROOT / "contracts" / "schema.sql"


class BrainDB:
    """
    SQLite connection manager.

    Parameters
    ----------
    db_path : str
        Filesystem path for the SQLite database file.
        Use ``":memory:"`` for ephemeral test databases.
    """

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self.conn: sqlite3.Connection = sqlite3.connect(
            db_path,
            check_same_thread=False,
        )
        self.conn.row_factory = sqlite3.Row

        # Core PRAGMAs — set before schema load to avoid WAL/FK conflicts.
        self.conn.execute("PRAGMA journal_mode = WAL;")
        self.conn.execute("PRAGMA foreign_keys = ON;")
        self.conn.execute("PRAGMA busy_timeout = 5000;")

        self._try_load_vec_extension()
        self._load_schema()
        self._create_vec_table()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _load_schema(self) -> None:
        """Execute contracts/schema.sql to create all tables idempotently."""
        sql = _SCHEMA_PATH.read_text(encoding="utf-8")
        # executescript commits any pending transaction first (SQLite behaviour).
        self.conn.executescript(sql)

    # ------------------------------------------------------------------
    # sqlite-vec extension (optional)
    # ------------------------------------------------------------------

    def _try_load_vec_extension(self) -> None:
        """
        Attempt to load the sqlite-vec shared extension.
        On failure, log a warning and continue without vector support.
        """
        self.vec_enabled = False
        try:
            self.conn.enable_load_extension(True)
            # Try the python package path first, then a bare library name.
            try:
                import sqlite_vec  # type: ignore
                sqlite_vec.load(self.conn)
                self.vec_enabled = True
                logger.info("sqlite-vec extension loaded via python package.")
            except ImportError:
                # Fallback: attempt to load by conventional library name.
                for lib in ("vec0", "sqlite_vec", "libsqlite_vec"):
                    try:
                        self.conn.load_extension(lib)
                        self.vec_enabled = True
                        logger.info("sqlite-vec extension loaded: %s", lib)
                        break
                    except sqlite3.OperationalError:
                        continue
                if not self.vec_enabled:
                    logger.warning(
                        "sqlite-vec extension not available. "
                        "Vector similarity search is disabled."
                    )
        except sqlite3.OperationalError as exc:
            logger.warning(
                "Cannot enable SQLite extension loading (%s). "
                "Vector search disabled.",
                exc,
            )
        finally:
            try:
                self.conn.enable_load_extension(False)
            except Exception:
                pass

    def _create_vec_table(self) -> None:
        """
        Create the brain_node_vectors virtual table only when sqlite-vec is loaded.
        Silently skips when vec is unavailable.
        """
        if not self.vec_enabled:
            return
        try:
            self.conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS brain_node_vectors USING vec0(
                    node_id TEXT PRIMARY KEY,
                    embedding float[384] distance_metric=cosine
                );
                """
            )
            self.conn.commit()
        except sqlite3.OperationalError as exc:
            logger.warning("Failed to create brain_node_vectors: %s", exc)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the SQLite connection."""
        if self.conn:
            self.conn.close()

    def __enter__(self) -> "BrainDB":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
        return False
