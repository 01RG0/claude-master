package gateway

import (
	"encoding/json"
	"os"
	"path/filepath"
	"sync"
)

// RoutingState persists pin/ban intent across gateway restarts.
// Stored next to config as capabilities.json (same file scan/probe use) under
// top-level banned_models / pinned_models so measured rows stay untouched.
type RoutingState struct {
	BannedModels []string `json:"banned_models,omitempty"`
	PinnedModels []string `json:"pinned_models,omitempty"`
}

type capsEnvelope struct {
	Providers    map[string]json.RawMessage `json:"providers"`
	BannedModels []string                   `json:"banned_models,omitempty"`
	PinnedModels []string                   `json:"pinned_models,omitempty"`
}

var (
	routingStateMu   sync.Mutex
	routingStatePath string
)

// SetRoutingStatePath tells the gateway where to persist pin/ban (usually
// gateway/capabilities.json beside the config). Empty disables persistence.
func SetRoutingStatePath(path string) { routingStatePath = path }

// LoadRoutingState reads banned/pinned model lists from path.
func LoadRoutingState(path string) RoutingState {
	var out RoutingState
	if path == "" {
		return out
	}
	b, err := os.ReadFile(path)
	if err != nil {
		return out
	}
	var env capsEnvelope
	if err := json.Unmarshal(b, &env); err != nil {
		return out
	}
	out.BannedModels = env.BannedModels
	out.PinnedModels = env.PinnedModels
	return out
}

// SaveRoutingState merges banned/pinned into the existing capabilities file
// without rewriting provider probe rows.
func SaveRoutingState(path string, st RoutingState) error {
	if path == "" {
		return nil
	}
	routingStateMu.Lock()
	defer routingStateMu.Unlock()

	env := capsEnvelope{Providers: map[string]json.RawMessage{}}
	if b, err := os.ReadFile(path); err == nil {
		_ = json.Unmarshal(b, &env)
		if env.Providers == nil {
			env.Providers = map[string]json.RawMessage{}
		}
	}
	env.BannedModels = st.BannedModels
	env.PinnedModels = st.PinnedModels
	b, err := json.MarshalIndent(env, "", "  ")
	if err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return err
	}
	return os.WriteFile(path, append(b, '\n'), 0o644)
}

// ApplyRoutingState loads path into the server's pinned map
// (true=banned, false=pinned/unbanned marker).
func (s *Server) ApplyRoutingState(path string) {
	st := LoadRoutingState(path)
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.pinned == nil {
		s.pinned = make(map[string]bool)
	}
	for _, m := range st.PinnedModels {
		if m != "" {
			s.pinned[m] = false
		}
	}
	for _, m := range st.BannedModels {
		if m != "" {
			s.pinned[m] = true
		}
	}
	SetRoutingStatePath(path)
}

// PersistPinned writes the in-memory pin/ban map back to disk.
func (s *Server) PersistPinned() error {
	path := routingStatePath
	if path == "" {
		return nil
	}
	s.mu.Lock()
	var banned, pinned []string
	for m, isBan := range s.pinned {
		if isBan {
			banned = append(banned, m)
		} else {
			pinned = append(pinned, m)
		}
	}
	s.mu.Unlock()
	return SaveRoutingState(path, RoutingState{BannedModels: banned, PinnedModels: pinned})
}

// CapsPathBesideConfig returns gateway/capabilities.json next to config.json,
// or respects CLAUDE_MASTER_GATEWAY_CAPABILITIES when test isolation is active.
func CapsPathBesideConfig(configPath string) string {
	if envCap := os.Getenv("CLAUDE_MASTER_GATEWAY_CAPABILITIES"); envCap != "" {
		return envCap
	}
	return filepath.Join(filepath.Dir(configPath), "capabilities.json")
}
