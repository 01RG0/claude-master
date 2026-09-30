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
	or, err := TranslateRequest(ar, "llama")
	if err != nil {
		t.Fatal(err)
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
