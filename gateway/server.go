// server.go — HTTP server for the Anthropic-compatible gateway.
// Listens on ANTHROPIC_BASE_URL path /v1/messages (streaming + tools).
package gateway

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"strings"
	"time"
)

// Server is the gateway HTTP server.
type Server struct {
	cfg      *Config
	bandit   *ThompsonBandit
	cooldown *CooldownCache
	client   *http.Client
}

// NewServer creates a Server from the provided configuration.
func NewServer(cfg *Config) *Server {
	var allModels []string
	for _, p := range cfg.Providers {
		if p.IsEnabled() {
			allModels = append(allModels, p.Models...)
		}
	}

	return &Server{
		cfg:    cfg,
		bandit: NewThompsonBandit(allModels),
		cooldown: NewCooldownCache(
			cfg.CooldownBase().Seconds(),
			cfg.CooldownMax().Seconds(),
		),
		client: &http.Client{Timeout: cfg.RequestTimeout()},
	}
}

// Bandit exposes the Thompson bandit for tests / outcome seeding.
func (s *Server) Bandit() *ThompsonBandit { return s.bandit }

// Cooldown exposes the cooldown cache for tests.
func (s *Server) Cooldown() *CooldownCache { return s.cooldown }

// Handler returns the HTTP mux (useful for httptest tests without Listen).
func (s *Server) Handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("/v1/messages", s.handleMessages)
	mux.HandleFunc("/v1/outcome", s.handleOutcome)
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

func (s *Server) handleMessages(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}

	body, err := io.ReadAll(io.LimitReader(r.Body, 4<<20))
	if err != nil {
		http.Error(w, "reading body failed", http.StatusBadRequest)
		return
	}

	var ar AnthropicRequest
	if err := json.Unmarshal(body, &ar); err != nil {
		http.Error(w, "invalid request", http.StatusBadRequest)
		return
	}

	privClass := EffectivePrivacyClass(&ar)
	primary, ghFallback := EligibleProviders(s.cfg, privClass)
	providers := append(append([]Provider{}, primary...), ghFallback...)
	if len(providers) == 0 {
		http.Error(w, "no eligible providers available", http.StatusServiceUnavailable)
		return
	}

	resp, upstreamModel, err := s.tryProviders(r.Context(), providers, &ar)
	if err != nil {
		http.Error(w, "all providers failed", http.StatusBadGateway)
		return
	}
	defer resp.Body.Close()

	if ar.Stream {
		s.streamResponse(w, resp, upstreamModel)
	} else {
		s.proxyResponse(w, resp, upstreamModel)
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
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	var rep OutcomeReport
	if err := json.NewDecoder(io.LimitReader(r.Body, 1<<20)).Decode(&rep); err != nil {
		http.Error(w, "invalid outcome", http.StatusBadRequest)
		return
	}
	if rep.ModelID == "" {
		http.Error(w, "model_id required", http.StatusBadRequest)
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

// tryProviders iterates providers; within each provider cascades keys on 429.
func (s *Server) tryProviders(ctx context.Context, providers []Provider, ar *AnthropicRequest) (*http.Response, string, error) {
	var lastErr error
	for _, p := range providers {
		keys := ResolveProviderKeys(p)
		if len(keys) == 0 {
			continue
		}

		// Cascade across keys of the SAME account pool on 429.
		tried := map[string]bool{}
		for {
			key, ok := s.cooldown.PickKey(keys)
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

			model := ""
			if s.cfg.Routing.Strategy == "thompson_sampling" || s.cfg.Routing.Strategy == "" {
				model = s.bandit.SampleModel(p.Models)
			}
			if model == "" && len(p.Models) > 0 {
				model = p.Models[0]
			}

			or, err := TranslateRequest(ar, model)
			if err != nil {
				lastErr = fmt.Errorf("translation error: %w", err)
				break
			}
			reqBody, err := json.Marshal(or)
			if err != nil {
				lastErr = err
				break
			}

			url := strings.TrimRight(p.BaseURL, "/") + "/chat/completions"
			req, err := http.NewRequestWithContext(ctx, http.MethodPost, url, bytes.NewReader(reqBody))
			if err != nil {
				lastErr = err
				break
			}
			req.Header.Set("Content-Type", "application/json")
			req.Header.Set("Authorization", "Bearer "+key)

			resp, err := s.client.Do(req)
			if err != nil {
				lastErr = fmt.Errorf("provider %s request error: %w", p.Name, err)
				s.bandit.Update(model, false)
				continue
			}

			if resp.StatusCode == http.StatusTooManyRequests {
				resp.Body.Close()
				dur := s.cooldown.Mark429(kh)
				// Never log raw keys — hash only.
				log.Printf("gateway: provider=%s model=%s key=%s 429 cooldown=%s", p.Name, model, kh, dur)
				s.bandit.Update(model, false)
				lastErr = fmt.Errorf("provider %s: 429 rate limited", p.Name)
				continue // cascade to next key
			}

			if resp.StatusCode >= 400 {
				resp.Body.Close()
				s.bandit.Update(model, false)
				lastErr = fmt.Errorf("provider %s: HTTP %d", p.Name, resp.StatusCode)
				break // non-429 error → try next provider
			}

			s.bandit.Update(model, true)
			return resp, model, nil
		}
	}
	if lastErr == nil {
		lastErr = fmt.Errorf("no providers attempted")
	}
	return nil, "", fmt.Errorf("all providers exhausted: %w", lastErr)
}

func (s *Server) proxyResponse(w http.ResponseWriter, resp *http.Response, model string) {
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		http.Error(w, "upstream read failed", http.StatusBadGateway)
		return
	}
	var oai OpenAIChatResponse
	if err := json.Unmarshal(body, &oai); err != nil {
		// Pass through if not parseable.
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(resp.StatusCode)
		_, _ = w.Write(body)
		return
	}
	anth := TranslateResponse(&oai, model)
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	_ = json.NewEncoder(w).Encode(anth)
}

func (s *Server) streamResponse(w http.ResponseWriter, resp *http.Response, model string) {
	flusher, ok := w.(http.Flusher)
	if !ok {
		http.Error(w, "streaming not supported", http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("X-Accel-Buffering", "no")
	w.WriteHeader(http.StatusOK)

	scanner := bufio.NewScanner(resp.Body)
	scanner.Buffer(make([]byte, 0, 64*1024), 1024*1024)
	isFirst := true
	for scanner.Scan() {
		line := scanner.Text()
		if !strings.HasPrefix(line, "data:") {
			continue
		}
		data := strings.TrimSpace(strings.TrimPrefix(line, "data:"))
		if data == "[DONE]" {
			break
		}

		var chunk StreamChunk
		if err := json.Unmarshal([]byte(data), &chunk); err != nil {
			continue
		}
		if chunk.Model == "" {
			chunk.Model = model
		}

		events := TranslateStreamChunk(&chunk, isFirst)
		isFirst = false

		for _, ev := range events {
			if b := EncodeSSE(ev); b != nil {
				_, _ = w.Write(b)
			}
		}
		flusher.Flush()
	}
}
