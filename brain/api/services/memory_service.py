"""brain/api/services/memory_service.py — Neocortical store browsing, search, decay, and snapshots.
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional
import sqlite3

from brain.api.database import get_setting, set_setting, log_audit_event
from brain.api.models import (
    LessonItem,
    EpisodicEventItem,
    MemoryQueryResponse,
    MemorySnapshotResponse,
)


def query_memory(conn: sqlite3.Connection, query: Optional[str] = None, limit: int = 50) -> MemoryQueryResponse:
    lessons: List[LessonItem] = []
    events: List[EpisodicEventItem] = []

    # 1. Lessons
    try:
        if query:
            rows = conn.execute(
                "SELECT l.* FROM lessons l JOIN lessons_fts f ON l.lesson_id = f.lesson_id "
                "WHERE lessons_fts MATCH ? ORDER BY l.confidence DESC LIMIT ?",
                (query, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM lessons ORDER BY confidence DESC LIMIT ?", (limit,)
            ).fetchall()

        for r in rows:
            tasks = []
            try:
                tasks = json.loads(r["source_task_ids"])
            except Exception:
                pass
            lessons.append(
                LessonItem(
                    lesson_id=r["lesson_id"],
                    rule_text=r["rule_text"],
                    confidence=r["confidence"],
                    usage_count=r["usage_count"],
                    reinforcements=r["reinforcements"],
                    removals=r["removals"],
                    source_task_ids=tasks,
                    created_at=r["created_at"],
                    updated_at=r["updated_at"],
                )
            )
    except Exception:
        pass

    # 2. Episodic events
    try:
        ev_rows = conn.execute(
            "SELECT * FROM episodic_events ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        for r in ev_rows:
            payload = {}
            try:
                payload = json.loads(r["action_payload"])
            except Exception:
                payload = r["action_payload"]
            events.append(
                EpisodicEventItem(
                    event_id=r["event_id"],
                    session_id=r["session_id"],
                    event_type=r["event_type"],
                    tool_name=r["tool_name"],
                    action_payload=payload,
                    outcome_reward=r["outcome_reward"],
                    created_at=r["created_at"],
                )
            )
    except Exception:
        pass

    total_lessons = len(lessons)
    total_events = len(events)
    try:
        total_lessons = conn.execute("SELECT COUNT(*) AS c FROM lessons").fetchone()["c"]
        total_events = conn.execute("SELECT COUNT(*) AS c FROM episodic_events").fetchone()["c"]
    except Exception:
        pass

    ab_learning = bool(get_setting(conn, "ab_learning_enabled", default=True))

    return MemoryQueryResponse(
        lessons=lessons,
        recent_events=events,
        total_lessons=total_lessons,
        total_events=total_events,
        ab_learning_enabled=ab_learning,
    )


def apply_confidence_decay(conn: sqlite3.Connection, rate: float = 0.05) -> int:
    """Decay confidence of older unreinforced lessons."""
    now = int(time.time() * 1000)
    cursor = conn.execute(
        "UPDATE lessons SET confidence = MAX(0.1, confidence * (1.0 - ?)), updated_at = ?",
        (rate, now),
    )
    conn.commit()
    log_audit_event(conn, action="confidence_decay", details={"rate": rate, "rows_updated": cursor.rowcount})
    return cursor.rowcount


def toggle_ab_learning(conn: sqlite3.Connection) -> bool:
    curr = bool(get_setting(conn, "ab_learning_enabled", default=True))
    new_val = not curr
    set_setting(conn, "ab_learning_enabled", new_val)
    log_audit_event(conn, action="toggle_ab_learning", details={"enabled": new_val})
    return new_val


def create_memory_snapshot(conn: sqlite3.Connection, notes: str = "") -> MemorySnapshotResponse:
    now = int(time.time() * 1000)
    snap_id = f"snap_{now}"

    nodes = [dict(r) for r in conn.execute("SELECT * FROM brain_nodes").fetchall()]
    lessons = [dict(r) for r in conn.execute("SELECT * FROM lessons").fetchall()]

    payload = {"nodes": nodes, "lessons": lessons, "created_at": now, "notes": notes}
    set_setting(conn, f"snapshot_{snap_id}", payload)

    log_audit_event(conn, action="create_memory_snapshot", details={"snapshot_id": snap_id, "notes": notes})
    return MemorySnapshotResponse(
        snapshot_id=snap_id,
        created_at=now,
        nodes_count=len(nodes),
        lessons_count=len(lessons),
    )


def rollback_memory_snapshot(conn: sqlite3.Connection, snapshot_id: str) -> bool:
    snap = get_setting(conn, f"snapshot_{snapshot_id}")
    if not snap:
        return False

    # Restore lessons
    conn.execute("DELETE FROM lessons")
    conn.execute("DELETE FROM lessons_fts")
    for l in snap.get("lessons", []):
        conn.execute(
            "INSERT INTO lessons (lesson_id, rule_text, usage_count, reinforcements, removals, confidence, source_task_ids, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (l["lesson_id"], l["rule_text"], l["usage_count"], l["reinforcements"], l["removals"], l["confidence"], l["source_task_ids"], l["created_at"], l["updated_at"]),
        )
        conn.execute(
            "INSERT INTO lessons_fts (lesson_id, rule_text) VALUES (?, ?)",
            (l["lesson_id"], l["rule_text"]),
        )
    conn.commit()
    log_audit_event(conn, action="rollback_memory_snapshot", details={"snapshot_id": snapshot_id})
    return True
