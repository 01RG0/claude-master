// server.go — HTTP server for the universal gateway.
//
// Front doors:
//   POST /v1/messages (+ streaming SSE, tools) — Anthropic-compatible
//   POST /v1/messages/count_tokens — token counting (measured or labeled estimate)
//   POST /v1/chat/completions — OpenAI-compatible
//   POST /v1/responses — OpenAI Responses (minimal mapping)
//   POST /v1/outcome — bandit outcome reports
//   GET  /v1/models — configured models + roles + capabilities summary
//   POST /v1/admin/keys — runtime key add/remove/rotate (loopback only)
//   GET  /v1/admin/stats — redacted live stats
//   GET  /health
package gateway

import (
	"bufio"
	"bytes"
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"hash/fnv"
	"io"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"
	"time"
)

// ModelStat tracks latency/cost per model for latency/cost strategies + stats.
type ModelStat struct {
	Calls      int64
	Errors     int64
	LatencyMs  int64 // EMA * 1000
	InputTok   int64
	OutputTok  int64
	CachedTok  int64
	CostUSD    float64
}

// Server is the gateway HTTP server.
type Server struct {
	cfg      *Config
	bandit   *ThompsonBandit
	cooldown *CooldownCache
	client   *http.Client

	mu         sync.Mutex
	keyOverlay map[string]string   // provider\x00envvar → raw key (runtime-added, never logged)
	keyModels  map[string][]string // provider\x00keyhash → allowed models (detection)
	pinned     map[string]bool     // model → banned (false) / pinned-only routing
	stats      map[string]*ModelStat
	rr         uint64
	logDir     string
	logMaxBody int
	respCache  *ResponseCache // exact-match replay cache (never logs content/keys)
	rescue     *ToolRescueEmulation
}

// NewServer creates a Server from the provided configuration.
func NewServer(cfg *Config) *Server {
	var allModels []string
	for _, p := range cfg.Providers {
		if p.IsEnabled() {
			allModels = append(allModels, p.Models...)
		}
	}

	s := &Server{
		cfg:        cfg,
		bandit:     NewThompsonBandit(allModels),
		cooldown:   NewCooldownCache(cfg.CooldownBase().Seconds(), cfg.CooldownMax().Seconds()),
		client:     &http.Client{Timeout: cfg.RequestTimeout()},
		keyOverlay: make(map[string]string),
		keyModels:  make(map[string][]string),
		pinned:     make(map[string]bool),
		stats:      make(map[string]*ModelStat),
		respCache:  NewResponseCache(),
		rescue:     NewToolRescueEmulation(),
	}
	if cfg.Logging != nil {
		s.logDir = cfg.Logging.RequestsDir
		s.logMaxBody = cfg.Logging.MaxBody
		if s.logMaxBody <= 0 {
			s.logMaxBody = 4096
		}
	}
	// Restore persisted runtime keys (DPAPI on Windows; never logged).
	if stored, err := KeystoreLoad(); err == nil {
		for prov, labels := range stored {
			for label, secret := range labels {
				s.keyOverlay[prov+"\x00"+label] = secret
			}
		}
	} else {
		log.Printf("gateway: keystore unavailable (%v); runtime keys start empty", redactForLog(err.Error()))
	}
	return s
}

// Bandit exposes the Thompson bandit for tests / outcome seeding.
func (s *Server) Bandit() *ThompsonBandit { return s.bandit }

// Cooldown exposes the cooldown cache for tests.
func (s *Server) Cooldown() *CooldownCache { return s.cooldown }

// Rescue exposes the tool rescue emulation layer for tests and metrics.
func (s *Server) Rescue() *ToolRescueEmulation { return s.rescue }

// Handler returns the HTTP mux (useful for httptest tests without Listen).
func (s *Server) Handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("/v1/messages", s.handleMessages)
	mux.HandleFunc("/v1/messages/count_tokens", s.handleCountTokens)
	mux.HandleFunc("/v1/chat/completions", s.handleOpenAIChat)
	mux.HandleFunc("/v1/responses", s.handleOpenAIResponses)
	mux.HandleFunc("/v1/outcome", s.handleOutcome)
	mux.HandleFunc("/v1/models", s.handleModels)
	mux.HandleFunc("/v1/admin/keys", s.handleAdminKeys)
	mux.HandleFunc("/v1/admin/stats", s.handleAdminStats)
	mux.HandleFunc("/admin/cooldown", s.handleAdminCooldown)
	mux.HandleFunc("/v1/admin/cooldown", s.handleAdminCooldown)
	mux.HandleFunc("/admin/toolrescue", s.handleAdminToolRescue)
	mux.HandleFunc("/v1/admin/toolrescue", s.handleAdminToolRescue)
	mux.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(`{"status":"ok"}`))
	})
	return mux
}

// ListenAndServe starts the HTTP server and blocks until ctx is cancelled.
func (s *Server) ListenAndServe(ctx context.Context) error {
	srv := &http.Server{
		Addr:    s.cfg.ListenAddr,
		Handler: s.Handler(),
	}

	go func() {
		<-ctx.Done()
		shutCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		_ = srv.Shutdown(shutCtx)
	}()

	log.Printf("gateway: listening on %s (brain_available=%v)", s.cfg.ListenAddr, BrainAvailable(s.cfg.BrainSocket))
	if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
		return err
	}
	return nil
}

// allCandidateModels returns enabled, unbanned model ids.
func (s *Server) allCandidateModels() []string {
	var out []string
	for _, p := range s.cfg.Providers {
		if !p.IsEnabled() {
			continue
		}
		for _, m := range p.Models {
			if banned, ok := s.pinned[m]; ok && banned {
				continue
			}
			out = append(out, m)
		}
	}
	return out
}

func (s *Server) hasCandidateModelInProviders(providers []Provider, reqKey string) bool {
	for _, p := range providers {
		for _, m := range p.Models {
			if m != "" && m != "*" && modelsKey(m) == reqKey {
				return true
			}
		}
	}
	return false
}

func (s *Server) hasCandidateModel(reqKey string) bool {
	return s.hasCandidateModelInProviders(s.cfg.Providers, reqKey)
}

// StageLatency holds duration measurements for request pipeline stages per Directive 5.
type StageLatency struct {
	GatewayOverheadMs float64 `json:"t_gateway_overhead_ms"`
	RouterMs          float64 `json:"t_router_ms"`
	ProviderTTFTMs    float64 `json:"t_provider_ttft_ms"`
	ProviderGenMs     float64 `json:"t_provider_generation_ms"`
	RescueMs          float64 `json:"t_rescue_ms"`
}

// HeaderValue formats the stage latency breakdown per Directive 5.
func (sl StageLatency) HeaderValue() string {
	return fmt.Sprintf("gw=%.2f,router=%.2f,ttft=%.2f,gen=%.2f,rescue=%.2f",
		sl.GatewayOverheadMs, sl.RouterMs, sl.ProviderTTFTMs, sl.ProviderGenMs, sl.RescueMs)
}

// StageTimings tracks durations of stages across the lifecycle of a request.
type StageTimings struct {
	GatewayOverhead time.Duration
	Router          time.Duration
	TTFT            time.Duration
	Generation      time.Duration
	Rescue          time.Duration
	RescueEnabled   bool
	RequestedModel  string
	RepairsApplied  []string
}

// StageLatency converts durations to millisecond floats.
func (st *StageTimings) StageLatency() StageLatency {
	if st == nil {
		return StageLatency{}
	}
	return StageLatency{
		GatewayOverheadMs: float64(st.GatewayOverhead.Nanoseconds()) / 1e6,
		RouterMs:          float64(st.Router.Nanoseconds()) / 1e6,
		ProviderTTFTMs:    float64(st.TTFT.Nanoseconds()) / 1e6,
		ProviderGenMs:     float64(st.Generation.Nanoseconds()) / 1e6,
		RescueMs:          float64(st.Rescue.Nanoseconds()) / 1e6,
	}
}

func (s *Server) toolRescueEnabledForRequest(r *http.Request) bool {
	if r != nil {
		if h := r.Header.Get("X-Tool-Rescue-Disabled"); strings.EqualFold(h, "true") || h == "1" {
			return false
		}
	}
	return s.cfg.IsToolRescueEnabled()
}

func (s *Server) handleMessages(w http.ResponseWriter, r *http.Request) {
	t0 := time.Now()
	if r.Method != http.MethodPost {
		writeAnthropicError(w, 405, "invalid_request_error", "method not allowed")
		return
	}

	body, err := io.ReadAll(io.LimitReader(r.Body, 4<<20))
	if err != nil {
		writeAnthropicError(w, 400, "invalid_request_error", "reading body failed")
		return
	}

	var ar AnthropicRequest
	if err := json.Unmarshal(body, &ar); err != nil {
		writeAnthropicError(w, 400, "invalid_request_error", "invalid request")
		return
	}
	tParse := time.Since(t0)

	tRouterStart := time.Now()
	// Model roles: every name maps, never 422.
	requested := ar.Model
	ar.Model = ResolveModel(requested, s.cfg.ModelAliases, s.cfg.Roles, s.allCandidateModels())

	// Honest prompt-caching: auto-inject ephemeral breakpoints only when the
	// client sent none. Log the count only — never content or keys.
	cacheBreakpoints := EnsureCacheBreakpoints(&ar)
	log.Printf("gateway: cache_breakpoints injected=%d", cacheBreakpoints)

	privClass := EffectivePrivacyClass(&ar)
	primary, ghFallback := EligibleProviders(s.cfg, privClass)
	providers := append(append([]Provider{}, primary...), ghFallback...)
	// Sticky session: keep one session on one provider for cache affinity.
	if s.cfg.Routing.StickySession {
		if sid := anthropicSessionID(&ar); sid != "" && len(providers) > 1 {
			providers = stickyOrder(providers, sid)
		}
	}
	tRouter := time.Since(tRouterStart)

	timings := &StageTimings{
		GatewayOverhead: tParse,
		Router:          tRouter,
		RescueEnabled:   s.toolRescueEnabledForRequest(r),
		RequestedModel:  requested,
	}

	if len(providers) == 0 {
		writeAnthropicError(w, 503, "overloaded_error", "no eligible providers available")
		return
	}

	// Exact-match replay cache: serve stored non-streaming responses without
	// contacting upstream. Usage is replayed byte-for-byte (passthrough);
	// no cache_read_input_tokens is fabricated (see honesty rule in cache.go).
	if s.respCache != nil {
		if cached, ok := s.respCache.Lookup(&ar); ok {
			s.recordCall(ar.Model, true, nil)
			sl := timings.StageLatency()
			w.Header().Set("Content-Type", "application/json")
			w.Header().Set("X-Gateway-Cache", "HIT")
			w.Header().Set("X-Stage-Latency", sl.HeaderValue())
			w.WriteHeader(http.StatusOK)
			_, _ = w.Write(cached)
			s.logRequest("anthropic", requested, &ar, map[string]interface{}{
				"cache":           "HIT",
				"stage_latency":   sl,
				"x_stage_latency": sl.HeaderValue(),
			})
			return
		}
	}

	resp, upstreamModel, stats, err := s.tryProviders(r.Context(), providers, &ar, timings)
	if err != nil {
		st, typ, _ := mapUpstreamStatus(502, "")
		writeAnthropicError(w, st, typ, "all providers failed: "+redactForLog(err.Error()))
		s.logRequest("anthropic", requested, &ar, map[string]interface{}{
			"error":           err.Error(),
			"stage_latency":   timings.StageLatency(),
			"x_stage_latency": timings.StageLatency().HeaderValue(),
		})
		return
	}
	defer resp.Body.Close()

	s.recordCall(upstreamModel, true, stats)
	if ar.Stream {
		s.streamResponse(w, resp, upstreamModel, &ar, timings)
	} else {
		s.proxyResponse(w, resp, upstreamModel, &ar, timings)
	}
}

// OutcomeReport updates Thompson sampling posteriors after a completed turn.
type OutcomeReport struct {
	ModelID string `json:"model_id"`
	Success bool   `json:"success"`
	// Optional fields accepted but not required.
	LatencyMs float64 `json:"latency_ms,omitempty"`
	Provider  string  `json:"provider,omitempty"`
}

func (s *Server) handleOutcome(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeAnthropicError(w, 405, "invalid_request_error", "method not allowed")
		return
	}
	var rep OutcomeReport
	if err := json.NewDecoder(io.LimitReader(r.Body, 1<<20)).Decode(&rep); err != nil {
		writeAnthropicError(w, 400, "invalid_request_error", "invalid outcome")
		return
	}
	if rep.ModelID == "" {
		writeAnthropicError(w, 400, "invalid_request_error", "model_id required")
		return
	}
	s.bandit.Update(rep.ModelID, rep.Success)
	w.Header().Set("Content-Type", "application/json")
	stats, _ := s.bandit.Stats(rep.ModelID)
	_ = json.NewEncoder(w).Encode(map[string]interface{}{
		"ok":         true,
		"model_id":   stats.ModelID,
		"successes":  stats.Successes,
		"failures":   stats.Failures,
	})
}

// callStats carries per-attempt observations for accounting and stage timings.
type callStats struct {
	latencyMs      float64
	promptTokens   int
	completionToks int
	cachedTokens   int
	timings        StageTimings
}

// tryProviders iterates providers; within each provider cascades keys on 429,
// then mirrors, then the next provider. Returns the winning response.
func (s *Server) tryProviders(ctx context.Context, providers []Provider, ar *AnthropicRequest, optTimings ...*StageTimings) (*http.Response, string, *callStats, error) {
	var timings *StageTimings
	if len(optTimings) > 0 && optTimings[0] != nil {
		timings = optTimings[0]
	} else {
		timings = &StageTimings{RescueEnabled: true}
	}

	var lastErr error
	ordered := s.orderProviders(providers, ar)
	for _, p := range ordered {
		keys := s.resolveKeys(p)
		if len(keys) == 0 {
			continue
		}

		model := s.pickModel(p, ar, ordered)
		if model == "" {
			continue
		}

		// Cascade across keys of the SAME account pool on 429 / 401 / 402 / 403.
		tried := map[string]bool{}
		for {
			key, ok := s.cooldown.PickKeyForModel(keys, model)
			if !ok {
				lastErr = fmt.Errorf("provider %s: all keys in cooldown", p.Name)
				break
			}
			kh := HashKey(key)
			if tried[kh] {
				lastErr = fmt.Errorf("provider %s: no remaining keys", p.Name)
				break
			}
			tried[kh] = true
			// Per-key model allowlist: only keys with access serve this model.
			var keyRec *ResolvedKey
			for i, k := range keys {
				if k.Value == key {
					keyRec = &keys[i]
					break
				}
			}
			if keyRec != nil {
				s.mu.Lock()
				overlay := s.keyModels
				s.mu.Unlock()
				if !KeyHasModel(*keyRec, model, overlay) {
					lastErr = fmt.Errorf("provider %s: no key with access to %s", p.Name, model)
					continue
				}
			}

			// Declarative adapter spec governs provider-specific request
			// downgrades (tool-message image handling, tool support, schema
			// stripping) BEFORE the request is sent upstream.
			adapter := EffectiveAdapter(p)

			tAdapterStart := time.Now()
			or, notes := TranslateRequest(ar, model, adapter)
			if or == nil {
				lastErr = fmt.Errorf("translation error: %v", notes)
				break
			}
			for _, n := range notes {
				log.Printf("gateway: translate provider=%s model=%s note=%s", p.Name, model, n)
			}
			// Sanitize tools per adapter limits (logged, never secrets).
			if len(or.Tools) > 0 && adapter.ToolSupport == "none" {
				lastErr = fmt.Errorf("provider %s: no native tool support for this request", p.Name)
				break
			}
			or.Tools = sanitizeTools(or.Tools, ar.Tools, adapter)
			timings.GatewayOverhead += time.Since(tAdapterStart)

			bases := []string{p.BaseURL}
			for _, m := range p.Mirrors {
				if m.BaseURL != "" {
					bases = append(bases, m.BaseURL)
				}
			}
			var resp *http.Response
			var reqErr error
			var usedBase string
			var ttft time.Duration
			for _, base := range bases {
				resp, reqErr, usedBase, ttft = s.doUpstream(ctx, p, adapter, base, key, or)
				if reqErr == nil {
					timings.TTFT = ttft
					break
				}
				log.Printf("gateway: provider=%s base=%s error=%s", p.Name, redactForLog(usedBase), redactForLog(reqErr.Error()))
			}
			if reqErr != nil {
				lastErr = fmt.Errorf("provider %s request error: %w", p.Name, reqErr)
				s.bandit.Update(model, false)
				s.noteLatency(model, 0, false)
				continue
			}

			if resp.StatusCode == http.StatusTooManyRequests || resp.StatusCode == 402 || resp.StatusCode == 401 || resp.StatusCode == 403 {
				retryAfter := resp.Header.Get("Retry-After")
				resp.Body.Close()
				var dur time.Duration
				switch resp.StatusCode {
				case http.StatusUnauthorized: // 401: invalid key -> dead
					dur = s.cooldown.RecordFailure(kh, "*", StatusDead, retryAfter)
					log.Printf("gateway: provider=%s model=%s key=%s HTTP 401 dead cooldown=%s", p.Name, model, kh, dur)
				case http.StatusPaymentRequired: // 402: payment required -> exhausted
					dur = s.cooldown.RecordFailure(kh, "*", StatusExhausted, retryAfter)
					log.Printf("gateway: provider=%s model=%s key=%s HTTP 402 exhausted cooldown=%s", p.Name, model, kh, dur)
				case http.StatusForbidden: // 403: permission denied -> restricted per model
					dur = s.cooldown.RecordFailure(kh, model, StatusRestricted, retryAfter)
					log.Printf("gateway: provider=%s model=%s key=%s HTTP 403 restricted cooldown=%s", p.Name, model, kh, dur)
				case http.StatusTooManyRequests: // 429: rate limited
					dur = s.cooldown.RecordFailure(kh, model, StatusRateLimited, retryAfter)
					// Never log raw keys — hash only.
					log.Printf("gateway: provider=%s model=%s key=%s 429 cooldown=%s", p.Name, model, kh, dur)
				}
				s.bandit.Update(model, false)
				lastErr = fmt.Errorf("provider %s: HTTP %d key cooldown", p.Name, resp.StatusCode)
				continue // cascade to next key
			}

			if resp.StatusCode >= 400 {
				b, _ := io.ReadAll(io.LimitReader(resp.Body, 2048))
				resp.Body.Close()
				s.bandit.Update(model, false)
				s.noteLatency(model, 0, false)
				st, _, _ := mapUpstreamStatus(resp.StatusCode, redactForLog(string(b)))
				if st == 401 || st == 404 || st == 400 {
					// Include a bounded, redacted upstream reason: without it a 400
					// chain across providers is undiagnosable ("all providers
					// exhausted" tells the operator nothing actionable).
					reason := redactForLog(strings.TrimSpace(string(b)))
					if len(reason) > 240 {
						reason = reason[:240]
					}
					log.Printf("gateway: provider=%s model=%s HTTP %d (no retry on key) reason=%s", p.Name, model, resp.StatusCode, reason)
				}
				lastErr = fmt.Errorf("provider %s: HTTP %d", p.Name, resp.StatusCode)
				break // non-429 error → try next provider
			}

			s.bandit.Update(model, true)
			s.cooldown.RecordSuccess(kh, model)
			return resp, model, &callStats{timings: *timings}, nil
		}
	}
	if lastErr == nil {
		lastErr = fmt.Errorf("no providers attempted")
	}
	return nil, "", nil, fmt.Errorf("all providers exhausted: %w", lastErr)
}

// doUpstream sends one translated request to one base URL with auth applied.
// Each attempt is bounded by AttemptTimeout so a hung provider fails over
// fast instead of consuming the whole request budget.
func (s *Server) doUpstream(ctx context.Context, p Provider, adapter AdapterSpec, base, key string, or *OpenAIRequest) (*http.Response, error, string, time.Duration) {
	reqBody, err := json.Marshal(or)
	if err != nil {
		return nil, err, base, 0
	}

	url := strings.TrimRight(base, "/") + adapter.ChatPath
	if adapter.ChatPath == "" {
		url = strings.TrimRight(base, "/") + "/chat/completions"
	}
	attemptCtx, cancel := context.WithTimeout(ctx, s.cfg.AttemptTimeout())
	req, err := http.NewRequestWithContext(attemptCtx, http.MethodPost, url, bytes.NewReader(reqBody))
	if err != nil {
		cancel()
		return nil, err, base, 0
	}
	req.Header.Set("Content-Type", "application/json")
	applyAuth(req, adapter, key)
	for k, v := range adapter.ExtraHeaders {
		req.Header.Set(k, v)
	}
	t0 := time.Now()
	resp, err := s.client.Do(req)
	ttft := time.Since(t0)
	if err == nil {
		// Canceling attemptCtx closes resp.Body (http.Client contract), so
		// release it only when the caller is done streaming, not on return.
		resp.Body = &cancelBody{ReadCloser: resp.Body, cancel: cancel}
	} else {
		cancel()
	}
	return resp, err, base, ttft
}

// cancelBody releases the attempt context when the body is fully consumed.
type cancelBody struct {
	io.ReadCloser
	cancel context.CancelFunc
	once   sync.Once
}

func (b *cancelBody) Close() error {
	b.once.Do(func() { b.cancel() })
	return b.ReadCloser.Close()
}

// applyAuth sets the Authorization header per adapter auth style (no logging).
func applyAuth(req *http.Request, adapter AdapterSpec, key string) {
	switch adapter.AuthStyle {
	case "x-api-key":
		req.Header.Set("x-api-key", key)
	case "query-param":
		q := req.URL.Query()
		param := adapter.AuthParam
		if param == "" {
			param = "key"
		}
		q.Set(param, key)
		req.URL.RawQuery = q.Encode()
	case "custom-header":
		param := adapter.AuthParam
		if param == "" {
			param = "Authorization"
		}
		req.Header.Set(param, key)
	case "none":
	default: // bearer
		req.Header.Set("Authorization", "Bearer "+key)
	}
}

func sanitizeTools(tools []OpenAITool, src []AnthropicTool, adapter AdapterSpec) []OpenAITool {
	if len(tools) == 0 {
		return tools
	}
	out := make([]OpenAITool, 0, len(tools))
	for i, t := range tools {
		var s AnthropicTool
		if i < len(src) {
			s = src[i]
		} else {
			s = AnthropicTool{Name: t.Function.Name}
		}
		fixed, notes := SanitizeTool(s, adapter.MaxToolName, adapter.StripKeywords)
		// Preserve already-converted parameters when the source schema is empty.
		if len(s.InputSchema) == 0 && len(t.Function.Parameters) > 0 {
			fixed.Function.Parameters = t.Function.Parameters
		}
		for _, n := range notes {
			log.Printf("gateway: tool sanitize: %s", n)
		}
		out = append(out, fixed)
	}
	return out
}

// orderProviders applies the configured selection strategy to providers.
func (s *Server) orderProviders(providers []Provider, ar *AnthropicRequest) []Provider {
	sel := s.cfg.Routing.Selection
	if sel == "" {
		sel = s.cfg.Routing.Strategy
	}
	var base []Provider
	switch sel {
	case "round_robin":
		if len(providers) == 0 {
			return providers
		}
		n := atomic.AddUint64(&s.rr, 1)
		k := int(n % uint64(len(providers)))
		base = make([]Provider, 0, len(providers))
		base = append(base, providers[k:]...)
		base = append(base, providers[:k]...)
	case "latency":
		base = s.sortByLatency(providers)
	case "cost":
		base = s.sortByCost(providers)
	default: // priority / thompson_sampling
		base = append([]Provider{}, providers...)
	}

	if ar == nil || ar.Model == "" || ar.Model == "*" {
		return base
	}

	reqKey := modelsKey(ar.Model)
	var exact []Provider
	var fallbacks []Provider
	for _, p := range base {
		hasModel := false
		for _, m := range p.Models {
			if modelsKey(m) == reqKey || m == "*" {
				hasModel = true
				break
			}
		}
		if hasModel {
			exact = append(exact, p)
		} else {
			fallbacks = append(fallbacks, p)
		}
	}
	return append(exact, fallbacks...)
}

// pickModel selects the upstream model for one provider attempt.
func (s *Server) pickModel(p Provider, ar *AnthropicRequest, eligible ...[]Provider) string {
	sel := s.cfg.Routing.Selection
	if sel == "" {
		sel = s.cfg.Routing.Strategy
	}
	// "*" means "any model acceptable" in config/scan (see diffModels); it is
	// not a real upstream id. Sending model="*" yields 404 (apertis).
	s.mu.Lock()
	pinned := s.pinned
	s.mu.Unlock()
	hasWildcard := false
	for _, m := range p.Models {
		if m == "*" {
			hasWildcard = true
			break
		}
	}

	cands := make([]string, 0, len(p.Models))
	for _, m := range p.Models {
		if m == "" || m == "*" {
			continue
		}
		if banned, ok := pinned[m]; ok && banned {
			continue
		}
		cands = append(cands, m)
	}

	// If a specific model was requested:
	if ar != nil && ar.Model != "" && ar.Model != "*" {
		reqKey := modelsKey(ar.Model)
		for _, m := range cands {
			if modelsKey(m) == reqKey {
				return m
			}
		}
		if hasWildcard {
			if banned, ok := pinned[ar.Model]; ok && banned {
				return ""
			}
			return ar.Model
		}
	}

	if len(cands) == 0 {
		return ""
	}
	switch sel {
	case "latency", "cost":
		best := cands[0]
		var bestScore float64 = -1
		for _, m := range cands {
			var sc float64
			if sel == "latency" {
				sc = -s.modelLatencyMS(m)
			} else {
				sc = -s.modelPrice(m)
			}
			if bestScore < 0 || sc > bestScore {
				bestScore = sc
				best = m
			}
		}
		return best
	default:
		m := s.bandit.SampleModel(cands)
		if m == "" {
			return cands[0]
		}
		return m
	}
}

func (s *Server) sortByLatency(providers []Provider) []Provider {
	out := append([]Provider{}, providers...)
	sortByFloat(out, func(p Provider) float64 {
		if len(p.Models) == 0 {
			return 0
		}
		return -s.modelLatencyMS(p.Models[0])
	})
	return out
}

func (s *Server) sortByCost(providers []Provider) []Provider {
	out := append([]Provider{}, providers...)
	sortByFloat(out, func(p Provider) float64 {
		if len(p.Models) == 0 {
			return 0
		}
		return -s.modelPrice(p.Models[0])
	})
	return out
}

func (s *Server) proxyResponse(w http.ResponseWriter, resp *http.Response, model string, ar *AnthropicRequest, optTimings ...*StageTimings) {
	var timings *StageTimings
	if len(optTimings) > 0 && optTimings[0] != nil {
		timings = optTimings[0]
	} else {
		timings = &StageTimings{RescueEnabled: true}
	}

	tGenStart := time.Now()
	body, err := io.ReadAll(resp.Body)
	timings.Generation = time.Since(tGenStart)

	if err != nil {
		writeAnthropicError(w, 502, "api_error", "upstream read failed")
		return
	}
	var oai OpenAIChatResponse
	if err := json.Unmarshal(body, &oai); err != nil {
		// Pass through if not parseable.
		sl := timings.StageLatency()
		w.Header().Set("Content-Type", "application/json")
		w.Header().Set("X-Stage-Latency", sl.HeaderValue())
		w.WriteHeader(resp.StatusCode)
		_, _ = w.Write(body)
		return
	}

	var tools []AnthropicTool
	if ar != nil {
		tools = ar.Tools
	}

	rescueLayer := s.rescue
	if rescueLayer == nil {
		rescueLayer = DefaultToolRescue
	}

	tRescueStart := time.Now()
	anth, repairTypes := rescueLayer.TranslateResponse(&oai, model, tools, timings.RescueEnabled)
	timings.Rescue = time.Since(tRescueStart)

	encoded, err := json.Marshal(anth)
	if err != nil {
		writeAnthropicError(w, 502, "api_error", "response encode failed")
		return
	}
	// Exact-match cache: store on miss. Streams never reach here (caller
	// branches on ar.Stream); tools/thinking requests are ignored by Store.
	if s.respCache != nil && ar != nil && s.respCache.Cacheable(ar) {
		s.respCache.Set(s.respCache.Key(ar), encoded)
		w.Header().Set("X-Gateway-Cache", "MISS")
	}

	sl := timings.StageLatency()
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("X-Stage-Latency", sl.HeaderValue())
	if len(repairTypes) > 0 {
		w.Header().Set("X-Tool-Rescue", strings.Join(repairTypes, ","))
	}
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write(encoded)

	reqModel := model
	if ar != nil && ar.Model != "" {
		reqModel = ar.Model
	}
	if timings.RequestedModel != "" {
		reqModel = timings.RequestedModel
	}
	log.Printf("gateway: stage_latency %s model=%s rescue=%v", sl.HeaderValue(), model, repairTypes)
	s.logRequest("anthropic", reqModel, ar, map[string]interface{}{
		"stage_latency": map[string]interface{}{
			"t_gateway_overhead_ms": sl.GatewayOverheadMs,
			"t_router_ms":           sl.RouterMs,
			"t_provider_ttft_ms":    sl.ProviderTTFTMs,
			"t_provider_generation_ms": sl.ProviderGenMs,
			"t_rescue_ms":           sl.RescueMs,
		},
		"x_stage_latency": sl.HeaderValue(),
		"x_tool_rescue":   repairTypes,
	})
}

func (s *Server) streamResponse(w http.ResponseWriter, resp *http.Response, model string, optArgs ...interface{}) {
	var ar *AnthropicRequest
	var timings *StageTimings
	for _, arg := range optArgs {
		switch v := arg.(type) {
		case *AnthropicRequest:
			ar = v
		case *StageTimings:
			timings = v
		}
	}
	if timings == nil {
		timings = &StageTimings{RescueEnabled: true}
	}

	flusher, ok := w.(http.Flusher)
	if !ok {
		writeAnthropicError(w, 500, "api_error", "streaming not supported")
		return
	}

	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("X-Accel-Buffering", "no")
	w.Header().Set("Trailer", "X-Stage-Latency, X-Tool-Rescue")
	w.Header().Set("X-Stage-Latency", timings.StageLatency().HeaderValue())
	w.WriteHeader(http.StatusOK)

	tGenStart := time.Now()

	translator := NewStreamTranslator(model, newMsgID())
	if ar != nil {
		translator.SetRescue(timings.RescueEnabled, ar.Tools)
	}
	// CORRECTION 5: route streaming rescue logs to this server's layer so
	// GET /admin/toolrescue reflects every rescue (log every rescue).
	if s.rescue != nil {
		translator.SetRescueLayer(s.rescue)
	}
	scanner := bufio.NewScanner(resp.Body)
	scanner.Buffer(make([]byte, 0, 64*1024), 1024*1024)
	usagePrompt, usageCompletion, usageCached, usageCreation := 0, 0, 0, 0
	sawDone := false
	for scanner.Scan() {
		line := scanner.Text()
		if line == "" {
			continue
		}
		if strings.HasPrefix(line, ":") || strings.HasPrefix(line, "event:") && !strings.Contains(line, "data:") {
			// Comment / ping lines: forward a ping to keep the client alive.
			if b := EncodeSSE(AnthropicSSEEvent{"ping", map[string]string{"type": "ping"}}); b != nil {
				_, _ = w.Write(b)
				flusher.Flush()
			}
			continue
		}
		if !strings.HasPrefix(line, "data:") {
			continue
		}
		data := strings.TrimSpace(strings.TrimPrefix(line, "data:"))
		if data == "[DONE]" {
			sawDone = true
			break
		}

		var chunk StreamChunk
		if err := json.Unmarshal([]byte(data), &chunk); err != nil {
			// Try usage-only trailer.
			var trailer struct {
				Usage *struct {
					PromptTokens        int `json:"prompt_tokens"`
					CompletionTokens    int `json:"completion_tokens"`
					CachedTokens        int `json:"cached_tokens"`
					CacheCreation       int `json:"cache_creation_input_tokens"`
					CacheCreationTokens int `json:"cache_creation_tokens"`
					PromptDetails       *struct {
						CachedTokens int `json:"cached_tokens"`
					} `json:"prompt_tokens_details"`
				} `json:"usage"`
			}
			if jerr := json.Unmarshal([]byte(data), &trailer); jerr == nil && trailer.Usage != nil {
				usagePrompt = trailer.Usage.PromptTokens
				usageCompletion = trailer.Usage.CompletionTokens
				usageCached = trailer.Usage.CachedTokens
				if trailer.Usage.PromptDetails != nil && trailer.Usage.PromptDetails.CachedTokens > usageCached {
					usageCached = trailer.Usage.PromptDetails.CachedTokens
				}
				usageCreation = trailer.Usage.CacheCreation
				if trailer.Usage.CacheCreationTokens > usageCreation {
					usageCreation = trailer.Usage.CacheCreationTokens
				}
			}
			continue
		}
		if chunk.Model == "" {
			chunk.Model = model
		}
		if chunk.Usage != nil {
			if chunk.Usage.PromptTokens > 0 {
				usagePrompt = chunk.Usage.PromptTokens
			}
			if chunk.Usage.CompletionTokens > 0 {
				usageCompletion = chunk.Usage.CompletionTokens
			}
			cached := chunk.Usage.CachedTokens
			if chunk.Usage.PromptTokensDetails != nil && chunk.Usage.PromptTokensDetails.CachedTokens > cached {
				cached = chunk.Usage.PromptTokensDetails.CachedTokens
			}
			if cached > 0 {
				usageCached = cached
			}
			creation := chunk.Usage.CacheCreationTokens
			if chunk.Usage.CacheCreationAlt > creation {
				creation = chunk.Usage.CacheCreationAlt
			}
			if creation > 0 {
				usageCreation = creation
			}
		}

		events := translator.Translate(&chunk)
		for _, ev := range events {
			if b := EncodeSSE(ev); b != nil {
				_, _ = w.Write(b)
			}
		}
		flusher.Flush()
		if len(translator.ToolArgs()) > 64 {
			break
		}
	}
	for _, ev := range translator.Finish(usagePrompt, usageCompletion, usageCached, usageCreation) {
		if b := EncodeSSE(ev); b != nil {
			_, _ = w.Write(b)
		}
	}
	if len(translator.RepairsApplied) > 0 {
		timings.RepairsApplied = append(timings.RepairsApplied, translator.RepairsApplied...)
		w.Header().Set("X-Tool-Rescue", strings.Join(timings.RepairsApplied, ","))
	}
	timings.Generation = time.Since(tGenStart)
	sl := timings.StageLatency()
	w.Header().Set("X-Stage-Latency", sl.HeaderValue())
	flusher.Flush()
	_ = sawDone

	reqModel := model
	if ar != nil && ar.Model != "" {
		reqModel = ar.Model
	}
	if timings.RequestedModel != "" {
		reqModel = timings.RequestedModel
	}
	log.Printf("gateway: stage_latency %s model=%s (stream)", sl.HeaderValue(), model)
	s.logRequest("anthropic", reqModel, ar, map[string]interface{}{
		"stage_latency": map[string]interface{}{
			"t_gateway_overhead_ms": sl.GatewayOverheadMs,
			"t_router_ms":           sl.RouterMs,
			"t_provider_ttft_ms":    sl.ProviderTTFTMs,
			"t_provider_generation_ms": sl.ProviderGenMs,
			"t_rescue_ms":           sl.RescueMs,
		},
		"x_stage_latency": sl.HeaderValue(),
	})
}

func newMsgID() string {
	var b [8]byte
	if _, err := rand.Read(b[:]); err != nil {
		return "msg_gateway_fallback"
	}
	return "msg_" + hex.EncodeToString(b[:])
}

// --- stats / accounting -------------------------------------------------

func (s *Server) statFor(model string) *ModelStat {
	s.mu.Lock()
	defer s.mu.Unlock()
	st, ok := s.stats[model]
	if !ok {
		st = &ModelStat{}
		s.stats[model] = st
	}
	return st
}

func (s *Server) recordCall(model string, success bool, cs *callStats) {
	st := s.statFor(model)
	s.mu.Lock()
	st.Calls++
	if !success {
		st.Errors++
	}
	price := s.modelPrice(model)
	s.mu.Unlock()
	_ = price
	if cs != nil {
		s.mu.Lock()
		st.InputTok += int64(cs.promptTokens)
		st.OutputTok += int64(cs.completionToks)
		st.CachedTok += int64(cs.cachedTokens)
		st.CostUSD += float64(cs.promptTokens) / 1e6 * price
		s.mu.Unlock()
	}
}

func (s *Server) noteLatency(model string, ms float64, _ bool) {
	if ms <= 0 {
		return
	}
	st := s.statFor(model)
	s.mu.Lock()
	if st.LatencyMs == 0 {
		st.LatencyMs = int64(ms * 1000)
	} else {
		st.LatencyMs = int64(float64(st.LatencyMs)*0.8 + ms*1000*0.2)
	}
	s.mu.Unlock()
}

func (s *Server) modelLatencyMS(model string) float64 {
	s.mu.Lock()
	defer s.mu.Unlock()
	if st, ok := s.stats[model]; ok && st.LatencyMs > 0 {
		return float64(st.LatencyMs) / 1000.0
	}
	return 0
}

func (s *Server) modelPrice(model string) float64 {
	if s.cfg.Routing.ModelPrices != nil {
		if v, ok := s.cfg.Routing.ModelPrices[model]; ok {
			return v
		}
	}
	return 0
}

// --- keys overlay (runtime add/remove without restart) -------------------

func (s *Server) resolveKeys(p Provider) []ResolvedKey {
	keys := ResolveProviderKeys(p)
	s.mu.Lock()
	defer s.mu.Unlock()
	for _, k := range keys {
		_ = k
	}
	// Runtime overlay keys are stored under provider\x00envvar.
	for k, v := range s.keyOverlay {
		parts := strings.SplitN(k, "\x00", 2)
		if len(parts) != 2 || parts[0] != p.Name {
			continue
		}
		keys = append(keys, ResolvedKey{Value: v, Priority: 5, EnvVar: parts[1] + " (runtime)",
			Provider: p.Name, AccountLabel: "runtime"})
	}
	return keys
}

// --- request logging (redacted, truncated) -------------------------------

func (s *Server) logRequest(door, requested string, ar *AnthropicRequest, extra map[string]interface{}) {
	if s.logDir == "" {
		return
	}
	rec := map[string]interface{}{
		"ts":        time.Now().UTC().Format(time.RFC3339),
		"door":      door,
		"requested": requested,
		"mapped":    ar.Model,
		"stream":    ar.Stream,
		"messages":  len(ar.Messages),
		"tools":     len(ar.Tools),
		"blocks":    messageBlockTypes(ar),
		"max_tokens": ar.MaxTokens,
	}
	// Body fingerprint (first 12 hex of the content hash, never the content):
	// lets operators measure duplicate/auxiliary traffic and trace a request
	// across logs without storing prompts.
	if s.respCache != nil {
		if k := s.respCache.Key(ar); len(k) >= 12 {
			rec["sha"] = k[:12]
		}
	}
	if extra != nil {
		for k, v := range extra {
			rec[k] = v
		}
	}
	b, _ := json.Marshal(rec)
	line := redactForLog(string(b))
	if len(line) > s.logMaxBody && s.logMaxBody > 0 {
		line = line[:s.logMaxBody]
	}
	_ = os.MkdirAll(s.logDir, 0o755)
	f := filepath.Join(s.logDir, time.Now().UTC().Format("2006-01-02")+".jsonl")
	fh, err := os.OpenFile(f, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644)
	if err != nil {
		return
	}
	_, _ = fh.WriteString(line + "\n")
	_ = fh.Close()
}

func messageBlockTypes(ar *AnthropicRequest) []string {
	seen := map[string]bool{}
	var out []string
	add := func(t string) {
		if !seen[t] {
			seen[t] = true
			out = append(out, t)
		}
	}
	var sysBlocks []ContentBlock
	if ar.System != nil {
		if err := json.Unmarshal(ar.System, &sysBlocks); err == nil {
			for _, b := range sysBlocks {
				add("system:" + b.Type)
			}
		}
	}
	for _, m := range ar.Messages {
		var blocks []ContentBlock
		if err := json.Unmarshal(m.Content, &blocks); err != nil {
			add("string")
			continue
		}
		for _, b := range blocks {
			add(b.Type)
			// Images/files arrive INSIDE tool_result content arrays; log those
			// too or vision regressions hide from the traffic log.
			if b.Type == "tool_result" && len(b.Content) > 0 {
				var inner []ContentBlock
				if err := json.Unmarshal(b.Content, &inner); err == nil {
					for _, ib := range inner {
						add("tool_result/" + ib.Type)
					}
				}
			}
		}
	}
	return out
}

func anthropicSessionID(ar *AnthropicRequest) string {
	if ar.Metadata == nil {
		return ""
	}
	if v, ok := ar.Metadata["session_id"]; ok {
		if s, ok := v.(string); ok {
			return s
		}
	}
	if v, ok := ar.Metadata["user_id"]; ok {
		if s, ok := v.(string); ok {
			return s
		}
	}
	return ""
}

func stickyOrder(providers []Provider, session string) []Provider {
	h := fnv.New32a()
	_, _ = h.Write([]byte(session))
	start := int(h.Sum32() % uint32(len(providers)))
	out := make([]Provider, 0, len(providers))
	out = append(out, providers[start:]...)
	out = append(out, providers[:start]...)
	return out
}

func sortByFloat(providers []Provider, score func(Provider) float64) {
	for i := 1; i < len(providers); i++ {
		for j := i; j > 0 && score(providers[j]) > score(providers[j-1]); j-- {
			providers[j], providers[j-1] = providers[j-1], providers[j]
		}
	}
}
