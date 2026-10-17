// privacy_policy_test.go — Unit tests for Directive 6 Zero-Retention policy enforcement in Gateway.
package gateway

import (
	"testing"
)

func TestHasValidZeroRetentionEvidence(t *testing.T) {
	// Standard supported zero-retention providers must have verified evidence
	verifiedProviders := []string{
		"groq",
		"cerebras",
		"mistral",
		"cohere",
		"openrouter",
		"gemini",
		"xai",
		"mock-provider-a",
	}

	for _, p := range verifiedProviders {
		if !HasValidZeroRetentionEvidence(p) {
			t.Errorf("expected provider %q to have valid zero-retention evidence with provenance", p)
		}
		rec, ok := GetProviderPolicy(p)
		if !ok {
			t.Errorf("expected policy record for %q", p)
		}
		if !rec.ZeroRetentionCompliant {
			t.Errorf("expected %q to be zero_retention_compliant", p)
		}
		if rec.SourceURL == "" {
			t.Errorf("expected %q to have non-empty SourceURL", p)
		}
		if rec.VerifiedDate == "" {
			t.Errorf("expected %q to have non-empty VerifiedDate", p)
		}
		if rec.Provenance == "" {
			t.Errorf("expected %q to have non-empty Provenance", p)
		}
		if rec.ExactTerms == "" {
			t.Errorf("expected %q to have non-empty ExactTerms", p)
		}
	}

	// Non-compliant or public data only providers must fail verification
	nonCompliant := []string{
		"aihorde",
		"pollinations",
		"unknown_nonexistent_provider",
		"",
	}

	for _, p := range nonCompliant {
		if HasValidZeroRetentionEvidence(p) {
			t.Errorf("expected non-compliant provider %q to fail zero-retention evidence check", p)
		}
	}
}

func TestEligibleProviders_ZeroRetentionExclusion(t *testing.T) {
	cfg := &Config{
		Providers: []Provider{
			{Name: "groq", PrivacyPolicy: PrivacyZeroRetention, KeyPools: []KeyPool{{AccountLabel: "k"}}},
			{Name: "cerebras", PrivacyPolicy: PrivacyZeroRetention, KeyPools: []KeyPool{{AccountLabel: "k"}}},
			{Name: "mistral", PrivacyPolicy: PrivacyZeroRetention, KeyPools: []KeyPool{{AccountLabel: "k"}}},
			{Name: "cohere", PrivacyPolicy: PrivacyZeroRetention, KeyPools: []KeyPool{{AccountLabel: "k"}}},
			{Name: "openrouter", PrivacyPolicy: PrivacyZeroRetention, KeyPools: []KeyPool{{AccountLabel: "k"}}},
			{Name: "gemini", PrivacyPolicy: PrivacyZeroRetention, KeyPools: []KeyPool{{AccountLabel: "k"}}},
			// Provider claiming zero_retention in config, but lacking recorded provenance evidence:
			{Name: "unverified_third_party", PrivacyPolicy: PrivacyZeroRetention, KeyPools: []KeyPool{{AccountLabel: "k"}}},
			// Public data only provider:
			{Name: "aihorde", PrivacyPolicy: PrivacyPublicDataOnly, KeyPools: []KeyPool{{AccountLabel: "k"}}},
			{Name: "pollinations", PrivacyPolicy: PrivacyPublicDataOnly, KeyPools: []KeyPool{{AccountLabel: "k"}}},
		},
		Routing: RoutingConfig{
			GitHubModelsFallback: false,
		},
	}

	// Under normal public routing:
	publicPrimary, _ := EligibleProviders(cfg, PrivacyClassPublic)
	// Should include everything enabled (except disabled)
	if len(publicPrimary) != len(cfg.Providers) {
		t.Fatalf("expected all %d providers in public mode, got %d", len(cfg.Providers), len(publicPrimary))
	}

	// Under zero-retention enforcement:
	zrPrimary, _ := EligibleProviders(cfg, PrivacyClassZeroRetention)

	// Unverified provider, aihorde, and pollinations must be strictly excluded
	names := make(map[string]bool)
	for _, p := range zrPrimary {
		names[p.Name] = true
	}

	if names["unverified_third_party"] {
		t.Errorf("unverified_third_party lacked recorded evidence with valid provenance and MUST be excluded")
	}
	if names["aihorde"] {
		t.Errorf("aihorde is public_data_only and MUST be excluded from zero-retention routing")
	}
	if names["pollinations"] {
		t.Errorf("pollinations is public_data_only and MUST be excluded from zero-retention routing")
	}

	// Verified providers must be present
	expectedVerified := []string{"groq", "cerebras", "mistral", "cohere", "openrouter", "gemini"}
	for _, exp := range expectedVerified {
		if !names[exp] {
			t.Errorf("expected verified zero-retention provider %q to be included", exp)
		}
	}
}

func TestEffectivePrivacyClass_ZeroRetentionMetadata(t *testing.T) {
	// 1. require_zero_retention: true
	req1 := &AnthropicRequest{
		Metadata: map[string]interface{}{
			"require_zero_retention": true,
		},
	}
	if !req1.RequiresZeroRetention() {
		t.Errorf("expected RequiresZeroRetention == true when require_zero_retention=true")
	}
	if EffectivePrivacyClass(req1) != PrivacyClassZeroRetention {
		t.Errorf("expected EffectivePrivacyClass == PrivacyClassZeroRetention")
	}

	// 2. privacy_policy: "zero_retention"
	req2 := &AnthropicRequest{
		Metadata: map[string]interface{}{
			"privacy_policy": "zero_retention",
		},
	}
	if !req2.RequiresZeroRetention() {
		t.Errorf("expected RequiresZeroRetention == true when privacy_policy=zero_retention")
	}
	if EffectivePrivacyClass(req2) != PrivacyClassZeroRetention {
		t.Errorf("expected EffectivePrivacyClass == PrivacyClassZeroRetention")
	}

	// 3. privacy_class: "zero_retention"
	req3 := &AnthropicRequest{
		Metadata: map[string]interface{}{
			"privacy_class": "zero_retention",
		},
	}
	if !req3.RequiresZeroRetention() {
		t.Errorf("expected RequiresZeroRetention == true when privacy_class=zero_retention")
	}
	if EffectivePrivacyClass(req3) != PrivacyClassZeroRetention {
		t.Errorf("expected EffectivePrivacyClass == PrivacyClassZeroRetention")
	}

	// 4. normal request without zero retention flags
	req4 := &AnthropicRequest{
		Metadata: map[string]interface{}{
			"user": "test-user",
		},
	}
	if req4.RequiresZeroRetention() {
		t.Errorf("expected RequiresZeroRetention == false for standard request")
	}
	if EffectivePrivacyClass(req4) == PrivacyClassZeroRetention {
		t.Errorf("expected EffectivePrivacyClass != PrivacyClassZeroRetention")
	}
}

func TestRegisterProviderPolicy_ProvenanceValidation(t *testing.T) {
	defer ClearPolicyOverrides()

	// Register a mock provider with missing provenance
	RegisterProviderPolicy(ProviderPolicyRecord{
		Provider:               "mock-missing-prov",
		ZeroRetentionCompliant: true,
		SourceURL:              "https://example.com",
		VerifiedDate:           "2026-10-14",
		Provenance:             "", // missing!
	})
	if HasValidZeroRetentionEvidence("mock-missing-prov") {
		t.Errorf("provider with empty provenance should not be accepted as valid evidence")
	}

	// Register a mock provider with missing source URL
	RegisterProviderPolicy(ProviderPolicyRecord{
		Provider:               "mock-missing-url",
		ZeroRetentionCompliant: true,
		SourceURL:              "", // missing!
		VerifiedDate:           "2026-10-14",
		Provenance:             "official_vendor_terms",
	})
	if HasValidZeroRetentionEvidence("mock-missing-url") {
		t.Errorf("provider with empty source_url should not be accepted as valid evidence")
	}

	// Register a mock provider with missing verified date
	RegisterProviderPolicy(ProviderPolicyRecord{
		Provider:               "mock-missing-date",
		ZeroRetentionCompliant: true,
		SourceURL:              "https://example.com",
		VerifiedDate:           "", // missing!
		Provenance:             "official_vendor_terms",
	})
	if HasValidZeroRetentionEvidence("mock-missing-date") {
		t.Errorf("provider with empty verified_date should not be accepted as valid evidence")
	}

	// Register a mock provider with full valid provenance
	RegisterProviderPolicy(ProviderPolicyRecord{
		Provider:               "mock-fully-proven",
		ZeroRetentionCompliant: true,
		SourceURL:              "https://example.com/verified-terms",
		VerifiedDate:           "2026-10-14",
		Provenance:             "verified_dpa",
	})
	if !HasValidZeroRetentionEvidence("mock-fully-proven") {
		t.Errorf("provider with complete provenance must pass validation")
	}
}
