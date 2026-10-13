"""tests for the rewrite Decision Taker (no network on happy path)."""
import pytest


def _client_fail_open():
    from brain.judge.client import DrexClient

    return DrexClient(api_key="fake", base_url="http://localhost:19999", timeout_s=0.05, max_retries=0)


class TestDecisionTakerDegraded:
    def test_guard_fail_open_allows(self):
        from brain.judge.decision_taker import DecisionTaker

        dt = DecisionTaker(client=_client_fail_open())
        d = dt.decide_guard("Bash", "file_deletion", use_drex=True)
        assert d.action == "act" and d.value == "allow" and d.source == "fail_open"

    def test_guard_rule_only_by_default(self):
        from brain.judge.decision_taker import DecisionTaker

        dt = DecisionTaker(client=_client_fail_open())
        assert dt.decide_guard("Bash", "routine").value == "allow"
        d = dt.decide_guard("Bash", "file_deletion")
        assert d.value == "block" and d.source == "rule"

    def test_watchdog_restart_budget_escalates(self):
        from brain.judge.decision_taker import DecisionTaker

        dt = DecisionTaker(client=_client_fail_open())
        d = dt.decide_watchdog("daemon unhealthy x10", restarts=5)
        assert d.value == "escalate" and d.source == "rule"

    def test_provider_single_candidate_rule(self):
        from brain.judge.decision_taker import DecisionTaker

        dt = DecisionTaker(client=_client_fail_open())
        d = dt.decide_provider("summ", ["groq/llama"])
        assert d.value == "groq/llama" and d.source == "rule"

    def test_store_fail_open_stores(self):
        from brain.judge.decision_taker import DecisionTaker

        dt = DecisionTaker(client=_client_fail_open())
        d = dt.decide_store("event summary")
        assert d.value["store"] is True

    def test_guard_blocks_on_high_risk(self):
        from unittest.mock import MagicMock

        from brain.judge.decision_taker import DecisionTaker

        c = MagicMock()
        c.total_cost_usd = 0.0
        c.evaluate.return_value = {"answers": {"risk": {"noul": 0.95}}, "model": "drex-v2.0"}
        dt = DecisionTaker(client=c)
        d = dt.decide_guard("Bash", "file_deletion", use_drex=True)
        assert d.value == "block" and d.source == "drex"

    def test_guard_asks_in_band(self):
        from unittest.mock import MagicMock

        from brain.judge.decision_taker import DecisionTaker

        c = MagicMock()
        c.total_cost_usd = 0.0
        c.evaluate.return_value = {"answers": {"risk": {"noul": 0.6}}, "model": "drex-v2.0"}
        dt = DecisionTaker(client=c)
        d = dt.decide_guard("Bash", "network_pipe", use_drex=True)
        assert d.action == "escalate" and d.value == "ask-user"


class TestDrexClientRewrite:
    def test_no_hardcoded_host(self):
        from brain.judge import client as m

        assert "console.nace.ai" in m.DEFAULT_BASE_URL
        assert "drex.nace.ai" not in m.DEFAULT_BASE_URL

    def test_dotenv_parsing(self):
        from brain.judge.client import _parse_dotenv_file
        import tempfile, os

        with tempfile.NamedTemporaryFile("w", suffix=".env", delete=False) as fh:
            fh.write('export NACE_API_KEY="nace_sk_test123"\n# comment\nDREX_API_KEY=old\n')
            path = fh.name
        try:
            from pathlib import Path

            vals = _parse_dotenv_file(Path(path))
            assert vals["NACE_API_KEY"] == "nace_sk_test123"
        finally:
            os.remove(path)

    def test_never_retries_401(self):
        import urllib.error
        from unittest.mock import patch
        from brain.judge.client import DrexClient

        c = DrexClient(api_key="k", base_url="https://console.nace.ai", timeout_s=5, max_retries=2,
                       model="drex-v2.0")
        err = urllib.error.HTTPError("http://x", 401, "unauth", {}, None)
        with patch("urllib.request.urlopen", side_effect=err) as m:
            out = c.evaluate("s", {"q": {"type": "noul", "instructions": "?"}})
        assert out.get("_fail_open") is True and out.get("_status") == 401
        assert m.call_count == 1

    def test_body_over_1mib_fail_open(self):
        from brain.judge.client import DrexClient

        c = DrexClient(api_key="k", timeout_s=5)
        out = c.evaluate("x" * 1_100_000, {"q": {"type": "noul", "instructions": "?"}})
        assert out.get("_fail_open") is True
