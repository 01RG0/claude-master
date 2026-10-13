"""Catalog and Route Management for Universal Model Routing.

Builds and audits canonical models and multi-provider routes based on
empirical capability evidence and dynamic identity resolution.

Outputs:
- data/catalog/models.json
- data/catalog/routes.json
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from brain.routing.classifier import (
    EmpiricalProbeResult,
    ModelClassification,
    ModelModality,
    classify_from_probe,
    classify_model_capabilities,
    is_model_agentic,
)
from brain.routing.identity import (
    CanonicalIdentityResolver,
    CanonicalModelIdentity,
    resolve_canonical_identity,
)

logger = logging.getLogger(__name__)


@dataclass
class PricingSpec:
    prompt_per_m: float = 0.0
    completion_per_m: float = 0.0
    cache_read_per_m: float = 0.0


@dataclass
class RateLimitSpec:
    rpm: Optional[int] = None
    tpm: Optional[int] = None
    rpd: Optional[int] = None


@dataclass
class Route:
    route_id: str
    canonical_id: str
    provider: str
    provider_model_id: str
    key_pool: str
    base_url: str
    pricing: Dict[str, float]
    measured_latency_ms: float
    rate_limits: Dict[str, Any]
    priority: int = 100
    healthy: bool = True
    status_code: int = 200
    empirical_evidence: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CanonicalModel:
    canonical_id: str
    display_name: str
    vendor: str
    family: str
    parameter_size: Optional[str]
    type: str  # text_chat, tool_calling, multimodal, embedding, audio_stt, audio_tts, image_generation, classification_guard, rerank
    is_agentic: bool
    modalities: List[str]
    capabilities: Dict[str, bool]
    context_window: int
    routes: List[str]
    non_agentic_reason: Optional[str] = None
    empirical_evidence: Dict[str, Any] = field(default_factory=dict)


class CatalogAuditor:
    """Empirical auditor and resolver for universal catalog."""

    def __init__(self, root_dir: Optional[Path] = None):
        self.root_dir = root_dir or Path(os.getcwd())
        self.resolver = CanonicalIdentityResolver()
        self.routes: Dict[str, Route] = {}
        self.models: Dict[str, CanonicalModel] = {}
        self.misclassified_non_agentic: List[Dict[str, Any]] = []

        # Pricing and metadata caches
        self._litellm_prices: Dict[str, Any] = {}
        self._openrouter_models: Dict[str, Any] = {}
        self._models_dev: Dict[str, Any] = {}
        self._gateway_capabilities: Dict[str, Any] = {}
        self._env_vars: Dict[str, str] = {}
        self._load_datasets()

    def _load_datasets(self) -> None:
        """Load offline pricing and capability reference datasets."""
        # 1. .env variables (keys are kept strictly in memory, never exposed)
        env_file = self.root_dir / ".env"
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    self._env_vars[k.strip()] = v.strip().strip("'\"")

        # 2. litellm prices
        p = self.root_dir / "data" / "litellm-prices.json"
        if p.exists():
            try:
                self._litellm_prices = json.loads(p.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning(f"Failed loading litellm-prices: {e}")

        # 3. openrouter models
        p = self.root_dir / "data" / "openrouter-models.json"
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                for m in data.get("data", []):
                    if "id" in m:
                        self._openrouter_models[m["id"]] = m
            except Exception as e:
                logger.warning(f"Failed loading openrouter-models: {e}")

        # 4. models-dev
        p = self.root_dir / "data" / "models-dev.json"
        if p.exists():
            try:
                self._models_dev = json.loads(p.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning(f"Failed loading models-dev: {e}")

        # 5. gateway capabilities
        p = self.root_dir / "gateway" / "capabilities.json"
        if p.exists():
            try:
                self._gateway_capabilities = json.loads(p.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning(f"Failed loading capabilities.json: {e}")

    def probe_chat_completion(
        self,
        base_url: str,
        api_key: str,
        model_id: str,
        timeout: float = 6.0,
    ) -> EmpiricalProbeResult:
        """Perform real HTTP chat completion probe."""
        endpoint = base_url.rstrip("/") + "/chat/completions"
        payload = json.dumps({
            "model": model_id,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 5,
        }).encode("utf-8")

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "claude-master/1.0",
        }
        req = urllib.request.Request(endpoint, data=payload, headers=headers)

        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                lat = (time.time() - t0) * 1000
                raw = resp.read().decode("utf-8")
                parsed = json.loads(raw)
                content = ""
                choices = parsed.get("choices", [])
                if choices and isinstance(choices, list):
                    msg = choices[0].get("message", {})
                    content = msg.get("content") or ""

                # Check if it looks like a numeric safety classification score (e.g. 0.00091)
                is_classification = False
                if content:
                    stripped = content.strip()
                    try:
                        val = float(stripped)
                        if 0.0 <= val <= 1.0 and len(stripped) > 3:
                            is_classification = True
                    except ValueError:
                        pass

                return EmpiricalProbeResult(
                    endpoint=endpoint,
                    http_status=resp.status,
                    latency_ms=lat,
                    response_body=raw[:200],
                    parsed_json=parsed,
                    has_text_content=bool(content) and not is_classification,
                    is_classification_output=is_classification,
                    probe_type="chat",
                )
        except urllib.error.HTTPError as e:
            lat = (time.time() - t0) * 1000
            err_body = e.read().decode("utf-8", errors="ignore")
            return EmpiricalProbeResult(
                endpoint=endpoint,
                http_status=e.code,
                latency_ms=lat,
                error_message=err_body,
                response_body=err_body[:300],
                probe_type="chat",
            )
        except Exception as e:
            lat = (time.time() - t0) * 1000
            return EmpiricalProbeResult(
                endpoint=endpoint,
                http_status=0,
                latency_ms=lat,
                error_message=str(e),
                probe_type="chat",
            )

    def probe_tool_calling(
        self,
        base_url: str,
        api_key: str,
        model_id: str,
        timeout: float = 6.0,
    ) -> EmpiricalProbeResult:
        """Perform real HTTP tool calling probe."""
        endpoint = base_url.rstrip("/") + "/chat/completions"
        tools = [{
            "type": "function",
            "function": {
                "name": "check_status",
                "description": "Check status of system",
                "parameters": {
                    "type": "object",
                    "properties": {"service": {"type": "string"}},
                    "required": ["service"],
                },
            },
        }]
        payload = json.dumps({
            "model": model_id,
            "messages": [{"role": "user", "content": "Check status of database"}],
            "tools": tools,
            "tool_choice": "auto",
            "max_tokens": 50,
        }).encode("utf-8")

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "claude-master/1.0",
        }
        req = urllib.request.Request(endpoint, data=payload, headers=headers)

        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                lat = (time.time() - t0) * 1000
                raw = resp.read().decode("utf-8")
                parsed = json.loads(raw)
                has_tc = False
                choices = parsed.get("choices", [])
                if choices:
                    msg = choices[0].get("message", {})
                    has_tc = bool(msg.get("tool_calls"))

                return EmpiricalProbeResult(
                    endpoint=endpoint,
                    http_status=resp.status,
                    latency_ms=lat,
                    response_body=raw[:200],
                    parsed_json=parsed,
                    has_tool_calls=has_tc,
                    probe_type="tools",
                )
        except urllib.error.HTTPError as e:
            lat = (time.time() - t0) * 1000
            err_body = e.read().decode("utf-8", errors="ignore")
            return EmpiricalProbeResult(
                endpoint=endpoint,
                http_status=e.code,
                latency_ms=lat,
                error_message=err_body,
                response_body=err_body[:300],
                probe_type="tools",
            )
        except Exception as e:
            lat = (time.time() - t0) * 1000
            return EmpiricalProbeResult(
                endpoint=endpoint,
                http_status=0,
                latency_ms=lat,
                error_message=str(e),
                probe_type="tools",
            )

    def probe_embeddings(
        self,
        base_url: str,
        api_key: str,
        model_id: str,
        timeout: float = 6.0,
    ) -> EmpiricalProbeResult:
        """Perform real HTTP embeddings endpoint probe."""
        endpoint = base_url.rstrip("/") + "/embeddings"
        payload = json.dumps({
            "model": model_id,
            "input": "test embedding vector",
        }).encode("utf-8")

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "claude-master/1.0",
        }
        req = urllib.request.Request(endpoint, data=payload, headers=headers)

        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                lat = (time.time() - t0) * 1000
                raw = resp.read().decode("utf-8")
                parsed = json.loads(raw)
                data = parsed.get("data", [])
                has_emb = bool(data and "embedding" in data[0] and isinstance(data[0]["embedding"], list))

                return EmpiricalProbeResult(
                    endpoint=endpoint,
                    http_status=resp.status,
                    latency_ms=lat,
                    response_body=f"Embedding vector dimension {len(data[0]['embedding']) if has_emb else 0}",
                    parsed_json=parsed,
                    has_embedding=has_emb,
                    probe_type="embeddings",
                )
        except urllib.error.HTTPError as e:
            lat = (time.time() - t0) * 1000
            err_body = e.read().decode("utf-8", errors="ignore")
            return EmpiricalProbeResult(
                endpoint=endpoint,
                http_status=e.code,
                latency_ms=lat,
                error_message=err_body,
                response_body=err_body[:300],
                probe_type="embeddings",
            )
        except Exception as e:
            lat = (time.time() - t0) * 1000
            return EmpiricalProbeResult(
                endpoint=endpoint,
                http_status=0,
                latency_ms=lat,
                error_message=str(e),
                probe_type="embeddings",
            )

    def probe_vision(
        self,
        base_url: str,
        api_key: str,
        model_id: str,
        timeout: float = 6.0,
    ) -> EmpiricalProbeResult:
        """Perform real HTTP vision probe with base64 1x1 image."""
        endpoint = base_url.rstrip("/") + "/chat/completions"
        img_b64 = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
        payload = json.dumps({
            "model": model_id,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": "Describe image"},
                    {"type": "image_url", "image_url": {"url": img_b64}},
                ],
            }],
            "max_tokens": 10,
        }).encode("utf-8")

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "claude-master/1.0",
        }
        req = urllib.request.Request(endpoint, data=payload, headers=headers)

        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                lat = (time.time() - t0) * 1000
                raw = resp.read().decode("utf-8")
                return EmpiricalProbeResult(
                    endpoint=endpoint,
                    http_status=resp.status,
                    latency_ms=lat,
                    response_body=raw[:200],
                    probe_type="vision",
                )
        except urllib.error.HTTPError as e:
            lat = (time.time() - t0) * 1000
            err_body = e.read().decode("utf-8", errors="ignore")
            return EmpiricalProbeResult(
                endpoint=endpoint,
                http_status=e.code,
                latency_ms=lat,
                error_message=err_body,
                response_body=err_body[:300],
                probe_type="vision",
            )
        except Exception as e:
            lat = (time.time() - t0) * 1000
            return EmpiricalProbeResult(
                endpoint=endpoint,
                http_status=0,
                latency_ms=lat,
                error_message=str(e),
                probe_type="vision",
            )

    def lookup_pricing(self, provider: str, raw_model_id: str, canonical_id: str) -> PricingSpec:
        """Resolve pricing dynamically from litellm, openrouter, or models-dev."""
        # 1. Check openrouter
        if raw_model_id in self._openrouter_models:
            p_data = self._openrouter_models[raw_model_id].get("pricing", {})
            try:
                p_in = float(p_data.get("prompt", 0)) * 1e6
                p_out = float(p_data.get("completion", 0)) * 1e6
                p_cache = float(p_data.get("input_cache_read", 0)) * 1e6
                return PricingSpec(prompt_per_m=round(p_in, 4), completion_per_m=round(p_out, 4), cache_read_per_m=round(p_cache, 4))
            except (ValueError, TypeError):
                pass

        # 2. Check models-dev
        p_info = self._models_dev.get(provider, {})
        m_info = p_info.get("models", {}).get(raw_model_id)
        if m_info and "cost" in m_info and isinstance(m_info["cost"], dict):
            cost = m_info["cost"]
            p_in = float(cost.get("input", 0.0))
            p_out = float(cost.get("output", 0.0))
            p_cache = float(cost.get("cache_read", 0.0))
            return PricingSpec(prompt_per_m=p_in, completion_per_m=p_out, cache_read_per_m=p_cache)

        # 3. Check litellm
        for cand in [f"{provider}/{raw_model_id}", raw_model_id, canonical_id]:
            if cand in self._litellm_prices:
                spec = self._litellm_prices[cand]
                if isinstance(spec, dict):
                    in_cost = spec.get("input_cost_per_token")
                    out_cost = spec.get("output_cost_per_token")
                    if in_cost is not None or out_cost is not None:
                        return PricingSpec(
                            prompt_per_m=round((in_cost or 0.0) * 1e6, 4),
                            completion_per_m=round((out_cost or 0.0) * 1e6, 4),
                        )

        # Free tier providers
        if provider in ("pollinations", "aihorde") or ":free" in raw_model_id:
            return PricingSpec(prompt_per_m=0.0, completion_per_m=0.0)

        return PricingSpec(prompt_per_m=0.50, completion_per_m=1.50)

    def lookup_rate_limits(self, provider: str, raw_model_id: str) -> RateLimitSpec:
        """Resolve rate limits dynamically from known provider specifications."""
        prov = provider.lower()
        if "groq" in prov:
            return RateLimitSpec(rpm=30, tpm=6000, rpd=14400)
        elif "cerebras" in prov:
            return RateLimitSpec(rpm=30, tpm=60000)
        elif "mistral" in prov:
            return RateLimitSpec(rpm=120, tpm=100000)
        elif "gemini" in prov:
            return RateLimitSpec(rpm=15, tpm=1000000, rpd=1500)
        elif "alibaba" in prov or "dashscope" in prov:
            return RateLimitSpec(rpm=60, tpm=100000)
        elif "openrouter" in prov:
            return RateLimitSpec(rpm=200, tpm=500000)
        elif "zenmux" in prov:
            return RateLimitSpec(rpm=60, tpm=200000)
        elif "pollinations" in prov:
            return RateLimitSpec(rpm=30, tpm=50000)
        return RateLimitSpec(rpm=60, tpm=100000)

    def lookup_context_window(self, raw_model_id: str, canonical_id: str) -> int:
        """Resolve model context window."""
        if raw_model_id in self._openrouter_models:
            ctx = self._openrouter_models[raw_model_id].get("context_length")
            if ctx and isinstance(ctx, int):
                return ctx

        for cand in [raw_model_id, canonical_id]:
            if cand in self._litellm_prices:
                spec = self._litellm_prices[cand]
                if isinstance(spec, dict) and "max_tokens" in spec and spec["max_tokens"]:
                    return int(spec["max_tokens"])

        # Default standard context
        return 128000

    def audit_catalog(self, live_probing: bool = True) -> Dict[str, Any]:
        """Run full catalog audit across all active providers."""
        config_path = self.root_dir / "gateway" / "config.json"
        if not config_path.exists():
            raise FileNotFoundError(f"Missing config at {config_path}")

        cfg_data = json.loads(config_path.read_text(encoding="utf-8"))
        providers_list = cfg_data.get("providers", [])

        # Additional active providers present in environment
        active_provider_configs = []
        for p in providers_list:
            name = p.get("name")
            base_url = p.get("base_url")
            key_pools = p.get("key_pools", [])
            env_var = key_pools[0].get("env_var") if key_pools else None
            priority = key_pools[0].get("priority", 100) if key_pools else 100
            models = p.get("models", [])
            active_provider_configs.append({
                "name": name,
                "base_url": base_url,
                "env_var": env_var,
                "priority": priority,
                "declared_models": models,
            })

        # Add providers present in .env but not in config.json
        if "ZENMUX_API_KEY" in self._env_vars and not any(p["name"] == "zenmux" for p in active_provider_configs):
            active_provider_configs.append({
                "name": "zenmux",
                "base_url": "https://zenmux.ai/api/v1",
                "env_var": "ZENMUX_API_KEY",
                "priority": 65,
                "declared_models": ["*"],
            })
        if "DAHL_API_KEY" in self._env_vars and not any(p["name"] == "dahl" for p in active_provider_configs):
            active_provider_configs.append({
                "name": "dahl",
                "base_url": "https://api.dahl.dev/v1",
                "env_var": "DAHL_API_KEY",
                "priority": 75,
                "declared_models": ["*"],
            })

        logger.info(f"Loaded {len(active_provider_configs)} providers for audit")

        # Process each provider
        for prov_cfg in active_provider_configs:
            prov_name = prov_cfg["name"]
            base_url = prov_cfg["base_url"]
            env_var = prov_cfg["env_var"]
            priority = prov_cfg["priority"]
            api_key = self._env_vars.get(env_var, "")

            # If Alibaba has ALIBABA_BASE_URL, use that override
            if prov_name == "alibaba" and "ALIBABA_BASE_URL" in self._env_vars:
                base_url = self._env_vars["ALIBABA_BASE_URL"]

            # Determine list of models to evaluate
            provider_models = self._discover_provider_models(prov_name, base_url, api_key, prov_cfg.get("declared_models", []))

            logger.info(f"Auditing provider {prov_name} with {len(provider_models)} models")

            # Probe and classify each model
            for raw_model_id in provider_models:
                self._audit_single_model(
                    prov_name=prov_name,
                    base_url=base_url,
                    env_var=env_var,
                    api_key=api_key,
                    priority=priority,
                    raw_model_id=raw_model_id,
                    live_probing=live_probing,
                )

        audit_summary = {
            "total_canonical_models": len(self.models),
            "total_routes": len(self.routes),
            "agentic_models_count": sum(1 for m in self.models.values() if m.is_agentic),
            "non_agentic_models_filtered": sum(1 for m in self.models.values() if not m.is_agentic),
            "misclassified_evidence_count": len(self.misclassified_non_agentic),
        }
        return audit_summary

    def _discover_provider_models(
        self,
        prov_name: str,
        base_url: str,
        api_key: str,
        declared: List[str],
    ) -> List[str]:
        """Discover models: prioritizes declared models, capabilities models, and live candidates."""
        models: List[str] = []

        # 1. Start with declared models if explicit (not wildcard)
        if declared and declared != ["*"]:
            models.extend(declared)

        # 2. Add models from capabilities.json
        cap_models = self._gateway_capabilities.get("providers", {}).get(prov_name, {}).get("models", [])
        if cap_models and cap_models != ["*"]:
            for m in cap_models:
                if m not in models:
                    models.append(m)

        # 3. Add models from models-dev.json
        dev_models = list(self._models_dev.get(prov_name, {}).get("models", {}).keys())
        for m in dev_models:
            if m not in models:
                models.append(m)

        # 4. If list is still small or empty, and live key exists, fetch live models
        if (len(models) < 5 or declared == ["*"]) and api_key and base_url and base_url.startswith("http"):
            try:
                models_url = base_url.rstrip("/") + "/models"
                req = urllib.request.Request(models_url, headers={
                    "Authorization": f"Bearer {api_key}",
                    "User-Agent": "claude-master/1.0",
                })
                with urllib.request.urlopen(req, timeout=5) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    live_models = [m["id"] for m in data.get("data", []) if isinstance(m, dict) and "id" in m]
                    for lm in live_models:
                        if lm not in models:
                            models.append(lm)
            except Exception:
                pass

        return models

    def _audit_single_model(
        self,
        prov_name: str,
        base_url: str,
        env_var: Optional[str],
        api_key: str,
        priority: int,
        raw_model_id: str,
        live_probing: bool,
    ) -> None:
        """Probe, classify, resolve identity, and register route for a single model."""
        probes: List[EmpiricalProbeResult] = []
        measured_latency = 250.0
        status_code = 200

        # Perform live probe if credentials, live mode enabled, and under probe budget
        probe_count = getattr(self, "_provider_probe_counts", {})
        current_probes = probe_count.get(prov_name, 0)
        should_live_probe = live_probing and api_key and base_url and base_url.startswith("http") and current_probes < 10

        if should_live_probe:
            probe_count[prov_name] = current_probes + 1
            self._provider_probe_counts = probe_count

            # Chat probe
            chat_probe = self.probe_chat_completion(base_url, api_key, raw_model_id)
            probes.append(chat_probe)
            measured_latency = chat_probe.latency_ms
            status_code = chat_probe.http_status

            # If chat probe was rejected with an error, check if it's embeddings or audio
            if chat_probe.http_status == 400 or chat_probe.http_status == 404:
                err_text = (chat_probe.error_message or "").lower()
                if "embed" in raw_model_id.lower() or "embedding" in err_text:
                    emb_probe = self.probe_embeddings(base_url, api_key, raw_model_id)
                    probes.append(emb_probe)

            # If chat succeeded and not guard, test tool calling
            elif chat_probe.has_text_content and not chat_probe.is_classification_output:
                tool_probe = self.probe_tool_calling(base_url, api_key, raw_model_id)
                probes.append(tool_probe)

                # Test vision if model has multimodal cues
                if any(k in raw_model_id.lower() for k in ["omni", "vl", "vision", "flash", "pro"]):
                    vis_probe = self.probe_vision(base_url, api_key, raw_model_id)
                    probes.append(vis_probe)

        # Extract catalog metadata from offline datasets if available
        meta = self._get_metadata(prov_name, raw_model_id)

        # Classify modalities and agentic capability
        classification = classify_from_probe(raw_model_id, prov_name, probes, meta)

        # Resolve Canonical Model Identity
        identity = self.resolver.resolve(prov_name, raw_model_id, meta)
        canonical_id = identity.canonical_id

        # Determine primary modality type
        primary_type = self._determine_primary_type(classification.modalities)

        # Build / update CanonicalModel
        if canonical_id not in self.models:
            ctx = self.lookup_context_window(raw_model_id, canonical_id)
            self.models[canonical_id] = CanonicalModel(
                canonical_id=canonical_id,
                display_name=identity.display_name,
                vendor=identity.vendor,
                family=identity.family,
                parameter_size=identity.parameter_size,
                type=primary_type,
                is_agentic=classification.is_agentic,
                modalities=classification.modalities,
                capabilities=classification.capabilities,
                context_window=ctx,
                routes=[],
                non_agentic_reason=classification.non_agentic_reason,
                empirical_evidence=classification.empirical_evidence,
            )
        else:
            # Merge modalities and capabilities across routes
            curr = self.models[canonical_id]
            curr.modalities = sorted(list(set(curr.modalities + classification.modalities)))
            for cap_k, cap_v in classification.capabilities.items():
                if cap_v:
                    curr.capabilities[cap_k] = True
            if classification.is_agentic:
                curr.is_agentic = True
                curr.non_agentic_reason = None

        # Build Route
        route_id = f"{prov_name}:{raw_model_id}"
        pricing = self.lookup_pricing(prov_name, raw_model_id, canonical_id)
        limits = self.lookup_rate_limits(prov_name, raw_model_id)

        route = Route(
            route_id=route_id,
            canonical_id=canonical_id,
            provider=prov_name,
            provider_model_id=raw_model_id,
            key_pool=env_var or "",
            base_url=base_url,
            pricing=asdict(pricing),
            measured_latency_ms=round(measured_latency, 2),
            rate_limits=asdict(limits),
            priority=priority,
            healthy=(status_code in (200, 429, 402)),  # 429 and 402 are rate/balance limits, route exists
            status_code=status_code,
            empirical_evidence=classification.empirical_evidence,
        )

        self.routes[route_id] = route
        if route_id not in self.models[canonical_id].routes:
            self.models[canonical_id].routes.append(route_id)

        # If non-agentic, record in misclassified evidence log
        if not classification.is_agentic:
            self.misclassified_non_agentic.append({
                "provider": prov_name,
                "model_id": raw_model_id,
                "canonical_id": canonical_id,
                "modalities": classification.modalities,
                "reason": classification.non_agentic_reason,
                "evidence": classification.empirical_evidence,
            })

    def _determine_primary_type(self, modalities: List[str]) -> str:
        """Determine primary model type label."""
        mods = set(modalities)
        if ModelModality.CLASSIFICATION_GUARD.value in mods:
            return "classification_guard"
        if ModelModality.EMBEDDINGS.value in mods:
            return "embeddings"
        if ModelModality.AUDIO_STT.value in mods:
            return "audio_stt"
        if ModelModality.AUDIO_TTS.value in mods:
            return "audio_tts"
        if ModelModality.IMAGE_GENERATION.value in mods:
            return "image_generation"
        if ModelModality.RERANK.value in mods:
            return "rerank"
        if ModelModality.VISION.value in mods and ModelModality.TOOL_CALLING.value in mods:
            return "multimodal"
        if ModelModality.TOOL_CALLING.value in mods:
            return "tool_calling"
        return "text_chat"

    def _get_metadata(self, provider: str, raw_model_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve cached metadata for model."""
        if raw_model_id in self._openrouter_models:
            return self._openrouter_models[raw_model_id]
        p_models = self._models_dev.get(provider, {}).get("models", {})
        if raw_model_id in p_models:
            return p_models[raw_model_id]
        if raw_model_id in self._litellm_prices:
            return self._litellm_prices[raw_model_id]
        return None

    def export_catalog(self, output_dir: Optional[Path] = None) -> Tuple[Path, Path]:
        """Save canonical models and routes to disk."""
        target_dir = output_dir or (self.root_dir / "data" / "catalog")
        target_dir.mkdir(parents=True, exist_ok=True)

        models_file = target_dir / "models.json"
        routes_file = target_dir / "routes.json"
        evidence_file = target_dir / "non_agentic_evidence.json"

        # Export models
        models_dict = {
            m_id: asdict(m) for m_id, m in self.models.items()
        }
        models_file.write_text(json.dumps(models_dict, indent=2), encoding="utf-8")

        # Export routes
        routes_dict = {
            r_id: asdict(r) for r_id, r in self.routes.items()
        }
        routes_file.write_text(json.dumps(routes_dict, indent=2), encoding="utf-8")

        # Export non-agentic evidence
        evidence_file.write_text(json.dumps(self.misclassified_non_agentic, indent=2), encoding="utf-8")

        logger.info(f"Saved {len(self.models)} canonical models to {models_file}")
        logger.info(f"Saved {len(self.routes)} routes to {routes_file}")
        logger.info(f"Saved {len(self.misclassified_non_agentic)} non-agentic records to {evidence_file}")

        return models_file, routes_file
