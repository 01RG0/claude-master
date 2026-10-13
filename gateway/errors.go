// errors.go — provider errors → Anthropic error envelope.
//
// Claude Code retries on rate_limit/overloaded, fixes on invalid_request,
// re-auths on authentication. Mapping correctly is a reliability feature:
// a 429 misreported as 500 causes the wrong backoff; a 422 retried wastes
// quota. Every gateway error response uses this envelope.
package gateway

import (
	"encoding/json"
	"net/http"
)

// AnthropicError is the JSON error envelope.
type AnthropicError struct {
	Type    string `json:"type"`
	Error   struct {
		Type    string `json:"type"`
		Message string `json:"message"`
	} `json:"error"`
}

// writeAnthropicError writes {"type","error":{type,message}} with status.
func writeAnthropicError(w http.ResponseWriter, httpStatus int, errType, msg string) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(httpStatus)
	_ = json.NewEncoder(w).Encode(map[string]interface{}{
		"type": "error",
		"error": map[string]string{"type": errType, "message": msg},
	})
}

// mapUpstreamStatus converts an upstream HTTP failure into (status, type, msg).
// body is a truncated upstream body (already redacted by the caller).
func mapUpstreamStatus(status int, body string) (int, string, string) {
	switch {
	case status == 429:
		return 429, "rate_limit_error", "rate limited by upstream provider" + suffix(body)
	case status == 529 || status >= 500:
		return 529, "overloaded_error", "upstream provider overloaded" + suffix(body)
	case status == 401 || status == 403:
		return 401, "authentication_error", "upstream authentication failed" + suffix(body)
	case status == 404:
		return 404, "not_found_error", "upstream model not found" + suffix(body)
	case status == 400 || status == 422:
		return 400, "invalid_request_error", "upstream rejected the request" + suffix(body)
	case status == 408 || status == 504:
		return 529, "overloaded_error", "upstream timed out" + suffix(body)
	default:
		return 502, "api_error", "upstream request failed" + suffix(body)
	}
}

func suffix(body string) string {
	if body == "" {
		return ""
	}
	if len(body) > 160 {
		body = body[:160]
	}
	return ": " + body
}
