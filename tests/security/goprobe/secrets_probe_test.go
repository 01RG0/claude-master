// secrets_probe_test.go — in-package probe for the security suite.
//
// Injected into the gateway package at run time via `go test -overlay`
// (see tests/security/test_secrets.py). It is NOT part of the gateway
// module tree; it only proves the security contract:
//
//   1. redactForLog() strips bearer tokens and hardcoded keys.
//   2. ContainsSensitiveContent() keeps source code internal.

package gateway

import (
	"encoding/json"
	"strings"
	"testing"
)

// sk builds a syntactically-valid fake key at run time so that this file
// itself never contains a literal matching the repo-wide secret scanner.
func sk(body string) string { return "sk-" + strings.Repeat(body, 6) }

func TestSecurityRedactForLogStripsBearerTokens(t *testing.T) {
	secret := sk("bearer-secret")
	in := "Authorization: Bearer " + secret
	out := redactForLog(in)
	if strings.Contains(out, secret) {
		t.Fatalf("bearer token leaked into logs: %s", out)
	}
	if !strings.Contains(out, "[REDACTED]") {
		t.Fatalf("expected redaction marker, got: %s", out)
	}
}

func TestSecurityRedactForLogStripsVariousSecretShapes(t *testing.T) {
	ghp := "ghp_" + strings.Repeat("a", 36)
	aws := "AKIA" + strings.Repeat("B", 16)
	// Assembled from parts so this probe file never contains a literal that
	// the repo-wide secret scanner would flag.
	pem := strings.Repeat("-", 5) + "BEGIN RSA PRIVATE KEY" + strings.Repeat("-", 5)
	apiKey := "api_key=" + sk("apikey")

	for _, in := range []string{
		"token " + ghp,
		"aws " + aws,
		pem,
		apiKey,
	} {
		out := redactForLog(in)
		if out == in {
			t.Fatalf("redactForLog left input untouched: %s", in)
		}
		if !strings.Contains(out, "[REDACTED]") {
			t.Fatalf("missing redaction marker for %q -> %q", in, out)
		}
	}
}

func TestSecurityRedactForLogPreservesBenignText(t *testing.T) {
	benign := "gateway: provider=groq model=llama 429 cooldown=1m0s"
	if got := redactForLog(benign); got != benign {
		t.Fatalf("benign log line mangled: %q", got)
	}
}

// TestSecurityRedactForLogHandlesHyphenatedKeyFormats documents a real gap:
// the reSecretLike body is [A-Za-z0-9]{20,}, which excludes the hyphen that
// every production key format contains. Asserting the *correct* contract
// here makes this test fail until gateway/privacy.go is widened.
func TestSecurityRedactForLogHandlesHyphenatedKeyFormats(t *testing.T) {
	cases := map[string]string{
		"anthropic": sk("ant-api03-AbCdEf0123456789"),
		"openai":    sk("proj-T1aBcDeFgH"),
	}
	for name, secret := range cases {
		out := redactForLog("key=" + secret)
		if strings.Contains(out, secret) {
			t.Errorf("%s key leaked into log output: %s", name, out)
		}
	}
}

func TestSecurityRequestSnippetIsScrubbedAndTruncated(t *testing.T) {
	// An all-alphanumeric key body is matched by reSecretLike and scrubbed.
	// NOTE: keys containing hyphens (e.g. the real `sk-ant-api03-...` and
	// `sk-proj-...` formats) are NOT matched, because the pattern body is
	// `[A-Za-z0-9]{20,}` with no hyphen. That gap is tracked as an xfail in
	// tests/security/test_secrets.py; this probe asserts the subset that the
	// current implementation does cover.
	secret := sk("snippets") // repeated alphanumerics only
	ar := &AnthropicRequest{
		Messages: []AnthropicMessage{{
			Role:    "user",
			Content: json.RawMessage(`"` + secret + `"`),
		}},
	}
	snip := requestSnippet(ar)
	if strings.Contains(snip, secret) {
		t.Fatalf("requestSnippet leaked a secret: %s", snip)
	}
	if !strings.Contains(snip, "[REDACTED]") {
		t.Fatalf("expected redaction marker in snippet: %s", snip)
	}
}

func TestSecurityContainsSensitiveContentTrueForSourceCode(t *testing.T) {
	diff := &AnthropicRequest{
		Messages: []AnthropicMessage{{
			Role: "user",
			Content: json.RawMessage(`"diff --git a/brain/server.py b/brain/server.py
@@ -1,3 +1,4 @@
+def handle_hook(payload):
+    return {'allow': True}"`),
		}},
	}
	if !ContainsSensitiveContent(diff) {
		t.Fatal("a git diff containing source code must be classified sensitive")
	}
	if EffectivePrivacyClass(diff) != PrivacyClassInternal {
		t.Fatal("a git diff must be routed as privacy_class=internal")
	}
}

func TestSecurityContainsSensitiveContentTrueForSecrets(t *testing.T) {
	cases := map[string]string{
		"hardcoded key": "please set the value to " + sk("hardcoded"),
		"env file":      "read API_KEY from .env and wire it up",
		"code fence":    "```python\nimport os\nprint(os.environ)\n```",
	}
	for name, body := range cases {
		ar := &AnthropicRequest{
			Messages: []AnthropicMessage{{
				Role:    "user",
				Content: json.RawMessage(mustJSON(body)),
			}},
		}
		if !ContainsSensitiveContent(ar) {
			t.Fatalf("case %q should be sensitive", name)
		}
	}
}

func TestSecurityContainsSensitiveContentFalseForTheory(t *testing.T) {
	cases := []string{
		"What is the Big-O of binary search?",
		"Explain the difference between a mutex and a semaphore in plain English.",
		"Why does the CAP theorem matter for a read-heavy web service?",
	}
	for _, q := range cases {
		ar := &AnthropicRequest{
			Messages: []AnthropicMessage{{
				Role:    "user",
				Content: json.RawMessage(mustJSON(q)),
			}},
		}
		if ContainsSensitiveContent(ar) {
			t.Fatalf("pure theory question must stay public: %q", q)
		}
		if EffectivePrivacyClass(ar) != PrivacyClassPublic {
			t.Fatalf("pure theory question must be privacy_class=public: %q", q)
		}
	}
}

func TestSecurityContainsSensitiveContentNilSafe(t *testing.T) {
	if ContainsSensitiveContent(nil) {
		t.Fatal("nil request must not be classified sensitive")
	}
}

func mustJSON(s string) string {
	b, err := json.Marshal(s)
	if err != nil {
		panic(err)
	}
	return string(b)
}