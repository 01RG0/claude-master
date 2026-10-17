"""tests/routing/test_zero_retention_policy.py — Tests for Directive 6 Zero-Retention verification.

Verifies:
1. Provider policies registry contains verified evidence with official source URL, date, and exact terms
   for all supported providers: Groq, Cerebras, Mistral, Cohere, OpenRouter, Gemini.
2. Provenance validity checks: missing provenance, source URL, or verification date fails validation.
3. CandidateFilter strictly excludes non-compliant routes, unrecorded providers, and providers lacking provenance.
4. DynamicRouter end-to-end honors require_zero_retention and privacy_policy="zero_retention".
5. Route explanation captures zero-retention rejection provenance.
"""

import pytest
from brain.routing.privacy_policy import (
    get_provider_policy,
    has_valid_zero_retention_evidence,
    list_provider_policies,
    register_provider_policy,
    clear_policy_overrides,
)
from brain.routing.profiles import HardConstraints, RequirementProfile
from brain.routing.scorer import CandidateMetrics
from brain.routing.engine import (
    CandidateFilter,
    DynamicRouter,
    RouteRequest,
    TaskContext,
)


def _make_candidate(
    suffix: str,
    provider: str = "mock-provider-a",
    context: int = 65536,
    tools: bool = True,
    vision: bool = False,
    privacy: str = "zero_retention",
    quality: float = 0.80,
    ttft_ms: float = 300.0,
) -> CandidateMetrics:
    return CandidateMetrics(
        model_id=f"candidate-{suffix}",
        provider=provider,
        route_id=f"{provider}/candidate-{suffix}",
        context_window=context,
        pricing={"input_per_m": 0.50, "output_per_m": 1.50},
        capabilities={"tools": tools, "vision": vision, "streaming": True},
        privacy_policy=privacy,
        measured_quality=quality,
        measured_ttft_ms=ttft_ms,
    )


class TestProviderPoliciesEvidence:
    def teardown_method(self):
        clear_policy_overrides()

    def test_official_policies_recorded_for_supported_providers(self):
        """Directive 6 §2: Groq, Cerebras, Mistral, Cohere, OpenRouter, Gemini must have recorded policies."""
        required_providers = ["groq", "cerebras", "mistral", "cohere", "openrouter", "gemini"]
        all_policies = list_provider_policies()

        for prov in required_providers:
            assert prov in all_policies, f"Provider {prov} must be present in provider_policies.json"
            policy = all_policies[prov]
            assert policy.get("zero_retention_compliant") is True, f"{prov} must be marked compliant"
            assert policy.get("policy_tier") == "zero_retention"
            assert bool(policy.get("source_url")), f"{prov} must have an official source_url"
            assert policy["source_url"].startswith("http"), f"{prov} source_url must be a valid URL"
            assert bool(policy.get("verified_date")), f"{prov} must have a verified_date"
            assert bool(policy.get("provenance")), f"{prov} must have a provenance tag"
            assert bool(policy.get("exact_terms")), f"{prov} must have exact quoted terms"
            assert bool(policy.get("training_policy")), f"{prov} must have explicit training policy"
            assert has_valid_zero_retention_evidence(prov) is True

    def test_non_compliant_providers_rejected(self):
        """Public or unverified providers must fail zero-retention verification."""
        assert has_valid_zero_retention_evidence("alibaba") is False
        assert has_valid_zero_retention_evidence("aihubmix") is False
        assert has_valid_zero_retention_evidence("aihorde") is False
        assert has_valid_zero_retention_evidence("pollinations") is False
        assert has_valid_zero_retention_evidence("unknown-vendor-x") is False
        assert has_valid_zero_retention_evidence("") is False

    def test_provenance_validation_detects_incomplete_records(self):
        """Records missing provenance, source URL, or date must be rejected."""
        register_provider_policy("test-no-prov", {
            "provider": "test-no-prov",
            "zero_retention_compliant": True,
            "source_url": "https://example.com/terms",
            "verified_date": "2026-10-14",
            "provenance": "",  # missing
        })
        assert has_valid_zero_retention_evidence("test-no-prov") is False

        register_provider_policy("test-no-url", {
            "provider": "test-no-url",
            "zero_retention_compliant": True,
            "source_url": "",  # missing
            "verified_date": "2026-10-14",
            "provenance": "official_vendor_terms",
        })
        assert has_valid_zero_retention_evidence("test-no-url") is False

        register_provider_policy("test-no-date", {
            "provider": "test-no-date",
            "zero_retention_compliant": True,
            "source_url": "https://example.com/terms",
            "verified_date": "",  # missing
            "provenance": "official_vendor_terms",
        })
        assert has_valid_zero_retention_evidence("test-no-date") is False

        register_provider_policy("test-complete", {
            "provider": "test-complete",
            "zero_retention_compliant": True,
            "source_url": "https://example.com/terms",
            "verified_date": "2026-10-14",
            "provenance": "verified_dpa",
        })
        assert has_valid_zero_retention_evidence("test-complete") is True


class TestCandidateFilterStrictEnforcement:
    def setup_method(self):
        self.filter_engine = CandidateFilter()
        self.profile = RequirementProfile(
            name="test_zr_profile",
            hard_constraints=HardConstraints(
                tool_calling=True,
                min_context=4096,
                privacy="zero_retention",
                require_zero_retention=True,
            ),
        )
        self.task = TaskContext()

    def teardown_method(self):
        clear_policy_overrides()

    def test_excludes_unrecorded_provider_claiming_zero_retention(self):
        """Unverified provider claiming zero_retention must be rejected due to missing evidence."""
        c_verified = _make_candidate("groq", provider="groq")
        c_unverified = _make_candidate("unverified", provider="unverified-ai-corp")

        passed, rejections = self.filter_engine.filter([c_verified, c_unverified], self.profile, self.task)
        assert len(passed) == 1
        assert passed[0].route_id == c_verified.route_id
        assert c_unverified.route_id in rejections
        assert "zero_retention_unverified" in rejections[c_unverified.route_id]

    def test_excludes_public_providers(self):
        """Providers with public_data_only or retaining posture must be excluded."""
        c_verified = _make_candidate("cerebras", provider="cerebras")
        c_horde = _make_candidate("horde", provider="aihorde", privacy="public_data_only")
        c_poll = _make_candidate("poll", provider="pollinations", privacy="public_data_only")

        passed, rejections = self.filter_engine.filter([c_verified, c_horde, c_poll], self.profile, self.task)
        assert len(passed) == 1
        assert passed[0].route_id == c_verified.route_id
        assert c_horde.route_id in rejections
        assert c_poll.route_id in rejections

    def test_all_supported_verified_providers_pass(self):
        """All supported providers with recorded evidence pass CandidateFilter."""
        candidates = [
            _make_candidate("c-groq", provider="groq"),
            _make_candidate("c-cerebras", provider="cerebras"),
            _make_candidate("c-mistral", provider="mistral"),
            _make_candidate("c-cohere", provider="cohere"),
            _make_candidate("c-openrouter", provider="openrouter"),
            _make_candidate("c-gemini", provider="gemini"),
        ]
        passed, rejections = self.filter_engine.filter(candidates, self.profile, self.task)
        assert len(passed) == len(candidates)
        assert len(rejections) == 0

    def test_alibaba_aihubmix_pollinations_aihorde_strictly_excluded(self):
        """Directive 4: alibaba, aihubmix, pollinations, and aihorde must be strictly excluded under zero_retention."""
        c_groq = _make_candidate("groq", provider="groq")
        c_alibaba = _make_candidate("alibaba", provider="alibaba", privacy="zero_retention")
        c_aihubmix = _make_candidate("aihubmix", provider="aihubmix", privacy="zero_retention")
        c_poll = _make_candidate("poll", provider="pollinations", privacy="public_data_only")
        c_horde = _make_candidate("horde", provider="aihorde", privacy="public_data_only")

        passed, rejections = self.filter_engine.filter(
            [c_groq, c_alibaba, c_aihubmix, c_poll, c_horde],
            self.profile,
            self.task,
        )

        passed_route_ids = [c.route_id for c in passed]
        assert c_groq.route_id in passed_route_ids
        assert c_alibaba.route_id not in passed_route_ids
        assert c_aihubmix.route_id not in passed_route_ids
        assert c_poll.route_id not in passed_route_ids
        assert c_horde.route_id not in passed_route_ids

        assert c_alibaba.route_id in rejections
        assert c_aihubmix.route_id in rejections
        assert c_poll.route_id in rejections
        assert c_horde.route_id in rejections


class TestDynamicRouterZeroRetentionEndToEnd:
    def setup_method(self):
        self.router = DynamicRouter()

    def teardown_method(self):
        clear_policy_overrides()

    def test_route_request_with_require_zero_retention(self):
        """Router excludes non-compliant routes when require_zero_retention=True."""
        c_compliant = _make_candidate("compliant-1", provider="groq", quality=0.85)
        c_unverified = _make_candidate("unverified-1", provider="unverified-vendor", quality=0.99)
        c_public = _make_candidate("public-1", provider="aihorde", privacy="public_data_only", quality=0.95)

        self.router.set_candidate_pool([c_compliant, c_unverified, c_public])

        req = RouteRequest(
            prompt="Write a Python script to sort a list of numbers",
            require_zero_retention=True,
        )
        decision = self.router.route(req)

        assert decision.provider == "groq"
        assert decision.selected_model == "candidate-compliant-1"
        assert "unverified-vendor/candidate-unverified-1" not in decision.fallback_chain
        assert "aihorde/candidate-public-1" not in decision.fallback_chain

    def test_explain_contains_zero_retention_rejections(self):
        """Router explain trace records zero-retention rejection reasons."""
        c_compliant = _make_candidate("compliant-1", provider="cerebras", quality=0.85)
        c_unverified = _make_candidate("unverified-1", provider="unverified-vendor", quality=0.99)

        self.router.set_candidate_pool([c_compliant, c_unverified])

        req = RouteRequest(
            prompt="Process confidential user records",
            require_zero_retention=True,
        )
        decision = self.router.route(req)
        explanation = self.router.explain(decision.request_id)

        assert explanation is not None
        rejections = explanation.rejected_route_ids
        assert "unverified-vendor/candidate-unverified-1" in rejections
        assert "zero_retention_unverified" in rejections["unverified-vendor/candidate-unverified-1"]
