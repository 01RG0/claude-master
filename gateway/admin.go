// admin.go — runtime key management + live stats (loopback only).
//
// POST /v1/admin/keys {action: add|remove|rotate|set-models, provider,
//   env_var?, key?, models?} — keys are accepted ONLY on loopback, stored
//   in-process (never logged, never persisted to disk), effective immediately.
// GET /v1/admin/stats — per-provider/per-model calls, errors, latency,
//   tokens, cost. All key material rendered as hashes.
package gateway

import (
	"encoding/json"
	"io"
	"log"
	"net/http"
	"sort"
	"strings"
)

// handleAdminKeys manages runtime keys. Refuses non-loopback callers.
func (s *Server) handleAdminKeys(w http.ResponseWriter, r *http.Request) {
	if !isLoopback(r) {
		writeAnthropicError(w, 403, "authentication_error", "admin endpoints are loopback-only")
		return
	}
	if r.Method != http.MethodPost {
		writeAnthropicError(w, 405, "invalid_request_error", "method not allowed")
		return
	}
	var in struct {
		Action   string   `json:"action"`
		Provider string   `json:"provider"`
		EnvVar   string   `json:"env_var"`
		Key      string   `json:"key"`
		Models   []string `json:"models"`
	}
	if err := json.NewDecoder(io.LimitReader(r.Body, 1<<20)).Decode(&in); err != nil {
		writeAnthropicError(w, 400, "invalid_request_error", "invalid admin request")
		return
	}
	if in.Provider == "" {
		writeAnthropicError(w, 400, "invalid_request_error", "provider required")
		return
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	respond := func(v interface{}) {
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(v)
	}
	switch in.Action {
	case "add", "rotate":
		if in.Key == "" || in.EnvVar == "" {
			writeAnthropicError(w, 400, "invalid_request_error", "key and env_var required")
			return
		}
		s.keyOverlay[in.Provider+"\x00"+in.EnvVar] = in.Key
		if len(in.Models) > 0 {
			s.keyModels[in.Provider+"\x00"+HashKey(in.Key)] = in.Models
		}
		persistOverlay(s)
		respond(map[string]interface{}{"ok": true, "provider": in.Provider,
			"key_hash": HashKey(in.Key), "action": in.Action})
	case "remove":
		if in.EnvVar == "" {
			writeAnthropicError(w, 400, "invalid_request_error", "env_var required")
			return
		}
		delete(s.keyOverlay, in.Provider+"\x00"+in.EnvVar)
		persistOverlay(s)
		respond(map[string]interface{}{"ok": true, "provider": in.Provider, "action": "remove"})
	case "set-models":
		if in.Key == "" {
			writeAnthropicError(w, 400, "invalid_request_error", "key required")
			return
		}
		s.keyModels[in.Provider+"\x00"+HashKey(in.Key)] = in.Models
		respond(map[string]interface{}{"ok": true, "provider": in.Provider,
			"key_hash": HashKey(in.Key), "models": in.Models})
	case "pin":
		if len(in.Models) == 0 {
			writeAnthropicError(w, 400, "invalid_request_error", "models required")
			return
		}
		for _, m := range in.Models {
			s.pinned[m] = false
		}
		respond(map[string]interface{}{"ok": true, "pinned": in.Models})
	case "ban":
		if len(in.Models) == 0 {
			writeAnthropicError(w, 400, "invalid_request_error", "models required")
			return
		}
		for _, m := range in.Models {
			s.pinned[m] = true
		}
		respond(map[string]interface{}{"ok": true, "banned": in.Models})
	default:
		writeAnthropicError(w, 400, "invalid_request_error", "action must be add|remove|rotate|set-models|pin|ban")
	}
}

// handleAdminStats returns redacted live stats.
func (s *Server) handleAdminStats(w http.ResponseWriter, r *http.Request) {
	if !isLoopback(r) {
		writeAnthropicError(w, 403, "authentication_error", "admin endpoints are loopback-only")
		return
	}
	s.mu.Lock()
	models := make([]map[string]interface{}, 0, len(s.stats))
	for name, st := range s.stats {
		models = append(models, map[string]interface{}{
			"name": name, "calls": st.Calls, "errors": st.Errors,
			"latency_ms_ema": float64(st.LatencyMs) / 1000.0,
			"input_tokens": st.InputTok, "output_tokens": st.OutputTok,
			"cached_tokens": st.CachedTok, "cost_usd": st.CostUSD,
		})
	}
	overlays := []string{}
	for k := range s.keyOverlay {
		parts := strings.SplitN(k, "\x00", 2)
		overlays = append(overlays, parts[0]+":"+parts[1])
	}
	cooldowns := s.cooldown.ActiveCount()
	s.mu.Unlock()
	sort.Slice(models, func(i, j int) bool { return models[i]["name"].(string) < models[j]["name"].(string) })
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(map[string]interface{}{
		"models": models, "runtime_keys": overlays, "cooldowns_active": cooldowns,
	})
}

// persistOverlay saves runtime keys encrypted (DPAPI on Windows).
// Failures are logged with hashes only; the live overlay keeps serving.
func persistOverlay(s *Server) {
	entries := map[string]map[string]string{}
	for k, v := range s.keyOverlay {
		parts := strings.SplitN(k, "\x00", 2)
		if len(parts) != 2 {
			continue
		}
		if entries[parts[0]] == nil {
			entries[parts[0]] = map[string]string{}
		}
		entries[parts[0]][parts[1]] = v
	}
	if err := KeystoreSave(entries); err != nil {
		log.Printf("gateway: keystore save failed (%v)", redactForLog(err.Error()))
	}
}

func isLoopback(r *http.Request) bool {	host := r.Host
	if h := r.Header.Get("X-Forwarded-For"); h != "" {
		return false
	}
	if strings.HasPrefix(host, "127.") || host == "localhost" || strings.HasPrefix(host, "localhost:") ||
		strings.HasPrefix(host, "[::1]") || strings.HasPrefix(host, "::1") {
		return true
	}
	if ra := r.RemoteAddr; strings.HasPrefix(ra, "127.") || strings.HasPrefix(ra, "[::1]") {
		return true
	}
	return false
}
