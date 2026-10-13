"""brain/api/services/config_service.py — Gateway configuration and dynamic UI schema service.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
import sqlite3

from brain.api.database import log_audit_event
from brain.api.models import (
    DynamicSchemaResponse,
    DialectSchema,
    PresetModeSchema,
    ProviderConfig,
    KeyPoolItem,
)
from brain.api.security import mask_key


def get_repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent.parent


def get_gateway_config_path() -> Path:
    # CLAUDE_MASTER_GATEWAY_CONFIG lets tests point the admin API at a
    # throwaway copy; without it, every admin-API test would mutate the live
    # config and break the running system (observed 2026-10-13: test providers
    # written into gateway/config.json).
    override = os.environ.get("CLAUDE_MASTER_GATEWAY_CONFIG")
    if override:
        return Path(override)
    p = get_repo_root() / "gateway" / "config.json"
    if not p.exists():
        # Fallback to local gateway dir
        p = Path("gateway/config.json").resolve()
    return p


def get_capabilities_path() -> Path:
    override = os.environ.get("CLAUDE_MASTER_GATEWAY_CAPABILITIES")
    if override:
        return Path(override)
    p = get_repo_root() / "gateway" / "capabilities.json"
    if not p.exists():
        p = Path("gateway/capabilities.json").resolve()
    return p


def read_gateway_config() -> Dict[str, Any]:
    path = get_gateway_config_path()
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "listen_addr": ":8080",
        "brain_socket": "/tmp/claude_brain.sock",
        "request_timeout_s": 60,
        "providers": [],
        "routing": {
            "strategy": "thompson_sampling",
            "cooldown_base_s": 60,
            "cooldown_max_s": 3600,
        },
        "model_aliases": {},
        "roles": {},
    }


def save_gateway_config(config: Dict[str, Any], conn: Optional[sqlite3.Connection] = None, audit_action: str = "update_config") -> None:
    path = get_gateway_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(config, indent=2, ensure_ascii=False)
    path.write_text(content, encoding="utf-8")
    if conn:
        log_audit_event(conn, action=audit_action, details={"config_path": str(path)})


def get_dynamic_schema() -> DynamicSchemaResponse:
    """Return dynamic schema for UI so frontend never hardcodes dialects or capabilities."""
    dialects = [
        DialectSchema(
            id="openai",
            name="OpenAI Compatible",
            endpoint_suffix="/chat/completions",
            auth_header_format="Bearer {api_key}",
            supports_streaming=True,
            supports_tools=True,
            supports_vision=True,
        ),
        DialectSchema(
            id="anthropic",
            name="Anthropic Native",
            endpoint_suffix="/v1/messages",
            auth_header_format="x-api-key: {api_key}",
            supports_streaming=True,
            supports_tools=True,
            supports_vision=True,
        ),
        DialectSchema(
            id="gemini",
            name="Google Gemini",
            endpoint_suffix="/models/{model}:generateContent",
            auth_header_format="x-goog-api-key: {api_key}",
            supports_streaming=True,
            supports_tools=True,
            supports_vision=True,
        ),
        DialectSchema(
            id="cohere",
            name="Cohere v2",
            endpoint_suffix="/v2/chat",
            auth_header_format="Bearer {api_key}",
            supports_streaming=True,
            supports_tools=True,
            supports_vision=False,
        ),
        DialectSchema(
            id="ollama",
            name="Ollama Local",
            endpoint_suffix="/api/chat",
            auth_header_format="None",
            supports_streaming=True,
            supports_tools=True,
            supports_vision=True,
        ),
    ]

    preset_modes = [
        PresetModeSchema(
            id="economy",
            name="Maximum Economy",
            description="Prioritize fast, zero-cost and free-tier models (Groq, Cerebras, Pollinations, Mistral small)",
            routing_strategy="lowest_cost",
            default_role_mapping={
                "main": "llama-3.3-70b-versatile",
                "fast": "llama-3.1-8b-instant",
                "subagent": "ministral-8b-latest",
                "summarizer": "mistral-small-latest",
                "vision": "gemini-2.5-flash",
            },
        ),
        PresetModeSchema(
            id="balanced",
            name="Balanced (Default)",
            description="Adaptive Thompson sampling routing combining latency, accuracy, and budget constraints",
            routing_strategy="thompson_sampling",
            default_role_mapping={
                "main": "ministral-8b-latest",
                "fast": "llama-3.1-8b-instant",
                "subagent": "command-r-plus-08-2024",
                "summarizer": "mistral-small-latest",
                "vision": "gemini-2.5-flash",
            },
        ),
        PresetModeSchema(
            id="max_intelligence",
            name="Max Intelligence",
            description="Route high-difficulty coding and reasoning tasks to strongest flagship models",
            routing_strategy="highest_capability",
            default_role_mapping={
                "main": "claude-3-7-sonnet-latest",
                "fast": "llama-3.3-70b-versatile",
                "subagent": "llama-3.3-70b-versatile",
                "summarizer": "llama-3.1-8b-instant",
                "vision": "gemini-2.5-flash",
            },
        ),
        PresetModeSchema(
            id="local_only",
            name="Local Air-Gapped",
            description="Strictly route to local Ollama / vLLM endpoints for zero data egress",
            routing_strategy="local_first",
            default_role_mapping={
                "main": "ollama/qwen2.5-coder:32b",
                "fast": "ollama/qwen2.5-coder:7b",
                "subagent": "ollama/llama3.2:3b",
                "summarizer": "ollama/llama3.2:3b",
                "vision": "ollama/llama3.2-vision",
            },
        ),
    ]

    privacy_policies = [
        {"id": "zero_retention", "label": "Zero Data Retention (Ephemeral)", "description": "Provider logs no prompt data"},
        {"id": "internal_only", "label": "Internal / EU Data Boundary", "description": "Compliant with SOC2 / GDPR boundaries"},
        {"id": "public_data_only", "label": "Public / Non-confidential", "description": "Safe for open code and non-sensitive prompts"},
    ]

    roles = ["main", "fast", "subagent", "summarizer", "vision"]

    config_fields = {
        "listen_addr": {"type": "string", "default": ":8080", "description": "Address for the gateway to bind to"},
        "request_timeout_s": {"type": "integer", "default": 60, "description": "Gateway upstream request timeout in seconds"},
        "routing.strategy": {"type": "string", "enum": ["thompson_sampling", "priority", "lowest_cost", "round_robin"]},
        "routing.cooldown_base_s": {"type": "integer", "default": 60, "description": "Base backoff on HTTP 429 rate limits"},
        "routing.cooldown_max_s": {"type": "integer", "default": 3600, "description": "Max cooldown backoff"},
    }

    return DynamicSchemaResponse(
        dialects=dialects,
        preset_modes=preset_modes,
        privacy_policies=privacy_policies,
        roles=roles,
        config_fields=config_fields,
    )


def list_providers(conn: Optional[sqlite3.Connection] = None) -> List[ProviderConfig]:
    config = read_gateway_config()
    raw_providers = config.get("providers", [])
    result = []
    for p in raw_providers:
        pools = []
        for kp in p.get("key_pools", []):
            env_var = kp.get("env_var", "")
            # Look up existing env var or key state if active
            pools.append(
                KeyPoolItem(
                    account_label=kp.get("account_label", "personal"),
                    env_var=env_var,
                    priority=kp.get("priority", 10),
                    key_masked="configured" if env_var else None,
                    is_active=True,
                    budget_usd=kp.get("budget_usd"),
                    tags=kp.get("tags", []),
                )
            )
        result.append(
            ProviderConfig(
                name=p.get("name", ""),
                base_url=p.get("base_url", ""),
                privacy_policy=p.get("privacy_policy", "zero_retention"),
                adapter=p.get("adapter"),
                models=p.get("models", []),
                key_pools=pools,
            )
        )
    return result


def add_or_update_provider(provider: ProviderConfig, conn: Optional[sqlite3.Connection] = None) -> None:
    config = read_gateway_config()
    providers = config.get("providers", [])
    idx = next((i for i, p in enumerate(providers) if p.get("name") == provider.name), -1)

    new_entry = {
        "name": provider.name,
        "base_url": provider.base_url,
        "privacy_policy": provider.privacy_policy,
        "models": provider.models,
        "key_pools": [
            {
                "account_label": kp.account_label,
                "env_var": kp.env_var,
                "priority": kp.priority,
            }
            for kp in provider.key_pools
        ],
    }
    if provider.adapter:
        new_entry["adapter"] = provider.adapter

    if idx >= 0:
        providers[idx] = new_entry
        action = "update_provider"
    else:
        providers.append(new_entry)
        action = "add_provider"

    config["providers"] = providers
    save_gateway_config(config, conn=conn, audit_action=f"{action}:{provider.name}")


def delete_provider(name: str, conn: Optional[sqlite3.Connection] = None) -> bool:
    config = read_gateway_config()
    providers = config.get("providers", [])
    before_len = len(providers)
    providers = [p for p in providers if p.get("name") != name]
    if len(providers) < before_len:
        config["providers"] = providers
        save_gateway_config(config, conn=conn, audit_action=f"delete_provider:{name}")
        return True
    return False
