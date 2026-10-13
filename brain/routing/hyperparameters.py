"""brain/routing/hyperparameters.py — Typed, versioned hyperparameters with provenance.

Eliminates hardcoded routing thresholds and constants by loading them from
data/roles/hyperparameters.json with live reloading and audit provenance.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel


class HyperparameterRecord(BaseModel):
    name: str = ""
    value: Any
    type: str = "float"  # "float", "int", "bool", "str"
    range: Optional[List[Any]] = None
    description: str = ""
    provenance: str = ""
    source: str = ""
    calibration_status: str = "NOT MEASURED"
    last_calibrated_at: Optional[float] = None


def find_repo_root() -> Path:
    current = Path(__file__).resolve().parent
    while current != current.parent:
        if (current / ".git").exists() or (current / "data").exists():
            return current
        current = current.parent
    return Path.cwd()


def get_hyperparameters_path() -> Path:
    return find_repo_root() / "data" / "roles" / "hyperparameters.json"


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

    # Runtime policy must come from the checked-in configuration (or an
    # explicitly supplied caller default). Never silently fall back to a
    # second, code-embedded copy with unverifiable calibration provenance.

    result: Dict[str, HyperparameterRecord] = {}
    for name, item in data.items():
        if isinstance(item, dict):
            calibration_status = item.get("calibration_status", "NOT MEASURED")
            rec = HyperparameterRecord(
                name=name,
                value=item.get("value"),
                type=item.get("type", "float"),
                range=item.get("range"),
                description=item.get("description", ""),
                provenance=(
                    item.get("provenance", "")
                    if calibration_status != "NOT MEASURED"
                    else "NOT MEASURED"
                ),
                source=(
                    item.get("source", "")
                    if calibration_status != "NOT MEASURED"
                    else "NOT MEASURED"
                ),
                calibration_status=calibration_status,
                last_calibrated_at=item.get("last_calibrated_at"),
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
                "calibration_status": rec.calibration_status,
                "last_calibrated_at": rec.last_calibrated_at,
            }
            for name, rec in params.items()
        }
    }
    target_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    _HP_CACHE = dict(params)
    _HP_CACHE_MTIME = target_path.stat().st_mtime


_MISSING = object()


def get_hyperparameter(name: str, default: Any = _MISSING, path: Optional[Path] = None) -> Any:
    params = load_hyperparameters(path=path)
    if name in params:
        return params[name].value
    if default is not _MISSING:
        return default
    raise KeyError(f"Routing hyperparameter {name!r} is not configured; add it to data/roles/hyperparameters.json")


def set_hyperparameter(
    name: str, value: Any, provenance: Optional[str] = None, path: Optional[Path] = None
) -> HyperparameterRecord:
    params = load_hyperparameters(path=path, force_reload=True)
    if name in params:
        rec = params[name]
        rec.value = value
        if provenance:
            rec.provenance = provenance
        rec.calibration_status = "NOT MEASURED"
        rec.provenance = provenance or "Runtime configured; calibration NOT MEASURED"
        rec.last_calibrated_at = None
    else:
        rec = HyperparameterRecord(
            name=name,
            value=value,
            type=type(value).__name__,
            description=f"Runtime defined parameter {name}",
            provenance=provenance or "Runtime configured; calibration NOT MEASURED",
            source="runtime configuration",
            calibration_status="NOT MEASURED",
            last_calibrated_at=None,
        )
        params[name] = rec
    save_hyperparameters(params, path=path)
    return rec


def list_hyperparameters(path: Optional[Path] = None) -> List[HyperparameterRecord]:
    params = load_hyperparameters(path=path)
    return list(params.values())
