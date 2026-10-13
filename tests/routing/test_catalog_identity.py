"""Unit tests for empirical model classification and canonical identity resolution.

Tests:
1. Classification precision and recall over agentic vs non-agentic modalities.
2. Empirical probe response interpretation (chat, tools, vision, embeddings, audio, guards).
3. Dynamic canonical identity resolution across multiple aggregators without hardcoding.
4. Multi-route aggregation and catalog structure validation.
5. Zero secrets exposure in catalog data structures.
"""

import json
from pathlib import Path
from typing import Dict, List, Set

import pytest

from brain.routing.classifier import (
    ModelModality,
    NON_AGENTIC_MODALITIES,
    EmpiricalProbeResult,
    ModelClassification,
    classify_from_probe,
    is_model_agentic,
    infer_modalities_from_morphology,
)
from brain.routing.identity import (
    CanonicalIdentityResolver,
    resolve_canonical_identity,
)
from brain.routing.catalog import (
    CatalogAuditor,
    Route,
    CanonicalModel,
)
from brain.routing.scorer import (
    ModelScorer,
    QualityScore,
)


@pytest.fixture
def identity_resolver():
    return CanonicalIdentityResolver()


@pytest.fixture
def catalog_root():
    return Path(__file__).resolve().parent.parent.parent


class TestModelClassificationPrecisionRecall:
    """Test classification precision, recall, and empirical evidence evaluation."""

    def test_agentic_classification_rules(self):
        """Verify the agentic filtering rule across pure and mixed modality sets."""
        # Pure agentic modalities
        assert is_model_agentic([ModelModality.TEXT_CHAT.value]) is True
        assert is_model_agentic([ModelModality.TOOL_CALLING.value]) is True
        assert is_model_agentic([ModelModality.TEXT_CHAT.value, ModelModality.TOOL_CALLING.value]) is True
        assert is_model_agentic([ModelModality.TEXT_CHAT.value, ModelModality.VISION.value]) is True

        # Non-agentic pure modalities MUST be rejected
        for non_agentic_mod in NON_AGENTIC_MODALITIES:
            assert is_model_agentic([non_agentic_mod.value]) is False

        # Guardrails must ALWAYS be rejected even if text is present
        assert is_model_agentic([ModelModality.TEXT_CHAT.value, ModelModality.CLASSIFICATION_GUARD.value]) is False

        # Pure embeddings must be rejected
        assert is_model_agentic([ModelModality.EMBEDDINGS.value]) is False

    def test_probe_empirical_evidence_evaluation(self):
        """Verify empirical probe response interpretation for distinct failure/success signatures."""
        # 1. Successful Tool Calling probe
        tool_probe = EmpiricalProbeResult(
            endpoint="https://api.test.com/v1/chat/completions",
            http_status=200,
            latency_ms=210.0,
            has_tool_calls=True,
            probe_type="tools",
        )
        cls_tool = classify_from_probe("custom-agent-v1", "test-provider", [tool_probe])
        assert cls_tool.is_agentic is True
        assert ModelModality.TOOL_CALLING.value in cls_tool.modalities
        assert ModelModality.TEXT_CHAT.value in cls_tool.modalities

        # 2. Audio STT rejection error
        stt_probe = EmpiricalProbeResult(
            endpoint="https://api.test.com/v1/chat/completions",
            http_status=400,
            latency_ms=180.0,
            error_message='{"error":{"message":"The model `asr-proc-v1` does not support chat completions"}}',
            probe_type="chat",
        )
        cls_stt = classify_from_probe("asr-proc-v1", "test-provider", [stt_probe])
        assert cls_stt.is_agentic is False
        assert ModelModality.AUDIO_STT.value in cls_stt.modalities
        assert "Audio STT" in (cls_stt.non_agentic_reason or "")

        # 3. Audio TTS rejection error
        tts_probe = EmpiricalProbeResult(
            endpoint="https://api.test.com/v1/chat/completions",
            http_status=400,
            latency_ms=195.0,
            error_message="The requested combination of response modalities (TEXT) is not supported by the model.",
            probe_type="chat",
        )
        cls_tts = classify_from_probe("voice-synth-v2", "test-provider", [tts_probe])
        assert cls_tts.is_agentic is False
        assert ModelModality.AUDIO_TTS.value in cls_tts.modalities
        assert "Audio TTS" in (cls_tts.non_agentic_reason or "")

        # 4. Prompt Guard classification scalar output
        guard_probe = EmpiricalProbeResult(
            endpoint="https://api.test.com/v1/chat/completions",
            http_status=200,
            latency_ms=250.0,
            response_body="0.000919539",
            is_classification_output=True,
            probe_type="chat",
        )
        cls_guard = classify_from_probe("safety-moderator-v1", "test-provider", [guard_probe])
        assert cls_guard.is_agentic is False
        assert ModelModality.CLASSIFICATION_GUARD.value in cls_guard.modalities

        # 5. Embeddings vector output
        emb_probe = EmpiricalProbeResult(
            endpoint="https://api.test.com/v1/embeddings",
            http_status=200,
            latency_ms=95.0,
            has_embedding=True,
            probe_type="embeddings",
        )
        cls_emb = classify_from_probe("vector-embed-1024", "test-provider", [emb_probe])
        assert cls_emb.is_agentic is False
        assert ModelModality.EMBEDDINGS.value in cls_emb.modalities

    def test_precision_recall_metric_calculation(self):
        """Formally compute precision and recall across a labeled holdout evaluation set."""
        # Labeled test corpus: (identifier, metadata_dict, true_agentic_label)
        labeled_dataset = [
            # Agentic samples
            ("vendor-a/arch-70b-instruct", {"tool_call": True, "mode": "chat"}, True),
            ("vendor-b/fast-8b-chat", {"tool_call": True, "mode": "chat"}, True),
            ("vendor-c/code-32b-it", {"tool_call": True, "mode": "chat"}, True),
            ("vendor-d/multimodal-14b-vl", {"modalities": {"input": ["image", "text"], "output": ["text"]}}, True),
            ("vendor-e/reasoning-120b", {"tool_call": True, "mode": "chat"}, True),
            # Non-agentic samples: TTS
            ("voice-lab/speech-synth-v1", {"mode": "audio_speech"}, False),
            ("audio-team/orpheus-tts", {"mode": "tts"}, False),
            # Non-agentic samples: STT
            ("transcribe/whisper-asr-turbo", {"mode": "audio_transcription"}, False),
            ("audio-team/speech-to-text-v2", {"mode": "stt"}, False),
            # Non-agentic samples: Embeddings
            ("embed-lab/text-embedding-large", {"mode": "embedding"}, False),
            ("vector-ai/dense-embed-3", {"mode": "embedding"}, False),
            # Non-agentic samples: Image generation
            ("art-ai/diffusion-image-gen-v1", {"mode": "image_generation"}, False),
            ("pixel-lab/flux-image-edit", {"mode": "image_edit"}, False),
            # Non-agentic samples: Guards and Moderation
            ("safety-org/prompt-guard-classifier", {"mode": "guardrail"}, False),
            ("content-review/moderation-filter", {"mode": "moderation"}, False),
            # Non-agentic samples: Rerank
            ("search-team/document-rerank-v1", {"mode": "rerank"}, False),
        ]

        true_positives = 0
        false_positives = 0
        true_negatives = 0
        false_negatives = 0

        for mid, meta, expected_agentic in labeled_dataset:
            classification = classify_from_probe(mid, "test-prov", [], catalog_metadata=meta)
            predicted_agentic = classification.is_agentic

            if predicted_agentic and expected_agentic:
                true_positives += 1
            elif predicted_agentic and not expected_agentic:
                false_positives += 1
            elif not predicted_agentic and not expected_agentic:
                true_negatives += 1
            elif not predicted_agentic and expected_agentic:
                false_negatives += 1

        precision = true_positives / (true_positives + false_positives) if (true_positives + false_positives) > 0 else 0
        recall = true_positives / (true_positives + false_negatives) if (true_positives + false_negatives) > 0 else 0

        # Assert 100% precision and recall on the evaluation set
        assert precision == 1.0, f"Expected 1.0 precision, got {precision}"
        assert recall == 1.0, f"Expected 1.0 recall, got {recall}"
        assert false_positives == 0, "No non-agentic models should be misclassified as agentic"
        assert false_negatives == 0, "No agentic models should be falsely discarded"


class TestCanonicalIdentityResolution:
    """Test cross-aggregator canonical model identity resolution without hardcoded names."""

    def test_dynamic_aggregator_grouping(self, identity_resolver):
        """Verify identical underlying architectures served across distinct aggregators resolve to ONE canonical ID."""
        # Simulated multi-provider routes for the same underlying 70B model
        groq_variant = identity_resolver.resolve("groq", "llama-3.3-70b-versatile")
        cerebras_variant = identity_resolver.resolve("cerebras", "llama3.3-70b")
        openrouter_variant = identity_resolver.resolve("openrouter", "meta-llama/llama-3.3-70b-instruct")
        zenmux_variant = identity_resolver.resolve("zenmux", "meta-llama/llama-3.3-70b-instruct")

        # They must all resolve to the same canonical identity
        assert groq_variant.canonical_id == openrouter_variant.canonical_id
        assert cerebras_variant.canonical_id == openrouter_variant.canonical_id
        assert zenmux_variant.canonical_id == openrouter_variant.canonical_id
        assert groq_variant.vendor == "meta"
        assert groq_variant.parameter_size == "70b"

    def test_dynamic_version_and_size_extraction(self, identity_resolver):
        """Verify tokenizer and regex extraction on diverse version/size patterns."""
        cases = [
            ("cerebras", "gpt-oss-120b", "openai", "120b"),
            ("groq", "openai/gpt-oss-120b", "openai", "120b"),
            ("groq", "qwen/qwen3.8-27b", "qwen", "27b"),
            ("cerebras", "qwen-3.8-27b", "qwen", "27b"),
            ("alibaba", "qwen2.5-72b-instruct", "qwen", "72b"),
            ("dahl", "zai-org/GLM-5.3-Flash", "zhipu", None),
            ("dahl", "MiniMaxAI/MiniMax-M2.7", "minimax", None),
        ]

        for prov, raw_id, expected_vendor, expected_size in cases:
            res = identity_resolver.resolve(prov, raw_id)
            assert res.vendor == expected_vendor, f"Failed vendor for {raw_id}: expected {expected_vendor}, got {res.vendor}"
            if expected_size:
                assert res.parameter_size == expected_size, f"Failed size for {raw_id}: expected {expected_size}, got {res.parameter_size}"

    def test_canonical_slug_precedence(self, identity_resolver):
        """Ensure declared canonical metadata takes precedence when available."""
        meta = {"canonical_model_id": "deepseek/deepseek-v4-pro"}
        res = identity_resolver.resolve("custom-aggregator", "random-alias-v4", meta)
        assert res.canonical_id == "deepseek/deepseek-v4-pro"
        assert res.vendor == "deepseek"


class TestCatalogDataIntegrity:
    """Verify generated catalog files in data/catalog/."""

    def test_catalog_files_exist_and_non_empty(self, catalog_root):
        models_file = catalog_root / "data" / "catalog" / "models.json"
        routes_file = catalog_root / "data" / "catalog" / "routes.json"
        evidence_file = catalog_root / "data" / "catalog" / "non_agentic_evidence.json"

        assert models_file.exists(), "models.json must exist"
        assert routes_file.exists(), "routes.json must exist"
        assert evidence_file.exists(), "non_agentic_evidence.json must exist"

        models_data = json.loads(models_file.read_text(encoding="utf-8"))
        routes_data = json.loads(routes_file.read_text(encoding="utf-8"))
        evidence_data = json.loads(evidence_file.read_text(encoding="utf-8"))

        assert len(models_data) > 100, f"Expected >100 canonical models, got {len(models_data)}"
        assert len(routes_data) > 200, f"Expected >200 routes, got {len(routes_data)}"
        assert len(evidence_data) > 0, "Expected non-agentic evidence records"

    def test_route_model_referential_integrity(self, catalog_root):
        """Ensure every route references a valid canonical model and vice-versa."""
        models_data = json.loads((catalog_root / "data" / "catalog" / "models.json").read_text(encoding="utf-8"))
        routes_data = json.loads((catalog_root / "data" / "catalog" / "routes.json").read_text(encoding="utf-8"))

        for route_id, r in routes_data.items():
            cid = r["canonical_id"]
            assert cid in models_data, f"Route {route_id} points to non-existent canonical model {cid}"
            assert route_id in models_data[cid]["routes"], f"Route {route_id} not registered in canonical model {cid}"

    def test_no_keys_in_catalog(self, catalog_root):
        """CRITICAL: Ensure zero API key secrets are present in catalog files."""
        for fname in ["models.json", "routes.json", "non_agentic_evidence.json"]:
            text = (catalog_root / "data" / "catalog" / fname).read_text(encoding="utf-8")
            # Secrets patterns check
            assert "gsk_" not in text, f"Groq key leaked in {fname}"
            assert "sk-ant" not in text, f"Anthropic key leaked in {fname}"
            assert "dahl_" not in text, f"Dahl key leaked in {fname}"
            # Verify routes only contain key pool variable names
            if fname == "routes.json":
                data = json.loads(text)
                for rid, r in data.items():
                    pool = r.get("key_pool", "")
                    assert not pool.startswith("sk-") and not pool.startswith("gsk_"), f"Raw key leaked in key_pool of {rid}"


class TestUnmeasuredModelScorerAndPolicy:
    """Requirement 7: Verify Bayesian cold-start priors, uncertainty variance,

    early stopping bounds, and bandit exploration bonuses for unmeasured models.
    """

    def test_cold_start_prior_policy(self):
        scorer = ModelScorer()

        # Tier 1 with large parameter scale (e.g. 70b)
        score_large = scorer.get_or_create_score("vendor-a/arch-70b-instruct", vendor="openai", family="arch", parameter_size="70b")
        assert score_large.is_cold_start is True
        assert score_large.samples_count == 0
        assert score_large.mean_quality >= 0.85
        # High uncertainty / wide initial variance
        assert score_large.variance >= 0.010
        assert (score_large.ci_upper - score_large.ci_lower) > 0.30

        # Tier 3 with small parameter scale (e.g. 3b)
        score_small = scorer.get_or_create_score("vendor-c/arch-3b", vendor="community", family="arch", parameter_size="3b")
        assert score_small.mean_quality < score_large.mean_quality
        assert score_small.is_cold_start is True

    def test_bandit_exploration_bonus(self):
        scorer = ModelScorer(exploration_weight=0.40)

        # Unmeasured model gets high exploration bonus due to high variance
        unmeasured = scorer.get_or_create_score("new-vendor/novel-model", vendor="google", family="novel", parameter_size="27b")
        assert unmeasured.exploration_bonus > 0.15

        # Record observations: observations narrow variance and decay exploration bonus
        for _ in range(10):
            scorer.record_feedback("new-vendor/novel-model", success=True)

        measured = scorer.scores["new-vendor/novel-model"]
        assert measured.samples_count == 10
        assert measured.is_cold_start is False
        assert measured.variance < unmeasured.variance
        assert measured.exploration_bonus < unmeasured.exploration_bonus

    def test_early_stopping_criteria(self):
        scorer = ModelScorer()
        mid = "eval-lab/test-model"

        # Initially cannot early stop (no samples)
        assert scorer.can_early_stop(mid) is False

        # Accumulate consistent positive evaluations
        for _ in range(15):
            scorer.record_feedback(mid, success=True)

        score = scorer.scores[mid]
        ci_width = score.ci_upper - score.ci_lower
        # CI has narrowed sufficiently -> early stop allowed!
        assert ci_width <= scorer.EARLY_STOPPING_CI_WIDTH
        assert scorer.can_early_stop(mid) is True


class TestDynamicRoutingEngine:
    """Verify dynamic route selection with cold-start exploration under budget."""

    def test_routing_with_cold_start_exploration(self):
        from brain.routing.catalog import CanonicalModel, Route
        from brain.routing.engine import DynamicRoutingEngine, RoutingRequirements

        # Setup mock models
        models = {
            "meta/llama-3.3-70b-instruct": CanonicalModel(
                canonical_id="meta/llama-3.3-70b-instruct",
                display_name="Llama 3.3 70B",
                vendor="meta",
                family="llama-3.3",
                parameter_size="70b",
                type="tool_calling",
                is_agentic=True,
                modalities=["text_chat", "tool_calling"],
                capabilities={"chat": True, "tools": True, "vision": False},
                context_window=128000,
                routes=["groq:llama-3.3-70b", "openrouter:llama-3.3-70b"],
            ),
            "novel/experimental-27b": CanonicalModel(
                canonical_id="novel/experimental-27b",
                display_name="Experimental 27B",
                vendor="deepseek",
                family="experimental",
                parameter_size="27b",
                type="tool_calling",
                is_agentic=True,
                modalities=["text_chat", "tool_calling"],
                capabilities={"chat": True, "tools": True, "vision": False},
                context_window=128000,
                routes=["openrouter:experimental-27b"],
            ),
            "audio/tts-voice": CanonicalModel(
                canonical_id="audio/tts-voice",
                display_name="TTS Voice",
                vendor="openai",
                family="tts",
                parameter_size=None,
                type="audio_tts",
                is_agentic=False,
                modalities=["audio_tts"],
                capabilities={"chat": False, "tools": False, "vision": False},
                context_window=4096,
                routes=["groq:tts-voice"],
            ),
        }

        routes = {
            "groq:llama-3.3-70b": Route(
                route_id="groq:llama-3.3-70b",
                canonical_id="meta/llama-3.3-70b-instruct",
                provider="groq",
                provider_model_id="llama-3.3-70b-versatile",
                key_pool="GROQ_API_KEY",
                base_url="https://api.groq.com/openai/v1",
                pricing={"prompt_per_m": 0.59, "completion_per_m": 0.79},
                measured_latency_ms=210.0,
                rate_limits={"rpm": 30},
                priority=10,
                healthy=True,
            ),
            "openrouter:llama-3.3-70b": Route(
                route_id="openrouter:llama-3.3-70b",
                canonical_id="meta/llama-3.3-70b-instruct",
                provider="openrouter",
                provider_model_id="meta-llama/llama-3.3-70b-instruct",
                key_pool="OPENROUTER_API_KEY",
                base_url="https://openrouter.ai/api/v1",
                pricing={"prompt_per_m": 0.59, "completion_per_m": 0.79},
                measured_latency_ms=850.0,
                rate_limits={"rpm": 200},
                priority=50,
                healthy=True,
            ),
            "openrouter:experimental-27b": Route(
                route_id="openrouter:experimental-27b",
                canonical_id="novel/experimental-27b",
                provider="openrouter",
                provider_model_id="novel/experimental-27b",
                key_pool="OPENROUTER_API_KEY",
                base_url="https://openrouter.ai/api/v1",
                pricing={"prompt_per_m": 0.10, "completion_per_m": 0.20},
                measured_latency_ms=300.0,
                rate_limits={"rpm": 200},
                priority=50,
                healthy=True,
            ),
            "groq:tts-voice": Route(
                route_id="groq:tts-voice",
                canonical_id="audio/tts-voice",
                provider="groq",
                provider_model_id="tts-voice",
                key_pool="GROQ_API_KEY",
                base_url="https://api.groq.com/openai/v1",
                pricing={"prompt_per_m": 0.50, "completion_per_m": 1.50},
                measured_latency_ms=150.0,
                rate_limits={"rpm": 30},
                priority=10,
                healthy=True,
            ),
        }

        engine = DynamicRoutingEngine(models, routes)

        # 1. Non-agentic models must NEVER be selected
        candidates = engine.filter_candidates(RoutingRequirements(require_tools=True))
        assert not any(c.canonical_id == "audio/tts-voice" for c in candidates)

        # 2. Routing decision picks the optimal route
        decision = engine.route_request(RoutingRequirements(require_tools=True, allow_exploration=True))
        assert decision is not None
        assert decision.selected_route_id in routes
        assert decision.expected_quality > 0.0

