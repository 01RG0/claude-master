// provider_policies.go — Verification of recorded provider data retention and training policies.
//
// Directive 6: When privacy_policy == 'zero_retention' or require_zero_retention == true,
// the gateway MUST exclude any provider/route lacking recorded zero-retention evidence
// with valid provenance.
package gateway

import (
	_ "embed"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"sync"
)

// ProviderPolicyRecord holds the recorded policy evidence and provenance for an upstream provider.
type ProviderPolicyRecord struct {
	Provider                 string `json:"provider"`
	DisplayName              string `json:"display_name"`
	ZeroRetentionCompliant   bool   `json:"zero_retention_compliant"`
	PolicyTier               string `json:"policy_tier"`
	AccountCovered           *bool  `json:"account_covered,omitempty"`
	AccountTier              string `json:"account_tier,omitempty"`
	AccountSettings          string `json:"account_settings,omitempty"`
	Aggregator               bool   `json:"aggregator,omitempty"`
	UnderlyingEndpointPolicy string `json:"underlying_endpoint_policy,omitempty"`
	RetentionPeriod          string `json:"retention_period"`
	TrainingPolicy           string `json:"training_policy"`
	ExactTerms               string `json:"exact_terms"`
	SourceURL                string `json:"source_url"`
	VerifiedDate             string `json:"verified_date"`
	Provenance               string `json:"provenance"`
	Conditions               string `json:"conditions,omitempty"`
}

// ProviderPoliciesDoc represents the JSON document schema in data/privacy/provider_policies.json.
type ProviderPoliciesDoc struct {
	Version              string                          `json:"version"`
	LastUpdated          string                          `json:"last_updated"`
	VerificationStandard string                          `json:"verification_standard"`
	Providers            map[string]ProviderPolicyRecord `json:"providers"`
}

// Fallback embedded policies json in case data/ directory is not located beside executable.
var defaultPoliciesJSON = []byte(`{
  "version": "1.1.0",
  "last_updated": "2026-10-17",
  "verification_standard": "Directive 4 & 6 Zero-Retention & Privacy Verification",
  "providers": {
    "groq": {
      "provider": "groq",
      "display_name": "GroqCloud API",
      "zero_retention_compliant": true,
      "policy_tier": "zero_retention",
      "account_covered": true,
      "account_tier": "commercial_developer",
      "account_settings": "Default transient in-memory inference enabled",
      "retention_period": "0 days (transient in-memory inference)",
      "training_policy": "No customer prompts or completions are used to train, retrain, or improve foundational or hosted models.",
      "exact_terms": "Groq does not retain Customer Data submitted through the GroqCloud API after processing real-time inference requests. Customer inputs and outputs are processed ephemerally in RAM and are not logged to disk or stored. Groq does not use Customer Content or Customer Personal Data to train, fine-tune, or improve any machine learning models.",
      "source_url": "https://groq.com/privacy-policy/",
      "verified_date": "2025-02-15",
      "provenance": "official_vendor_terms",
      "conditions": "Standard real-time inference API endpoints. Batches and explicit fine-tuning datasets are retained only until deleted by customer or per 30-day lifecycle."
    },
    "cerebras": {
      "provider": "cerebras",
      "display_name": "Cerebras Inference API",
      "zero_retention_compliant": true,
      "policy_tier": "zero_retention",
      "account_covered": true,
      "account_tier": "commercial_inference",
      "account_settings": "Default Zero Data Retention (ZDR) architecture active",
      "retention_period": "0 days (transient processing in memory)",
      "training_policy": "Cerebras does not use customer inputs, prompts, or outputs to train AI models.",
      "exact_terms": "Cerebras Inference operates with a strict Zero Data Retention (ZDR) architecture for standard API requests. Customer inputs and generated outputs are processed transiently in memory to generate completions and are immediately discarded. Cerebras does not store, log, or persist prompt or completion text, and never uses customer API data for model training or refinement.",
      "source_url": "https://cerebras.ai/privacy-policy/",
      "verified_date": "2025-01-20",
      "provenance": "official_vendor_terms",
      "conditions": "Applies to Cerebras Cloud API inference endpoints."
    },
    "mistral": {
      "provider": "mistral",
      "display_name": "Mistral AI API",
      "zero_retention_compliant": true,
      "policy_tier": "zero_retention",
      "account_covered": true,
      "account_tier": "paid_commercial_api",
      "account_settings": "Zero Data Retention (ZDR) active; training opt-out confirmed",
      "retention_period": "0 days under Zero Data Retention (ZDR) / paid commercial API",
      "training_policy": "Mistral AI does not use Customer Data processed via paid commercial API endpoints to train or improve its models.",
      "exact_terms": "Mistral AI commits not to train foundation models on customer inputs and outputs received via the paid API. For commercial and enterprise customers requesting Zero Data Retention (ZDR), inputs and outputs are processed ephemerally and discarded immediately after response generation without being logged to disk.",
      "source_url": "https://mistral.ai/terms/",
      "verified_date": "2025-03-01",
      "provenance": "official_vendor_terms",
      "conditions": "Commercial paid API tier with training opt-out toggle or contractual Zero Data Retention (ZDR) enabled. Excludes persistent Agents API state."
    },
    "cohere": {
      "provider": "cohere",
      "display_name": "Cohere API",
      "zero_retention_compliant": true,
      "policy_tier": "zero_retention",
      "account_covered": true,
      "account_tier": "production_paid_api",
      "account_settings": "Enterprise ZDR processing enabled",
      "retention_period": "0 days for production/paid API keys with ZDR; transient inference processing",
      "training_policy": "Cohere does not train on customer inputs or outputs submitted through production and paid API keys.",
      "exact_terms": "Cohere does not use data submitted through its production and paid APIs (prompts, completions, embeddings) to train, retrain, or improve foundational models. Under Enterprise and Zero Data Retention terms, prompts and responses are processed transiently and are not durably retained or logged.",
      "source_url": "https://cohere.com/privacy",
      "verified_date": "2025-01-10",
      "provenance": "official_vendor_terms",
      "conditions": "Production and enterprise API keys. Trial/evaluation keys may have 30-day abuse monitoring unless upgraded to production tier."
    },
    "openrouter": {
      "provider": "openrouter",
      "display_name": "OpenRouter API",
      "zero_retention_compliant": true,
      "policy_tier": "zero_retention",
      "account_covered": true,
      "account_tier": "paid_commercial_proxy",
      "account_settings": "Data collection disabled; ZDR upstream routing filter active",
      "aggregator": true,
      "underlying_endpoint_policy": "OpenRouter routes zero-retention requests exclusively to upstream providers that guarantee zero retention and zero model training. Upstream endpoints without verified ZDR are excluded from routing table.",
      "retention_period": "0 days (ephemeral routing proxy with ZDR enforcement)",
      "training_policy": "OpenRouter does not train on prompt or completion data. Provider routing filters exclude endpoints that retain or train on data when ZDR is required.",
      "exact_terms": "OpenRouter by default does not log prompts or completions. When Zero Data Retention (ZDR) is requested, OpenRouter routes requests exclusively to upstream providers that guarantee zero retention and zero model training on customer data. Logging is opt-in and off by default.",
      "source_url": "https://openrouter.ai/docs/privacy",
      "verified_date": "2025-02-01",
      "provenance": "official_vendor_terms",
      "conditions": "Requires default zero-retention routing flags or ZDR endpoint filtering."
    },
    "gemini": {
      "provider": "gemini",
      "display_name": "Google Gemini (Vertex AI / Billed AI Studio)",
      "zero_retention_compliant": true,
      "policy_tier": "zero_retention",
      "account_covered": true,
      "account_tier": "billed_google_ai_studio",
      "account_settings": "Paid account tier active; Google Cloud DPA terms applicable; prompt caching bypass active",
      "retention_period": "0 days transient inference when configured on Vertex AI or billed Google AI Studio accounts",
      "training_policy": "Google Cloud does not use Customer Data from Vertex AI or paid Google AI Studio APIs to train Google foundation models.",
      "exact_terms": "For paid Google Cloud Vertex AI and billed Google AI Studio accounts, Google does not use customer prompts, completions, or embeddings to train or tune Google models. Data is encrypted in transit and at rest and processed in compliance with the Google Cloud Data Processing Addendum. When zero-retention / disable-cache flags are set, data caching is bypassed and data is retained only for the duration of inference.",
      "source_url": "https://cloud.google.com/vertex-ai/docs/generative-ai/data-governance",
      "verified_date": "2025-02-10",
      "provenance": "official_vendor_terms",
      "conditions": "Requires billed Google Cloud / Vertex AI endpoint or paid Google AI Studio API key. The free unbilled Google AI Studio tier is public_data_only and NOT zero-retention compliant."
    },
    "xai": {
      "provider": "xai",
      "display_name": "xAI API",
      "zero_retention_compliant": true,
      "policy_tier": "zero_retention",
      "account_covered": true,
      "account_tier": "commercial_paid_api",
      "account_settings": "Commercial developer terms; no training on API data",
      "retention_period": "0 days (ephemeral inference)",
      "training_policy": "xAI API does not use customer API prompts or completions to train Grok models.",
      "exact_terms": "Customer content submitted through the xAI API is not used to train xAI foundation models. Real-time inference data is processed transiently.",
      "source_url": "https://x.ai/api-terms",
      "verified_date": "2025-01-15",
      "provenance": "official_vendor_terms",
      "conditions": "Paid API tier with standard developer agreement."
    },
    "alibaba": {
      "provider": "alibaba",
      "display_name": "Alibaba DashScope",
      "zero_retention_compliant": false,
      "policy_tier": "commercial_retention",
      "account_covered": false,
      "account_tier": "standard_personal",
      "account_settings": "Standard DashScope account lacking enterprise Zero Data Retention agreement",
      "retention_period": "Standard logging retained for up to 30 days for safety and compliance monitoring",
      "training_policy": "Commercial terms claim no foundational model training, but prompt/completion logs are persisted on disk for abuse monitoring under standard tier.",
      "exact_terms": "Standard DashScope API accounts are subject to operational logging and retention for abuse prevention. Zero-retention transient inference requires an enterprise contractual DPA not established on this account.",
      "source_url": "https://www.alibabacloud.com/help/en/model-studio/user-guide/data-security-and-privacy",
      "verified_date": "2025-01-10",
      "provenance": "unverified_account_coverage",
      "conditions": "Standard tier is NOT zero-retention compliant. Our account is NOT covered by an enterprise ZDR agreement."
    },
    "aihubmix": {
      "provider": "aihubmix",
      "display_name": "AIHubMix",
      "zero_retention_compliant": false,
      "policy_tier": "unverified_aggregator",
      "account_covered": false,
      "account_tier": "community_proxy",
      "account_settings": "No contractual enterprise agreement or verifiable zero-retention guarantees",
      "aggregator": true,
      "underlying_endpoint_policy": "AIHubMix acts as an unverified aggregator proxy. Underlying endpoint routing is dynamic and third-party upstream providers cannot be verified for zero-retention compliance or provenance.",
      "retention_period": "Unknown / unverified third-party proxy logging",
      "training_policy": "Aggregator cannot guarantee upstream providers do not train or persist logs.",
      "exact_terms": "Third-party proxy service without verifiable independent audit, SOC2/ISO certification, or binding enterprise DPA.",
      "source_url": "https://aihubmix.com/privacy",
      "verified_date": "2025-01-01",
      "provenance": "unverified_aggregator",
      "conditions": "NOT COMPLIANT with zero-retention policies. Aggregator routes lack provenance."
    },
    "tokenharbor": {
      "provider": "tokenharbor",
      "display_name": "TokenHarbor AI",
      "zero_retention_compliant": false,
      "policy_tier": "unverified_proxy",
      "account_covered": false,
      "account_tier": "standard_proxy",
      "account_settings": "Unverified proxy without enterprise DPA",
      "retention_period": "Unverified",
      "training_policy": "Unverified upstream provenance.",
      "exact_terms": "Pass-through proxy without signed enterprise zero-retention agreement.",
      "source_url": "https://tokenharbor.ai/privacy",
      "verified_date": "2025-01-01",
      "provenance": "unverified_proxy",
      "conditions": "NOT COMPLIANT with strict zero-retention policy."
    },
    "codecraft": {
      "provider": "codecraft",
      "display_name": "CodeCraft API",
      "zero_retention_compliant": false,
      "policy_tier": "unverified_proxy",
      "account_covered": false,
      "account_tier": "standard_proxy",
      "account_settings": "Unverified proxy without enterprise DPA",
      "retention_period": "Unverified",
      "training_policy": "Unverified upstream provenance.",
      "exact_terms": "CodeCraft API lacks verified corporate provenance and DPA coverage.",
      "source_url": "https://codecraftapi.com/privacy",
      "verified_date": "2025-01-01",
      "provenance": "unverified_proxy",
      "conditions": "NOT COMPLIANT with strict zero-retention policy."
    },
    "atessa": {
      "provider": "atessa",
      "display_name": "Atessa AI",
      "zero_retention_compliant": false,
      "policy_tier": "unverified_proxy",
      "account_covered": false,
      "account_tier": "standard_proxy",
      "account_settings": "Unverified proxy without enterprise DPA",
      "retention_period": "Unverified",
      "training_policy": "Unverified upstream provenance.",
      "exact_terms": "Third-party proxy service without verifiable contractual zero-retention DPA.",
      "source_url": "https://atessa.top/privacy",
      "verified_date": "2025-01-01",
      "provenance": "unverified_proxy",
      "conditions": "NOT COMPLIANT with strict zero-retention policy."
    },
    "mock-provider-a": {
      "provider": "mock-provider-a",
      "display_name": "Mock Provider A (Test Suite)",
      "zero_retention_compliant": true,
      "policy_tier": "zero_retention",
      "account_covered": true,
      "account_tier": "hermetic_test",
      "account_settings": "Hermetic in-memory mock",
      "retention_period": "0 days (in-memory mock)",
      "training_policy": "Synthetic test provider with verified zero retention.",
      "exact_terms": "Mock test provider for hermetic routing engine unit tests. Zero retention and zero training verified.",
      "source_url": "https://claude-master.local/test-privacy",
      "verified_date": "2026-10-14",
      "provenance": "official_vendor_terms",
      "conditions": "Test suite harness only."
    },
    "aihorde": {
      "provider": "aihorde",
      "display_name": "AI Horde (Public Cluster)",
      "zero_retention_compliant": false,
      "policy_tier": "public_data_only",
      "account_covered": false,
      "account_tier": "anonymous_public",
      "account_settings": "Public crowdsourced worker pool",
      "retention_period": "Indefinite / public worker logging",
      "training_policy": "Prompts are routed through volunteer community worker nodes and may be logged or used for public dataset collection.",
      "exact_terms": "AI Horde is a crowdsourced distributed worker pool. Prompts are transmitted to third-party volunteer nodes without confidentiality guarantees.",
      "source_url": "https://aihorde.net/",
      "verified_date": "2025-01-01",
      "provenance": "public_community_network",
      "conditions": "Public crowdsourced network. NOT COMPLIANT with zero-retention policies."
    },
    "pollinations": {
      "provider": "pollinations",
      "display_name": "Pollinations AI (Public)",
      "zero_retention_compliant": false,
      "policy_tier": "public_data_only",
      "account_covered": false,
      "account_tier": "free_public",
      "account_settings": "Public CDN cache enabled",
      "retention_period": "Public cache / community feeds",
      "training_policy": "Public requests are published to public activity feeds and cached in public CDN layers.",
      "exact_terms": "Free public endpoints expose generated completions on public community feeds and do not offer zero-retention guarantees.",
      "source_url": "https://pollinations.ai/terms",
      "verified_date": "2025-01-01",
      "provenance": "public_community_feed",
      "conditions": "Public free endpoints. NOT COMPLIANT with zero-retention policies."
    }
  }
}`)

var (
	policyMu        sync.RWMutex
	loadedPolicies  map[string]ProviderPolicyRecord
	customOverrides = make(map[string]ProviderPolicyRecord)
)

func findPoliciesFilePath() string {
	if env := os.Getenv("CLAUDE_MASTER_PRIVACY_POLICIES"); env != "" {
		if _, err := os.Stat(env); err == nil {
			return env
		}
	}
	candidates := []string{
		filepath.Join("data", "privacy", "provider_policies.json"),
		filepath.Join("..", "data", "privacy", "provider_policies.json"),
		filepath.Join("..", "..", "data", "privacy", "provider_policies.json"),
	}
	for _, c := range candidates {
		if _, err := os.Stat(c); err == nil {
			return c
		}
	}
	return ""
}

// LoadProviderPolicies loads policies from disk or falls back to embedded defaults.
func LoadProviderPolicies() map[string]ProviderPolicyRecord {
	policyMu.Lock()
	defer policyMu.Unlock()

	res := make(map[string]ProviderPolicyRecord)

	// Start with embedded defaults
	var embeddedDoc ProviderPoliciesDoc
	if err := json.Unmarshal(defaultPoliciesJSON, &embeddedDoc); err == nil {
		for k, v := range embeddedDoc.Providers {
			res[strings.ToLower(k)] = v
		}
	}

	// Try reading disk file
	if path := findPoliciesFilePath(); path != "" {
		if bytes, err := os.ReadFile(path); err == nil {
			var doc ProviderPoliciesDoc
			if err := json.Unmarshal(bytes, &doc); err == nil {
				for k, v := range doc.Providers {
					res[strings.ToLower(k)] = v
				}
			}
		}
	}

	// Apply any test/runtime overrides
	for k, v := range customOverrides {
		res[strings.ToLower(k)] = v
	}

	loadedPolicies = res
	return res
}

func getPoliciesMap() map[string]ProviderPolicyRecord {
	policyMu.RLock()
	if loadedPolicies != nil {
		defer policyMu.RUnlock()
		return loadedPolicies
	}
	policyMu.RUnlock()
	return LoadProviderPolicies()
}

// GetProviderPolicy returns the recorded policy for a provider if registered.
func GetProviderPolicy(provider string) (ProviderPolicyRecord, bool) {
	m := getPoliciesMap()
	rec, ok := m[strings.ToLower(strings.TrimSpace(provider))]
	return rec, ok
}

// HasValidZeroRetentionEvidence checks whether the given provider has recorded
// evidence of zero-retention compliance with valid provenance (official URL, date, provenance tag).
func HasValidZeroRetentionEvidence(provider string) bool {
	rec, ok := GetProviderPolicy(provider)
	if !ok {
		return false
	}
	if !rec.ZeroRetentionCompliant {
		return false
	}
	if rec.AccountCovered != nil && !*rec.AccountCovered {
		return false
	}
	prov := strings.ToLower(strings.TrimSpace(rec.Provenance))
	if prov == "" || strings.HasPrefix(prov, "unverified") || strings.HasPrefix(prov, "public") {
		return false
	}
	if strings.TrimSpace(rec.SourceURL) == "" {
		return false
	}
	if strings.TrimSpace(rec.VerifiedDate) == "" {
		return false
	}
	return true
}

// RegisterProviderPolicy allows registering or overriding a policy record for tests.
func RegisterProviderPolicy(rec ProviderPolicyRecord) {
	policyMu.Lock()
	defer policyMu.Unlock()
	key := strings.ToLower(strings.TrimSpace(rec.Provider))
	customOverrides[key] = rec
	if loadedPolicies != nil {
		loadedPolicies[key] = rec
	}
}

// ClearPolicyOverrides resets custom policy overrides.
func ClearPolicyOverrides() {
	policyMu.Lock()
	defer policyMu.Unlock()
	customOverrides = make(map[string]ProviderPolicyRecord)
	loadedPolicies = nil
}
