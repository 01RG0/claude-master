// cache_test.go — unit tests for honest caching (no live calls).
package gateway

import (
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

func fptr(f float64) *float64 { return &f }

func mustAnthropic(t *testing.T, body string) *AnthropicRequest {
	t.Helper()
	var ar AnthropicRequest
	if err := json.Unmarshal([]byte(body), &ar); err != nil {
		t.Fatalf("unmarshal request: %v", err)
	}
	return &ar
}

func hasBreakpoint(t *testing.T, raw json.RawMessage) bool {
	t.Helper()
	var blocks []ContentBlock
	if err := json.Unmarshal(raw, &blocks); err != nil {
		return false
	}
	for _, b := range blocks {
		if len(b.CacheControl) > 0 && string(b.CacheControl) != "null" {
			return true
		}
	}
	return false
}

// 1. Inject 0 when client already sent breakpoints — touch nothing.
func TestEnsureCacheNoOpWhenPresent(t *testing.T) {
	ar := mustAnthropic(t, `{
		"model":"m","max_tokens":16,
		"system":[{"type":"text","text":"sys","cache_control":{"type":"ephemeral"}}],
		"messages":[{"role":"user","content":[{"type":"text","text":"hi"}]}]
	}`)
	beforeSys := string(ar.System)
	beforeMsg := string(ar.Messages[0].Content)
	if n := EnsureCacheBreakpoints(ar); n != 0 {
		t.Fatalf("expected 0 injections when present, got %d", n)
	}
	if string(ar.System) != beforeSys || string(ar.Messages[0].Content) != beforeMsg {
		t.Fatal("request with breakpoints must be untouched")
	}

	// Message-level breakpoint also suppresses injection.
	ar2 := mustAnthropic(t, `{
		"model":"m","max_tokens":16,
		"messages":[{"role":"user","content":[{"type":"text","text":"hi","cache_control":{"type":"ephemeral"}}]}]
	}`)
	if n := EnsureCacheBreakpoints(ar2); n != 0 {
		t.Fatalf("expected 0 when message has breakpoint, got %d", n)
	}

	// Tool-level breakpoint also suppresses injection.
	ar3 := mustAnthropic(t, `{
		"model":"m","max_tokens":16,
		"messages":[{"role":"user","content":[{"type":"text","text":"hi"}]}],
		"tools":[{"name":"t","cache_control":{"type":"ephemeral"}}]
	}`)
	if n := EnsureCacheBreakpoints(ar3); n != 0 {
		t.Fatalf("expected 0 when tool has breakpoint, got %d", n)
	}
}

// 2. Inject at most 2 (system + last block of last message).
func TestEnsureCacheInjectsAtMostTwo(t *testing.T) {
	ar := mustAnthropic(t, `{
		"model":"m","max_tokens":16,
		"system":[{"type":"text","text":"sys"}],
		"messages":[
			{"role":"user","content":[{"type":"text","text":"one"}]},
			{"role":"assistant","content":[{"type":"text","text":"two"}]},
			{"role":"user","content":[{"type":"text","text":"three"},{"type":"text","text":"four"}]}
		]
	}`)
	n := EnsureCacheBreakpoints(ar)
	if n > 2 {
		t.Fatalf("injected %d, want <=2", n)
	}
	if n != 2 {
		t.Fatalf("expected 2 injections (system+last), got %d", n)
	}
	if !hasBreakpoint(t, ar.System) {
		t.Fatal("system block should carry breakpoint")
	}
	if !hasBreakpoint(t, ar.Messages[len(ar.Messages)-1].Content) {
		t.Fatal("last message last block should carry breakpoint")
	}
	// Earlier messages must be untouched.
	if hasBreakpoint(t, ar.Messages[0].Content) || hasBreakpoint(t, ar.Messages[1].Content) {
		t.Fatal("only the last message may be touched")
	}
	// First block of last message must be untouched (only last block).
	var lastBlocks []ContentBlock
	if err := json.Unmarshal(ar.Messages[2].Content, &lastBlocks); err != nil {
		t.Fatal(err)
	}
	if len(lastBlocks) != 2 {
		t.Fatalf("last message blocks=%d", len(lastBlocks))
	}
	if len(lastBlocks[0].CacheControl) != 0 {
		t.Fatal("only the last block of the last message should carry a breakpoint")
	}
	if len(lastBlocks[1].CacheControl) == 0 {
		t.Fatal("last block missing breakpoint")
	}
}

// 3. System-only request (no messages) gets a single injection.
func TestEnsureCacheSystemOnly(t *testing.T) {
	ar := mustAnthropic(t, `{
		"model":"m","max_tokens":16,
		"system":[{"type":"text","text":"sys-only"}],
		"messages":[]
	}`)
	n := EnsureCacheBreakpoints(ar)
	if n != 1 {
		t.Fatalf("system-only should inject 1, got %d", n)
	}
	if !hasBreakpoint(t, ar.System) {
		t.Fatal("system breakpoint missing")
	}
}

// 3b. String-form system and content are converted with breakpoints.
func TestEnsureCacheStringForms(t *testing.T) {
	ar := mustAnthropic(t, `{
		"model":"m","max_tokens":16,
		"system":"sys text",
		"messages":[{"role":"user","content":"hello"}]
	}`)
	n := EnsureCacheBreakpoints(ar)
	if n != 2 {
		t.Fatalf("string forms should inject 2, got %d", n)
	}
	// System must still translate to the same text.
	text, err := extractSystemText(ar.System)
	if err != nil || text != "sys text" {
		t.Fatalf("system text changed: %q err=%v", text, err)
	}
	if !hasBreakpoint(t, ar.System) || !hasBreakpoint(t, ar.Messages[0].Content) {
		t.Fatal("string forms missing breakpoints")
	}
}

// 4. Tools request is never cached.
func TestResponseCacheToolsNeverCached(t *testing.T) {
	c := NewResponseCache()
	ar := mustAnthropic(t, `{
		"model":"m","max_tokens":8,
		"messages":[{"role":"user","content":[{"type":"text","text":"hi"}]}],
		"tools":[{"name":"bash","description":"run","input_schema":{"type":"object"}}]
	}`)
	if c.Cacheable(ar) {
		t.Fatal("tools request must not be cacheable")
	}
	if _, ok := c.Lookup(ar); ok {
		t.Fatal("tools Lookup must miss")
	}
	c.Store(ar, []byte(`{"x":1}`))
	if _, ok := c.Get(c.Key(ar)); ok {
		t.Fatal("tools Store must be ignored")
	}
}

// 5. Stream request is never cached.
func TestResponseCacheStreamNeverCached(t *testing.T) {
	c := NewResponseCache()
	ar := mustAnthropic(t, `{
		"model":"m","max_tokens":8,"stream":true,
		"messages":[{"role":"user","content":[{"type":"text","text":"hi"}]}]
	}`)
	if c.Cacheable(ar) {
		t.Fatal("stream request must not be cacheable")
	}
	if _, ok := c.Lookup(ar); ok {
		t.Fatal("stream Lookup must miss")
	}
	c.Store(ar, []byte(`{"x":1}`))
	if _, ok := c.Get(c.Key(ar)); ok {
		t.Fatal("stream Store must be ignored")
	}
}

// 5b. Thinking request is never cached.
func TestResponseCacheThinkingNeverCached(t *testing.T) {
	c := NewResponseCache()
	ar := mustAnthropic(t, `{
		"model":"m","max_tokens":8,
		"thinking":{"type":"enabled","budget_tokens":1000},
		"messages":[{"role":"user","content":[{"type":"text","text":"hi"}]}]
	}`)
	if c.Cacheable(ar) {
		t.Fatal("thinking request must not be cacheable")
	}
	c.Store(ar, []byte(`{"x":1}`))
	if _, ok := c.Get(c.Key(ar)); ok {
		t.Fatal("thinking Store must be ignored")
	}
}

// 6. TTL expiry evicts entries.
func TestResponseCacheTTLExpiry(t *testing.T) {
	c := NewResponseCache()
	now := time.Now()
	c.now = func() time.Time { return now }
	c.ttl = 5 * time.Minute

	ar := mustAnthropic(t, `{
		"model":"m","max_tokens":8,
		"messages":[{"role":"user","content":[{"type":"text","text":"hi"}]}]
	}`)
	body := []byte(`{"id":"msg_1","type":"message"}`)
	c.Store(ar, body)
	if _, ok := c.Lookup(ar); !ok {
		t.Fatal("expected hit before expiry")
	}
	now = now.Add(5*time.Minute + time.Second)
	if _, ok := c.Lookup(ar); ok {
		t.Fatal("expected miss after TTL expiry")
	}
}

// 7. Key differs on temperature (and other canonical fields).
func TestResponseCacheKeyDiffersOnTemperature(t *testing.T) {
	c := NewResponseCache()
	base := `{"model":"m","max_tokens":8,"messages":[{"role":"user","content":[{"type":"text","text":"hi"}]}]%s}`
	a := mustAnthropic(t, `{"model":"m","max_tokens":8,"messages":[{"role":"user","content":[{"type":"text","text":"hi"}]}]}`)
	b := mustAnthropic(t, `{"model":"m","max_tokens":8,"temperature":0.7,"messages":[{"role":"user","content":[{"type":"text","text":"hi"}]}]}`)
	_ = base
	a.Temperature = nil
	b.Temperature = fptr(0.7)
	if c.Key(a) == c.Key(b) {
		t.Fatal("keys must differ when temperature differs")
	}
	b2 := mustAnthropic(t, `{"model":"m","max_tokens":8,"temperature":0.7,"messages":[{"role":"user","content":[{"type":"text","text":"hi"}]}]}`)
	b2.Temperature = fptr(0.7)
	if c.Key(b) != c.Key(b2) {
		t.Fatal("identical requests must share a key")
	}
	c2 := mustAnthropic(t, `{"model":"other","max_tokens":8,"messages":[{"role":"user","content":[{"type":"text","text":"hi"}]}]}`)
	if c.Key(a) == c.Key(c2) {
		t.Fatal("keys must differ across models")
	}
}

// 8. HIT preserves usage byte-for-byte (no fabricated cache_read).
func TestResponseCacheHitPreservesUsage(t *testing.T) {
	c := NewResponseCache()
	ar := mustAnthropic(t, `{
		"model":"m","max_tokens":8,
		"messages":[{"role":"user","content":[{"type":"text","text":"hi"}]}]
	}`)
	stored := &AnthropicResponse{
		ID: "msg_1", Type: "message", Role: "assistant", Model: "m",
		Content:    []ContentBlock{{Type: "text", Text: "hello"}},
		StopReason: "end_turn",
		Usage:      map[string]int{"input_tokens": 10, "output_tokens": 5},
	}
	raw, _ := json.Marshal(stored)
	c.Store(ar, raw)
	got, ok := c.Lookup(ar)
	if !ok {
		t.Fatal("expected HIT")
	}
	var back AnthropicResponse
	if err := json.Unmarshal(got, &back); err != nil {
		t.Fatal(err)
	}
	if back.Usage["input_tokens"] != 10 || back.Usage["output_tokens"] != 5 {
		t.Fatalf("usage not preserved: %v", back.Usage)
	}
	if _, ok := back.Usage["cache_read_input_tokens"]; ok {
		t.Fatal("replay must not fabricate cache_read_input_tokens")
	}
	if string(got) != string(raw) {
		t.Fatal("HIT body must be byte-identical (passthrough)")
	}
}

// 9. proxyResponse stores on MISS with header; second serve is a HIT.
func TestProxyResponseMissThenHit(t *testing.T) {
	c := NewResponseCache()
	s := NewServer(&Config{Providers: []Provider{}, Routing: RoutingConfig{Strategy: "priority"}})
	s.respCache = c

	ar := mustAnthropic(t, `{
		"model":"m","max_tokens":8,
		"messages":[{"role":"user","content":[{"type":"text","text":"hi"}]}]
	}`)
	_ = EnsureCacheBreakpoints(ar)

	upstreamBody := `{"id":"chatcmpl-1","model":"m","choices":[{"index":0,"message":{"role":"assistant","content":"hello"},"finish_reason":"stop"}],"usage":{"prompt_tokens":10,"completion_tokens":5}}`
	resp := &http.Response{StatusCode: 200, Body: io.NopCloser(strings.NewReader(upstreamBody))}

	rr := httptest.NewRecorder()
	s.proxyResponse(rr, resp, "m", ar)
	if rr.Header().Get("X-Gateway-Cache") != "MISS" {
		t.Fatalf("expected MISS header, got %q", rr.Header().Get("X-Gateway-Cache"))
	}
	var first AnthropicResponse
	if err := json.Unmarshal(rr.Body.Bytes(), &first); err != nil {
		t.Fatal(err)
	}
	if len(first.Content) == 0 || first.Content[0].Text != "hello" {
		t.Fatalf("unexpected content: %+v", first.Content)
	}

	// HIT path replays identical bytes.
	cached, ok := c.Lookup(ar)
	if !ok {
		t.Fatal("proxyResponse should have stored the response")
	}
	if string(cached) != strings.TrimSpace(rr.Body.String()) {
		t.Fatal("stored body must match MISS body byte-for-byte")
	}
}

// 10. handleMessages serves HIT without contacting upstream.
func TestHandleMessagesHitBypassesUpstream(t *testing.T) {
	var upstreamHits int
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		upstreamHits++
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"id":"chatcmpl-9","model":"llama","choices":[{"index":0,"message":{"role":"assistant","content":"upstream"},"finish_reason":"stop"}],"usage":{"prompt_tokens":3,"completion_tokens":2}}`))
	}))
	defer upstream.Close()

	t.Setenv("HIT_TEST_KEY", "test-key-value")
	en := true
	cfg := &Config{
		Providers: []Provider{{
			Name: "mock", BaseURL: upstream.URL, PrivacyPolicy: PrivacyZeroRetention,
			Enabled: &en, Models: []string{"llama"},
			KeyPools: []KeyPool{{AccountLabel: "a", EnvVar: "HIT_TEST_KEY", Priority: 10}},
		}},
		Routing: RoutingConfig{Strategy: "priority"},
	}
	s := NewServer(cfg)
	s.client = upstream.Client()

	body := `{"model":"llama","max_tokens":16,"messages":[{"role":"user","content":[{"type":"text","text":"repeat me"}]}]}`

	// First request: MISS, hits upstream once.
	req1 := httptest.NewRequest(http.MethodPost, "/v1/messages", strings.NewReader(body))
	rr1 := httptest.NewRecorder()
	s.Handler().ServeHTTP(rr1, req1)
	if rr1.Code != http.StatusOK {
		t.Fatalf("first status %d: %s", rr1.Code, rr1.Body.String())
	}
	if got := rr1.Header().Get("X-Gateway-Cache"); got != "MISS" {
		t.Fatalf("first should be MISS, got %q", got)
	}
	if upstreamHits != 1 {
		t.Fatalf("first should hit upstream once, got %d", upstreamHits)
	}

	// Second identical request: HIT, no additional upstream contact.
	req2 := httptest.NewRequest(http.MethodPost, "/v1/messages", strings.NewReader(body))
	rr2 := httptest.NewRecorder()
	s.Handler().ServeHTTP(rr2, req2)
	if rr2.Code != http.StatusOK {
		t.Fatalf("second status %d: %s", rr2.Code, rr2.Body.String())
	}
	if got := rr2.Header().Get("X-Gateway-Cache"); got != "HIT" {
		t.Fatalf("second should be HIT, got %q", got)
	}
	if upstreamHits != 1 {
		t.Fatalf("HIT must bypass upstream; hits=%d", upstreamHits)
	}
	var b1, b2 AnthropicResponse
	if err := json.Unmarshal(rr1.Body.Bytes(), &b1); err != nil {
		t.Fatal(err)
	}
	if err := json.Unmarshal(rr2.Body.Bytes(), &b2); err != nil {
		t.Fatal(err)
	}
	if len(b1.Content) == 0 || len(b2.Content) == 0 || b1.Content[0].Text != b2.Content[0].Text {
		t.Fatal("HIT must replay identical content (usage passthrough)")
	}
	if _, ok := b2.Usage["cache_read_input_tokens"]; ok {
		t.Fatal("gateway replay must not fabricate cache_read_input_tokens")
	}
}
