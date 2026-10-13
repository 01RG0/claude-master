// toolrescue.go — Tier-2 tool-call argument rescue.
//
// Tier-1 (RepairToolArgsJSON in stream_translator.go) only closes open
// braces/quotes. Tier-2 adds:
//   - rescue-extract: find JSON embedded in narrated text or ```json fences,
//     using the largest {...} span (or first-{ to end when truncated),
//   - fuzzy param-name repair: levenshtein<=2 against schema properties,
//   - downgrade signal: the tier label. Callers treat tier=="fail" as the
//     signal to downgrade (e.g. render as text / ask for retry) instead of
//     emitting a corrupt tool_use block. TranslateResponseWithTools keeps
//     emitting the block (id passthrough) so existing clients never break;
//     the signal is available via RescueToolArgs for the caller to inspect.
package gateway

import (
	"encoding/json"
	"strings"
)

// RescueToolArgs attempts to salvage a tool-arguments string.
//
// Returns (repairedJSON, ok, tier) where tier is one of:
// "exact" (already valid), "closed" (Tier-1 brace/quote close sufficed),
// "rescued" (fence/brace extraction + close sufficed),
// "fuzzy" (a top-level key was renamed via levenshtein<=2),
// "fail" (downgrade signal — garbage, caller should not trust args).
func RescueToolArgs(raw string, schemaProps []string) (string, bool, string) {
	trimmed := strings.TrimSpace(raw)
	if trimmed == "" {
		return "{}", true, "exact"
	}
	// 1. Exact: valid JSON object already.
	if isJSONObject(trimmed) {
		if fixed, renamed := fuzzyFixKeys(trimmed, schemaProps); renamed {
			if isJSONObject(fixed) {
				return fixed, true, "fuzzy"
			}
			return trimmed, true, "exact"
		}
		return trimmed, true, "exact"
	}
	// 2. Tier-1 close on the raw string.
	if closed, ok := RepairToolArgsJSON(trimmed); ok {
		if fixed, renamed := fuzzyFixKeys(closed, schemaProps); renamed {
			if isJSONObject(fixed) {
				return fixed, true, "fuzzy"
			}
			return closed, true, "closed"
		}
		return closed, true, "closed"
	}
	// 3. Rescue-extract: fenced blocks first, then largest {...} span.
	for _, cand := range extractionCandidates(trimmed) {
		closed, ok := RepairToolArgsJSON(cand)
		if !ok {
			continue
		}
		if !isJSONObject(closed) {
			continue
		}
		if fixed, renamed := fuzzyFixKeys(closed, schemaProps); renamed {
			if isJSONObject(fixed) {
				return fixed, true, "fuzzy"
			}
			return closed, true, "rescued"
		}
		return closed, true, "rescued"
	}
	return raw, false, "fail"
}

// isJSONObject reports whether s parses as a JSON object.
func isJSONObject(s string) bool {
	t := strings.TrimSpace(s)
	if t == "" || !strings.HasPrefix(t, "{") {
		return false
	}
	var m map[string]json.RawMessage
	if err := json.Unmarshal([]byte(t), &m); err != nil {
		return false
	}
	// Reject literal "null" (unmarshals to nil map without error).
	if m == nil && strings.TrimSpace(t) != "{}" {
		// "{}" unmarshals to non-nil empty map; "null" to nil.
		// Distinguish defensively.
		var v interface{}
		if err := json.Unmarshal([]byte(t), &v); err != nil {
			return false
		}
		if _, ok := v.(map[string]interface{}); !ok {
			return false
		}
	}
	return true
}

// extractionCandidates returns rescue candidates in priority order:
// all ``` fenced blocks (inner content), then the largest {...} span.
func extractionCandidates(s string) []string {
	var out []string
	for _, f := range extractFencedBlocks(s) {
		if strings.TrimSpace(f) != "" {
			out = append(out, f)
		}
	}
	if span, ok := extractLargestBraceSpan(s); ok {
		out = append(out, span)
	}
	return out
}

// extractFencedBlocks returns the inner content of every ```...``` span.
// A leading language tag line (e.g. "json") is stripped.
func extractFencedBlocks(s string) []string {
	var blocks []string
	rest := s
	for {
		start := strings.Index(rest, "```")
		if start < 0 {
			break
		}
		after := rest[start+3:]
		end := strings.Index(after, "```")
		if end < 0 {
			break
		}
		inner := after[:end]
		// Strip a leading language-tag line ("json", "JSON", etc.).
		if i := strings.Index(inner, "\n"); i >= 0 {
			first := strings.TrimSpace(inner[:i])
			if isFenceTag(first) {
				inner = inner[i+1:]
			}
		} else if isFenceTag(strings.TrimSpace(inner)) {
			inner = ""
		}
		blocks = append(blocks, strings.TrimSpace(inner))
		rest = after[end+3:]
	}
	return blocks
}

func isFenceTag(s string) bool {
	t := strings.ToLower(strings.TrimSpace(s))
	switch t {
	case "", "json", "jsonc", "javascript", "js", "object":
		return true
	}
	// Short single-word tag with no braces: treat as language label.
	if !strings.ContainsAny(t, "{}\"':") && len(t) < 16 {
		return true
	}
	return false
}

// extractLargestBraceSpan returns the substring from the first '{' to the
// last '}' (largest span). When truncated (no closing brace), it returns
// from the first '{' to the end so RepairToolArgsJSON can close it.
func extractLargestBraceSpan(s string) (string, bool) {
	first := strings.Index(s, "{")
	if first < 0 {
		return "", false
	}
	if last := strings.LastIndex(s, "}"); last > first {
		return strings.TrimSpace(s[first : last+1]), true
	}
	// Truncated: no closing brace at all.
	return strings.TrimSpace(s[first:]), true
}

// fuzzyFixKeys renames top-level keys not in props to the closest prop with
// levenshtein distance <=2. Returns (fixedJSON, renamed). With no schema
// props, unknown keys are kept untouched (nil, false).
func fuzzyFixKeys(jsonStr string, props []string) (string, bool) {
	if len(props) == 0 {
		return jsonStr, false
	}
	var m map[string]json.RawMessage
	if err := json.Unmarshal([]byte(jsonStr), &m); err != nil {
		return jsonStr, false
	}
	set := make(map[string]struct{}, len(props))
	for _, p := range props {
		set[p] = struct{}{}
	}
	renamed := false
	// Snapshot keys to avoid mutating during iteration.
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	for _, k := range keys {
		if _, ok := set[k]; ok {
			continue
		}
		best := ""
		bestDist := 3 // strictly greater than allowed max
		for _, p := range props {
			if _, taken := m[p]; taken {
				// Target already present: renaming would collide.
				// Still allow it as a candidate only if no better free slot.
				continue
			}
			if d := levenshteinDistance(k, p); d < bestDist {
				bestDist = d
				best = p
			}
		}
		if best != "" && bestDist <= 2 {
			m[best] = m[k]
			delete(m, k)
			set[best] = struct{}{}
			renamed = true
		}
	}
	if !renamed {
		return jsonStr, false
	}
	b, err := json.Marshal(m)
	if err != nil {
		return jsonStr, false
	}
	return string(b), true
}

// levenshteinDistance is the rune-wise edit distance.
func levenshteinDistance(a, b string) int {
	ar, br := []rune(a), []rune(b)
	if len(ar) == 0 {
		return len(br)
	}
	if len(br) == 0 {
		return len(ar)
	}
	prev := make([]int, len(br)+1)
	for j := range prev {
		prev[j] = j
	}
	for i := 1; i <= len(ar); i++ {
		cur := make([]int, len(br)+1)
		cur[0] = i
		for j := 1; j <= len(br); j++ {
			cost := 0
			if ar[i-1] != br[j-1] {
				cost = 1
			}
			del := prev[j] + 1
			ins := cur[j-1] + 1
			sub := prev[j-1] + cost
			cur[j] = del
			if ins < cur[j] {
				cur[j] = ins
			}
			if sub < cur[j] {
				cur[j] = sub
			}
		}
		prev = cur
	}
	return prev[len(br)]
}

// schemaPropertyNames extracts top-level property names from an Anthropic
// input_schema ({"type":"object","properties":{...}}). Returns nil when the
// schema is absent or has no properties.
func schemaPropertyNames(schema json.RawMessage) []string {
	if len(schema) == 0 {
		return nil
	}
	var s struct {
		Properties map[string]json.RawMessage `json:"properties"`
	}
	if err := json.Unmarshal(schema, &s); err != nil {
		return nil
	}
	if len(s.Properties) == 0 {
		return nil
	}
	out := make([]string, 0, len(s.Properties))
	for k := range s.Properties {
		out = append(out, k)
	}
	return out
}

// TranslateResponseWithTools maps an OpenAI chat completion to Anthropic
// messages format, rescuing tool arguments with Tier-2 logic. Schema
// property names are taken from the AnthropicTool whose name matches the
// tool call, when available; pass nil tools to rescue without fuzzy repair.
// On total rescue failure (tier "fail") the original args are preserved and
// the block id/name still pass through — the "fail" tier from RescueToolArgs
// is the downgrade signal for callers that need to branch (e.g. render the
// call as text instead).
func TranslateResponseWithTools(or *OpenAIChatResponse, model string, tools []AnthropicTool) *AnthropicResponse {
	ar := &AnthropicResponse{
		ID:         or.ID,
		Type:       "message",
		Role:       "assistant",
		Model:      model,
		StopReason: "end_turn",
		Content:    nil,
	}
	// Index schema props by tool name for fuzzy repair.
	propsByName := make(map[string][]string, len(tools))
	for _, t := range tools {
		if _, dup := propsByName[t.Name]; !dup {
			propsByName[t.Name] = schemaPropertyNames(t.InputSchema)
		}
	}
	if len(or.Choices) > 0 {
		ch := or.Choices[0]
		switch ch.FinishReason {
		case "tool_calls":
			ar.StopReason = "tool_use"
		case "length":
			ar.StopReason = "max_tokens"
		case "content_filter", "refusal":
			ar.StopReason = "refusal"
		case "stop_sequence":
			ar.StopReason = "stop_sequence"
		}
		// Upstream OpenAI-style reasoning_content → Anthropic thinking
		// block. The signature is an emulated marker, never a real
		// Anthropic signature. Thinking comes first (Anthropic order).
		reasoning := ch.Message.ReasoningContent
		if reasoning == "" {
			reasoning = ch.Message.Reasoning
		}
		if reasoning != "" {
			ar.Content = append(ar.Content, ContentBlock{
				Type:      "thinking",
				Thinking:  reasoning,
				Signature: emulatedThinkingSignature,
			})
		}
		if text := openAIContentText(ch.Message.Content); text != "" {
			ar.Content = append(ar.Content, ContentBlock{Type: "text", Text: text})
		}
		if ch.Message.Refusal != "" {
			ar.Content = append(ar.Content, ContentBlock{Type: "text", Text: ch.Message.Refusal})
		}
		for _, tc := range ch.Message.ToolCalls {
			args := tc.Function.Arguments
			if repaired, ok, _ := RescueToolArgs(args, propsByName[tc.Function.Name]); ok {
				args = repaired
			}
			if strings.TrimSpace(args) == "" {
				args = "{}"
			}
			ar.Content = append(ar.Content, ContentBlock{
				Type:  "tool_use",
				ID:    tc.ID,
				Name:  tc.Function.Name,
				Input: json.RawMessage(args),
			})
		}
	}
	if ar.Content == nil {
		ar.Content = []ContentBlock{}
	}
	if or.Usage != nil {
		ar.Usage = map[string]int{
			"input_tokens":  or.Usage.PromptTokens,
			"output_tokens": or.Usage.CompletionTokens,
		}
		cached := or.Usage.CachedTokens
		if or.Usage.PromptDetails != nil && or.Usage.PromptDetails.CachedTokens > cached {
			cached = or.Usage.PromptDetails.CachedTokens
		}
		if cached > 0 {
			ar.Usage["cache_read_input_tokens"] = cached
		}
		creation := or.Usage.CacheCreationTokens
		if or.Usage.CacheCreationAlt > creation {
			creation = or.Usage.CacheCreationAlt
		}
		if creation > 0 {
			ar.Usage["cache_creation_input_tokens"] = creation
		}
	}
	return ar
}
