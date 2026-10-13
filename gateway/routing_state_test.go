package gateway

import (
	"bytes"
	"os"
	"path/filepath"
	"testing"
)

func TestRoutingStateRoundTrip(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "capabilities.json")
	// Seed with a provider row that must survive SaveRoutingState.
	if err := os.WriteFile(path, []byte(`{"providers":{"groq":{"models":["m1"]}}}`+"\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := SaveRoutingState(path, RoutingState{
		BannedModels: []string{"bad-model"},
		PinnedModels: []string{"good-model"},
	}); err != nil {
		t.Fatal(err)
	}
	st := LoadRoutingState(path)
	if len(st.BannedModels) != 1 || st.BannedModels[0] != "bad-model" {
		t.Fatalf("banned=%v", st.BannedModels)
	}
	if len(st.PinnedModels) != 1 || st.PinnedModels[0] != "good-model" {
		t.Fatalf("pinned=%v", st.PinnedModels)
	}
	b, _ := os.ReadFile(path)
	if !bytes.Contains(b, []byte(`"groq"`)) || !bytes.Contains(b, []byte(`"m1"`)) {
		t.Fatalf("provider rows wiped: %s", b)
	}

	s := NewServer(&Config{Providers: []Provider{{Name: "p", Models: []string{"bad-model", "ok"}}},
		Routing: RoutingConfig{Strategy: "priority"}})
	s.ApplyRoutingState(path)
	cands := s.allCandidateModels()
	for _, m := range cands {
		if m == "bad-model" {
			t.Fatalf("banned model still a candidate: %v", cands)
		}
	}
}
