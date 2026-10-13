// adapters.go — declarative provider adapter specs.
//
// Any provider is: endpoint + auth + request/response mapping + streaming
// format + error mapping. Unknown providers are added WITHOUT code via
// config (see docs/adding-a-provider.md): the gateway validates the spec
// (ValidateAdapter) and probes it (ProbeAdapter). Sanitization of tool
// schemas per provider limits is logged (what was dropped, never secrets).
package gateway

import (
	"encoding/json"
	"fmt"
	"regexp"
	"strings"
)

// AdapterSpec describes how to talk to one provider's HTTP API.
type AdapterSpec struct {
	Dialect       string            `json:"dialect"` // openai-chat (default), anthropic, gemini-openai, cohere, ollama, unknown
	ChatPath      string            `json:"chat_path,omitempty"`      // default "/chat/completions"
	ModelsPath    string            `json:"models_path,omitempty"`    // default "/models"
	StreamFormat  string            `json:"stream_format,omitempty"`  // sse-openai (default), sse-anthropic, ndjson, none
	AuthStyle     string            `json:"auth_style,omitempty"`     // bearer (default), x-api-key, query-param, custom-header
	AuthParam     string            `json:"auth_param,omitempty"`     // header name or query key for non-bearer styles
	ExtraHeaders  map[string]string `json:"extra_headers,omitempty"`
	ToolSupport   string            `json:"tool_support,omitempty"`   // native (default), none
	MaxToolName   int               `json:"max_tool_name,omitempty"`  // 0 = no limit enforced
	StripKeywords []string          `json:"strip_keywords,omitempty"` // JSON-schema keys to drop (logged)
	Vision        bool              `json:"vision,omitempty"`
	// ToolImages says what to do with image parts that arrive inside a
	// tool_result block. The OpenAI wire shape allows image_url parts in
	// user/assistant messages, but Gemini's OpenAI endpoint rejects them in
	// tool messages ("Invalid content part type: image_url"), so providers
	// that 400 on that shape must downgrade here rather than fail the whole
	// request. Values: "parts" (default — keep), "text" (placeholder), "drop".
	ToolImages     string            `json:"tool_images,omitempty"`
}

// EffectiveAdapter returns the provider's spec with documented defaults.
func EffectiveAdapter(p Provider) AdapterSpec {
	a := p.Adapter
	if a.Dialect == "" {
		a.Dialect = "openai-chat"
	}
	if a.ChatPath == "" {
		a.ChatPath = "/chat/completions"
	}
	if a.ModelsPath == "" {
		a.ModelsPath = "/models"
	}
	if a.StreamFormat == "" {
		a.StreamFormat = "sse-openai"
	}
	if a.AuthStyle == "" {
		a.AuthStyle = "bearer"
	}
	if a.ToolSupport == "" {
		a.ToolSupport = "native"
	}
	if a.ToolImages == "" {
		a.ToolImages = "parts"
	}
	return a
}

// ValidateAdapter checks a spec without network. Returns human errors.
func ValidateAdapter(a AdapterSpec) []string {
	var errs []string
	switch a.Dialect {
	case "", "openai-chat", "anthropic", "gemini-openai", "cohere", "ollama",
		"openrouter", "azure-openai", "huggingface", "unknown":
	default:
		errs = append(errs, fmt.Sprintf("dialect %q: use openai-chat|anthropic|gemini-openai|cohere|ollama|openrouter|azure-openai|huggingface|unknown", a.Dialect))
	}
	switch a.AuthStyle {
	case "", "bearer", "x-api-key", "query-param", "custom-header", "none":
	default:
		errs = append(errs, fmt.Sprintf("auth_style %q: use bearer|x-api-key|query-param|custom-header|none", a.AuthStyle))
	}
	if (a.AuthStyle == "custom-header" || a.AuthStyle == "query-param") && a.AuthParam == "" {
		errs = append(errs, "auth_param required for custom-header/query-param")
	}
	switch a.StreamFormat {
	case "", "sse-openai", "sse-anthropic", "ndjson", "none":
	default:
		errs = append(errs, fmt.Sprintf("stream_format %q: use sse-openai|sse-anthropic|ndjson|none", a.StreamFormat))
	}
	if a.ChatPath != "" && !strings.HasPrefix(a.ChatPath, "/") {
		errs = append(errs, "chat_path must start with /")
	}
	return errs
}

var validToolName = regexp.MustCompile(`^[A-Za-z0-9_-]+$`)

// SanitizeTool converts one Anthropic tool def to OpenAI shape within provider
// limits. It returns the converted tool and a list of human-readable notes
// about what was changed (for logs; contains no secrets).
func SanitizeTool(t AnthropicTool, maxName int, strip []string) (OpenAITool, []string) {
	var notes []string
	name := t.Name
	if maxName > 0 && len(name) > maxName {
		name = name[:maxName]
		notes = append(notes, "tool name truncated to "+name)
	}
	if !validToolName.MatchString(name) {
		re := regexp.MustCompile(`[^A-Za-z0-9_-]+`)
		fixed := re.ReplaceAllString(name, "_")
		notes = append(notes, "tool name sanitized to "+fixed)
		name = fixed
	}
	params := t.InputSchema
	if len(params) > 0 && len(strip) > 0 {
		var schema map[string]interface{}
		if err := json.Unmarshal(params, &schema); err == nil {
			dropped := stripSchemaKeys(schema, strip)
			if len(dropped) > 0 {
				if b, err := json.Marshal(schema); err == nil {
					params = b
				}
				notes = append(notes, "schema keywords dropped: "+strings.Join(dropped, ","))
			}
		}
	}
	if len(params) == 0 {
		params = json.RawMessage(`{"type":"object","properties":{}}`)
	}
	return OpenAITool{Type: "function", Function: OpenAIToolSchema{
		Name: name, Description: t.Description, Parameters: params,
	}}, notes
}

func stripSchemaKeys(schema map[string]interface{}, strip []string) []string {
	drop := make(map[string]bool, len(strip))
	for _, k := range strip {
		drop[k] = true
	}
	var dropped []string
	var walk func(v interface{})
	walk = func(v interface{}) {
		switch n := v.(type) {
		case map[string]interface{}:
			for k := range n {
				if drop[k] {
					delete(n, k)
					dropped = append(dropped, k)
				}
			}
			for _, v := range n {
				walk(v)
			}
		case []interface{}:
			for _, v := range n {
				walk(v)
			}
		}
	}
	walk(schema)
	return dropped
}
