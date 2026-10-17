"""tests/routing/test_dynamic_roles_config.py — Verification of dynamic role resolution.

Tests that when gateway/config.json roles and model_aliases are empty,
roles (main, fast, subagent, summarizer, vision, complex_reasoning, opus, sonnet, haiku)
are resolved dynamically by requirement profiles and candidate metrics.
"""

import pytest
from brain.api.services.routing_service import get_routing_config, build_candidate_metrics_from_models
from brain.routing.profiles import load_profiles


def test_dynamic_roles_resolution_when_config_roles_empty():
    """Verify that empty config roles resolve dynamically via requirement profiles."""
    cfg = get_routing_config()

    # Verify all core task roles exist and are non-empty strings
    required_roles = [
        "main",
        "fast",
        "subagent",
        "summarizer",
        "vision",
        "complex_reasoning",
        "opus",
        "sonnet",
        "haiku",
    ]

    for role in required_roles:
        assert role in cfg.roles, f"Missing dynamic role: {role}"
        assert cfg.roles[role], f"Dynamic role {role} resolved to empty model ID"

    # Verify model_aliases are dynamically generated when empty in config
    assert "opus" in cfg.model_aliases
    assert "sonnet" in cfg.model_aliases
    assert "haiku" in cfg.model_aliases
    assert "default" in cfg.model_aliases

    assert cfg.model_aliases["sonnet"] == cfg.roles["main"]
    assert cfg.model_aliases["haiku"] == cfg.roles["fast"]

    # Verify profiles dump contains profile details
    profiles = load_profiles()
    for p_name in ["main", "fast", "subagent", "summarizer", "vision", "complex_reasoning", "opus", "sonnet", "haiku"]:
        assert p_name in cfg.profiles
        assert "hard_constraints" in cfg.profiles[p_name]
        assert "soft_objectives" in cfg.profiles[p_name]


def test_candidate_metrics_built_from_models():
    """Verify candidate metrics have proper capabilities and non-empty candidate list."""
    candidates = build_candidate_metrics_from_models()
    assert len(candidates) > 0, "Candidate pool should not be empty"

    # At least some candidates should have tools and streaming
    has_tools = any(c.capabilities.get("tools") for c in candidates)
    assert has_tools, "At least one candidate should have tool capability"
