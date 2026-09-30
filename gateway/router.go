// router.go — Provider eligibility, static fallback table, GitHub Models gate.
//
// Errata 1: gateway sits on ANTHROPIC_BASE_URL primary path.
// Errata 4: public_data_only never receives internal/sensitive content.
// Errata 5 / risks §3.2: GitHub Models = single interactive fallback only.
package gateway

import (
	"os"
	"sort"
	"strings"
)

// StaticFallbackChain is used when the brain router/socket is unavailable.
// Ordered preference for free-tier providers (GitHub Models last — interactive
// fallback only, never part of the active rotation pool).
var StaticFallbackChain = []string{
	"groq",
	"cerebras",
	"mistral",
	"gemini",
	"github-models",
}

// IsGitHubModels reports whether a provider is GitHub Models (by name or URL).
func IsGitHubModels(p Provider) bool {
	name := strings.ToLower(p.Name)
	if strings.Contains(name, "github") {
		return true
	}
	u := strings.ToLower(p.BaseURL)
	return strings.Contains(u, "models.github.ai") || strings.Contains(u, "api.githubcopilot")
}

// BrainAvailable probes the configured brain Unix socket. Fail-open: if the
// path is empty or missing, returns false and callers use StaticFallbackChain.
func BrainAvailable(socketPath string) bool {
	if socketPath == "" {
		return false
	}
	fi, err := os.Stat(socketPath)
	if err != nil {
		return false
	}
	// Unix sockets report as ModeSocket on Linux; accept any existing path
	// that is not a regular directory as "present".
	return !fi.IsDir()
}

// ResolveFallbackOrder returns the provider order to try. Prefer config
// fallback_chain; otherwise StaticFallbackChain when brain is unavailable.
func ResolveFallbackOrder(cfg *Config) []string {
	if cfg == nil {
		return append([]string(nil), StaticFallbackChain...)
	}
	if len(cfg.Routing.FallbackChain) > 0 {
		return append([]string(nil), cfg.Routing.FallbackChain...)
	}
	if !BrainAvailable(cfg.BrainSocket) {
		return append([]string(nil), StaticFallbackChain...)
	}
	// Brain present but no explicit chain — still use static as baseline.
	return append([]string(nil), StaticFallbackChain...)
}

// EligibleProviders returns providers allowed for the privacy class, with
// GitHub Models deferred to a separate last-resort slice when
// github_models_fallback_only is set (default true).
func EligibleProviders(cfg *Config, pc PrivacyClass) (primary, githubFallback []Provider) {
	if cfg == nil {
		return nil, nil
	}
	ghOnly := cfg.Routing.GitHubModelsFallback // json default true via LoadConfig

	order := ResolveFallbackOrder(cfg)
	rank := make(map[string]int, len(order))
	for i, name := range order {
		rank[strings.ToLower(name)] = i
	}

	var candidates []Provider
	for _, p := range cfg.Providers {
		if !p.IsEnabled() {
			continue
		}
		// Privacy: never send internal/sensitive content to public_data_only.
		if pc == PrivacyClassInternal && p.PrivacyPolicy == PrivacyPublicDataOnly {
			continue
		}
		if ghOnly && IsGitHubModels(p) {
			githubFallback = append(githubFallback, p)
			continue
		}
		candidates = append(candidates, p)
	}

	sort.SliceStable(candidates, func(i, j int) bool {
		oi, oki := rank[strings.ToLower(candidates[i].Name)]
		oj, okj := rank[strings.ToLower(candidates[j].Name)]
		if !oki {
			oi = len(rank) + i
		}
		if !okj {
			oj = len(rank) + j
		}
		return oi < oj
	})
	return candidates, githubFallback
}
