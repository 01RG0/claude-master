"""Canonical Model Identity Resolver.

Resolves heterogeneous provider model strings across aggregators (Groq, Cerebras,
OpenRouter, Dahl, ZenMux, Mistral, Dashscope, Gemini, etc.) into ONE canonical
model identity.

NO HARDCODED MODEL NAMES. Identity resolution is driven by:
1. Vendor/Creator morphological normalization
2. Architecture & version tokenization
3. Parameter scale extraction (e.g., 70b, 8b, 27b, 120b, 72b)
4. Flavor/Variant standardization (e.g., instruct, vision, coder)
5. Dataset canonical metadata (openrouter canonical_slug, models-dev canonical_model_id)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class CanonicalModelIdentity:
    canonical_id: str
    display_name: str
    vendor: str
    family: str
    version: Optional[str] = None
    parameter_size: Optional[str] = None
    variant: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class CanonicalIdentityResolver:
    """Dynamic model identity resolver across disparate provider nomenclatures."""

    VENDOR_ALIASES: Dict[str, str] = {
        "meta-llama": "meta",
        "meta": "meta",
        "mistralai": "mistralai",
        "mistral": "mistralai",
        "google": "google",
        "openai": "openai",
        "qwen": "qwen",
        "alibaba": "qwen",
        "dashscope": "qwen",
        "zai-org": "zhipu",
        "z-ai": "zhipu",
        "zhipuai": "zhipu",
        "deepseek-ai": "deepseek",
        "deepseek": "deepseek",
        "minimaxai": "minimax",
        "minimax": "minimax",
        "cohere": "cohere",
        "anthropic": "anthropic",
        "canopylabs": "canopy",
        "inclusionai": "inclusion",
        "meituan": "meituan",
        "xiaomi": "xiaomi",
    }

    # Suffixes that aggregators attach to chat models that mean "instruct"
    INSTRUCT_EQUIVALENT_SUFFIXES = (
        "-versatile",
        "-instant",
        "-latest",
        "-it",
        "-prime",
        "-default",
        "-free",
        "-preview",
        "-turbo",
        "-fallback",
        "-official",
    )

    def resolve(
        self,
        provider: str,
        raw_model_id: str,
        catalog_metadata: Optional[Dict[str, Any]] = None,
    ) -> CanonicalModelIdentity:
        """Resolve any provider model ID to a canonical model identity."""
        # 1. Check if high-confidence dataset canonical ID is already declared
        if catalog_metadata:
            declared_canonical = (
                catalog_metadata.get("canonical_model_id")
                or catalog_metadata.get("canonical_slug")
            )
            if declared_canonical:
                return self._build_from_canonical_slug(declared_canonical, catalog_metadata)

        # 2. Dynamic normalization of the raw identifier
        s = raw_model_id.strip()

        # Strip Google prefix: models/
        if s.startswith("models/"):
            s = s[len("models/"):]

        # Strip free/nitro tags
        s = re.sub(r":(free|nitro|extended|beta)$", "", s, flags=re.IGNORECASE)

        # Extract org prefix if explicitly present in model string (e.g. meta-llama/llama-3.3-70b-instruct)
        extracted_org: Optional[str] = None
        if "/" in s:
            parts = s.split("/", 1)
            extracted_org = parts[0].strip()
            s = parts[1].strip()

        # Normalize casing and punctuation
        s_clean = s.lower().replace("_", "-")

        # Separate concatenated numbers: llama3.1 -> llama-3.1, qwen2.5 -> qwen-2.5
        s_clean = re.sub(r"([a-zA-Z]+)(\d+\.\d+)", r"\1-\2", s_clean)
        # Separate parameter scale: 70b -> -70b if directly glued
        s_clean = re.sub(r"([a-zA-Z]+)(\d+)(b|m)\b", r"\1-\2\3", s_clean)

        # Extract parameter scale (e.g., 70b, 8b, 27b, 120b, 72b, 14b, 3b)
        param_match = re.search(r"\b(\d+(\.\d+)?)[bm]\b", s_clean)
        param_size = param_match.group(0) if param_match else None

        # Extract version number if present (e.g. 3.3, 3.1, 2.5, 4.0)
        version_match = re.search(r"\b\d+\.\d+\b", s_clean)
        version = version_match.group(0) if version_match else None

        # Detect vendor / creator
        vendor = self._detect_vendor(extracted_org, s_clean, provider)

        # Detect family
        family = self._detect_family(s_clean, vendor)

        # Standardize variant
        variant = self._standardize_variant(s_clean)
        if variant is None and any(k in family for k in ["llama", "qwen", "mistral"]):
            variant = "instruct"

        # Construct canonical ID
        # Format: {vendor}/{family}-{version/size/variant}
        core_tokens = [family]
        if version and version not in family:
            core_tokens.append(version)
        if param_size and param_size not in family:
            core_tokens.append(param_size)
        if variant and variant not in family and variant not in ("instruct",):
            core_tokens.append(variant)
        elif variant == "instruct" and not any(t.endswith("-instruct") for t in core_tokens):
            core_tokens.append("instruct")

        canonical_slug = f"{vendor}/" + "-".join(core_tokens)

        # Build display name
        display_name = f"{vendor.capitalize()} {canonical_slug.split('/')[-1].replace('-', ' ').title()}"

        return CanonicalModelIdentity(
            canonical_id=canonical_slug,
            display_name=display_name,
            vendor=vendor,
            family=family,
            version=version,
            parameter_size=param_size,
            variant=variant,
            metadata={"raw_model_id": raw_model_id, "provider": provider},
        )

    def _build_from_canonical_slug(self, slug: str, meta: Dict[str, Any]) -> CanonicalModelIdentity:
        slug_clean = slug.strip().lower().replace("_", "-")
        if "/" in slug_clean:
            org, rest = slug_clean.split("/", 1)
        else:
            org, rest = "community", slug_clean

        vendor = self.VENDOR_ALIASES.get(org, org)
        param_match = re.search(r"\b(\d+(\.\d+)?)[bm]\b", rest)
        param_size = param_match.group(0) if param_match else None
        version_match = re.search(r"\b\d+\.\d+\b", rest)
        version = version_match.group(0) if version_match else None

        canonical_id = f"{vendor}/{rest}"
        display_name = f"{vendor.capitalize()} {rest.replace('-', ' ').title()}"

        return CanonicalModelIdentity(
            canonical_id=canonical_id,
            display_name=display_name,
            vendor=vendor,
            family=rest.split("-")[0],
            version=version,
            parameter_size=param_size,
            metadata=meta,
        )

    def _detect_vendor(self, org: Optional[str], model_str: str, provider: str) -> str:
        if org:
            org_lower = org.lower()
            if org_lower in self.VENDOR_ALIASES:
                return self.VENDOR_ALIASES[org_lower]

        s = model_str.lower()
        if "llama" in s:
            return "meta"
        if "qwen" in s:
            return "qwen"
        if "mistral" in s or "ministral" in s or "codestral" in s:
            return "mistralai"
        if "gemini" in s or "gemma" in s:
            return "google"
        if "gpt" in s or "whisper" in s:
            return "openai"
        if "glm" in s:
            return "zhipu"
        if "deepseek" in s:
            return "deepseek"
        if "minimax" in s:
            return "minimax"
        if "command" in s:
            return "cohere"
        if "claude" in s:
            return "anthropic"
        if "grok" in s:
            return "xai"
        if "orpheus" in s:
            return "canopy"
        if "allam" in s:
            return "sdaia"

        # Fallback to provider if provider is the creator
        prov_lower = provider.lower()
        if prov_lower in self.VENDOR_ALIASES:
            return self.VENDOR_ALIASES[prov_lower]
        return prov_lower

    def _detect_family(self, model_str: str, vendor: str) -> str:
        s = model_str.lower()
        # Look for leading architecture token
        for fam in [
            "llama-3.3", "llama-3.1", "llama-3", "llama-2", "llama",
            "qwen-3.8", "qwen-3.7", "qwen-3.5", "qwen-2.5", "qwen-2", "qwen",
            "codestral", "ministral", "mistral-small", "mistral-large", "mistral-embed", "mistral",
            "gemini-2.5", "gemini-2.0", "gemini-1.5", "gemini", "gemma-4", "gemma-3", "gemma-2", "gemma",
            "gpt-oss", "gpt-4o", "gpt-4", "gpt-3.5",
            "glm-5.3", "glm-5.2", "glm-5", "glm-4", "glm",
            "deepseek-v4", "deepseek-v3", "deepseek-r1", "deepseek",
            "minimax-m2.7", "minimax",
            "command-r", "command-a", "command",
            "whisper", "orpheus",
        ]:
            if fam in s:
                return fam

        # Extract leading alphabetic token
        m = re.match(r"^([a-z]+(-[a-z]+)?)", s)
        if m:
            return m.group(1)
        return s.split("-")[0]

    def _standardize_variant(self, model_str: str) -> Optional[str]:
        s = model_str.lower()

        # Check for specialized variants
        if "coder" in s or "code" in s or "fim" in s:
            return "coder"
        if "vl" in s or "vision" in s:
            return "vision"
        if "flash" in s:
            return "flash"
        if "pro" in s:
            return "pro"
        if "image" in s:
            return "image"
        if "tts" in s or "speech" in s:
            return "tts"
        if "embed" in s:
            return "embedding"
        if "guard" in s:
            return "guard"

        # If it has any instruct equivalent or ends in instruct/it
        for suff in self.INSTRUCT_EQUIVALENT_SUFFIXES:
            if s.endswith(suff):
                return "instruct"
        if "-instruct" in s:
            return "instruct"

        return None


def resolve_canonical_identity(
    provider: str,
    raw_model_id: str,
    catalog_metadata: Optional[Dict[str, Any]] = None,
) -> CanonicalModelIdentity:
    """Convenience functional resolver."""
    resolver = CanonicalIdentityResolver()
    return resolver.resolve(provider, raw_model_id, catalog_metadata)
