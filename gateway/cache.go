// cache.go — honest caching for the Anthropic front door.
//
// Two mechanisms:
//
//  1. Cache-control auto-inject (provider-side prompt caching):
//     EnsureCacheBreakpoints adds ephemeral breakpoints when the client sent
//     none. At most 2 injections: the system block (if present) and the last
//     content block of the last message (Anthropic semantics: up to 4
//     breakpoints allowed; we use at most 2 to stay conservative).
//
//  2. Exact-match response cache (gateway replay):
//     ResponseCache stores non-streaming POST /v1/messages responses WITHOUT
//     tools and WITHOUT thinking, keyed by sha256(canonical JSON of
//     {model,messages,system,max_tokens,temperature}). TTL 5min, max 256.
//
// Honesty rule (see TranslateResponse): provider cache_read_input_tokens is
// reported ONLY when the upstream provider reports cached_tokens. A gateway
// exact-match replay NEVER fabricates cache_read_input_tokens — it replays
// the stored body byte-for-byte (usage passthrough) and signals the replay
// via the X-Gateway-Cache: HIT header. MISS responses carry
// X-Gateway-Cache: MISS. Streams are never cached.
//
// Security: this file never logs or prints keys or content. Callers must log
// only counts and hashes.
package gateway

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"strings"
	"sync"
	"time"
)

var ephemeralCacheControl = json.RawMessage(`{"type":"ephemeral"}`)

// EnsureCacheBreakpoints injects ephemeral cache_control breakpoints when the
// client sent none. Returns the number injected (0-2).
//
//   - If ANY block in the request already carries cache_control (system
//     blocks, message blocks, or tools), the request is left untouched and 0
//     is returned.
//   - Otherwise, set an ephemeral breakpoint on the system block (if present)
//     and on the last content block of the last message. Max 2 injections.
func EnsureCacheBreakpoints(ar *AnthropicRequest) int {
	if ar == nil {
		return 0
	}
	if hasAnyCacheControl(ar) {
		return 0
	}
	injected := 0

	// 1. System block (if present).
	if len(ar.System) > 0 && strings.TrimSpace(string(ar.System)) != "" && string(ar.System) != "null" {
		var s string
		if err := json.Unmarshal(ar.System, &s); err == nil {
			// String-form system: convert to a single-block array carrying
			// the breakpoint. Text is preserved; translation handles both.
			blocks := []ContentBlock{{Type: "text", Text: s, CacheControl: ephemeralCacheControl}}
			if b, err := json.Marshal(blocks); err == nil {
				ar.System = b
				injected++
			}
		} else if blocks, err := unmarshalBlocks(ar.System); err == nil && len(blocks) > 0 {
			blocks[len(blocks)-1].CacheControl = ephemeralCacheControl
			if b, err := json.Marshal(blocks); err == nil {
				ar.System = b
				injected++
			}
		} else {
			// Try single-object system form.
			var single ContentBlock
			if err := json.Unmarshal(ar.System, &single); err == nil && single.Type != "" {
				single.CacheControl = ephemeralCacheControl
				if b, err := json.Marshal([]ContentBlock{single}); err == nil {
					ar.System = b
					injected++
				}
			}
		}
	}

	// 2. Last content block of the last message.
	if len(ar.Messages) > 0 {
		last := &ar.Messages[len(ar.Messages)-1]
		if len(last.Content) > 0 && string(last.Content) != "null" {
			var s string
			if err := json.Unmarshal(last.Content, &s); err == nil {
				blocks := []ContentBlock{{Type: "text", Text: s, CacheControl: ephemeralCacheControl}}
				if b, err := json.Marshal(blocks); err == nil {
					last.Content = b
					injected++
				}
			} else if blocks, err := unmarshalBlocks(last.Content); err == nil && len(blocks) > 0 {
				blocks[len(blocks)-1].CacheControl = ephemeralCacheControl
				if b, err := json.Marshal(blocks); err == nil {
					last.Content = b
					injected++
				}
			}
		}
	}

	if injected > 2 {
		injected = 2
	}
	return injected
}

// hasAnyCacheControl reports whether any system block, message block, or
// tool already carries a cache_control value.
func hasAnyCacheControl(ar *AnthropicRequest) bool {
	for _, t := range ar.Tools {
		if len(t.CacheControl) > 0 && strings.TrimSpace(string(t.CacheControl)) != "" && string(t.CacheControl) != "null" {
			return true
		}
	}
	if len(ar.System) > 0 && string(ar.System) != "null" {
		if blocks, err := unmarshalBlocks(ar.System); err == nil {
			for _, b := range blocks {
				if len(b.CacheControl) > 0 && strings.TrimSpace(string(b.CacheControl)) != "" && string(b.CacheControl) != "null" {
					return true
				}
			}
		} else {
			var single ContentBlock
			if err := json.Unmarshal(ar.System, &single); err == nil && len(single.CacheControl) > 0 && string(single.CacheControl) != "null" {
				return true
			}
		}
	}
	for _, m := range ar.Messages {
		if len(m.Content) == 0 {
			continue
		}
		if blocks, err := unmarshalBlocks(m.Content); err == nil {
			for _, b := range blocks {
				if len(b.CacheControl) > 0 && strings.TrimSpace(string(b.CacheControl)) != "" && string(b.CacheControl) != "null" {
					return true
				}
			}
		}
	}
	return false
}

func unmarshalBlocks(raw json.RawMessage) ([]ContentBlock, error) {
	var blocks []ContentBlock
	if err := json.Unmarshal(raw, &blocks); err != nil {
		return nil, err
	}
	return blocks, nil
}

// --- Exact-match response cache -------------------------------------------

const (
	responseCacheTTL      = 5 * time.Minute
	responseCacheMaxItems = 256
)

type cacheEntry struct {
	body      []byte
	expiresAt time.Time
}

// ResponseCache is a mutex-guarded exact-match cache for non-streaming
// POST /v1/messages responses without tools and without thinking.
type ResponseCache struct {
	mu         sync.Mutex
	entries    map[string]cacheEntry
	ttl        time.Duration
	maxEntries int
	now        func() time.Time
}

// NewResponseCache creates a cache with 5-minute TTL and 256-entry cap.
func NewResponseCache() *ResponseCache {
	return &ResponseCache{
		entries:    make(map[string]cacheEntry),
		ttl:        responseCacheTTL,
		maxEntries: responseCacheMaxItems,
		now:        time.Now,
	}
}

// Cacheable reports whether ar is eligible for exact-match caching:
// non-streaming, no tools, no thinking.
func (c *ResponseCache) Cacheable(ar *AnthropicRequest) bool {
	if c == nil || ar == nil {
		return false
	}
	if ar.Stream {
		return false
	}
	if len(ar.Tools) > 0 {
		return false
	}
	if !isEmptyRaw(ar.Thinking) {
		return false
	}
	return true
}

func isEmptyRaw(raw json.RawMessage) bool {
	if len(raw) == 0 {
		return true
	}
	s := strings.TrimSpace(string(raw))
	return s == "" || s == "null" || s == "{}"
}

// cacheKeyPayload is the canonical subset hashed for the cache key.
type cacheKeyPayload struct {
	Model       string              `json:"model"`
	Messages    []AnthropicMessage  `json:"messages"`
	System      json.RawMessage     `json:"system"`
	MaxTokens   int                 `json:"max_tokens"`
	Temperature *float64            `json:"temperature"`
}

// Key returns the hex sha256 of the canonical JSON of
// {model,messages,system,max_tokens,temperature}. It never logs content.
func (c *ResponseCache) Key(ar *AnthropicRequest) string {
	msgs := ar.Messages
	if msgs == nil {
		msgs = []AnthropicMessage{}
	}
	sys := ar.System
	if len(sys) == 0 {
		sys = json.RawMessage("null")
	}
	payload := cacheKeyPayload{
		Model:       ar.Model,
		Messages:    msgs,
		System:      sys,
		MaxTokens:   ar.MaxTokens,
		Temperature: ar.Temperature,
	}
	b, _ := json.Marshal(payload)
	sum := sha256.Sum256(b)
	return hex.EncodeToString(sum[:])
}

// Get returns a copy of the cached body when present and unexpired.
func (c *ResponseCache) Get(key string) ([]byte, bool) {
	if c == nil {
		return nil, false
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	e, ok := c.entries[key]
	if !ok {
		return nil, false
	}
	if !c.now().Before(e.expiresAt) {
		delete(c.entries, key)
		return nil, false
	}
	out := make([]byte, len(e.body))
	copy(out, e.body)
	return out, true
}

// Set stores body under key, evicting the oldest entry when at capacity.
func (c *ResponseCache) Set(key string, body []byte) {
	if c == nil {
		return
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	if _, ok := c.entries[key]; !ok && len(c.entries) >= c.maxEntries {
		// Evict the entry expiring soonest (oldest insertion under fixed TTL).
		var oldest string
		var first = true
		var minTime time.Time
		for k, e := range c.entries {
			if first || e.expiresAt.Before(minTime) {
				oldest, minTime, first = k, e.expiresAt, false
			}
		}
		if oldest != "" {
			delete(c.entries, oldest)
		}
	}
	cp := make([]byte, len(body))
	copy(cp, body)
	c.entries[key] = cacheEntry{body: cp, expiresAt: c.now().Add(c.ttl)}
}

// Lookup returns the cached body for ar when cacheable and present.
func (c *ResponseCache) Lookup(ar *AnthropicRequest) ([]byte, bool) {
	if !c.Cacheable(ar) {
		return nil, false
	}
	return c.Get(c.Key(ar))
}

// Store caches body for ar when cacheable. Non-cacheable requests are ignored.
func (c *ResponseCache) Store(ar *AnthropicRequest, body []byte) {
	if !c.Cacheable(ar) {
		return
	}
	c.Set(c.Key(ar), body)
}
