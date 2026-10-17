// Package gateway implements the free-tier Anthropic gateway.
// config.go loads and validates the gateway configuration from JSON.
package gateway

import (
	"encoding/json"
	"fmt"
	"os"
	"time"
)

// PrivacyPolicy represents the data retention / training policy of a provider.
type PrivacyPolicy string

const (
	PrivacyZeroRetention  PrivacyPolicy = "zero_retention"
	PrivacyInternal       PrivacyPolicy = "internal"
	PrivacyPublicDataOnly PrivacyPolicy = "public_data_only"
)

// PrivacyClass is the sensitivity label on an incoming request.
type PrivacyClass string

const (
	PrivacyClassInternal      PrivacyClass = "internal"
	PrivacyClassPublic        PrivacyClass = "public"
	PrivacyClassZeroRetention PrivacyClass = "zero_retention"
)

// KeyPool holds one API key slot referencing an environment variable.
// Multiple pools = multiple keys from ONE account (errata 5). Never farm
// keys across different accounts.
type KeyPool struct {
	AccountLabel string `json:"account_label"`
	EnvVar       string `json:"env_var"`
	Priority     int    `json:"priority"`
	// Models optionally restricts this key to a subset (tiers/allowlists).
	// Empty = all provider models. Detection fills PerKeyModels at runtime.
	Models []string `json:"models,omitempty"`
}

// Mirror is an alternate base URL for the same provider (region, mirror,
// proxy, self-hosted replica) with its own priority.
type Mirror struct {
	BaseURL  string `json:"base_url"`
	Priority int    `json:"priority"`
}

// RateLimit holds soft rate-limit hints for a provider.
type RateLimit struct {
	RequestsPerMinute int `json:"requests_per_minute"`
	TokensPerMinute   int `json:"tokens_per_minute"`
	RequestsPerDay    int `json:"requests_per_day"`
	MaxConcurrent     int `json:"max_concurrent"`
}

// Provider describes a single upstream LLM provider.
type Provider struct {
	Name          string        `json:"name"`
	BaseURL       string        `json:"base_url"`
	PrivacyPolicy PrivacyPolicy `json:"privacy_policy"`
	KeyPools      []KeyPool     `json:"key_pools"`
	Models        []string      `json:"models"`
	RateLimit     *RateLimit    `json:"rate_limit,omitempty"`
	Enabled       *bool         `json:"enabled"`
	// Mirrors: alternate endpoints tried after the primary (priority desc).
	Mirrors []Mirror `json:"mirrors,omitempty"`
	// Adapter: declarative dialect spec (see adapters.go). Empty = OpenAI-chat.
	Adapter AdapterSpec `json:"adapter,omitempty"`
}

// IsEnabled defaults to true when the field is omitted (schema default).
func (p Provider) IsEnabled() bool {
	if p.Enabled == nil {
		return true
	}
	return *p.Enabled
}

// RoutingConfig controls the model selection and fallback strategy.
type RoutingConfig struct {
	Strategy             string            `json:"strategy"`
	FallbackChain        []string          `json:"fallback_chain,omitempty"`
	CooldownBaseS        float64           `json:"cooldown_base_s"`
	CooldownMaxS         float64           `json:"cooldown_max_s"`
	GitHubModelsFallback bool              `json:"github_models_fallback_only"`
	// Selection: thompson_sampling (default) | priority | round_robin |
	// latency | cost. StickySession keeps one session on one provider
	// (provider-side cache affinity) when true.
	Selection     string             `json:"selection,omitempty"`
	StickySession bool               `json:"sticky_session,omitempty"`
	// AttemptTimeoutS bounds one upstream attempt (failover speed).
	AttemptTimeoutS float64 `json:"attempt_timeout_s,omitempty"`
	// ModelPrices: USD per 1M input tokens, for cost-first routing + accounting.
	ModelPrices map[string]float64 `json:"model_prices,omitempty"`
}

// DrexConfig holds optional Drex integration settings.
type DrexConfig struct {
	Enabled              bool     `json:"enabled"`
	BaseURL              string   `json:"base_url"`
	Model                string   `json:"model"`
	TimeoutMs            int      `json:"timeout_ms"`
	CacheTTLS            int      `json:"cache_ttl_s"`
	RiskyCommandPatterns []string `json:"risky_command_patterns,omitempty"`
}

// Config is the root gateway configuration object.
type Config struct {
	ListenAddr      string            `json:"listen_addr"`
	BrainSocket     string            `json:"brain_socket"`
	RequestTimeoutS float64           `json:"request_timeout_s"`
	Providers       []Provider        `json:"providers"`
	Routing         RoutingConfig     `json:"routing"`
	Drex            *DrexConfig       `json:"drex,omitempty"`
	// ModelAliases maps requested names (claude-*, aliases) to upstream ids.
	ModelAliases map[string]string `json:"model_aliases,omitempty"`
	// Roles maps task roles to upstream model ids (main required).
	Roles *RoleMapping `json:"roles,omitempty"`
	// Logging enables redacted request logging for traffic capture/tuning.
	Logging *LoggingConfig `json:"logging,omitempty"`
	// ToolRescueEnabled controls Tier-2 argument and format rescue (default true).
	ToolRescueEnabled *bool `json:"tool_rescue_enabled,omitempty"`
}

// IsToolRescueEnabled returns whether tool rescue is enabled (default true).
func (c *Config) IsToolRescueEnabled() bool {
	if c == nil || c.ToolRescueEnabled == nil {
		return true
	}
	return *c.ToolRescueEnabled
}

// LoggingConfig controls redacted request logging.
type LoggingConfig struct {
	RequestsDir string `json:"requests_dir,omitempty"`
	MaxBody     int    `json:"max_body_bytes,omitempty"`
}

// RequestTimeout returns the configured request timeout as a Duration.
func (c *Config) RequestTimeout() time.Duration {
	if c.RequestTimeoutS <= 0 {
		return 60 * time.Second
	}
	return time.Duration(c.RequestTimeoutS * float64(time.Second))
}

// AttemptTimeout bounds ONE upstream attempt so a hung provider fails over
// fast instead of consuming the whole request budget (default 25s).
func (c *Config) AttemptTimeout() time.Duration {
	if c.Routing.AttemptTimeoutS > 0 {
		return time.Duration(c.Routing.AttemptTimeoutS * float64(time.Second))
	}
	return 25 * time.Second
}

// CooldownBase returns the base cooldown duration.
func (c *Config) CooldownBase() time.Duration {
	base := c.Routing.CooldownBaseS
	if base <= 0 {
		base = 60
	}
	return time.Duration(base * float64(time.Second))
}

// CooldownMax returns the maximum cooldown duration.
func (c *Config) CooldownMax() time.Duration {
	max := c.Routing.CooldownMaxS
	if max <= 0 {
		max = 3600
	}
	return time.Duration(max * float64(time.Second))
}

// ResolvedKey is an env-resolved API key with priority (raw value never logged).
type ResolvedKey struct {
	Value         string
	Priority      int
	EnvVar        string
	Provider      string
	AccountLabel  string
	AllowedModels []string
}

// ResolveProviderKeys reads env vars for all key pools of a provider.
// Keys with empty values are skipped. Same-account multi-key load spreading only.
func ResolveProviderKeys(p Provider) []ResolvedKey {
	var out []ResolvedKey
	for _, pool := range p.KeyPools {
		val := os.Getenv(pool.EnvVar)
		if val == "" {
			continue
		}
		prio := pool.Priority
		if prio == 0 {
			prio = 10
		}
		out = append(out, ResolvedKey{Value: val, Priority: prio, EnvVar: pool.EnvVar,
			Provider: p.Name, AccountLabel: pool.AccountLabel, AllowedModels: pool.Models})
	}
	return out
}

// KeyHasModel reports whether a resolved key may serve a model.
// Empty allowlist = all models (detection narrows it at runtime via overlay).
func KeyHasModel(k ResolvedKey, model string, overlay map[string][]string) bool {
	if models, ok := overlay[k.Provider+"\x00"+HashKey(k.Value)]; ok && len(models) > 0 {
		return modelAllowed(models, model)
	}
	if len(k.AllowedModels) == 0 {
		return true
	}
	return modelAllowed(k.AllowedModels, model)
}

func modelAllowed(list []string, model string) bool {
	base := model
	if i := len(base) - 1; i >= 0 {
		_ = i
	}
	for _, m := range list {
		if m == model || m == base {
			return true
		}
		if idx := lastSlash(m); idx >= 0 && m[idx+1:] == model {
			return true
		}
		if idx := lastSlash(model); idx >= 0 && model[idx+1:] == m {
			return true
		}
	}
	return false
}

func lastSlash(s string) int {
	for i := len(s) - 1; i >= 0; i-- {
		if s[i] == '/' {
			return i
		}
	}
	return -1
}

// LoadConfig reads and parses a JSON config file from path.
func LoadConfig(path string) (*Config, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("reading config %q: %w", path, err)
	}
	return ParseConfig(data)
}

// ParseConfig unmarshals config JSON bytes.
func ParseConfig(data []byte) (*Config, error) {
	var cfg Config
	if err := json.Unmarshal(data, &cfg); err != nil {
		return nil, fmt.Errorf("parsing config: %w", err)
	}
	if cfg.ListenAddr == "" {
		cfg.ListenAddr = "127.0.0.1:8080"
	}
	if cfg.Routing.CooldownBaseS == 0 {
		cfg.Routing.CooldownBaseS = 60
	}
	if cfg.Routing.CooldownMaxS == 0 {
		cfg.Routing.CooldownMaxS = 3600
	}
	if cfg.RequestTimeoutS == 0 {
		cfg.RequestTimeoutS = 120
	}
	// github_models_fallback_only defaults to true (schema + risks §3.2).
	// Detect omission via raw map.
	var raw map[string]json.RawMessage
	if err := json.Unmarshal(data, &raw); err == nil {
		if rraw, ok := raw["routing"]; ok {
			var rm map[string]json.RawMessage
			if json.Unmarshal(rraw, &rm) == nil {
				if _, set := rm["github_models_fallback_only"]; !set {
					cfg.Routing.GitHubModelsFallback = true
				}
			}
		} else {
			cfg.Routing.GitHubModelsFallback = true
		}
	}
	if cfg.Routing.Strategy == "" {
		cfg.Routing.Strategy = "thompson_sampling"
	}
	return &cfg, nil
}
