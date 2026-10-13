"""tests/routing/test_routing_api.py — API and CLI tests for dynamic routing.
"""

from __future__ import annotations

import os
import sys
import tempfile
import pytest
from fastapi.testclient import TestClient

from brain.api.app import create_app
from brain.api.security import get_or_create_auth_token
from brain.server import BrainServer
from cli.cm import CMClient, cmd_route
import argparse


@pytest.fixture(scope="module")
def api_test_env():
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    server = BrainServer(db_path=db_path)
    app = create_app(server)
    token = get_or_create_auth_token()
    client = TestClient(app)
    auth_headers = {"Authorization": f"Bearer {token}"}

    yield {
        "server": server,
        "app": app,
        "client": client,
        "token": token,
        "auth_headers": auth_headers,
        "db_path": db_path,
    }

    try:
        server.store.close()
        if os.path.exists(db_path):
            os.remove(db_path)
    except Exception:
        pass


def test_api_routing_profiles(api_test_env):
    client = api_test_env["client"]
    auth = api_test_env["auth_headers"]

    # 1. List profiles
    resp = client.get("/api/routing/profiles", headers=auth)
    assert resp.status_code == 200
    profiles = resp.json()
    assert len(profiles) >= 5
    names = [p["name"] for p in profiles]
    assert "main" in names
    assert "fast" in names

    # 2. Get specific profile
    resp_single = client.get("/api/routing/profiles/main", headers=auth)
    assert resp_single.status_code == 200
    main_prof = resp_single.json()
    assert main_prof["name"] == "main"
    assert "hard_constraints" in main_prof
    assert "soft_objectives" in main_prof


def test_api_routing_simulate(api_test_env):
    client = api_test_env["client"]
    auth = api_test_env["auth_headers"]

    # Simulate routing for fast profile
    sim_resp = client.post(
        "/api/routing/simulate",
        json={"task": "def add(a, b): return a + b", "role": "fast", "prompt_tokens": 300},
        headers=auth,
    )
    assert sim_resp.status_code == 200
    data = sim_resp.json()
    assert data["resolved_role"] == "fast"
    assert "selected_model" in data
    assert "selected_provider" in data
    assert "fallback_chain" in data
    assert "request_id" in data

    # Explain the simulated decision
    req_id = data["request_id"]
    exp_resp = client.get(f"/api/routing/explain/{req_id}", headers=auth)
    assert exp_resp.status_code == 200
    exp_data = exp_resp.json()
    assert exp_data["request_id"] == req_id


def test_cli_cmd_route(monkeypatch, api_test_env):
    client = api_test_env["client"]
    token = api_test_env["token"]

    class MockCMClient:
        def request(self, method, path, params=None, body=None, curl=False, api_only=False):
            # Dispatch to FastAPI TestClient
            headers = {"Authorization": f"Bearer {token}"}
            if method == "GET":
                r = client.get(path, headers=headers, params=params)
            elif method == "POST":
                r = client.post(path, headers=headers, json=body)
            elif method == "PUT":
                r = client.put(path, headers=headers, json=body)
            else:
                raise ValueError(method)
            return r.status_code, r.json()

    mock_client = MockCMClient()

    # 1. cm route profiles
    args_profiles = argparse.Namespace(
        subcommand="profiles",
        strategy=None,
        curl=False,
        api=False,
        json=False,
    )
    assert cmd_route(mock_client, args_profiles) == 0

    # 2. cm route simulate
    args_sim = argparse.Namespace(
        subcommand="simulate",
        strategy=None,
        task="Write a fast parser",
        profile="fast",
        tokens=400,
        vision=False,
        curl=False,
        api=False,
        json=False,
    )
    assert cmd_route(mock_client, args_sim) == 0
