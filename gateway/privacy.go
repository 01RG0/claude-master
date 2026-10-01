// privacy.go — Privacy-aware content classification for routing.
//
// Enforces errata item 4 / risks §3.1: public_data_only providers (e.g. Gemini
// free) must NEVER receive repo code, diffs, or secrets.
package gateway

import (
	"encoding/json"
	"regexp"
	"strings"
)

var (
	reSecretLike = regexp.MustCompile(`(?i)(api[_-]?key|secret[_-]?key|access[_-]?token|bearer\s+[a-z0-9._\-]{16,}|BEGIN (RSA |OPENSSH |EC )?PRIVATE KEY|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_\-]{20,})`)
	reEnvFile    = regexp.MustCompile(`(?i)(?:^|[\s"'=/])\.env(?:\.[a-z0-9_-]+)?(?:$|[\s"'])`)
	reGitDiff    = regexp.MustCompile(`(?m)^diff --git |(?m)^@@ -\d+|^\+\+\+ [ab]/`)
	reSourcePath = regexp.MustCompile(`(?i)(?:^|[\s"'` + "`" + `])(?:[\w./-]+\.(?:go|py|ts|tsx|js|jsx|rs|java|c|cpp|h|hpp|rb|php|cs|swift|kt|scala|sql|sh|yaml|yml|toml|json|md))(?:$|[\s"'` + "`" + `:])`)
	reCodeFence  = regexp.MustCompile("(?s)```(?:go|python|typescript|javascript|rust|java|diff|bash|shell|sql)\\b")
)

// ContainsSensitiveContent scans the request for secrets, repo paths, diffs,
// or source-like payloads that must stay off public_data_only providers.
func ContainsSensitiveContent(ar *AnthropicRequest) bool {
	if ar == nil {
		return false
	}
	var chunks []string
	if ar.System != nil {
		chunks = append(chunks, string(ar.System))
	}
	for _, m := range ar.Messages {
		chunks = append(chunks, string(m.Content))
	}
	for _, t := range ar.Tools {
		chunks = append(chunks, t.Name, t.Description, string(t.InputSchema))
	}
	joined := strings.Join(chunks, "\n")
	if reSecretLike.MatchString(joined) {
		return true
	}
	if reEnvFile.MatchString(joined) {
		return true
	}
	if reGitDiff.MatchString(joined) {
		return true
	}
	if reCodeFence.MatchString(joined) {
		return true
	}
	if reSourcePath.MatchString(joined) && looksLikeCodeOrDiff(joined) {
		return true
	}
	return false
}

func looksLikeCodeOrDiff(s string) bool {
	if strings.Contains(s, "\n+") || strings.Contains(s, "\n-") {
		return true
	}
	indicators := []string{"func ", "def ", "class ", "import ", "package ", "const ", "let ", "var ", "#!/"}
	n := 0
	lower := s
	for _, ind := range indicators {
		if strings.Contains(lower, ind) {
			n++
		}
	}
	return n >= 1
}

// EffectivePrivacyClass returns the privacy class for routing. Explicit
// metadata.internal always wins; otherwise content heuristics may elevate
// a request to internal.
func EffectivePrivacyClass(ar *AnthropicRequest) PrivacyClass {
	if ar == nil {
		return PrivacyClassPublic
	}
	if ar.PrivacyClass() == PrivacyClassInternal {
		return PrivacyClassInternal
	}
	if ContainsSensitiveContent(ar) {
		return PrivacyClassInternal
	}
	return PrivacyClassPublic
}

// redactForLog strips likely secrets from a string before logging.
func redactForLog(s string) string {
	return reSecretLike.ReplaceAllString(s, "[REDACTED]")
}

// requestSnippet returns a short, secret-scrubbed preview for diagnostics.
func requestSnippet(ar *AnthropicRequest) string {
	if ar == nil || len(ar.Messages) == 0 {
		return ""
	}
	raw, _ := json.Marshal(ar.Messages[0].Content)
	s := string(raw)
	if len(s) > 120 {
		s = s[:120] + "…"
	}
	return redactForLog(s)
}
