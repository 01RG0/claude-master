"""
brain/reflect/skill_store.py
----------------------------
Docstring-indexed procedural skill library (Voyager-style).

Algorithm provenance (MIT — port algorithm only, no source paste):
  MineDojo/Voyager — voyager/agents/skill.py
  Key ideas: embed/index the synthesized docstring (not raw code),
  monotonic version bumps on same skill name, dual disk + DB persistence.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol


def _now_ms() -> int:
    return int(time.time() * 1000)


class _SkillDB(Protocol):
    conn: Any


_TOKEN_RE = re.compile(r"[a-z0-9_]+", re.I)


def _tokenize(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN_RE.findall(text or "") if len(t) > 1}


class SkillStore:
    """
    Save verified code snippets indexed by docstring for later retrieval.
    """

    def __init__(
        self,
        db: Optional[_SkillDB] = None,
        skills_dir: Optional[Path | str] = None,
    ) -> None:
        self.db = db
        self.skills_dir = Path(skills_dir) if skills_dir else None
        if self.skills_dir is not None:
            self.skills_dir.mkdir(parents=True, exist_ok=True)
        self._memory: Dict[str, List[Dict[str, Any]]] = {}

    def add_skill(
        self,
        name: str,
        code_body: str,
        docstring: str,
        language: str = "python",
        verified: bool = False,
    ) -> Dict[str, Any]:
        if not verified:
            raise ValueError("only verified skills may be stored")
        if not docstring or not docstring.strip():
            raise ValueError("docstring is required for indexing")
        if not name or not name.strip():
            raise ValueError("skill name is required")

        version = self._next_version(name)
        skill_id = str(uuid.uuid4())
        now = _now_ms()
        record = {
            "skill_id": skill_id,
            "name": name,
            "version": version,
            "docstring": docstring.strip(),
            "code_body": code_body,
            "language": language,
            "success_count": 1,
            "created_at": now,
            "updated_at": now,
        }

        self._memory.setdefault(name, []).append(record)
        self._persist_db(record)
        self._persist_disk(record)
        return dict(record)

    def search(self, query: str, k: int = 5) -> List[Dict[str, Any]]:
        """Retrieve top-k skills by docstring token overlap (Voyager index target)."""
        q_tokens = _tokenize(query)
        if not q_tokens:
            return []

        candidates = self._all_skills()
        scored: List[tuple[float, Dict[str, Any]]] = []
        for skill in candidates:
            d_tokens = _tokenize(skill["docstring"])
            if not d_tokens:
                continue
            overlap = len(q_tokens & d_tokens)
            if overlap == 0:
                continue
            score = overlap / float(len(q_tokens | d_tokens))
            # Prefer latest version on ties
            scored.append((score + skill.get("version", 1) * 1e-6, skill))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [s for _, s in scored[:k]]

    def _next_version(self, name: str) -> int:
        versions = [s["version"] for s in self._skills_named(name)]
        return (max(versions) + 1) if versions else 1

    def _skills_named(self, name: str) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = list(self._memory.get(name, []))
        if self.db is not None:
            try:
                rows = self.db.conn.execute(
                    "SELECT * FROM skills WHERE name = ? ORDER BY version DESC",
                    (name,),
                ).fetchall()
                seen = {s["skill_id"] for s in out}
                for r in rows:
                    d = dict(r)
                    if d["skill_id"] not in seen:
                        out.append(d)
            except Exception:
                pass
        return out

    def _all_skills(self) -> List[Dict[str, Any]]:
        by_id: Dict[str, Dict[str, Any]] = {}
        for skills in self._memory.values():
            for s in skills:
                by_id[s["skill_id"]] = s
        if self.db is not None:
            try:
                # Prefer FTS when available; fall back to full table.
                rows = self.db.conn.execute("SELECT * FROM skills").fetchall()
                for r in rows:
                    d = dict(r)
                    by_id[d["skill_id"]] = d
            except Exception:
                pass
        return list(by_id.values())

    def _persist_db(self, record: Dict[str, Any]) -> None:
        if self.db is None:
            return
        conn = self.db.conn
        conn.execute(
            """
            INSERT INTO skills
                (skill_id, name, version, docstring, code_body, language,
                 success_count, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["skill_id"],
                record["name"],
                record["version"],
                record["docstring"],
                record["code_body"],
                record["language"],
                record["success_count"],
                record["created_at"],
                record["updated_at"],
            ),
        )
        try:
            conn.execute(
                "DELETE FROM skills_fts WHERE skill_id = ?",
                (record["skill_id"],),
            )
            conn.execute(
                "INSERT INTO skills_fts (skill_id, name, docstring) VALUES (?, ?, ?)",
                (record["skill_id"], record["name"], record["docstring"]),
            )
        except Exception:
            pass
        conn.commit()

    def _persist_disk(self, record: Dict[str, Any]) -> None:
        if self.skills_dir is None:
            return
        path = self.skills_dir / f"{record['name']}.json"
        payload: Dict[str, Any] = {}
        if path.exists():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                payload = {}
        key = f"{record['name']}V{record['version']}"
        payload[key] = {
            "code": record["code_body"],
            "description": record["docstring"],
            "skill_id": record["skill_id"],
            "language": record["language"],
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
