package gateway

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestValidateModelsParsesAllDialects(t *testing.T) {
	// present: declared model exists on the provider list -> no missing
	present := []struct {
		name string
		body string
		want string
	}{
		{"openai-shape", `{"object":"list","data":[{"id":"openai-fast","object":"model"}]}`, "openai-fast"},
		{"cohere-shape", `{"models":[{"name":"command-r-plus-08-2024","endpoints":["chat"]}]}`, "command-r-plus-08-2024"},
		{"gemini-prefixed", `{"data":[{"id":"models/gemini-2.5-flash","object":"model"}]}`, "gemini-2.5-flash"},
	}
	for _, c := range present {
		srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			_ = json.NewEncoder(w).Encode(json.RawMessage(c.body))
		}))
		missing := ValidateModels(&http.Client{}, srv.URL, "/models", "k", []string{c.want})
		srv.Close()
		if len(missing) != 0 {
			t.Errorf("%s: %q is present, should not be missing, got %v", c.name, c.want, missing)
		}
	}

	// absent: declared model is NOT on the list -> reported as missing
	absent := []struct {
		name string
		body string
		want string
	}{
		{"openai-missing", `{"object":"list","data":[{"id":"openai-fast","object":"model"}]}`, "openai"},
		{"cohere-missing", `{"models":[{"name":"command-r-plus-08-2024","endpoints":["chat"]}]}`, "command-r-plus"},
		{"gemini-prefixed-missing", `{"data":[{"id":"models/gemini-2.5-flash","object":"model"}]}`, "gemini-2.5-pro"},
	}
	for _, c := range absent {
		srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			_ = json.NewEncoder(w).Encode(json.RawMessage(c.body))
		}))
		missing := ValidateModels(&http.Client{}, srv.URL, "/models", "k", []string{c.want})
		srv.Close()
		if len(missing) == 0 || missing[0] != c.want {
			t.Errorf("%s: %q is absent, should be missing, got %v", c.name, c.want, missing)
		}
	}

	// wildcard: "*" means "any model" -> never reported
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(json.RawMessage(`{"data":[{"id":"x"}]}`))
	}))
	missing := ValidateModels(&http.Client{}, srv.URL, "/models", "k", []string{"*"})
	srv.Close()
	if len(missing) != 0 {
		t.Errorf("wildcard should never be missing, got %v", missing)
	}
}

func TestValidateModelsUnreachableReturnsNil(t *testing.T) {
	// closed port -> non-200 -> caller can't verify -> nil (not a hard error)
	missing := ValidateModels(&http.Client{}, "http://127.0.0.1:1", "/models", "k", []string{"whatever"})
	if missing != nil {
		t.Errorf("unreachable should return nil, got %v", missing)
	}
}