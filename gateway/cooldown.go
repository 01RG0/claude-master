// cooldown.go — Adaptive Cooldown Cache for multi-key rate-limit cascades.
//
// Algorithm ported (MIT concept) from:
//   BerriAI/litellm litellm/router_utils/cooldown_cache.py
//
// NOTICE: Clean-room Go reimplementation. No source code was copied.
package gateway

import (
	"crypto/sha256"
	"fmt"
	"sort"
	"sync"
	"time"
)

// cooldownEntry holds the state for a single key that is in cooldown.
type cooldownEntry struct {
	cooldownUntil time.Time
	backoffS      float64
}

// CooldownCache tracks which API key hashes are currently rate-limited.
// On a 429 the caller marks the key; the cache refuses to return it until
// the cooldown expires. Repeated 429s double the backoff (up to maxS).
type CooldownCache struct {
	mu      sync.Mutex
	entries map[string]*cooldownEntry
	baseS   float64
	maxS    float64
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

// HashKey returns a short SHA-256 prefix for an API key. Raw secrets are never
// stored or logged — only this hash is retained in memory.
func HashKey(key string) string {
	h := sha256.Sum256([]byte(key))
	return fmt.Sprintf("%x", h[:8])
}

// IsAvailable returns true when the key is NOT in cooldown.
func (c *CooldownCache) IsAvailable(keyHash string) bool {
	c.mu.Lock()
	defer c.mu.Unlock()
	e, ok := c.entries[keyHash]
	if !ok {
		return true
	}
	if time.Now().After(e.cooldownUntil) {
		delete(c.entries, keyHash)
		return true
	}
	return false
}

// Mark429 places keyHash into cooldown, doubling backoff on repeat 429s.
// Returns the cooldown duration that was applied.
func (c *CooldownCache) Mark429(keyHash string) time.Duration {
	c.mu.Lock()
	defer c.mu.Unlock()

	var newBackoff float64
	if e, ok := c.entries[keyHash]; ok && time.Now().Before(e.cooldownUntil) {
		newBackoff = e.backoffS * 2
		if newBackoff > c.maxS {
			newBackoff = c.maxS
		}
	} else {
		newBackoff = c.baseS
	}

	c.entries[keyHash] = &cooldownEntry{
		cooldownUntil: time.Now().Add(time.Duration(newBackoff * float64(time.Second))),
		backoffS:      newBackoff,
	}
	return time.Duration(newBackoff * float64(time.Second))
}

// PickKey selects the first available key (by priority desc) from a resolved
// key slice. Returns empty string if all keys are in cooldown.
func (c *CooldownCache) PickKey(keys []ResolvedKey) (string, bool) {
	sorted := make([]ResolvedKey, len(keys))
	copy(sorted, keys)
	sort.Slice(sorted, func(i, j int) bool {
		return sorted[i].Priority > sorted[j].Priority
	})
	for _, k := range sorted {
		h := HashKey(k.Value)
		if c.IsAvailable(h) {
			return k.Value, true
		}
	}
	return "", false
}

// ActiveCount returns how many keys are currently in cooldown (for tests/stats).
func (c *CooldownCache) ActiveCount() int {
	c.mu.Lock()
	defer c.mu.Unlock()
	now := time.Now()
	n := 0
	for _, e := range c.entries {
		if now.Before(e.cooldownUntil) {
			n++
		}
	}
	return n
}
