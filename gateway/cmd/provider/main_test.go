package main

import "testing"

// Regression: diffModels compared raw strings, so Gemini's "models/" prefixed
// ids were reported as retired and the "*" wildcard (any model is acceptable)
// was reported as a retired model. Both mis-reports made scan output untrustworthy.
func TestDiffModelsNormalizesPrefixAndCase(t *testing.T) {
	added, gone := diffModels([]string{"gemini-2.5-flash"}, []string{"models/gemini-2.5-flash"})
	if len(gone) != 0 {
		t.Errorf("prefixed live model must not be retired, got gone=%v", gone)
	}
	if len(added) != 0 {
		t.Errorf("prefixed live model must not be reported as new, got added=%v", added)
	}

	_, gone = diffModels([]string{"GPT-OSS-120B"}, []string{"gpt-oss-120b"})
	if len(gone) != 0 {
		t.Errorf("case-insensitive match expected, got gone=%v", gone)
	}
}

func TestDiffModelsSkipsWildcard(t *testing.T) {
	_, gone := diffModels([]string{"*"}, []string{"some-model"})
	if len(gone) != 0 {
		t.Errorf("wildcard means any model is acceptable and must never be retired, got %v", gone)
	}
	_, gone = diffModels([]string{""}, []string{"some-model"})
	if len(gone) != 0 {
		t.Errorf("empty entry must be ignored, got %v", gone)
	}
}

func TestDiffModelsDetectsRealRetirements(t *testing.T) {
	added, gone := diffModels(
		[]string{"llama-3.3-70b-versatile", "llama-3.1-8b-instant"},
		[]string{"openai/gpt-oss-120b", "qwen/qwen3.8-27b"},
	)
	if len(gone) != 2 {
		t.Errorf("both dead ids must be reported retired, got %v", gone)
	}
	if len(added) != 2 {
		t.Errorf("both live ids must be reported new, got %v", added)
	}
}
