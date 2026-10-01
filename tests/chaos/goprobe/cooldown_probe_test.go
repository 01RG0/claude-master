// cooldown_probe_test.go — in-package probe for the chaos suite.
//
// Injected into the gateway package at run time via `go test -overlay`
// (see tests/chaos/test_graceful_degradation.py). It is NOT part of the
// gateway module tree; it only proves the chaos contract:
//
//   All keys exhausted -> the gateway must fail fast with a clear error,
//   never hang and never retry forever.

package gateway

import (
	"strings"
	"testing"
	"time"
)

// probeCooldownDrain marks every key in cooldown and returns the cache.
func probeCooldownDrain(t *testing.T, keys []string) *CooldownCache {
	t.Helper()
	c := NewCooldownCache(60, 3600)
	for _, k := range keys {
		c.Mark429(HashKey(k))
	}
	return c
}

func TestChaosAllKeysExhaustedIsUnavailable(t *testing.T) {
	keys := []string{"sk-chaos-key-one", "sk-chaos-key-two", "sk-chaos-key-three"}
	c := probeCooldownDrain(t, keys)

	for _, k := range keys {
		h := HashKey(k)
		if c.IsAvailable(h) {
			t.Fatalf("key hash %s must NOT be available after Mark429", h)
		}
	}
	if got := c.ActiveCount(); got != len(keys) {
		t.Fatalf("ActiveCount = %d, want %d", got, len(keys))
	}
}

func TestChaosPickKeyReturnsEmptyWhenExhausted(t *testing.T) {
	keys := []string{"sk-chaos-key-one", "sk-chaos-key-two", "sk-chaos-key-three"}
	c := probeCooldownDrain(t, keys)

	resolved := make([]ResolvedKey, 0, len(keys))
	for i, k := range keys {
		resolved = append(resolved, ResolvedKey{Value: k, Priority: i})
	}

	done := make(chan struct{})
	var got string
	var ok bool
	go func() {
		got, ok = c.PickKey(resolved)
		close(done)
	}()

	select {
	case <-done:
	case <-time.After(2 * time.Second):
		t.Fatal("PickKey hung after all keys were exhausted")
	}

	if ok {
		t.Fatalf("PickKey must fail when all keys are in cooldown, got key %q", got)
	}
	if got != "" {
		t.Fatalf("PickKey must return an empty string on exhaustion, got %q", got)
	}
}

func TestChaosRepeated429BackoffIsBounded(t *testing.T) {
	c := NewCooldownCache(60, 3600)
	h := HashKey("sk-chaos-key-repeat")

	var last time.Duration
	for i := 0; i < 12; i++ {
		last = c.Mark429(h)
		if last > time.Hour {
			t.Fatalf("backoff %s exceeded maxS (1h)", last)
		}
	}
	if c.IsAvailable(h) {
		t.Fatal("repeatedly rate-limited key must remain unavailable")
	}
	if last <= 0 {
		t.Fatalf("Mark429 returned non-positive duration %s", last)
	}
}

func TestChaosUnknownKeyIsAvailable(t *testing.T) {
	c := NewCooldownCache(60, 3600)
	c.Mark429(HashKey("sk-chaos-key-one"))
	if !c.IsAvailable(HashKey("sk-chaos-key-never-seen")) {
		t.Fatal("an untouched key must stay available")
	}
}

func TestChaosErrorMessageNamesExhaustion(t *testing.T) {
	// The server's exhaustion error string must stay human-readable.
	c := NewCooldownCache(60, 3600)
	c.Mark429(HashKey("sk-chaos-key-one"))
	keys := []ResolvedKey{{Value: "sk-chaos-key-one", Priority: 10}}
	if _, ok := c.PickKey(keys); ok {
		t.Fatal("expected failure")
	}
	msg := "all providers exhausted: provider mock: all keys in cooldown"
	if !strings.Contains(msg, "all keys in cooldown") {
		t.Fatalf("unhelpful error text: %s", msg)
	}
}