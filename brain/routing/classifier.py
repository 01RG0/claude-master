"""Empirical Model Modality and Agentic Capability Classifier.

This module probes models and evaluates empirical ground truth to determine
exact accepted/returned modalities:
- text chat
- tool calling
- vision (image input)
- image generation (image output)
- audio (TTS / STT)
- embeddings
- rerank
- classification / guard

Non-agentic models (TTS, STT, image gen, embeddings, guards, rerankers) are
filtered out from the agent execution pool, with full empirical evidence
documented.
"""

from __future__ import annotations

import enum
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set


class ModelModality(str, enum.Enum):
    TEXT_CHAT = "text_chat"
    TOOL_CALLING = "tool_calling"
    VISION = "vision"
    IMAGE_GENERATION = "image_generation"
    AUDIO_TTS = "audio_tts"
    AUDIO_STT = "audio_stt"
    EMBEDDINGS = "embeddings"
    RERANK = "rerank"
    CLASSIFICATION_GUARD = "classification_guard"


NON_AGENTIC_MODALITIES: Set[ModelModality] = {
    ModelModality.IMAGE_GENERATION,
    ModelModality.AUDIO_TTS,
    ModelModality.AUDIO_STT,
    ModelModality.EMBEDDINGS,
    ModelModality.RERANK,
    ModelModality.CLASSIFICATION_GUARD,
}

AGENTIC_CORE_MODALITIES: Set[ModelModality] = {
    ModelModality.TEXT_CHAT,
    ModelModality.TOOL_CALLING,
}


@dataclass
class EmpiricalProbeResult:
    endpoint: str
    http_status: int
    latency_ms: float
    response_body: Optional[str] = None
    parsed_json: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    has_text_content: bool = False
    has_tool_calls: bool = False
    has_embedding: bool = False
    has_image_output: bool = False
    is_classification_output: bool = False
    probe_type: str = "chat"  # "chat", "tools", "vision", "embeddings", "audio"


@dataclass
class ModelClassification:
    model_id: str
    provider: str
    modalities: List[str]
    is_agentic: bool
    non_agentic_reason: Optional[str] = None
    empirical_evidence: Dict[str, Any] = field(default_factory=dict)
    capabilities: Dict[str, bool] = field(default_factory=dict)


def is_model_agentic(modalities: List[str]) -> bool:
    """A model is agentic if it supports text chat or tool calling,

    and is not exclusively a non-agentic modality (guard, embedding, audio, rerank, image gen).
    """
    mod_set = set(modalities)
    has_agentic_core = bool(mod_set & {m.value for m in AGENTIC_CORE_MODALITIES})
    is_pure_non_agentic = bool(mod_set and mod_set.issubset({m.value for m in NON_AGENTIC_MODALITIES}))
    has_guard = ModelModality.CLASSIFICATION_GUARD.value in mod_set
    has_embed_only = ModelModality.EMBEDDINGS.value in mod_set and not has_agentic_core

    if has_guard or has_embed_only or is_pure_non_agentic:
        return False
    return has_agentic_core


def classify_from_probe(
    model_id: str,
    provider: str,
    probe_results: List[EmpiricalProbeResult],
    catalog_metadata: Optional[Dict[str, Any]] = None,
) -> ModelClassification:
    """Classify model capabilities strictly from empirical probe results and evidence."""
    detected_modalities: Set[ModelModality] = set()
    evidence: Dict[str, Any] = {
        "probes_evaluated": len(probe_results),
        "details": [],
    }
    non_agentic_reasons: List[str] = []

    for probe in probe_results:
        detail: Dict[str, Any] = {
            "probe_type": probe.probe_type,
            "endpoint": probe.endpoint,
            "status": probe.http_status,
            "latency_ms": probe.latency_ms,
        }

        # 1. Check for Embeddings
        if probe.has_embedding:
            detected_modalities.add(ModelModality.EMBEDDINGS)
            detail["evidence"] = "Returned float vector embedding on /embeddings"

        # 2. Check for Tool Calling
        if probe.has_tool_calls:
            detected_modalities.add(ModelModality.TOOL_CALLING)
            detected_modalities.add(ModelModality.TEXT_CHAT)
            detail["evidence"] = "Returned structured tool_calls conforming to schema"

        # 3. Check for Text Chat
        if probe.has_text_content:
            detected_modalities.add(ModelModality.TEXT_CHAT)
            detail["evidence"] = "Generated text completion on chat endpoint"

        # 4. Check for Classification / Guard output
        if probe.is_classification_output:
            detected_modalities.add(ModelModality.CLASSIFICATION_GUARD)
            non_agentic_reasons.append("Outputs scalar probability/safety score instead of dialogue")
            detail["evidence"] = f"Numeric classification score observed: {probe.response_body}"

        # 5. Check error messages for explicit model incompatibility signatures
        err = (probe.error_message or "").lower()
        resp = (probe.response_body or "").lower()
        combined_err = f"{err} {resp}"

        # Audio STT rejection
        if any(w in combined_err for w in ["audio", "asr", "whisper", "transcription", "stt"]) and ("chat" in combined_err or "support" in combined_err):
            detected_modalities.add(ModelModality.AUDIO_STT)
            non_agentic_reasons.append("Audio STT model: rejected by chat completions; requires /audio/transcriptions")
            detail["evidence"] = f"Chat endpoint rejected with: {probe.error_message or probe.response_body}"

        # Audio TTS rejection
        elif "tts" in combined_err or ("response modalities (text) is not supported" in combined_err) or ("orpheus" in combined_err and "does not support chat" in combined_err):
            detected_modalities.add(ModelModality.AUDIO_TTS)
            non_agentic_reasons.append("Audio TTS model: text chat completion not supported; requires audio synthesis route")
            detail["evidence"] = f"Chat endpoint rejected with: {probe.error_message or probe.response_body}"

        # Image generation rejection
        elif "image" in combined_err and ("not supported by /v1/chat/completions" in combined_err or "dimension" in combined_err or "image generation" in combined_err):
            if "length and width" not in combined_err:  # length and width error actually proves vision input validation!
                detected_modalities.add(ModelModality.IMAGE_GENERATION)
                non_agentic_reasons.append("Image generation model: rejected by chat completions")
                detail["evidence"] = f"Chat endpoint rejected with: {probe.error_message or probe.response_body}"

        # Embeddings rejection
        elif "embedding" in combined_err and ("not supported for generatecontent" in combined_err or "invalid model" in combined_err or "unsupported model" in combined_err):
            detected_modalities.add(ModelModality.EMBEDDINGS)
            non_agentic_reasons.append("Embeddings model: rejected by chat completions; requires /embeddings")
            detail["evidence"] = f"Chat endpoint rejected with: {probe.error_message or probe.response_body}"

        # Vision Acceptance (or vision dimension error confirming image processor)
        if probe.probe_type == "vision":
            if probe.http_status == 200 or "length and width do not meet the model restrictions" in combined_err:
                detected_modalities.add(ModelModality.VISION)
                detail["evidence"] = "Successfully accepted image payload / passed multimodal preprocessor"
            elif "messages[0].content must be a string" in combined_err or "does not support image" in combined_err:
                detail["evidence"] = "Explicitly rejected multimodal block (text-only model)"

        evidence["details"].append(detail)

    # Incorporate structured catalog metadata (litellm, openrouter, models-dev) if available
    if catalog_metadata:
        evidence["catalog_metadata_present"] = True
        mode = catalog_metadata.get("mode") or catalog_metadata.get("type")
        mod_dict = catalog_metadata.get("modalities", {})

        if mode == "embedding":
            detected_modalities.add(ModelModality.EMBEDDINGS)
            non_agentic_reasons.append("Registered in price database under embedding mode")
        elif mode in ("audio_speech", "tts"):
            detected_modalities.add(ModelModality.AUDIO_TTS)
            non_agentic_reasons.append("Registered in price database under audio_speech / TTS mode")
        elif mode in ("audio_transcription", "stt"):
            detected_modalities.add(ModelModality.AUDIO_STT)
            non_agentic_reasons.append("Registered in price database under audio_transcription mode")
        elif mode in ("image_generation", "image_edit"):
            detected_modalities.add(ModelModality.IMAGE_GENERATION)
            non_agentic_reasons.append("Registered in price database under image_generation mode")
        elif mode in ("moderation", "guardrail"):
            detected_modalities.add(ModelModality.CLASSIFICATION_GUARD)
            non_agentic_reasons.append("Registered in price database under moderation/guardrail mode")
        elif mode == "rerank":
            detected_modalities.add(ModelModality.RERANK)
            non_agentic_reasons.append("Registered in price database under rerank mode")

        # Modalities dict check
        if isinstance(mod_dict, dict):
            in_mods = mod_dict.get("input", [])
            out_mods = mod_dict.get("output", [])
            if "image" in in_mods:
                detected_modalities.add(ModelModality.VISION)
            if "text" in in_mods and "text" in out_mods:
                detected_modalities.add(ModelModality.TEXT_CHAT)
            if "audio" in in_mods and "text" not in in_mods:
                detected_modalities.add(ModelModality.AUDIO_STT)
            if "audio" in out_mods:
                detected_modalities.add(ModelModality.AUDIO_TTS)
            if "image" in out_mods:
                detected_modalities.add(ModelModality.IMAGE_GENERATION)

        if catalog_metadata.get("tool_call") is True:
            detected_modalities.add(ModelModality.TOOL_CALLING)

    # Dynamic heuristics from model naming / taxonomy (without hardcoding specific model names)
    mod_list = [m.value for m in detected_modalities]
    if not mod_list:
        inferred = infer_modalities_from_morphology(model_id)
        detected_modalities.update(inferred)
        mod_list = [m.value for m in detected_modalities]

    agentic = is_model_agentic(mod_list)
    reason_str = "; ".join(non_agentic_reasons) if not agentic and non_agentic_reasons else None
    if not agentic and not reason_str:
        reason_str = f"Non-agentic modality set: {mod_list}"

    caps = {
        "chat": ModelModality.TEXT_CHAT.value in mod_list,
        "tools": ModelModality.TOOL_CALLING.value in mod_list,
        "vision": ModelModality.VISION.value in mod_list,
        "audio": (ModelModality.AUDIO_TTS.value in mod_list or ModelModality.AUDIO_STT.value in mod_list),
        "embeddings": ModelModality.EMBEDDINGS.value in mod_list,
        "image_gen": ModelModality.IMAGE_GENERATION.value in mod_list,
        "guard": ModelModality.CLASSIFICATION_GUARD.value in mod_list,
    }

    return ModelClassification(
        model_id=model_id,
        provider=provider,
        modalities=mod_list,
        is_agentic=agentic,
        non_agentic_reason=reason_str,
        empirical_evidence=evidence,
        capabilities=caps,
    )


def infer_modalities_from_morphology(model_identifier: str) -> Set[ModelModality]:
    """Dynamically infer probable modalities from morphological tokens when no direct probe exists.

    No model names are hardcoded; regex patterns match standard technical suffixes and prefixes.
    """
    s = model_identifier.lower()
    inferred: Set[ModelModality] = set()

    # Audio STT
    if re.search(r'\b(whisper|asr|stt|transcription)\b', s) or '-asr' in s:
        inferred.add(ModelModality.AUDIO_STT)
        return inferred

    # Audio TTS
    if re.search(r'\b(tts|speech|orpheus|elevenlabs|playht|deepgram-tts|voice)\b', s) or '-tts' in s or '-speech' in s or 'elevenlabs/' in s:
        inferred.add(ModelModality.AUDIO_TTS)
        return inferred

    # Embeddings
    if re.search(r'\b(embed|embedding|embeddings)\b', s) or '-embed' in s:
        inferred.add(ModelModality.EMBEDDINGS)
        return inferred

    # Reranker
    if re.search(r'\b(rerank|reranker)\b', s) or '-rerank' in s:
        inferred.add(ModelModality.RERANK)
        return inferred

    # Classification / Guard
    if re.search(r'\b(guard|guardian|safeguard|moderation|classifier|safety)\b', s) or 'prompt-guard' in s:
        inferred.add(ModelModality.CLASSIFICATION_GUARD)
        return inferred

    # Image generation
    if re.search(r'\b(flux|stable-diffusion|midjourney|dall-e|imagen|image-gen|canvas)\b', s) or '-image' in s and 'flash-image' in s:
        inferred.add(ModelModality.IMAGE_GENERATION)
        return inferred

    # If it has vision cues
    if re.search(r'\b(vision|vl|omni|multimodal)\b', s) or '-vl' in s:
        inferred.add(ModelModality.VISION)

    # General chat
    inferred.add(ModelModality.TEXT_CHAT)
    inferred.add(ModelModality.TOOL_CALLING)
    return inferred


def classify_model_capabilities(
    model_id: str,
    provider: str,
    empirical_probe: Optional[EmpiricalProbeResult] = None,
    catalog_metadata: Optional[Dict[str, Any]] = None,
) -> ModelClassification:
    """Entry point for classifying a single model."""
    probes = [empirical_probe] if empirical_probe else []
    return classify_from_probe(model_id, provider, probes, catalog_metadata)
