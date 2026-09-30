"""
brain/reflect/distiller.py
--------------------------
Cross-trajectory lesson distiller (ExpeL-style).

Algorithm provenance (Apache-2.0 — port algorithm only, no source paste):
  LeapLabTHU/ExpeL — agent/expel.py (create_rules / update_rules, ~L418–520)
  Rule calculus: ADD / EDIT / AGREE / REMOVE with usage counters & confidence.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from typing import Any, Dict, List, Optional, Protocol, Sequence


def _now_ms() -> int:
    return int(time.time() * 1000)


class _LessonDB(Protocol):
    conn: Any


_TOKEN_RE = re.compile(r"[a-z0-9_]+", re.I)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _tokens(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN_RE.findall(text or "") if len(t) > 2}


def _similar(a: str, b: str, threshold: float = 0.55) -> bool:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return _norm(a) == _norm(b)
    return len(ta & tb) / float(len(ta | tb)) >= threshold


class LessonDistiller:
    """
    Compare success vs failure trajectories and maintain operational guidelines.
    """

    def __init__(self, db: Optional[_LessonDB] = None) -> None:
        self.db = db
        self._rules: Dict[str, Dict[str, Any]] = {}
        self._load_from_db()

    def distill(
        self,
        success_traces: Sequence[Dict[str, Any]],
        failure_traces: Sequence[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Extract operational guidelines from paired success/failure traces.
        Returns the lesson records touched by this distillation pass.
        """
        ops = self._propose_ops(success_traces, failure_traces)
        source_ids = [
            t.get("task_id", "")
            for t in list(success_traces) + list(failure_traces)
            if t.get("task_id")
        ]
        return self.apply_ops(ops, source_task_ids=source_ids)

    def apply_ops(
        self,
        ops: Sequence[Dict[str, Any]],
        source_task_ids: Optional[Sequence[str]] = None,
    ) -> List[Dict[str, Any]]:
        touched: List[Dict[str, Any]] = []
        sources = list(source_task_ids or [])
        for op in ops:
            kind = (op.get("op") or "").upper()
            rule_text = (op.get("rule_text") or "").strip()
            if not rule_text and kind != "REMOVE":
                continue
            if kind == "ADD":
                touched.append(self._add(rule_text, sources))
            elif kind == "AGREE":
                existing = self._find(rule_text)
                if existing:
                    touched.append(self._agree(existing["lesson_id"], sources))
                else:
                    touched.append(self._add(rule_text, sources))
            elif kind == "EDIT":
                existing = self._find(rule_text) or self._find(op.get("match", ""))
                new_text = op.get("new_text") or rule_text
                if existing:
                    touched.append(
                        self._edit(existing["lesson_id"], new_text, sources)
                    )
                else:
                    touched.append(self._add(new_text, sources))
            elif kind == "REMOVE":
                existing = self._find(rule_text) or self._find(op.get("match", ""))
                if existing:
                    touched.append(self._remove(existing["lesson_id"]))
        return touched

    # ------------------------------------------------------------------
    # Proposal heuristics (stand-in for ExpeL critic LLM)
    # ------------------------------------------------------------------

    def _propose_ops(
        self,
        success_traces: Sequence[Dict[str, Any]],
        failure_traces: Sequence[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        success_steps = self._flatten(success_traces)
        failure_steps = self._flatten(failure_traces)
        ops: List[Dict[str, Any]] = []

        # Contrastive cues: actions present in success but absent/negated in failure.
        for s in success_steps:
            s_tok = _tokens(s)
            if not s_tok:
                continue
            contrasted = False
            for f in failure_steps:
                f_low = f.lower()
                if any(t in f_low for t in s_tok) and any(
                    neg in f_low
                    for neg in ("skip", "left", "forgot", "failed", "open", "without")
                ):
                    contrasted = True
                    break
            if contrasted or (success_steps and failure_steps):
                guideline = self._to_guideline(s)
                if guideline:
                    # AGREE if near-duplicate already known, else ADD
                    if self._find(guideline):
                        ops.append({"op": "AGREE", "rule_text": guideline})
                    else:
                        ops.append({"op": "ADD", "rule_text": guideline})

        # Failure-only: "Avoid X" guidelines
        for f in failure_steps:
            f_low = f.lower()
            if any(k in f_low for k in ("skip", "left", "forgot", "failed")):
                guideline = self._avoid_guideline(f)
                if guideline:
                    if self._find(guideline):
                        ops.append({"op": "AGREE", "rule_text": guideline})
                    else:
                        ops.append({"op": "ADD", "rule_text": guideline})

        # Deduplicate ops by normalized rule text
        seen: set[str] = set()
        uniq: List[Dict[str, Any]] = []
        for op in ops:
            key = _norm(op["rule_text"])
            if key in seen:
                continue
            seen.add(key)
            uniq.append(op)
        return uniq

    @staticmethod
    def _flatten(traces: Sequence[Dict[str, Any]]) -> List[str]:
        steps: List[str] = []
        for t in traces:
            for step in t.get("trace") or []:
                if isinstance(step, str) and step.strip():
                    steps.append(step.strip())
        return steps

    @staticmethod
    def _to_guideline(success_step: str) -> str:
        s = success_step.strip()
        low = s.lower()
        if low.startswith("always ") or low.startswith("must "):
            return s[0].upper() + s[1:] if s else s
        # Normalize common verbs into imperative ops guidelines
        if "gofmt" in low or "go fmt" in low or "format" in low:
            return "Always run go fmt before submitting"
        if "pool" in low and "close" in low:
            return "Database connection pool must be closed before worker exit"
        if "test" in low and "pass" in low:
            return "Always ensure tests passed before considering the task done"
        return f"Always {s[0].lower() + s[1:] if s else s}"

    @staticmethod
    def _avoid_guideline(failure_step: str) -> str:
        low = failure_step.lower()
        if "gofmt" in low or "format" in low:
            return "Always run go fmt before submitting"
        if "pool" in low:
            return "Database connection pool must be closed before worker exit"
        return f"Avoid: {failure_step.strip()}"

    # ------------------------------------------------------------------
    # Rule calculus
    # ------------------------------------------------------------------

    def _add(self, rule_text: str, sources: Sequence[str]) -> Dict[str, Any]:
        existing = self._find(rule_text)
        if existing:
            return self._agree(existing["lesson_id"], sources)
        now = _now_ms()
        lesson = {
            "lesson_id": str(uuid.uuid4()),
            "rule_text": rule_text,
            "usage_count": 1,
            "reinforcements": 0,
            "removals": 0,
            "confidence": 0.5,
            "source_task_ids": list(sources),
            "created_at": now,
            "updated_at": now,
        }
        self._rules[lesson["lesson_id"]] = lesson
        self._persist(lesson)
        return dict(lesson)

    def _agree(self, lesson_id: str, sources: Sequence[str]) -> Dict[str, Any]:
        lesson = self._rules[lesson_id]
        lesson["reinforcements"] = int(lesson.get("reinforcements", 0)) + 1
        lesson["usage_count"] = int(lesson.get("usage_count", 0)) + 1
        lesson["confidence"] = min(
            1.0, float(lesson.get("confidence", 0.5)) + 0.05
        )
        ids = list(lesson.get("source_task_ids") or [])
        for s in sources:
            if s and s not in ids:
                ids.append(s)
        lesson["source_task_ids"] = ids
        lesson["updated_at"] = _now_ms()
        self._persist(lesson)
        return dict(lesson)

    def _edit(
        self, lesson_id: str, new_text: str, sources: Sequence[str]
    ) -> Dict[str, Any]:
        lesson = self._rules[lesson_id]
        lesson["rule_text"] = new_text
        lesson["usage_count"] = int(lesson.get("usage_count", 0)) + 1
        lesson["updated_at"] = _now_ms()
        ids = list(lesson.get("source_task_ids") or [])
        for s in sources:
            if s and s not in ids:
                ids.append(s)
        lesson["source_task_ids"] = ids
        self._persist(lesson)
        return dict(lesson)

    def _remove(self, lesson_id: str) -> Dict[str, Any]:
        lesson = self._rules[lesson_id]
        lesson["removals"] = int(lesson.get("removals", 0)) + 1
        lesson["confidence"] = max(
            0.0, float(lesson.get("confidence", 0.5)) - 0.2
        )
        lesson["updated_at"] = _now_ms()
        if lesson["confidence"] <= 0.1 or lesson["removals"] >= 3:
            self._rules.pop(lesson_id, None)
            self._delete_db(lesson_id)
        else:
            self._persist(lesson)
        return dict(lesson)

    def _find(self, rule_text: str) -> Optional[Dict[str, Any]]:
        if not rule_text:
            return None
        for lesson in self._rules.values():
            if _similar(lesson["rule_text"], rule_text):
                return lesson
        return None

    def _load_from_db(self) -> None:
        if self.db is None:
            return
        try:
            rows = self.db.conn.execute("SELECT * FROM lessons").fetchall()
            for r in rows:
                d = dict(r)
                raw = d.get("source_task_ids") or "[]"
                if isinstance(raw, str):
                    try:
                        d["source_task_ids"] = json.loads(raw)
                    except json.JSONDecodeError:
                        d["source_task_ids"] = []
                self._rules[d["lesson_id"]] = d
        except Exception:
            pass

    def _persist(self, lesson: Dict[str, Any]) -> None:
        if self.db is None:
            return
        conn = self.db.conn
        sources = lesson.get("source_task_ids") or []
        if not isinstance(sources, str):
            sources_json = json.dumps(list(sources))
        else:
            sources_json = sources
        conn.execute(
            """
            INSERT INTO lessons
                (lesson_id, rule_text, usage_count, reinforcements, removals,
                 confidence, source_task_ids, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(lesson_id) DO UPDATE SET
                rule_text = excluded.rule_text,
                usage_count = excluded.usage_count,
                reinforcements = excluded.reinforcements,
                removals = excluded.removals,
                confidence = excluded.confidence,
                source_task_ids = excluded.source_task_ids,
                updated_at = excluded.updated_at
            """,
            (
                lesson["lesson_id"],
                lesson["rule_text"],
                lesson["usage_count"],
                lesson["reinforcements"],
                lesson["removals"],
                lesson["confidence"],
                sources_json,
                lesson["created_at"],
                lesson["updated_at"],
            ),
        )
        try:
            conn.execute(
                "DELETE FROM lessons_fts WHERE lesson_id = ?",
                (lesson["lesson_id"],),
            )
            conn.execute(
                "INSERT INTO lessons_fts (lesson_id, rule_text) VALUES (?, ?)",
                (lesson["lesson_id"], lesson["rule_text"]),
            )
        except Exception:
            pass
        conn.commit()

    def _delete_db(self, lesson_id: str) -> None:
        if self.db is None:
            return
        self.db.conn.execute("DELETE FROM lessons WHERE lesson_id = ?", (lesson_id,))
        try:
            self.db.conn.execute(
                "DELETE FROM lessons_fts WHERE lesson_id = ?", (lesson_id,)
            )
        except Exception:
            pass
        self.db.conn.commit()
