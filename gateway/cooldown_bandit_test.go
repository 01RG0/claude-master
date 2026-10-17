package gateway

import (
	"bufio"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

func TestCooldownCascadeOn429(t *testing.T) {
	os.Setenv("TEST_KEY_1", "sk-test-key-one-aaaaaaaa")
	os.Setenv("TEST_KEY_2", "sk-test-key-two-bbbbbbbb")
	t.Cleanup(func() {
		os.Unsetenv("TEST_KEY_1")
		os.Unsetenv("TEST_KEY_2")
	})

	var hits atomic.Int32
	var usedAuth []string
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		auth := r.Header.Get("Authorization")
		usedAuth = append(usedAuth, auth)
		n := hits.Add(1)
		if n == 1 {
			w.WriteHeader(http.StatusTooManyRequests)
			_, _ = w.Write([]byte(`{"error":"rate_limited"}`))
			return
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{
			"id":"chatcmpl-1","model":"llama","choices":[
				{"index":0,"message":{"role":"assistant","content":"ok"},"finish_reason":"stop"}
			]
		}`))
	}))
	defer upstream.Close()

	en := true
	cfg := &Config{
		ListenAddr: "127.0.0.1:0",
		Providers: []Provider{{
			Name: "mock", BaseURL: upstream.URL, PrivacyPolicy: PrivacyZeroRetention,
			Enabled: &en,
			Models:  []string{"llama"},
			KeyPools: []KeyPool{
				{AccountLabel: "personal-01", EnvVar: "TEST_KEY_1", Priority: 20},
				{AccountLabel: "personal-01", EnvVar: "TEST_KEY_2", Priority: 10},
			},
		}},
		Routing: RoutingConfig{
			Strategy:             "thompson_sampling",
			CooldownBaseS:        60,
			CooldownMaxS:         3600,
			GitHubModelsFallback: true,
		},
	}
	s := NewServer(cfg)
	s.client = upstream.Client()

	body := `{"model":"claude","max_tokens":16,"messages":[{"role":"user","content":"hi"}]}`
	req := httptest.NewRequest(http.MethodPost, "/v1/messages", strings.NewReader(body))
	rr := httptest.NewRecorder()
	s.Handler().ServeHTTP(rr, req)

	if rr.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d body=%s", rr.Code, rr.Body.String())
	}
	if hits.Load() != 2 {
		t.Fatalf("expected 2 upstream hits (429 then success), got %d", hits.Load())
	}
	if len(usedAuth) != 2 {
		t.Fatalf("expected 2 auth headers, got %v", usedAuth)
	}
	if usedAuth[0] == usedAuth[1] {
		t.Fatalf("expected cascade to different key, got same auth twice")
	}
	if !strings.Contains(usedAuth[0], "sk-test-key-one") {
		t.Fatalf("highest priority key should be tried first: %s", usedAuth[0])
	}
	if !strings.Contains(usedAuth[1], "sk-test-key-two") {
		t.Fatalf("second key should be used after 429: %s", usedAuth[1])
	}
	if s.Cooldown().ActiveCount() < 1 {
		t.Fatal("key1 should be in cooldown after 429")
	}
	h1 := HashKey("sk-test-key-one-aaaaaaaa")
	if s.Cooldown().IsAvailable(h1) {
		t.Fatal("key1 hash should not be available")
	}
}

func TestStreamingSSEAnthropicProtocol(t *testing.T) {
	os.Setenv("TEST_STREAM_KEY", "sk-stream-key-xxxxxxxxxxxx")
	t.Cleanup(func() { os.Unsetenv("TEST_STREAM_KEY") })

	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		flusher, _ := w.(http.Flusher)
		w.Header().Set("Content-Type", "text/event-stream")
		w.WriteHeader(http.StatusOK)
		chunks := []string{
			`{"id":"c1","model":"llama","choices":[{"index":0,"delta":{"role":"assistant","content":"Hel"},"finish_reason":null}]}`,
			`{"id":"c1","model":"llama","choices":[{"index":0,"delta":{"content":"lo"},"finish_reason":null}]}`,
			`{"id":"c1","model":"llama","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}`,
		}
		for _, c := range chunks {
			fmt.Fprintf(w, "data: %s\n\n", c)
			flusher.Flush()
		}
		fmt.Fprintf(w, "data: [DONE]\n\n")
		flusher.Flush()
	}))
	defer upstream.Close()

	en := true
	cfg := &Config{
		Providers: []Provider{{
			Name: "mock", BaseURL: upstream.URL, PrivacyPolicy: PrivacyZeroRetention,
			Enabled: &en, Models: []string{"llama"},
			KeyPools: []KeyPool{{AccountLabel: "a", EnvVar: "TEST_STREAM_KEY", Priority: 10}},
		}},
		Routing: RoutingConfig{Strategy: "thompson_sampling", CooldownBaseS: 1, GitHubModelsFallback: true},
	}
	s := NewServer(cfg)
	s.client = &http.Client{Timeout: 5 * time.Second}

	body := `{"model":"claude","max_tokens":16,"stream":true,"messages":[{"role":"user","content":"hi"}],"tools":[{"name":"bash","description":"run","input_schema":{"type":"object"}}]}`
	req := httptest.NewRequest(http.MethodPost, "/v1/messages", strings.NewReader(body))
	rr := httptest.NewRecorder()
	s.Handler().ServeHTTP(rr, req)

	if rr.Code != http.StatusOK {
		t.Fatalf("status %d: %s", rr.Code, rr.Body.String())
	}
	ct := rr.Header().Get("Content-Type")
	if !strings.Contains(ct, "text/event-stream") {
		t.Fatalf("expected SSE content-type, got %q", ct)
	}

	events := parseSSEEvents(rr.Body.String())
	want := []string{"message_start", "content_block_start", "content_block_delta", "content_block_delta", "content_block_stop", "message_delta", "message_stop"}
	if len(events) < len(want) {
		t.Fatalf("events=%v want at least %v", events, want)
	}
	for i, e := range want {
		if events[i] != e {
			t.Fatalf("event[%d]=%q want %q; all=%v", i, events[i], e, events)
		}
	}
	if !strings.Contains(rr.Body.String(), `"type":"text_delta"`) && !strings.Contains(rr.Body.String(), `"type": "text_delta"`) {
		// JSON marshal has no spaces
		if !strings.Contains(rr.Body.String(), "text_delta") {
			t.Fatalf("missing text_delta in SSE body: %s", rr.Body.String())
		}
	}
}

func parseSSEEvents(body string) []string {
	var events []string
	sc := bufio.NewScanner(strings.NewReader(body))
	for sc.Scan() {
		line := sc.Text()
		if strings.HasPrefix(line, "event: ") {
			events = append(events, strings.TrimPrefix(line, "event: "))
		}
	}
	return events
}

func TestPrivacyBlocksGeminiForSensitiveContent(t *testing.T) {
	os.Setenv("GROQ_KEY", "sk-groq-key-yyyyyyyyyyyy")
	os.Setenv("GEMINI_KEY", "sk-gemini-key-zzzzzzzzzz")
	t.Cleanup(func() {
		os.Unsetenv("GROQ_KEY")
		os.Unsetenv("GEMINI_KEY")
	})

	var hitProvider atomic.Value
	upstreamGroq := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		hitProvider.Store("groq")
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"id":"1","model":"llama","choices":[{"index":0,"message":{"role":"assistant","content":"safe"},"finish_reason":"stop"}]}`))
	}))
	defer upstreamGroq.Close()
	upstreamGem := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		hitProvider.Store("gemini")
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"id":"1","model":"gemini","choices":[{"index":0,"message":{"role":"assistant","content":"leak"},"finish_reason":"stop"}]}`))
	}))
	defer upstreamGem.Close()

	en := true
	cfg := &Config{
		Providers: []Provider{
			{Name: "gemini", BaseURL: upstreamGem.URL, PrivacyPolicy: PrivacyPublicDataOnly, Enabled: &en,
				Models: []string{"gemini-flash"}, KeyPools: []KeyPool{{AccountLabel: "g", EnvVar: "GEMINI_KEY", Priority: 100}}},
			{Name: "groq", BaseURL: upstreamGroq.URL, PrivacyPolicy: PrivacyZeroRetention, Enabled: &en,
				Models: []string{"llama"}, KeyPools: []KeyPool{{AccountLabel: "g", EnvVar: "GROQ_KEY", Priority: 10}}},
		},
		Routing: RoutingConfig{
			Strategy: "priority", FallbackChain: []string{"gemini", "groq"},
			CooldownBaseS: 1, GitHubModelsFallback: true,
		},
	}
	s := NewServer(cfg)
	s.client = &http.Client{Timeout: 5 * time.Second}

	// Sensitive: contains .env secret-like content + source path.
	body := `{
		"model":"claude","max_tokens":32,
		"messages":[{"role":"user","content":"Please fix gateway/server.go — API_KEY=sk-abc12345678901234567890 from .env"}],
		"metadata":{"privacy_class":"public"}
	}`
	req := httptest.NewRequest(http.MethodPost, "/v1/messages", strings.NewReader(body))
	rr := httptest.NewRecorder()
	s.Handler().ServeHTTP(rr, req)
	if rr.Code != http.StatusOK {
		t.Fatalf("status %d: %s", rr.Code, rr.Body.String())
	}
	if hitProvider.Load() != "groq" {
		t.Fatalf("sensitive request must not hit gemini; got %v", hitProvider.Load())
	}

	// Explicit internal metadata also blocks gemini.
	hitProvider.Store("")
	body2 := `{"model":"claude","max_tokens":8,"messages":[{"role":"user","content":"hello theory"}],"metadata":{"privacy_class":"internal"}}`
	req2 := httptest.NewRequest(http.MethodPost, "/v1/messages", strings.NewReader(body2))
	rr2 := httptest.NewRecorder()
	s.Handler().ServeHTTP(rr2, req2)
	if hitProvider.Load() != "groq" {
		t.Fatalf("internal metadata must skip gemini; got %v", hitProvider.Load())
	}
}

func TestThompsonSamplingPrefersHealthyModel(t *testing.T) {
	b := NewThompsonBandit([]string{"good-model", "bad-model"})
	for i := 0; i < 40; i++ {
		b.Update("good-model", true)
		b.Update("bad-model", false)
	}
	counts := map[string]int{}
	for i := 0; i < 200; i++ {
		counts[b.SampleModel([]string{"good-model", "bad-model"})]++
	}
	if counts["good-model"] <= counts["bad-model"] {
		t.Fatalf("expected good-model to dominate samples: %v", counts)
	}
	gs, _ := b.Stats("good-model")
	if gs.Successes < 40 {
		t.Fatalf("successes not recorded: %+v", gs)
	}
}

func TestGitHubModelsExcludedFromRotationPool(t *testing.T) {
	en := true
	cfg := &Config{
		BrainSocket: "/tmp/claude_brain_does_not_exist.sock",
		Providers: []Provider{
			{Name: "groq", BaseURL: "https://api.groq.com/openai/v1", PrivacyPolicy: PrivacyZeroRetention, Enabled: &en, Models: []string{"llama"}, KeyPools: []KeyPool{{EnvVar: "X"}}},
			{Name: "github-models", BaseURL: "https://models.github.ai/inference", PrivacyPolicy: PrivacyInternal, Enabled: &en, Models: []string{"gpt"}, KeyPools: []KeyPool{{EnvVar: "Y"}}},
		},
		Routing: RoutingConfig{GitHubModelsFallback: true},
	}
	primary, gh := EligibleProviders(cfg, PrivacyClassPublic)
	if len(primary) != 1 || primary[0].Name != "groq" {
		t.Fatalf("primary=%v", primary)
	}
	if len(gh) != 1 || !IsGitHubModels(gh[0]) {
		t.Fatalf("github fallback=%v", gh)
	}
	order := ResolveFallbackOrder(cfg)
	if len(order) == 0 || order[len(order)-1] != "github-models" {
		// static chain ends with github-models
		found := false
		for _, n := range StaticFallbackChain {
			if n == "github-models" {
				found = true
			}
		}
		if !found {
			t.Fatal("static fallback missing github-models")
		}
		_ = order
	}
}

func TestOutcomeReportingUpdatesBandit(t *testing.T) {
	cfg := &Config{
		Providers: []Provider{},
		Routing:   RoutingConfig{Strategy: "thompson_sampling", GitHubModelsFallback: true},
	}
	s := NewServer(cfg)
	body := `{"model_id":"llama-3","success":true,"latency_ms":12.5}`
	req := httptest.NewRequest(http.MethodPost, "/v1/outcome", strings.NewReader(body))
	rr := httptest.NewRecorder()
	s.Handler().ServeHTTP(rr, req)
	if rr.Code != http.StatusOK {
		t.Fatalf("status %d", rr.Code)
	}
	st, ok := s.Bandit().Stats("llama-3")
	if !ok || st.Successes != 1 {
		t.Fatalf("stats=%+v ok=%v", st, ok)
	}
}

func TestTranslateRequestWithTools(t *testing.T) {
	ar := &AnthropicRequest{
		Model:     "claude",
		MaxTokens: 100,
		Messages: []AnthropicMessage{{
			Role: "user",
			Content: json.RawMessage(`[{"type":"text","text":"run it"},{"type":"tool_use","id":"t1","name":"bash","input":{"cmd":"ls"}}]`),
		}},
		Tools: []AnthropicTool{{
			Name: "bash", Description: "shell",
			InputSchema: json.RawMessage(`{"type":"object"}`),
		}},
	}
	or, notes := TranslateRequest(ar, "llama", AdapterSpec{})
	if or == nil {
		t.Fatalf("translation failed: %v", notes)
	}
	if or.Model != "llama" || len(or.Tools) != 1 {
		t.Fatalf("unexpected: %+v", or)
	}
	if len(or.Messages) == 0 || len(or.Messages[0].ToolCalls) != 1 {
		t.Fatalf("tool_use not translated: %+v", or.Messages)
	}
}

func TestHashKeyNeverEqualsRawSecret(t *testing.T) {
	secret := "sk-super-secret-value-do-not-log"
	h := HashKey(secret)
	if h == secret || strings.Contains(h, secret) {
		t.Fatal("hash must not contain raw secret")
	}
	if len(h) != 16 { // 8 bytes hex
		t.Fatalf("unexpected hash len %d", len(h))
	}
}

func TestLoadConfigDefaults(t *testing.T) {
	raw := []byte(`{
		"listen_addr":"127.0.0.1:9090",
		"brain_socket":"/tmp/x.sock",
		"providers":[{"name":"groq","base_url":"https://example.com","privacy_policy":"zero_retention","key_pools":[{"account_label":"a","env_var":"K"}],"models":["m"]}],
		"routing":{"strategy":"thompson_sampling"}
	}`)
	cfg, err := ParseConfig(raw)
	if err != nil {
		t.Fatal(err)
	}
	if !cfg.Routing.GitHubModelsFallback {
		t.Fatal("github_models_fallback_only should default true")
	}
	if !cfg.Providers[0].IsEnabled() {
		t.Fatal("enabled should default true")
	}
	if cfg.Routing.CooldownBaseS != 60 {
		t.Fatalf("cooldown default: %v", cfg.Routing.CooldownBaseS)
	}
}

func TestContainsSensitiveContent(t *testing.T) {
	ar := &AnthropicRequest{
		Messages: []AnthropicMessage{{
			Role:    "user",
			Content: json.RawMessage(`"diff --git a/foo.go b/foo.go\n@@ -1 +1 @@\n+func main() {}"`),
		}},
	}
	if !ContainsSensitiveContent(ar) {
		t.Fatal("git diff should be sensitive")
	}
	pub := &AnthropicRequest{
		Messages: []AnthropicMessage{{
			Role:    "user",
			Content: json.RawMessage(`"What is Big-O of binary search?"`),
		}},
	}
	if ContainsSensitiveContent(pub) {
		t.Fatal("theory question should be public")
	}
}

func TestProxyDoesNotLogSecrets(t *testing.T) {
	// Ensure redactForLog strips bearer-like tokens.
	in := "Authorization Bearer sk-abcdefghijklmnopqrstuvwxyz123456"
	out := redactForLog(in)
	if strings.Contains(out, "sk-abcdefghijklmnopqrstuvwxyz123456") {
		t.Fatalf("secret leaked in log scrub: %s", out)
	}
}

func TestStaticFallbackWhenBrainMissing(t *testing.T) {
	cfg := &Config{BrainSocket: "/nonexistent/brain.sock"}
	order := ResolveFallbackOrder(cfg)
	if len(order) < 2 {
		t.Fatalf("expected static chain, got %v", order)
	}
	if BrainAvailable("/nonexistent/brain.sock") {
		t.Fatal("missing socket should be unavailable")
	}
}

func TestPerKeyAndPerModelCooldownUnit(t *testing.T) {
	c := NewCooldownCache(60, 3600)
	key1 := "sk-test-key-alpha-11111111"
	key2 := "sk-test-key-beta-22222222"
	h1 := HashKey(key1)
	h2 := HashKey(key2)

	// Initially active
	if st := c.Status(h1, "model-a"); st != StatusActive {
		t.Fatalf("expected status active, got %s", st)
	}
	if !c.IsAvailableForModel(h1, "model-a") {
		t.Fatal("h1 should be available for model-a")
	}

	// 1. Mark h1 rate-limited on model-a
	dur := c.MarkRateLimited(h1, "model-a")
	if dur != 60*time.Second {
		t.Fatalf("expected 60s, got %v", dur)
	}
	if st := c.Status(h1, "model-a"); st != StatusRateLimited {
		t.Fatalf("expected rate_limited, got %s", st)
	}
	// model-a is in cooldown, but model-b on h1 is active!
	if c.IsAvailableForModel(h1, "model-a") {
		t.Fatal("h1 should NOT be available for model-a")
	}
	if !c.IsAvailableForModel(h1, "model-b") {
		t.Fatal("h1 SHOULD be available for model-b")
	}
	if st := c.Status(h1, "model-b"); st != StatusActive {
		t.Fatalf("expected active for model-b, got %s", st)
	}

	// PickKeyForModel: key1 priority 20, key2 priority 10
	keys := []ResolvedKey{
		{Value: key1, Priority: 20},
		{Value: key2, Priority: 10},
	}
	// For model-a, key1 is rate limited so key2 must be picked
	picked, ok := c.PickKeyForModel(keys, "model-a")
	if !ok || picked != key2 {
		t.Fatalf("expected key2 for model-a, got %v, ok=%v", picked, ok)
	}
	// For model-b, key1 is available and higher priority so key1 must be picked
	picked, ok = c.PickKeyForModel(keys, "model-b")
	if !ok || picked != key1 {
		t.Fatalf("expected key1 for model-b, got %v, ok=%v", picked, ok)
	}

	// 2. Exponential backoff on repeat 429
	dur2 := c.MarkRateLimited(h1, "model-a")
	if dur2 != 120*time.Second {
		t.Fatalf("expected 120s backoff on repeat 429, got %v", dur2)
	}

	// 3. Mark h1 restricted on model-c (HTTP 403, adaptive base backoff)
	durRestricted := c.MarkRestricted(h1, "model-c")
	if durRestricted != 60*time.Second {
		t.Fatalf("expected 60s backoff, got %v", durRestricted)
	}
	if st := c.Status(h1, "model-c"); st != StatusRestricted {
		t.Fatalf("expected restricted, got %s", st)
	}
	if c.IsAvailableForModel(h1, "model-c") {
		t.Fatal("h1 should not be available for model-c")
	}

	// 4. Mark h2 exhausted (HTTP 402, key-wide, adaptive base backoff)
	durExhausted := c.MarkExhausted(h2)
	if durExhausted != 120*time.Second {
		t.Fatalf("expected 120s backoff, got %v", durExhausted)
	}
	if st := c.Status(h2, "any-model"); st != StatusExhausted {
		t.Fatalf("expected exhausted, got %s", st)
	}
	if c.IsAvailableForModel(h2, "model-a") || c.IsAvailableForModel(h2, "model-b") {
		t.Fatal("h2 should be unavailable across all models when exhausted")
	}

	// 5. Mark h1 dead (HTTP 401, key-wide, adaptive base backoff)
	durDead := c.MarkDead(h1)
	if durDead != 300*time.Second {
		t.Fatalf("expected 300s backoff, got %v", durDead)
	}
	if st := c.Status(h1, "model-b"); st != StatusDead {
		t.Fatalf("expected dead, got %s", st)
	}
	if c.IsAvailableForModel(h1, "model-b") {
		t.Fatal("h1 should be dead across all models")
	}

	// 6. Test Entries() inspection
	entries := c.Entries()
	if len(entries) < 3 {
		t.Fatalf("expected at least 3 entries, got %d: %+v", len(entries), entries)
	}
	foundDead := false
	foundExhausted := false
	foundRestricted := false
	for _, e := range entries {
		if e.Status == StatusDead {
			foundDead = true
		}
		if e.Status == StatusExhausted {
			foundExhausted = true
		}
		if e.Status == StatusRestricted {
			foundRestricted = true
		}
	}
	if !foundDead || !foundExhausted || !foundRestricted {
		t.Fatalf("missing expected entry statuses in %+v", entries)
	}
}

func TestCascadeOn401DeadAnd402ExhaustedAnd403Restricted(t *testing.T) {
	os.Setenv("TEST_ROUTE_KEY_1", "sk-route-key-alpha-11111111")
	os.Setenv("TEST_ROUTE_KEY_2", "sk-route-key-beta-22222222")
	t.Cleanup(func() {
		os.Unsetenv("TEST_ROUTE_KEY_1")
		os.Unsetenv("TEST_ROUTE_KEY_2")
	})

	// Test 403 Forbidden -> Restricted (model-scoped)
	t.Run("403_Restricted_ModelScoped", func(t *testing.T) {
		upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			auth := r.Header.Get("Authorization")
			if strings.Contains(auth, "sk-route-key-alpha") {
				w.WriteHeader(http.StatusForbidden)
				_, _ = w.Write([]byte(`{"error":"forbidden"}`))
				return
			}
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write([]byte(`{"id":"chatcmpl-1","model":"llama","choices":[{"index":0,"message":{"role":"assistant","content":"ok"},"finish_reason":"stop"}]}`))
		}))
		defer upstream.Close()

		en := true
		cfg := &Config{
			Providers: []Provider{{
				Name: "mock", BaseURL: upstream.URL, PrivacyPolicy: PrivacyZeroRetention, Enabled: &en,
				Models: []string{"llama"},
				KeyPools: []KeyPool{
					{AccountLabel: "p-01", EnvVar: "TEST_ROUTE_KEY_1", Priority: 20},
					{AccountLabel: "p-01", EnvVar: "TEST_ROUTE_KEY_2", Priority: 10},
				},
			}},
			Routing: RoutingConfig{Strategy: "priority", GitHubModelsFallback: true},
		}
		s := NewServer(cfg)
		s.client = upstream.Client()

		body := `{"model":"llama","max_tokens":16,"messages":[{"role":"user","content":"hi"}]}`
		req := httptest.NewRequest(http.MethodPost, "/v1/messages", strings.NewReader(body))
		rr := httptest.NewRecorder()
		s.Handler().ServeHTTP(rr, req)

		if rr.Code != http.StatusOK {
			t.Fatalf("expected 200 after 403 cascade, got %d body=%s", rr.Code, rr.Body.String())
		}
		h1 := HashKey("sk-route-key-alpha-11111111")
		if st := s.Cooldown().Status(h1, "llama"); st != StatusRestricted {
			t.Fatalf("expected key1 to be restricted for llama, got %s", st)
		}
		if st := s.Cooldown().Status(h1, "other-model"); st != StatusActive {
			t.Fatalf("expected key1 to be active for other-model, got %s", st)
		}
	})

	// Test 401 Unauthorized -> Dead (key-wide, 24h backoff)
	t.Run("401_Dead_KeyWide", func(t *testing.T) {
		upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			auth := r.Header.Get("Authorization")
			if strings.Contains(auth, "sk-route-key-alpha") {
				w.WriteHeader(http.StatusUnauthorized)
				_, _ = w.Write([]byte(`{"error":"invalid_key"}`))
				return
			}
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write([]byte(`{"id":"chatcmpl-1","model":"llama","choices":[{"index":0,"message":{"role":"assistant","content":"ok"},"finish_reason":"stop"}]}`))
		}))
		defer upstream.Close()

		en := true
		cfg := &Config{
			Providers: []Provider{{
				Name: "mock", BaseURL: upstream.URL, PrivacyPolicy: PrivacyZeroRetention, Enabled: &en,
				Models: []string{"llama"},
				KeyPools: []KeyPool{
					{AccountLabel: "p-01", EnvVar: "TEST_ROUTE_KEY_1", Priority: 20},
					{AccountLabel: "p-01", EnvVar: "TEST_ROUTE_KEY_2", Priority: 10},
				},
			}},
			Routing: RoutingConfig{Strategy: "priority", GitHubModelsFallback: true},
		}
		s := NewServer(cfg)
		s.client = upstream.Client()

		body := `{"model":"llama","max_tokens":16,"messages":[{"role":"user","content":"hi"}]}`
		req := httptest.NewRequest(http.MethodPost, "/v1/messages", strings.NewReader(body))
		rr := httptest.NewRecorder()
		s.Handler().ServeHTTP(rr, req)

		if rr.Code != http.StatusOK {
			t.Fatalf("expected 200 after 401 cascade, got %d body=%s", rr.Code, rr.Body.String())
		}
		h1 := HashKey("sk-route-key-alpha-11111111")
		if st := s.Cooldown().Status(h1, "llama"); st != StatusDead {
			t.Fatalf("expected key1 to be dead, got %s", st)
		}
		if st := s.Cooldown().Status(h1, "any-model"); st != StatusDead {
			t.Fatalf("expected key1 to be dead for all models, got %s", st)
		}
	})

	// Test 402 Payment Required -> Exhausted (key-wide, 1h backoff)
	t.Run("402_Exhausted_KeyWide", func(t *testing.T) {
		upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			auth := r.Header.Get("Authorization")
			if strings.Contains(auth, "sk-route-key-alpha") {
				w.WriteHeader(http.StatusPaymentRequired)
				_, _ = w.Write([]byte(`{"error":"balance_depleted"}`))
				return
			}
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write([]byte(`{"id":"chatcmpl-1","model":"llama","choices":[{"index":0,"message":{"role":"assistant","content":"ok"},"finish_reason":"stop"}]}`))
		}))
		defer upstream.Close()

		en := true
		cfg := &Config{
			Providers: []Provider{{
				Name: "mock", BaseURL: upstream.URL, PrivacyPolicy: PrivacyZeroRetention, Enabled: &en,
				Models: []string{"llama"},
				KeyPools: []KeyPool{
					{AccountLabel: "p-01", EnvVar: "TEST_ROUTE_KEY_1", Priority: 20},
					{AccountLabel: "p-01", EnvVar: "TEST_ROUTE_KEY_2", Priority: 10},
				},
			}},
			Routing: RoutingConfig{Strategy: "priority", GitHubModelsFallback: true},
		}
		s := NewServer(cfg)
		s.client = upstream.Client()

		body := `{"model":"llama","max_tokens":16,"messages":[{"role":"user","content":"hi"}]}`
		req := httptest.NewRequest(http.MethodPost, "/v1/messages", strings.NewReader(body))
		rr := httptest.NewRecorder()
		s.Handler().ServeHTTP(rr, req)

		if rr.Code != http.StatusOK {
			t.Fatalf("expected 200 after 402 cascade, got %d body=%s", rr.Code, rr.Body.String())
		}
		h1 := HashKey("sk-route-key-alpha-11111111")
		if st := s.Cooldown().Status(h1, "llama"); st != StatusExhausted {
			t.Fatalf("expected key1 to be exhausted, got %s", st)
		}
		if st := s.Cooldown().Status(h1, "any-model"); st != StatusExhausted {
			t.Fatalf("expected key1 to be exhausted for all models, got %s", st)
		}
	})
}

func TestAdminCooldownEndpoint(t *testing.T) {
	cfg := &Config{
		Providers: []Provider{},
		Routing:   RoutingConfig{Strategy: "priority", GitHubModelsFallback: true},
	}
	s := NewServer(cfg)
	h := HashKey("sk-admin-test-key")
	s.Cooldown().MarkRestricted(h, "gpt-4")
	s.Cooldown().MarkDead(HashKey("sk-dead-key"))

	for _, path := range []string{"/admin/cooldown", "/v1/admin/cooldown"} {
		req := httptest.NewRequest(http.MethodGet, path, nil)
		rr := httptest.NewRecorder()
		s.Handler().ServeHTTP(rr, req)

		if rr.Code != http.StatusOK {
			t.Fatalf("expected 200 on %s, got %d body=%s", path, rr.Code, rr.Body.String())
		}
		if ct := rr.Header().Get("Content-Type"); !strings.Contains(ct, "application/json") {
			t.Fatalf("expected application/json, got %s", ct)
		}

		var resp struct {
			ActiveCount int                  `json:"active_count"`
			Entries     []RouteCooldownEntry `json:"entries"`
		}
		if err := json.Unmarshal(rr.Body.Bytes(), &resp); err != nil {
			t.Fatalf("failed to decode response on %s: %v", path, err)
		}
		if resp.ActiveCount != 2 {
			t.Fatalf("expected active_count=2, got %d", resp.ActiveCount)
		}
		if len(resp.Entries) != 2 {
			t.Fatalf("expected 2 entries, got %d", len(resp.Entries))
		}
	}

	// Test method not allowed for POST
	reqPost := httptest.NewRequest(http.MethodPost, "/admin/cooldown", nil)
	rrPost := httptest.NewRecorder()
	s.Handler().ServeHTTP(rrPost, reqPost)
	if rrPost.Code != http.StatusMethodNotAllowed {
		t.Fatalf("expected 405 for POST, got %d", rrPost.Code)
	}

	// Test non-loopback rejected with 403
	reqExt := httptest.NewRequest(http.MethodGet, "/admin/cooldown", nil)
	reqExt.Header.Set("X-Forwarded-For", "203.0.113.195")
	rrExt := httptest.NewRecorder()
	s.Handler().ServeHTTP(rrExt, reqExt)
	if rrExt.Code != http.StatusForbidden {
		t.Fatalf("expected 403 for forwarded external client, got %d", rrExt.Code)
	}
}

func TestParseRetryAfter(t *testing.T) {
	now := time.Date(2026, 10, 14, 12, 0, 0, 0, time.UTC)

	// Seconds (integer and float)
	d, ok := ParseRetryAfter("30", now)
	if !ok || d != 30*time.Second {
		t.Fatalf("expected 30s, got %v (ok=%v)", d, ok)
	}
	d, ok = ParseRetryAfter(" 120 ", now)
	if !ok || d != 120*time.Second {
		t.Fatalf("expected 120s, got %v (ok=%v)", d, ok)
	}
	d, ok = ParseRetryAfter("2.5", now)
	if !ok || d != 2500*time.Millisecond {
		t.Fatalf("expected 2.5s, got %v (ok=%v)", d, ok)
	}

	// HTTP-date (RFC1123)
	d, ok = ParseRetryAfter("Wed, 14 Oct 2026 12:01:00 GMT", now)
	if !ok || d != 60*time.Second {
		t.Fatalf("expected 60s for RFC1123, got %v (ok=%v)", d, ok)
	}

	// HTTP-date in the past
	d, ok = ParseRetryAfter("Wed, 14 Oct 2026 11:59:00 GMT", now)
	if !ok || d != 0 {
		t.Fatalf("expected 0s for past date, got %v (ok=%v)", d, ok)
	}

	// Empty and invalid
	_, ok = ParseRetryAfter("", now)
	if ok {
		t.Fatalf("expected ok=false for empty header")
	}
	_, ok = ParseRetryAfter("invalid-value", now)
	if ok {
		t.Fatalf("expected ok=false for invalid header")
	}
}

func TestAdaptiveBackoffAndRetryAfterPrecedence(t *testing.T) {
	cache := NewCooldownCache(10, 300)
	kh := "hash123"
	model := "test-model"

	// 1st failure without retry-after: StatusRateLimited (429) -> base (10s), status_code_default
	dur1 := cache.RecordFailure(kh, model, StatusRateLimited, "")
	if dur1 != 10*time.Second {
		t.Fatalf("expected 10s, got %v", dur1)
	}
	entries := cache.Entries()
	if len(entries) != 1 {
		t.Fatalf("expected 1 entry, got %d", len(entries))
	}
	if entries[0].Provenance != ProvenanceStatusCodeDefault {
		t.Fatalf("expected provenance %s, got %s", ProvenanceStatusCodeDefault, entries[0].Provenance)
	}
	if entries[0].FailureCount != 1 {
		t.Fatalf("expected failure_count 1, got %d", entries[0].FailureCount)
	}
	if entries[0].State != StatusRateLimited {
		t.Fatalf("expected state %s, got %s", StatusRateLimited, entries[0].State)
	}

	// 2nd failure without retry-after: adaptive backoff -> base * 2 = 20s
	dur2 := cache.RecordFailure(kh, model, StatusRateLimited, "")
	if dur2 != 20*time.Second {
		t.Fatalf("expected 20s, got %v", dur2)
	}
	entries = cache.Entries()
	if entries[0].Provenance != ProvenanceAdaptiveBackoff {
		t.Fatalf("expected provenance %s, got %s", ProvenanceAdaptiveBackoff, entries[0].Provenance)
	}
	if entries[0].FailureCount != 2 {
		t.Fatalf("expected failure_count 2, got %d", entries[0].FailureCount)
	}

	// 3rd failure with Retry-After header "45" -> precedence over adaptive backoff!
	dur3 := cache.RecordFailure(kh, model, StatusRateLimited, "45")
	if dur3 != 45*time.Second {
		t.Fatalf("expected 45s, got %v", dur3)
	}
	entries = cache.Entries()
	if entries[0].Provenance != ProvenanceRetryAfterHeader {
		t.Fatalf("expected provenance %s, got %s", ProvenanceRetryAfterHeader, entries[0].Provenance)
	}
	if entries[0].FailureCount != 3 {
		t.Fatalf("expected failure_count 3, got %d", entries[0].FailureCount)
	}
	if entries[0].LearnedBackoffMs != 45000 {
		t.Fatalf("expected learned_backoff_ms 45000, got %d", entries[0].LearnedBackoffMs)
	}

	// 4th failure without header: adaptive backoff continues: base * 2^(4-1) = 10 * 8 = 80s
	dur4 := cache.RecordFailure(kh, model, StatusRateLimited, "")
	if dur4 != 80*time.Second {
		t.Fatalf("expected 80s, got %v", dur4)
	}
	entries = cache.Entries()
	if entries[0].Provenance != ProvenanceAdaptiveBackoff {
		t.Fatalf("expected provenance %s, got %s", ProvenanceAdaptiveBackoff, entries[0].Provenance)
	}
}

func TestCooldownProbingAndRecovery(t *testing.T) {
	cache := NewCooldownCache(1, 10)
	kh := "hash-probe"
	model := "probe-model"

	// Trigger failure
	cache.RecordFailure(kh, model, StatusRateLimited, "1")
	if cache.IsAvailableForModel(kh, model) {
		t.Fatalf("expected route to be in cooldown")
	}

	// Advance time past cooldown
	time.Sleep(1100 * time.Millisecond)

	// Route should allow probing now
	if !cache.CanProbe(kh, model) {
		t.Fatalf("expected CanProbe=true after cooldown expired")
	}

	// IsAvailableForModel should claim probe turn and transition to StatusProbing
	if !cache.IsAvailableForModel(kh, model) {
		t.Fatalf("expected IsAvailableForModel=true for probe attempt")
	}

	// While probing is in-flight, concurrent check should return false
	if cache.IsAvailableForModel(kh, model) {
		t.Fatalf("expected IsAvailableForModel=false while probing is in-flight")
	}

	// On success, state recovers to active with probe_recovery provenance
	cache.RecordSuccess(kh, model)
	if cache.Status(kh, model) != StatusActive {
		t.Fatalf("expected active status after success, got %s", cache.Status(kh, model))
	}
	if !cache.IsAvailableForModel(kh, model) {
		t.Fatalf("expected route to be available after recovery")
	}
}

func TestAdminCooldownDetailedResponse(t *testing.T) {
	cfg := &Config{
		Providers: []Provider{},
		Routing:   RoutingConfig{Strategy: "priority", GitHubModelsFallback: true},
	}
	s := NewServer(cfg)
	kh := HashKey("sk-admin-detailed-test")
	s.Cooldown().RecordFailure(kh, "gpt-4", StatusRateLimited, "30")

	req := httptest.NewRequest(http.MethodGet, "/admin/cooldown", nil)
	rr := httptest.NewRecorder()
	s.Handler().ServeHTTP(rr, req)

	if rr.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", rr.Code)
	}

	var resp struct {
		ActiveCount int `json:"active_count"`
		Entries     []struct {
			KeyHash          string  `json:"key_hash"`
			Model            string  `json:"model"`
			Status           string  `json:"status"`
			State            string  `json:"state"`
			RemainingS       float64 `json:"remaining_s"`
			DurationMs       int64   `json:"duration_ms"`
			LearnedBackoffMs int64   `json:"learned_backoff_ms"`
			FailureCount     int     `json:"failure_count"`
			Provenance       string  `json:"provenance"`
		} `json:"entries"`
	}
	if err := json.Unmarshal(rr.Body.Bytes(), &resp); err != nil {
		t.Fatalf("unmarshal error: %v", err)
	}
	if resp.ActiveCount != 1 || len(resp.Entries) != 1 {
		t.Fatalf("expected 1 entry, got %d", len(resp.Entries))
	}
	e := resp.Entries[0]
	if e.KeyHash != kh || e.Model != "gpt-4" {
		t.Fatalf("unexpected entry identity: %+v", e)
	}
	if e.State != StatusRateLimited || e.Provenance != ProvenanceRetryAfterHeader {
		t.Fatalf("expected state rate_limited and provenance retry_after_header, got %+v", e)
	}
	if e.LearnedBackoffMs != 30000 || e.FailureCount != 1 {
		t.Fatalf("expected learned_backoff_ms=30000, failure_count=1, got %+v", e)
	}
}


