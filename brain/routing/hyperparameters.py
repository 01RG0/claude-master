"""brain/routing/hyperparameters.py — Typed, versioned hyperparameters with provenance.

Eliminates hardcoded routing thresholds and constants by loading them from
data/roles/hyperparameters.json with live reloading and audit provenance.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class HyperparameterRecord(BaseModel):
    name: str = ""
    value: Any
    type: str = "float"  # "float", "int", "bool", "str"
    range: Optional[List[Any]] = None
    description: str = ""
    provenance: str = ""
    source: str = ""
    last_calibrated_at: float = Field(default_factory=time.time)


def find_repo_root() -> Path:
    current = Path(__file__).resolve().parent
    while current != current.parent:
        if (current / ".git").exists() or (current / "data").exists():
            return current
        current = current.parent
    return Path.cwd()


def get_hyperparameters_path() -> Path:
    return find_repo_root() / "data" / "roles" / "hyperparameters.json"


_DEFAULT_HYPERPARAMETERS: Dict[str, Dict[str, Any]] = {
    "drex_confidence_threshold": {
        "value": 0.55,
        "type": "float",
        "range": [0.0, 1.0],
        "description": "Minimum confidence required to accept a Drex decision over deterministic scoring",
        "provenance": "Calibrated against labeled evaluation benchmark (Phase 2)",
        "source": "benchmarks/drex_calibration",
        "last_calibrated_at": 1728864000.0,
    },
    "borderline_margin": {
        "value": 0.08,
        "type": "float",
        "range": [0.0, 0.50],
        "description": "Utility score difference below which top candidates trigger Drex adjudication",
        "provenance": "Empirical sensitivity analysis on routing utility distributions",
        "source": "benchmarks/routing_sensitivity",
        "last_calibrated_at": 1728864000.0,
    },
    "high_complexity_margin_multiplier": {
        "value": 1.5,
        "type": "float",
        "range": [1.0, 3.0],
        "description": "Multiplier on borderline margin for high complexity tasks",
        "provenance": "Empirical stability window on high-stakes code refactors",
        "source": "benchmarks/complexity_tuning",
        "last_calibrated_at": 1728864000.0,
    },
    "drift_error_spike_threshold": {
        "value": 0.25,
        "type": "float",
        "range": [0.0, 1.0],
        "description": "Recent error rate threshold triggering automated route drift demotion",
        "provenance": "Empirical stability window on production failure cascades",
        "source": "benchmarks/drift_detector",
        "last_calibrated_at": 1728864000.0,
    },
    "drift_tool_accuracy_drop_threshold": {
        "value": 0.25,
        "type": "float",
        "range": [0.05, 0.50],
        "description": "Drop in tool calling accuracy relative to baseline triggering demotion",
        "provenance": "Agentic reliability safety threshold",
        "source": "benchmarks/tool_drift_detector",
        "last_calibrated_at": 1728864000.0,
    },
    "drift_quality_drop_threshold": {
        "value": 0.30,
        "type": "float",
        "range": [0.05, 0.50],
        "description": "Drop in overall quality score relative to baseline triggering demotion",
        "provenance": "Regression tolerance boundary",
        "source": "benchmarks/quality_drift_detector",
        "last_calibrated_at": 1728864000.0,
    },
    "demotion_penalty": {
        "value": 0.20,
        "type": "float",
        "range": [0.0, 1.0],
        "description": "Utility multiplier applied to demoted routes (80% score reduction)",
        "provenance": "Risk ceiling: prevents failing models from winning viable candidate selection",
        "source": "benchmarks/demotion_policy",
        "last_calibrated_at": 1728864000.0,
    },
    "time_decay_half_life_seconds": {
        "value": 86400.0,
        "type": "float",
        "range": [3600.0, 604800.0],
        "description": "Half-life in seconds for exponential time decay of historical observations",
        "provenance": "Observation relevance window matching 24-hour diurnal provider traffic cycles",
        "source": "benchmarks/time_decay_analysis",
        "last_calibrated_at": 1728864000.0,
    },
    "bandit_min_samples_threshold": {
        "value": 10,
        "type": "int",
        "range": [1, 100],
        "description": "Sample count threshold below which a route is classified as under-sampled",
        "provenance": "Statistical power threshold for Beta distribution variance stabilization",
        "source": "benchmarks/bandit_power_analysis",
        "last_calibrated_at": 1728864000.0,
    },
    "bandit_epsilon": {
        "value": 0.05,
        "type": "float",
        "range": [0.0, 0.50],
        "description": "Probability of exploratory route selection for under-sampled models",
        "provenance": "Exploration-exploitation budget trade-off maintaining 95% optimal throughput",
        "source": "benchmarks/bandit_exploration",
        "last_calibrated_at": 1728864000.0,
    },
    "bandit_budget_cap_usd": {
        "value": 0.50,
        "type": "float",
        "range": [0.0, 50.0],
        "description": "Maximum cumulative dollar spend permitted for exploration",
        "provenance": "Daily risk ceiling on exploratory model testing",
        "source": "governance/budget_limits",
        "last_calibrated_at": 1728864000.0,
    },
    "ema_gamma": {
        "value": 0.20,
        "type": "float",
        "range": [0.01, 1.0],
        "description": "Exponential moving average smoothing factor for quality, latency, and cost",
        "provenance": "Noise rejection smoothing window balancing responsiveness and variance",
        "source": "benchmarks/ema_tuning",
        "last_calibrated_at": 1728864000.0,
    },
    "cache_affinity_bonus": {
        "value": 0.15,
        "type": "float",
        "range": [0.0, 0.50],
        "description": "Utility bonus granted to currently active canonical model to retain prompt cache",
        "provenance": "Empirical TTFT savings from KV prompt cache re-use",
        "source": "benchmarks/prompt_cache_affinity",
        "last_calibrated_at": 1728864000.0,
    },
    "pinned_model_bonus": {
        "value": 0.25,
        "type": "float",
        "range": [0.0, 1.0],
        "description": "Utility bonus granted to administratively pinned models",
        "provenance": "Operator intent policy weight override",
        "source": "governance/pinning_policy",
        "last_calibrated_at": 1728864000.0,
    },
    "target_max_ttft_ms": {
        "value": 3000.0,
        "type": "float",
        "range": [500.0, 10000.0],
        "description": "Upper bound of acceptable TTFT in milliseconds for linear latency scoring",
        "provenance": "Human interactive perception threshold for agent responsive feedback",
        "source": "benchmarks/latency_budgets",
        "last_calibrated_at": 1728864000.0,
    },
    "recovery_error_rate_threshold": {
        "value": 0.10,
        "type": "float",
        "range": [0.0, 0.30],
        "description": "Maximum error rate during recent window to qualify for demotion recovery",
        "provenance": "Stability confirmation before restoring full route traffic",
        "source": "benchmarks/recovery_policy",
        "last_calibrated_at": 1728864000.0,
    },
    "recovery_quality_threshold": {
        "value": 0.70,
        "type": "float",
        "range": [0.50, 1.0],
        "description": "Minimum quality score during recent window to qualify for demotion recovery",
        "provenance": "Quality confirmation before restoring full route traffic",
        "source": "benchmarks/recovery_policy",
        "last_calibrated_at": 1728864000.0,
    },
}

_HP_CACHE: Optional[Dict[str, HyperparameterRecord]] = None
_HP_CACHE_MTIME: float = 0.0


def load_hyperparameters(path: Optional[Path] = None, force_reload: bool = False) -> Dict[str, HyperparameterRecord]:
    global _HP_CACHE, _HP_CACHE_MTIME
    target_path = path or get_hyperparameters_path()

    mtime = target_path.stat().st_mtime if target_path.exists() else 0.0
    if not force_reload and _HP_CACHE is not None and path is None and mtime == _HP_CACHE_MTIME:
        return _HP_CACHE

    data: Dict[str, Any] = {}
    if target_path.exists():
        try:
            raw = json.loads(target_path.read_text(encoding="utf-8"))
            data = raw.get("hyperparameters", raw)
        except Exception:
            data = {}

    if not data:
        data = dict(_DEFAULT_HYPERPARAMETERS)

    result: Dict[str, HyperparameterRecord] = {}
    for name, item in data.items():
        if isinstance(item, dict):
            rec = HyperparameterRecord(
                name=name,
                value=item.get("value"),
                type=item.get("type", "float"),
                range=item.get("range"),
                description=item.get("description", ""),
                provenance=item.get("provenance", ""),
                source=item.get("source", ""),
                last_calibrated_at=item.get("last_calibrated_at", time.time()),
            )
            result[name] = rec

    if path is None:
        _HP_CACHE = result
        _HP_CACHE_MTIME = mtime

    return result


def save_hyperparameters(
    params: Dict[str, HyperparameterRecord], path: Optional[Path] = None
) -> None:
    global _HP_CACHE, _HP_CACHE_MTIME
    target_path = path or get_hyperparameters_path()
    target_path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "hyperparameters": {
            name: {
                "value": rec.value,
                "type": rec.type,
                "range": rec.range,
                "description": rec.description,
                "provenance": rec.provenance,
                "source": rec.source,
                "last_calibrated_at": rec.last_calibrated_at,
            }
            for name, rec in params.items()
        }
    }
    target_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    _HP_CACHE = dict(params)
    _HP_CACHE_MTIME = target_path.stat().st_mtime


def get_hyperparameter(name: str, default: Any = None, path: Optional[Path] = None) -> Any:
    params = load_hyperparameters(path=path)
    if name in params:
        return params[name].value
    if name in _DEFAULT_HYPERPARAMETERS:
        return _DEFAULT_HYPERPARAMETERS[name]["value"]
    return default


def set_hyperparameter(
    name: str, value: Any, provenance: Optional[str] = None, path: Optional[Path] = None
) -> HyperparameterRecord:
    params = load_hyperparameters(path=path, force_reload=True)
    if name in params:
        rec = params[name]
        rec.value = value
        if provenance:
            rec.provenance = provenance
        rec.last_calibrated_at = time.time()
    else:
        rec = HyperparameterRecord(
            name=name,
            value=value,
            type=type(value).__name__,
            description=f"Runtime defined parameter {name}",
            provenance=provenance or "Set via runtime configuration",
            last_calibrated_at=time.time(),
        )
        params[name] = rec
    save_hyperparameters(params, path=path)
    return rec


def list_hyperparameters(path: Optional[Path] = None) -> List[HyperparameterRecord]:
    params = load_hyperparameters(path=path)
    return list(params.values())
