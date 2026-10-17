// cooldown.go — Adaptive Cooldown Cache for multi-key and multi-model rate-limit cascades.
//
// Algorithm ported (MIT concept) from:
//   BerriAI/litellm litellm/router_utils/cooldown_cache.py
//
// NOTICE: Clean-room Go reimplementation. No source code was copied.
package gateway

import (
	"crypto/sha256"
	"fmt"
	"math"
	"math/rand"
	"sort"
	"strings"
	"sync"
	"time"
)

// Cooldown status / state constants
const (
	StatusActive      = "active"
	StatusRateLimited = "rate_limited" // HTTP 429: learned exponential backoff starting at 60s up to maxS
	StatusExhausted   = "exhausted"    // HTTP 402: credit balance depleted / payment required
	StatusDead        = "dead"         // HTTP 401: invalid key
	StatusRestricted  = "restricted"   // HTTP 403: permission denied / model not enabled for key
	StatusProbing     = "probing"      // cheap re-probe half-open state before full recovery
)

// Provenance constants tracking the source of learned backoff
const (
	ProvenanceRetryAfterHeader  = "retry_after_header"
	ProvenanceAdaptiveBackoff   = "adaptive_backoff"
	ProvenanceProbeRecovery     = "probe_recovery"
	ProvenanceStatusCodeDefault = "status_code_default"
)

// RouteCooldownEntry represents a cooldown entry for status inspection and admin reporting.
type RouteCooldownEntry struct {
	KeyHash          string    `json:"key_hash"`
	Model            string    `json:"model"`
	Status           string    `json:"status"`
	State            string    `json:"state"`
	CooldownUntil    time.Time `json:"cooldown_until"`
	BackoffS         float64   `json:"backoff_s"`
	RemainingS       float64   `json:"remaining_s"`
	DurationMs       int64     `json:"duration_ms"`
	LearnedBackoffMs int64     `json:"learned_backoff_ms"`
	FailureCount     int       `json:"failure_count"`
	Provenance       string    `json:"provenance"`
	LastTestedAt     time.Time `json:"last_tested_at"`
}

// cooldownEntry holds the state for a single key or key@model that is in cooldown.
type cooldownEntry struct {
	keyHash           string
	model             string
	status            string
	cooldownUntil     time.Time
	backoffS          float64
	durationMs        int64
	learnedDurationMs int64
	failureCount      int
	provenance        string
	lastTestedAt      time.Time
	probingInFlight   bool
}

// CooldownCache tracks which API key hashes and models are currently in cooldown.
// Tracks per-key-per-model (keyHash@model) as well as key-wide (keyHash@*) failures.
// Supports Retry-After header parsing, adaptive exponential backoff with jitter,
// and cheap re-probe recovery through half-open "probing" state.
type CooldownCache struct {
	mu           sync.Mutex
	entries      map[string]*cooldownEntry
	baseS        float64
	maxS         float64
	enableJitter bool
	jitterFn     func(backoffS float64) float64
}

// NewCooldownCache creates a CooldownCache with the given base and max backoff.
func NewCooldownCache(baseSeconds, maxSeconds float64) *CooldownCache {
	if baseSeconds <= 0 {
		baseSeconds = 60
	}
	if maxSeconds <= 0 {
		maxSeconds = 3600
	}
	return &CooldownCache{
		entries: make(map[string]*cooldownEntry),
		baseS:   baseSeconds,
		maxS:    maxSeconds,
	}
}

// SetJitter enables or disables jitter on adaptive backoff.
func (c *CooldownCache) SetJitter(enabled bool) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.enableJitter = enabled
}

// SetJitterFunc sets a custom jitter function (useful for deterministic tests).
func (c *CooldownCache) SetJitterFunc(fn func(backoffS float64) float64) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.jitterFn = fn
}

// HashKey returns a short SHA-256 prefix for an API key. Raw secrets are never
// stored or logged — only this hash is retained in memory.
func HashKey(key string) string {
	h := sha256.Sum256([]byte(key))
	return fmt.Sprintf("%x", h[:8])
}

// routeKey formats the composite key: keyHash@model or keyHash@*
func routeKey(keyHash, model string) string {
	if model == "" {
		model = "*"
	}
	if strings.Contains(keyHash, "@") {
		parts := strings.SplitN(keyHash, "@", 2)
		keyHash = parts[0]
		if model == "*" {
			model = parts[1]
		}
	}
	return keyHash + "@" + model
}

// ParseRetryAfter parses an HTTP Retry-After header which can be an integer/float number
// of seconds (e.g. "30", "120") or an HTTP-date (e.g. "Wed, 21 Oct 2026 07:28:00 GMT").
func ParseRetryAfter(header string, now time.Time) (time.Duration, bool) {
	h := strings.TrimSpace(header)
	if h == "" {
		return 0, false
	}
	var sec float64
	if _, err := fmt.Sscanf(h, "%f", &sec); err == nil && sec >= 0 {
		return time.Duration(sec * float64(time.Second)), true
	}

	layouts := []string{
		time.RFC1123,
		time.RFC1123Z,
		time.RFC850,
		time.ANSIC,
		"Mon, 02 Jan 2006 15:04:05 GMT",
		time.RFC3339,
	}
	for _, l := range layouts {
		if t, err := time.Parse(l, h); err == nil {
			d := t.Sub(now)
			if d < 0 {
				d = 0
			}
			return d, true
		}
	}
	return 0, false
}

// RecordFailure records a failure for keyHash@model with status and optional Retry-After header.
// Implements Retry-After precedence, adaptive exponential backoff with failure count, and jitter.
func (c *CooldownCache) RecordFailure(keyHash, model, status, retryAfterHeader string) time.Duration {
	c.mu.Lock()
	defer c.mu.Unlock()

	now := time.Now()
	rk := routeKey(keyHash, model)
	parts := strings.SplitN(rk, "@", 2)
	normHash, normModel := parts[0], parts[1]

	e, ok := c.entries[rk]
	if !ok {
		e = &cooldownEntry{
			keyHash: normHash,
			model:   normModel,
		}
		c.entries[rk] = e
	}

	e.failureCount++
	e.lastTestedAt = now
	e.probingInFlight = false

	var backoffS float64
	var provenance string

	// a) Provider retry-after header parsing when given
	if retryDur, parsed := ParseRetryAfter(retryAfterHeader, now); parsed && retryDur > 0 {
		backoffS = retryDur.Seconds()
		provenance = ProvenanceRetryAfterHeader
	} else {
		// b) Adaptive exponential backoff: track failure count per keyHash@model and keyHash@*
		base := c.baseS
		switch status {
		case StatusDead: // 401
			base = c.baseS * 5
			if base < 300 {
				base = 300
			}
		case StatusExhausted: // 402
			base = c.baseS * 2
			if base < 120 {
				base = 120
			}
		case StatusRestricted: // 403
			base = c.baseS
		case StatusRateLimited: // 429
			base = c.baseS
		default:
			base = c.baseS
		}

		if e.failureCount <= 1 {
			backoffS = base
			provenance = ProvenanceStatusCodeDefault
		} else {
			// Exponential progression: base * 2^(failureCount-1)
			mult := math.Pow(2, float64(e.failureCount-1))
			backoffS = base * mult
			provenance = ProvenanceAdaptiveBackoff
		}
	}

	if backoffS > c.maxS {
		backoffS = c.maxS
	}

	jitterS := 0.0
	if c.enableJitter {
		if c.jitterFn != nil {
			jitterS = c.jitterFn(backoffS)
		} else {
			jitterMax := math.Min(5.0, backoffS*0.1)
			if jitterMax > 0 {
				jitterS = rand.Float64() * jitterMax
			}
		}
	}

	totalDur := time.Duration((backoffS + jitterS) * float64(time.Second))
	if totalDur > time.Duration(c.maxS*float64(time.Second)) {
		totalDur = time.Duration(c.maxS * float64(time.Second))
	}

	e.status = status
	e.cooldownUntil = now.Add(totalDur)
	e.backoffS = backoffS
	e.durationMs = int64(totalDur / time.Millisecond)
	e.learnedDurationMs = int64(backoffS * 1000)
	e.provenance = provenance

	return totalDur
}

// RecordSuccess updates route state after a successful request/probe.
// If the route was probing or cooling, it transitions to active with probe_recovery provenance.
func (c *CooldownCache) RecordSuccess(keyHash, model string) {
	c.mu.Lock()
	defer c.mu.Unlock()

	now := time.Now()
	rk := routeKey(keyHash, model)
	if e, ok := c.entries[rk]; ok {
		e.lastTestedAt = now
		e.probingInFlight = false
		if e.status == StatusProbing || now.After(e.cooldownUntil) {
			e.status = StatusActive
			e.provenance = ProvenanceProbeRecovery
			e.failureCount = 0
		}
	}
	if model != "" && model != "*" {
		wideKey := routeKey(keyHash, "*")
		if e, ok := c.entries[wideKey]; ok {
			e.lastTestedAt = now
			e.probingInFlight = false
			if e.status == StatusProbing || now.After(e.cooldownUntil) {
				e.status = StatusActive
				e.provenance = ProvenanceProbeRecovery
				e.failureCount = 0
			}
		}
	}
}

// CanProbe returns true if the route has expired its cooldown and is ready for a probe test.
func (c *CooldownCache) CanProbe(keyHash, model string) bool {
	c.mu.Lock()
	defer c.mu.Unlock()
	rk := routeKey(keyHash, model)
	now := time.Now()
	if e, ok := c.entries[rk]; ok {
		if (e.status == StatusProbing || now.After(e.cooldownUntil)) && !e.probingInFlight {
			return true
		}
	}
	return false
}

// AllowProbe attempts to claim a single probe attempt for the route.
// Returns true if probe was claimed; false if route is still cooling down or another probe is in-flight.
func (c *CooldownCache) AllowProbe(keyHash, model string) bool {
	c.mu.Lock()
	defer c.mu.Unlock()

	now := time.Now()
	rk := routeKey(keyHash, model)
	e, ok := c.entries[rk]
	if !ok {
		return true // not in cooldown
	}

	if e.status == StatusActive {
		return true
	}

	if now.Before(e.cooldownUntil) {
		return false // still cooling down
	}

	if e.probingInFlight {
		return false // probe already active
	}

	e.status = StatusProbing
	e.probingInFlight = true
	e.lastTestedAt = now
	return true
}

// IsAvailableForModel returns true when the key is NOT in cooldown for the given model.
// When a cooldown timer has expired, it allows a single test turn by transitioning to
// the half-open "probing" state.
func (c *CooldownCache) IsAvailableForModel(keyHash string, model string) bool {
	c.mu.Lock()
	defer c.mu.Unlock()
	now := time.Now()

	// 1. Check key-wide cooldown (keyHash@*)
	wideKey := routeKey(keyHash, "*")
	if e, ok := c.entries[wideKey]; ok && e.status != StatusActive {
		if e.status == StatusProbing {
			if e.probingInFlight {
				return false
			}
			e.probingInFlight = true
			e.lastTestedAt = now
		} else if now.Before(e.cooldownUntil) {
			return false
		} else {
			// Cooldown expired: transition to probing half-open state
			e.status = StatusProbing
			e.probingInFlight = true
			e.lastTestedAt = now
		}
	}

	// 2. Check model-specific cooldown (keyHash@model)
	if model != "" && model != "*" {
		modelKey := routeKey(keyHash, model)
		if e, ok := c.entries[modelKey]; ok && e.status != StatusActive {
			if e.status == StatusProbing {
				if e.probingInFlight {
					return false
				}
				e.probingInFlight = true
				e.lastTestedAt = now
			} else if now.Before(e.cooldownUntil) {
				return false
			} else {
				// Cooldown expired: transition to probing half-open state
				e.status = StatusProbing
				e.probingInFlight = true
				e.lastTestedAt = now
			}
		}
	}
	return true
}

// IsAvailable returns true when the key is NOT in cooldown.
// If keyHash contains an '@', it checks that specific route.
// If keyHash is plain (no '@'), it returns true only if the key has no active cooldowns.
func (c *CooldownCache) IsAvailable(keyHash string) bool {
	if strings.Contains(keyHash, "@") {
		parts := strings.SplitN(keyHash, "@", 2)
		return c.IsAvailableForModel(parts[0], parts[1])
	}

	c.mu.Lock()
	defer c.mu.Unlock()
	now := time.Now()

	// Check key-wide
	wideKey := routeKey(keyHash, "*")
	if e, ok := c.entries[wideKey]; ok && e.status != StatusActive {
		if now.Before(e.cooldownUntil) {
			return false
		}
	}

	// Also check if any model-specific cooldown is active for this key
	prefix := keyHash + "@"
	hasActive := false
	for k, e := range c.entries {
		if strings.HasPrefix(k, prefix) && e.status != StatusActive {
			if now.Before(e.cooldownUntil) {
				hasActive = true
			}
		}
	}
	return !hasActive
}

// MarkRateLimited places keyHash@model into rate_limited cooldown.
func (c *CooldownCache) MarkRateLimited(keyHash, model string) time.Duration {
	return c.RecordFailure(keyHash, model, StatusRateLimited, "")
}

// Mark429 places keyHash into rate_limited cooldown. Backward-compatible helper.
func (c *CooldownCache) Mark429(keyHash string) time.Duration {
	if strings.Contains(keyHash, "@") {
		parts := strings.SplitN(keyHash, "@", 2)
		return c.MarkRateLimited(parts[0], parts[1])
	}
	return c.MarkRateLimited(keyHash, "*")
}

// MarkExhausted places keyHash into exhausted cooldown (HTTP 402, key-wide).
func (c *CooldownCache) MarkExhausted(keyHash string) time.Duration {
	return c.RecordFailure(keyHash, "*", StatusExhausted, "")
}

// MarkDead places keyHash into dead cooldown (HTTP 401, key-wide).
func (c *CooldownCache) MarkDead(keyHash string) time.Duration {
	return c.RecordFailure(keyHash, "*", StatusDead, "")
}

// MarkRestricted places keyHash@model into restricted cooldown (HTTP 403, model-scoped).
func (c *CooldownCache) MarkRestricted(keyHash, model string) time.Duration {
	if model == "" {
		model = "*"
	}
	return c.RecordFailure(keyHash, model, StatusRestricted, "")
}

// MarkStatus places keyHash and model into cooldown for the given status.
func (c *CooldownCache) MarkStatus(keyHash, model, status string) time.Duration {
	switch status {
	case StatusDead:
		return c.MarkDead(keyHash)
	case StatusExhausted:
		return c.MarkExhausted(keyHash)
	case StatusRestricted:
		return c.MarkRestricted(keyHash, model)
	case StatusRateLimited:
		return c.MarkRateLimited(keyHash, model)
	default:
		return c.MarkRateLimited(keyHash, model)
	}
}

// Status returns the current cooldown status for keyHash and model.
// Returns "active" if not in cooldown.
func (c *CooldownCache) Status(keyHash, model string) string {
	c.mu.Lock()
	defer c.mu.Unlock()
	now := time.Now()

	// Check key-wide first
	wideKey := routeKey(keyHash, "*")
	if e, ok := c.entries[wideKey]; ok {
		if e.status == StatusActive {
			// active
		} else if e.status == StatusProbing {
			return StatusProbing
		} else if now.Before(e.cooldownUntil) {
			return e.status
		} else {
			e.status = StatusProbing
			return StatusProbing
		}
	}

	// Check model-specific
	if model != "" && model != "*" {
		modelKey := routeKey(keyHash, model)
		if e, ok := c.entries[modelKey]; ok {
			if e.status == StatusActive {
				// active
			} else if e.status == StatusProbing {
				return StatusProbing
			} else if now.Before(e.cooldownUntil) {
				return e.status
			} else {
				e.status = StatusProbing
				return StatusProbing
			}
		}
	}
	return StatusActive
}

// PickKeyForModel selects the first available key (by priority desc) from a resolved
// key slice for the specified model. Checks both keyHash@* and keyHash@model.
// Returns empty string if all keys are in cooldown.
func (c *CooldownCache) PickKeyForModel(keys []ResolvedKey, model string) (string, bool) {
	sorted := make([]ResolvedKey, len(keys))
	copy(sorted, keys)
	sort.SliceStable(sorted, func(i, j int) bool {
		return sorted[i].Priority > sorted[j].Priority
	})
	for _, k := range sorted {
		h := HashKey(k.Value)
		if c.IsAvailableForModel(h, model) {
			return k.Value, true
		}
	}
	return "", false
}

// PickKey selects the first available key (by priority desc) from a resolved
// key slice. Returns empty string if all keys are in cooldown.
func (c *CooldownCache) PickKey(keys []ResolvedKey) (string, bool) {
	return c.PickKeyForModel(keys, "*")
}

// Entries returns all active cooldown and probing entries with full provenance and learned stats.
func (c *CooldownCache) Entries() []RouteCooldownEntry {
	c.mu.Lock()
	defer c.mu.Unlock()
	now := time.Now()
	var out []RouteCooldownEntry
	for k, e := range c.entries {
		if now.After(e.cooldownUntil) && e.status != StatusProbing && e.status != StatusActive {
			e.status = StatusProbing
			e.probingInFlight = false
		}
		if now.Before(e.cooldownUntil) || e.status == StatusProbing {
			rem := e.cooldownUntil.Sub(now).Seconds()
			if rem < 0 {
				rem = 0
			}
			out = append(out, RouteCooldownEntry{
				KeyHash:          e.keyHash,
				Model:            e.model,
				Status:           e.status,
				State:            e.status,
				CooldownUntil:    e.cooldownUntil,
				BackoffS:         e.backoffS,
				RemainingS:       rem,
				DurationMs:       e.durationMs,
				LearnedBackoffMs: e.learnedDurationMs,
				FailureCount:     e.failureCount,
				Provenance:       e.provenance,
				LastTestedAt:     e.lastTestedAt,
			})
		} else if e.status != StatusActive {
			delete(c.entries, k)
		}
	}
	sort.Slice(out, func(i, j int) bool {
		if out[i].KeyHash == out[j].KeyHash {
			return out[i].Model < out[j].Model
		}
		return out[i].KeyHash < out[j].KeyHash
	})
	return out
}

// ActiveCount returns how many entries are currently in cooldown or probing.
func (c *CooldownCache) ActiveCount() int {
	c.mu.Lock()
	defer c.mu.Unlock()
	now := time.Now()
	n := 0
	for k, e := range c.entries {
		if now.Before(e.cooldownUntil) || e.status == StatusProbing {
			n++
		} else if e.status != StatusActive {
			delete(c.entries, k)
		}
	}
	return n
}
