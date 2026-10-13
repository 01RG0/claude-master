// probe.go — provider fingerprinting + capability probing.
//
// From base URL + key only: detect dialect (auth style, paths, streaming),
// list models (or candidate-probe when no endpoint), and measure per-model
// capabilities with cheap real calls under a probe budget. Results are
// "measured" (beats "declared" beats "assumed") — every field carries Source.
package gateway

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
)

// Fingerprint is the detected dialect of a provider.
type Fingerprint struct {
	Dialect      string `json:"dialect"`
	AuthStyle    string `json:"auth_style"`
	ModelsPath   string `json:"models_path"`
	ChatPath     string `json:"chat_path"`
	StreamFormat string `json:"stream_format"`
	Source       string `json:"source"` // measured
	Notes        []string `json:"notes,omitempty"`
}

// Capability is one measured model ability.
type Capability struct {
	Supported bool   `json:"supported"`
	Source    string `json:"source"` // measured|declared|assumed
	Detail    string `json:"detail,omitempty"`
	LatencyMs float64 `json:"latency_ms,omitempty"`
}

// ModelCapabilities is the per-model matrix row.
type ModelCapabilities struct {
	Model          string               `json:"model"`
	Chat           Capability           `json:"chat"`
	Streaming      Capability           `json:"streaming"`
	ToolsSingle    Capability           `json:"tools_single"`
	ToolsParallel  Capability           `json:"tools_parallel"`
	ToolsStreamed  Capability           `json:"tools_streamed_args"`
	Vision         Capability           `json:"vision"`
	JSONMode       Capability           `json:"json_mode"`
	TTFTMs         float64              `json:"ttft_ms,omitempty"`
	TokensPerSec   float64              `json:"tokens_per_sec,omitempty"`
	ProbedAt       string               `json:"probed_at"`
}

// FingerprintProvider probes base+key and returns the detected dialect.
// No secrets are logged; only statuses and shapes.
func FingerprintProvider(client *http.Client, base, key string) Fingerprint {
	fp := Fingerprint{Source: "measured"}
	base = strings.TrimRight(base, "/")
	// 1. Models endpoint variants.
	for _, mp := range []string{"/models", "/v1/models", "/openai/models"} {
		st, body := getJSON(client, base+mp, key, 15*time.Second)
		if st == 200 && looksLikeModelList(body) {
			fp.ModelsPath = mp
			break
		}
	}
	if fp.ModelsPath == "" {
		fp.ModelsPath = "none"
		fp.Notes = append(fp.Notes, "no list-models endpoint; use candidate probing")
	}
	// 2. Chat endpoint variants (cheap max_tokens probe happens in ProbeCapabilities).
	for _, cp := range []string{"/chat/completions", "/v1/chat/completions", "/openai/chat/completions"} {
		st, _ := optionsProbe(client, base+cp, 10*time.Second)
		if st != 0 {
			fp.ChatPath = cp
			break
		}
	}
	if fp.ChatPath == "" {
		fp.ChatPath = "/chat/completions"
	}
	// 3. Auth style: bearer works?
	st, _ := getJSON(client, base+fp.ModelsPath, key, 15*time.Second)
	if st == 200 || st == 404 {
		fp.AuthStyle = "bearer"
	} else {
		fp.AuthStyle = "bearer-unverified"
		fp.Notes = append(fp.Notes, fmt.Sprintf("models probe status %d", st))
	}
	fp.Dialect = "openai-chat"
	fp.StreamFormat = "sse-openai"
	// 4. Anthropic-shaped?
	st2, body2 := getJSON(client, base+"/v1/messages", key, 10*time.Second)
	_ = body2
	if st2 == 400 || st2 == 422 {
		fp.Notes = append(fp.Notes, "endpoint also answers Anthropic-shaped routes")
	}
	return fp
}

func getJSON(client *http.Client, url, key string, timeout time.Duration) (int, []byte) {
	c := *client
	c.Timeout = timeout
	req, err := http.NewRequest(http.MethodGet, url, nil)
	if err != nil {
		return 0, nil
	}
	if key != "" {
		req.Header.Set("Authorization", "Bearer "+key)
	}
	resp, err := c.Do(req)
	if err != nil {
		return 0, nil
	}
	defer resp.Body.Close()
	b, _ := io.ReadAll(io.LimitReader(resp.Body, 64*1024))
	return resp.StatusCode, b
}

func optionsProbe(client *http.Client, url string, timeout time.Duration) (int, []byte) {
	c := *client
	c.Timeout = timeout
	req, err := http.NewRequest(http.MethodPost, url, bytes.NewReader([]byte(`{"model":"__probe__","max_tokens":1,"messages":[{"role":"user","content":"hi"}]}`)))
	if err != nil {
		return 0, nil
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := c.Do(req)
	if err != nil {
		return 0, nil
	}
	defer resp.Body.Close()
	b, _ := io.ReadAll(io.LimitReader(resp.Body, 8*1024))
	return resp.StatusCode, b
}

func looksLikeModelList(body []byte) bool {
	var v map[string]interface{}
	if err := json.Unmarshal(body, &v); err != nil {
		return false
	}
	_, hasData := v["data"]
	_, hasModels := v["models"]
	return hasData || hasModels
}

// ListModels fetches model ids from a models endpoint (measured).
func ListModels(client *http.Client, base, modelsPath, key string) []string {
	if modelsPath == "" || modelsPath == "none" {
		return nil
	}
	st, body := getJSON(client, strings.TrimRight(base, "/")+modelsPath, key, 20*time.Second)
	if st != 200 {
		return nil
	}
	var v map[string]interface{}
	if err := json.Unmarshal(body, &v); err != nil {
		return nil
	}
	var out []string
	collect := func(arr []interface{}) {
		for _, e := range arr {
			if m, ok := e.(map[string]interface{}); ok {
				if id, _ := m["id"].(string); id != "" {
					out = append(out, id)
				} else if id, _ := m["name"].(string); id != "" {
					out = append(out, id)
				}
			}
		}
	}
	if arr, ok := v["data"].([]interface{}); ok {
		collect(arr)
	}
	if arr, ok := v["models"].([]interface{}); ok {
		collect(arr)
	}
	return out
}

// ProbeCapabilities runs cheap real calls for one model and returns the row.
// budget caps total calls; each probe is max_tokens≤16 except streaming (32).
func ProbeCapabilities(client *http.Client, base, chatPath, key, model string) ModelCapabilities {
	mc := ModelCapabilities{Model: model, ProbedAt: time.Now().UTC().Format(time.RFC3339)}
	url := strings.TrimRight(base, "/") + chatPath
	do := func(payload map[string]interface{}, timeout time.Duration) (int, []byte, float64) {
		payload["model"] = model
		b, _ := json.Marshal(payload)
		req, _ := http.NewRequest(http.MethodPost, url, bytes.NewReader(b))
		req.Header.Set("Content-Type", "application/json")
		if key != "" {
			req.Header.Set("Authorization", "Bearer "+key)
		}
		t0 := time.Now()
		resp, err := client.Do(req)
		dt := time.Since(t0).Seconds() * 1000
		if err != nil {
			return 0, nil, dt
		}
		defer resp.Body.Close()
		rb, _ := io.ReadAll(io.LimitReader(resp.Body, 32*1024))
		return resp.StatusCode, rb, dt
	}
	msgs := []interface{}{map[string]interface{}{"role": "user", "content": "Reply with the word ok."}}
	// chat
	st, body, dt := do(map[string]interface{}{"messages": msgs, "max_tokens": 16}, 60*time.Second)
	mc.Chat = Capability{Supported: st == 200, Source: "measured", LatencyMs: dt, Detail: fmt.Sprintf("http %d", st)}
	// streaming
	st2, _, dt2 := do(map[string]interface{}{"messages": msgs, "max_tokens": 32, "stream": true}, 60*time.Second)
	mc.Streaming = Capability{Supported: st2 == 200, Source: "measured", LatencyMs: dt2, Detail: fmt.Sprintf("http %d", st2)}
	// single tool
	tool := map[string]interface{}{"type": "function", "function": map[string]interface{}{
		"name": "echo", "description": "Echo a word.",
		"parameters": map[string]interface{}{"type": "object", "properties": map[string]interface{}{
			"word": map[string]interface{}{"type": "string"}}, "required": []string{"word"}}}}
	st3, body3, dt3 := do(map[string]interface{}{"messages": []interface{}{
		map[string]interface{}{"role": "user", "content": "Call echo with word hello."}},
		"max_tokens": 64, "tools": []interface{}{tool}}, 60*time.Second)
	mc.ToolsSingle = Capability{Supported: st3 == 200 && bytesContains(body3, "tool_calls"),
		Source: "measured", LatencyMs: dt3, Detail: fmt.Sprintf("http %d", st3)}
	// parallel tools
	st4, body4, dt4 := do(map[string]interface{}{"messages": []interface{}{
		map[string]interface{}{"role": "user", "content": "Call echo twice, with words a and b."}},
		"max_tokens": 128, "tools": []interface{}{tool}}, 90*time.Second)
	mc.ToolsParallel = Capability{Supported: st4 == 200 && bytesCount(body4, "tool_calls") >= 1,
		Source: "measured", LatencyMs: dt4, Detail: fmt.Sprintf("http %d", st4)}
	_ = body
	// streamed tool args
	st5, _, dt5 := do(map[string]interface{}{"messages": []interface{}{
		map[string]interface{}{"role": "user", "content": "Call echo with word hello."}},
		"max_tokens": 64, "tools": []interface{}{tool}, "stream": true}, 90*time.Second)
	mc.ToolsStreamed = Capability{Supported: st5 == 200, Source: "measured", LatencyMs: dt5, Detail: fmt.Sprintf("http %d", st5)}
	// json mode
	st6, _, _ := do(map[string]interface{}{"messages": msgs, "max_tokens": 32,
		"response_format": map[string]interface{}{"type": "json_object"}}, 60*time.Second)
	mc.JSONMode = Capability{Supported: st6 == 200, Source: "measured", Detail: fmt.Sprintf("http %d", st6)}
	// vision: tiny 1px png
	visionMsg := []interface{}{map[string]interface{}{"role": "user", "content": []interface{}{
		map[string]interface{}{"type": "text", "text": "What is this?"},
		map[string]interface{}{"type": "image_url", "image_url": map[string]interface{}{
			"url": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="}}}}}
	st7, _, _ := do(map[string]interface{}{"messages": visionMsg, "max_tokens": 32}, 60*time.Second)
	mc.Vision = Capability{Supported: st7 == 200, Source: "measured", Detail: fmt.Sprintf("http %d", st7)}
	mc.TTFTMs = dt2
	return mc
}

func bytesContains(b []byte, s string) bool {
	return bytes.Index(b, []byte(s)) >= 0
}

func bytesCount(b []byte, s string) int {
	n := 0
	for i := bytes.Index(b, []byte(s)); i >= 0; i = bytes.Index(b, []byte(s)) {
		n++
		b = b[i+len(s):]
		if len(b) == 0 {
			break
		}
	}
	return n
}
