"""
Tests for brain/reflect and brain/sleep (B4 – Reflexion, Skills & Sleep).

Acceptance:
1. Reflexion captures failed assertions → episodic verbal memory snippet
2. Skill store saves verified snippets indexed by docstrings
3. Distiller extracts guidelines from success/failure pairs
4. Sleep job runs all 4 phases and logs to sleep_log
"""

from __future__ import annotations

import pytest


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "reflect_brain.db")


@pytest.fixture
def graph_store(db_path):
    from brain.store.graph import GraphStore

    gs = GraphStore(db_path)
    yield gs
    gs.close()


# ---------------------------------------------------------------------------
# 1. Reflexion harness
# ---------------------------------------------------------------------------


class TestReflexionHarness:
    def test_captures_failed_assertion_as_episodic_snippet(self):
        from brain.reflect.reflexion import ReflexionHarness

        harness = ReflexionHarness()
        code = "def add(a, b):\n    return a - b\n"
        tests = [
            "assert add(2, 3) == 5",
            "assert add(0, 0) == 0",
        ]
        result = harness.run(code, tests)

        assert result.passed is False
        assert len(result.failed_assertions) >= 1
        assert result.reflection_snippet
        snippet = result.reflection_snippet
        assert "Reflection" in snippet or "reflection" in snippet.lower()
        assert "failed" in snippet.lower() or "wrong" in snippet.lower()
        # Episodic buffer accumulates verbal memory
        assert len(harness.episodic_buffer) >= 1
        assert harness.episodic_buffer[-1] == result.reflection_snippet

    def test_passing_tests_skip_reflection(self):
        from brain.reflect.reflexion import ReflexionHarness

        harness = ReflexionHarness()
        code = "def add(a, b):\n    return a + b\n"
        result = harness.run(code, ["assert add(1, 1) == 2"])
        assert result.passed is True
        assert result.reflection_snippet == ""
        assert harness.episodic_buffer == []

    def test_format_reflections_header(self):
        from brain.reflect.reflexion import format_reflections

        text = format_reflections(["forgot to handle zeros", "off-by-one on bounds"])
        assert "Reflections:" in text
        assert "forgot to handle zeros" in text
        assert format_reflections([]) == ""


# ---------------------------------------------------------------------------
# 2. Voyager-style skill store
# ---------------------------------------------------------------------------


class TestSkillStore:
    def test_saves_verified_snippet_indexed_by_docstring(self, graph_store, tmp_path):
        from brain.reflect.skill_store import SkillStore

        skills_dir = tmp_path / "skills"
        store = SkillStore(db=graph_store, skills_dir=skills_dir)
        skill = store.add_skill(
            name="safe_div",
            code_body="def safe_div(a, b):\n    return a / b if b else 0\n",
            docstring="Divide a by b; return 0 when divisor is zero.",
            language="python",
            verified=True,
        )
        assert skill["name"] == "safe_div"
        assert skill["version"] == 1
        assert "zero" in skill["docstring"].lower()

        # Indexed by docstring — retrieve via docstring query
        hits = store.search("divisor is zero", k=3)
        assert any(h["name"] == "safe_div" for h in hits)

        # Persisted in skills table
        row = graph_store.conn.execute(
            "SELECT name, docstring, code_body FROM skills WHERE name = ?",
            ("safe_div",),
        ).fetchone()
        assert row is not None
        assert "safe_div" in row["code_body"]

    def test_monotonic_versioning(self, graph_store, tmp_path):
        from brain.reflect.skill_store import SkillStore

        store = SkillStore(db=graph_store, skills_dir=tmp_path / "skills")
        v1 = store.add_skill(
            name="parse_json",
            code_body="def parse_json(s): return {}",
            docstring="Parse JSON string into a dict.",
            verified=True,
        )
        v2 = store.add_skill(
            name="parse_json",
            code_body="def parse_json(s):\n    import json\n    return json.loads(s)\n",
            docstring="Parse JSON string into a dict using json.loads.",
            verified=True,
        )
        assert v1["version"] == 1
        assert v2["version"] == 2

    def test_rejects_unverified(self, graph_store, tmp_path):
        from brain.reflect.skill_store import SkillStore

        store = SkillStore(db=graph_store, skills_dir=tmp_path / "skills")
        with pytest.raises(ValueError):
            store.add_skill(
                name="bad",
                code_body="x",
                docstring="nope",
                verified=False,
            )


# ---------------------------------------------------------------------------
# 3. ExpeL lesson distiller
# ---------------------------------------------------------------------------


class TestLessonDistiller:
    def test_extracts_guidelines_from_success_failure_pairs(self, graph_store):
        from brain.reflect.distiller import LessonDistiller

        distiller = LessonDistiller(db=graph_store)
        success = {
            "task_id": "t1",
            "trace": [
                "ran gofmt before commit",
                "closed db pool before exit",
                "tests passed",
            ],
            "outcome": "success",
        }
        failure = {
            "task_id": "t2",
            "trace": [
                "skipped gofmt",
                "left db pool open",
                "tests failed on formatting",
            ],
            "outcome": "failure",
        }
        lessons = distiller.distill(success_traces=[success], failure_traces=[failure])
        assert len(lessons) >= 1
        texts = " ".join(L["rule_text"].lower() for L in lessons)
        # Operational guideline should contrast the paired outcomes
        assert any(
            kw in texts
            for kw in ("gofmt", "format", "pool", "close", "always", "must", "avoid")
        )

        # Persisted
        count = graph_store.conn.execute("SELECT COUNT(*) AS c FROM lessons").fetchone()["c"]
        assert count >= 1

    def test_agree_increments_reinforcements(self, graph_store):
        from brain.reflect.distiller import LessonDistiller

        distiller = LessonDistiller(db=graph_store)
        rule = "Always run go fmt before submitting"
        first = distiller.apply_ops([{"op": "ADD", "rule_text": rule}], source_task_ids=["a"])
        assert len(first) == 1
        second = distiller.apply_ops(
            [{"op": "AGREE", "rule_text": rule}],
            source_task_ids=["b"],
        )
        assert second[0]["reinforcements"] >= 1
        assert second[0]["usage_count"] >= 1


# ---------------------------------------------------------------------------
# 4. Nightly sleep consolidator — 4 phases + sleep_log
# ---------------------------------------------------------------------------


class TestSleepConsolidator:
    def _seed_graph(self, gs):
        for nid, name in [("A", "alpha"), ("B", "beta"), ("C", "gamma"), ("D", "delta")]:
            gs.upsert_node(id=nid, node_type="concept", name=name, content=name)
        # A->B, B->C (transitive A->C should appear), A->D weak lateral
        gs.add_edge("A", "B", "reinforces", weight=0.8)
        gs.add_edge("B", "C", "reinforces", weight=0.7)
        gs.add_edge("A", "D", "lateral", weight=0.4)

    def test_sleep_runs_four_phases_and_logs(self, graph_store):
        from brain.sleep.consolidator import SleepConsolidator

        self._seed_graph(graph_store)
        consolidator = SleepConsolidator(db=graph_store)
        report = consolidator.run(
            replay_paths=[["A", "B", "C"]],
            success_traces=[],
            failure_traces=[],
        )

        assert report["phases_completed"] == [
            "nrem_replay",
            "transitive_closure",
            "rem_abstract",
            "shy_downscale",
        ]

        # Phase 1: replay strengthened A->B (and B->C)
        ab = graph_store.conn.execute(
            "SELECT weight FROM brain_edges WHERE source_id='A' AND target_id='B' "
            "AND invalid_at IS NULL"
        ).fetchone()
        # After LTP (*1.10) then SHY (*0.95): 0.8 * 1.10 * 0.95 = 0.836
        assert ab["weight"] == pytest.approx(0.8 * 1.10 * 0.95, rel=1e-3)

        # Phase 2: transitive A->C exists
        ac = graph_store.conn.execute(
            "SELECT weight FROM brain_edges WHERE source_id='A' AND target_id='C' "
            "AND invalid_at IS NULL"
        ).fetchone()
        assert ac is not None

        # Phase 4: non-replayed A->D only got SHY downscale (and maybe LTD in phase1)
        ad = graph_store.conn.execute(
            "SELECT weight FROM brain_edges WHERE source_id='A' AND target_id='D' "
            "AND invalid_at IS NULL"
        ).fetchone()
        assert ad["weight"] < 0.4

        # sleep_log rows for all four phases
        phases = {
            r["phase"]
            for r in graph_store.conn.execute("SELECT phase FROM sleep_log").fetchall()
        }
        assert phases == {
            "nrem_replay",
            "transitive_closure",
            "rem_abstract",
            "shy_downscale",
        }
        assert report["run_id"]
        unfinished = graph_store.conn.execute(
            "SELECT COUNT(*) AS c FROM sleep_log WHERE finished_at IS NULL"
        ).fetchone()["c"]
        assert unfinished == 0

    def test_downscale_factor_is_0_95(self, graph_store):
        from brain.sleep.consolidator import SleepConsolidator, SHY_GAMMA

        assert SHY_GAMMA == pytest.approx(0.95)
        self._seed_graph(graph_store)
        # Isolate SHY: empty replay so phase1 doesn't LTP
        before = graph_store.conn.execute(
            "SELECT id, weight FROM brain_edges WHERE invalid_at IS NULL"
        ).fetchall()
        weights_before = {r["id"]: r["weight"] for r in before}

        consolidator = SleepConsolidator(db=graph_store)
        consolidator.run(replay_paths=[], success_traces=[], failure_traces=[])

        after = graph_store.conn.execute(
            "SELECT id, weight FROM brain_edges WHERE invalid_at IS NULL"
        ).fetchall()
        for r in after:
            if r["id"] in weights_before:
                # New transitive edges may appear; existing ones must be ~ *0.95
                # (phase1 LTD may also apply to neighbors — with empty replay no LTP/LTD)
                expected = weights_before[r["id"]] * 0.95
                assert r["weight"] == pytest.approx(expected, rel=1e-3)
