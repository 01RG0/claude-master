"""brain/routing/profiles.py — Requirement profiles for dynamic model routing.

Completely decouples task roles from static model names. A requirement profile
defines hard constraints (capabilities, context, privacy, budget) and soft
objective weights (quality, TTFT, cost, reliability) used to score candidates.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class HardConstraints(BaseModel):
    tool_calling: bool = False
    min_context: int = 4096
    vision: bool = False
    max_budget_usd: float = 0.50
    privacy: str = "zero_retention"
    require_zero_retention: bool = False


class SoftObjectives(BaseModel):
    quality: float = Field(default=0.40, ge=0.0)
    ttft: float = Field(default=0.20, ge=0.0)
    cost: float = Field(default=0.20, ge=0.0)
    reliability: float = Field(default=0.20, ge=0.0)

    def normalized(self) -> "SoftObjectives":
        total = self.quality + self.ttft + self.cost + self.reliability
        if total <= 0.0:
            return SoftObjectives(quality=0.25, ttft=0.25, cost=0.25, reliability=0.25)
        return SoftObjectives(
            quality=round(self.quality / total, 4),
            ttft=round(self.ttft / total, 4),
            cost=round(self.cost / total, 4),
            reliability=round(self.reliability / total, 4),
        )


class RequirementProfile(BaseModel):
    name: str
    description: str = ""
    hard_constraints: HardConstraints = Field(default_factory=HardConstraints)
    soft_objectives: SoftObjectives = Field(default_factory=SoftObjectives)


def find_repo_root() -> Path:
    current = Path(__file__).resolve().parent
    while current != current.parent:
        if (current / ".git").exists() or (current / "data").exists():
            return current
        current = current.parent
    return Path.cwd()


def get_profiles_path() -> Path:
    return find_repo_root() / "data" / "roles" / "profiles.json"


_DEFAULT_PROFILES: Dict[str, Dict[str, Any]] = {
    "main": {
        "description": "General agentic coding and multi-turn problem solving",
        "hard_constraints": {
            "tool_calling": True,
            "min_context": 32768,
            "vision": False,
            "max_budget_usd": 0.10,
            "privacy": "zero_retention",
        },
        "soft_objectives": {
            "quality": 0.45,
            "ttft": 0.20,
            "cost": 0.15,
            "reliability": 0.20,
        },
    },
    "fast": {
        "description": "Low-latency lightweight queries, inline completions, and simple classification",
        "hard_constraints": {
            "tool_calling": False,
            "min_context": 8192,
            "vision": False,
            "max_budget_usd": 0.01,
            "privacy": "zero_retention",
        },
        "soft_objectives": {
            "quality": 0.15,
            "ttft": 0.50,
            "cost": 0.20,
            "reliability": 0.15,
        },
    },
    "subagent": {
        "description": "Autonomous subagent tool-calling and workflow orchestration",
        "hard_constraints": {
            "tool_calling": True,
            "min_context": 65536,
            "vision": False,
            "max_budget_usd": 0.08,
            "privacy": "zero_retention",
        },
        "soft_objectives": {
            "quality": 0.40,
            "ttft": 0.15,
            "cost": 0.20,
            "reliability": 0.25,
        },
    },
    "summarizer": {
        "description": "Long-context digestion, compression, and report generation",
        "hard_constraints": {
            "tool_calling": False,
            "min_context": 65536,
            "vision": False,
            "max_budget_usd": 0.03,
            "privacy": "zero_retention",
        },
        "soft_objectives": {
            "quality": 0.30,
            "ttft": 0.20,
            "cost": 0.40,
            "reliability": 0.10,
        },
    },
    "vision": {
        "description": "Multimodal visual reasoning, UI review, and diagram analysis",
        "hard_constraints": {
            "tool_calling": False,
            "min_context": 16384,
            "vision": True,
            "max_budget_usd": 0.08,
            "privacy": "zero_retention",
        },
        "soft_objectives": {
            "quality": 0.45,
            "ttft": 0.20,
            "cost": 0.15,
            "reliability": 0.20,
        },
    },
    "complex_reasoning": {
        "description": "Deep architecture, multi-file refactoring, and hard debugging",
        "hard_constraints": {
            "tool_calling": True,
            "min_context": 65536,
            "vision": False,
            "max_budget_usd": 0.20,
            "privacy": "zero_retention",
        },
        "soft_objectives": {
            "quality": 0.60,
            "ttft": 0.10,
            "cost": 0.10,
            "reliability": 0.20,
        },
    },
    "opus": {
        "description": "High-complexity reasoning, deep architecture, multi-file refactoring, and hard debugging",
        "hard_constraints": {
            "tool_calling": True,
            "min_context": 65536,
            "vision": False,
            "max_budget_usd": 0.20,
            "privacy": "zero_retention",
        },
        "soft_objectives": {
            "quality": 0.60,
            "ttft": 0.10,
            "cost": 0.10,
            "reliability": 0.20,
        },
    },
    "sonnet": {
        "description": "Primary agentic coding, multi-turn tool calling and reasoning",
        "hard_constraints": {
            "tool_calling": True,
            "min_context": 32768,
            "vision": False,
            "max_budget_usd": 0.10,
            "privacy": "zero_retention",
        },
        "soft_objectives": {
            "quality": 0.45,
            "ttft": 0.20,
            "cost": 0.15,
            "reliability": 0.20,
        },
    },
    "haiku": {
        "description": "Ultra-fast lightweight queries, simple completions, and rapid triage",
        "hard_constraints": {
            "tool_calling": False,
            "min_context": 8192,
            "vision": False,
            "max_budget_usd": 0.01,
            "privacy": "zero_retention",
        },
        "soft_objectives": {
            "quality": 0.15,
            "ttft": 0.50,
            "cost": 0.20,
            "reliability": 0.15,
        },
    },
}


def load_profiles(path: Optional[Path] = None) -> Dict[str, RequirementProfile]:
    target_path = path or get_profiles_path()
    data: Dict[str, Any] = {}
    if target_path.exists():
        try:
            raw = json.loads(target_path.read_text(encoding="utf-8"))
            data = raw.get("profiles", raw)
        except Exception:
            data = {}

    if not data:
        data = dict(_DEFAULT_PROFILES)

    result: Dict[str, RequirementProfile] = {}
    for name, p in data.items():
        if isinstance(p, dict):
            profile = RequirementProfile(
                name=name,
                description=p.get("description", ""),
                hard_constraints=HardConstraints(**p.get("hard_constraints", {})),
                soft_objectives=SoftObjectives(**p.get("soft_objectives", {})).normalized(),
            )
            result[name] = profile
    return result


def save_profiles(profiles: Dict[str, RequirementProfile], path: Optional[Path] = None) -> None:
    target_path = path or get_profiles_path()
    target_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "profiles": {
            name: {
                "description": prof.description,
                "hard_constraints": prof.hard_constraints.model_dump(),
                "soft_objectives": prof.soft_objectives.model_dump(),
            }
            for name, prof in profiles.items()
        }
    }
    target_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def get_profile(name: str, path: Optional[Path] = None) -> RequirementProfile:
    profiles = load_profiles(path=path)
    if name in profiles:
        return profiles[name]
    # Fallback to main profile or generic defaults
    if "main" in profiles:
        return profiles["main"]
    return RequirementProfile(name=name)


def list_profiles(path: Optional[Path] = None) -> List[RequirementProfile]:
    profiles = load_profiles(path=path)
    return list(profiles.values())
