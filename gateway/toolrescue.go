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
	"fmt"
	"strings"
	"sync"
	"sync/atomic"
	"time"
)

// ModelRescueStats holds per-model rescue attempt and repair counts.
type ModelRescueStats struct {
	Attempted     uint64            `json:"attempted"`
	Rescued       uint64            `json:"rescued"`
	RepairsByType map[string]uint64 `json:"repairs_by_type"`
}

// RescueLogEntry records a recent repair event with diff and summary.
type RescueLogEntry struct {
	Timestamp  string `json:"timestamp"`
	Model      string `json:"model"`
	Tool       string `json:"tool"`
	RepairType string `json:"repair_type"`
	Diff       string `json:"diff"`
	Summary    string `json:"summary"`
}

// ToolRescueSnapshot is the admin API payload for GET /admin/toolrescue.
type ToolRescueSnapshot struct {
	RescueAttemptedTotal uint64                       `json:"rescue_attempted_total"`
	RescuedCallsTotal    uint64                       `json:"rescued_calls_total"`
	RepairsByType        map[string]uint64            `json:"repairs_by_type"`
	ByModel              map[string]*ModelRescueStats `json:"by_model"`
	RecentRepairs        []RescueLogEntry             `json:"recent_repairs"`
}

// ToolRescueEmulation manages tool rescue metrics, emulation repairs, and logging.
type ToolRescueEmulation struct {
	RescueAttemptedTotal uint64 `json:"rescue_attempted_total"`
	RescuedCallsTotal    uint64 `json:"rescued_calls_total"`

	// Atomic counters for standard repair types.
	FencedMarkdownJSONTotal uint64 `json:"fenced_markdown_json_total"`
	EscapedJSONStringTotal  uint64 `json:"escaped_json_string_total"`
	ArgSchemaCoercionTotal  uint64 `json:"arg_schema_coercion_total"`
	BraceExtractionTotal    uint64 `json:"brace_extraction_total"`
	ClosedUnbalancedTotal   uint64 `json:"closed_unbalanced_total"`

	mu            sync.RWMutex
	repairsByType map[string]uint64
	byModel       map[string]*ModelRescueStats
	recentLogs    []RescueLogEntry
	maxRecentLogs int
}

// NewToolRescueEmulation instantiates a fresh emulation layer.
func NewToolRescueEmulation() *ToolRescueEmulation {
	return &ToolRescueEmulation{
		repairsByType: map[string]uint64{
			"fenced_markdown_json": 0,
			"escaped_json_string":  0,
			"arg_schema_coercion":  0,
			"brace_extraction":     0,
			"closed_unbalanced":    0,
		},
		byModel:       make(map[string]*ModelRescueStats),
		recentLogs:    make([]RescueLogEntry, 0, 100),
		maxRecentLogs: 100,
	}
}

// DefaultToolRescue is the default package-level emulation instance.
var DefaultToolRescue = NewToolRescueEmulation()

// RecordAttempt records an attempted tool evaluation for a model.
func (e *ToolRescueEmulation) RecordAttempt(model string) {
	atomic.AddUint64(&e.RescueAttemptedTotal, 1)
	if model == "" {
		model = "unknown"
	}
	e.mu.Lock()
	defer e.mu.Unlock()
	st, ok := e.byModel[model]
	if !ok {
		st = &ModelRescueStats{
			RepairsByType: map[string]uint64{
				"fenced_markdown_json": 0,
				"escaped_json_string":  0,
				"arg_schema_coercion":  0,
				"brace_extraction":     0,
				"closed_unbalanced":    0,
			},
		}
		e.byModel[model] = st
	}
	st.Attempted++
}

// RecordRescue records a successful repair of one or more types.
func (e *ToolRescueEmulation) RecordRescue(model, tool string, repairTypes []string, original, repaired string) {
	if len(repairTypes) == 0 {
		return
	}
	atomic.AddUint64(&e.RescuedCallsTotal, 1)
	for _, rt := range repairTypes {
		switch rt {
		case "fenced_markdown_json":
			atomic.AddUint64(&e.FencedMarkdownJSONTotal, 1)
		case "escaped_json_string":
			atomic.AddUint64(&e.EscapedJSONStringTotal, 1)
		case "arg_schema_coercion":
			atomic.AddUint64(&e.ArgSchemaCoercionTotal, 1)
		case "brace_extraction":
			atomic.AddUint64(&e.BraceExtractionTotal, 1)
		case "closed_unbalanced":
			atomic.AddUint64(&e.ClosedUnbalancedTotal, 1)
		}
	}
	if model == "" {
		model = "unknown"
	}
	e.mu.Lock()
	defer e.mu.Unlock()
	st, ok := e.byModel[model]
	if !ok {
		st = &ModelRescueStats{
			RepairsByType: map[string]uint64{
				"fenced_markdown_json": 0,
				"escaped_json_string":  0,
				"arg_schema_coercion":  0,
				"brace_extraction":     0,
				"closed_unbalanced":    0,
			},
		}
		e.byModel[model] = st
	}
	st.Rescued++
	for _, rt := range repairTypes {
		e.repairsByType[rt]++
		st.RepairsByType[rt]++
	}
	entry := RescueLogEntry{
		Timestamp:  time.Now().UTC().Format(time.RFC3339),
		Model:      model,
		Tool:       tool,
		RepairType: strings.Join(repairTypes, ","),
		Diff:       makeRescueDiff(original, repaired),
		Summary:    makeRescueSummary(repairTypes),
	}
	if len(e.recentLogs) >= e.maxRecentLogs {
		e.recentLogs = append(e.recentLogs[1:], entry)
	} else {
		e.recentLogs = append(e.recentLogs, entry)
	}
}

// Snapshot returns a copy of the current metrics and recent logs for inspection.
func (e *ToolRescueEmulation) Snapshot() ToolRescueSnapshot {
	e.mu.RLock()
	defer e.mu.RUnlock()
	repMap := make(map[string]uint64, len(e.repairsByType))
	for k, v := range e.repairsByType {
		repMap[k] = v
	}
	bm := make(map[string]*ModelRescueStats, len(e.byModel))
	for k, v := range e.byModel {
		cp := &ModelRescueStats{
			Attempted:     v.Attempted,
			Rescued:       v.Rescued,
			RepairsByType: make(map[string]uint64, len(v.RepairsByType)),
		}
		for rk, rv := range v.RepairsByType {
			cp.RepairsByType[rk] = rv
		}
		bm[k] = cp
	}
	recent := make([]RescueLogEntry, len(e.recentLogs))
	copy(recent, e.recentLogs)
	return ToolRescueSnapshot{
		RescueAttemptedTotal: atomic.LoadUint64(&e.RescueAttemptedTotal),
		RescuedCallsTotal:    atomic.LoadUint64(&e.RescuedCallsTotal),
		RepairsByType:        repMap,
		ByModel:              bm,
		RecentRepairs:        recent,
	}
}

// Reset clears all counters and logs (useful in tests).
func (e *ToolRescueEmulation) Reset() {
	atomic.StoreUint64(&e.RescueAttemptedTotal, 0)
	atomic.StoreUint64(&e.RescuedCallsTotal, 0)
	atomic.StoreUint64(&e.FencedMarkdownJSONTotal, 0)
	atomic.StoreUint64(&e.EscapedJSONStringTotal, 0)
	atomic.StoreUint64(&e.ArgSchemaCoercionTotal, 0)
	atomic.StoreUint64(&e.BraceExtractionTotal, 0)
	atomic.StoreUint64(&e.ClosedUnbalancedTotal, 0)
	e.mu.Lock()
	defer e.mu.Unlock()
	e.repairsByType = map[string]uint64{
		"fenced_markdown_json": 0,
		"escaped_json_string":  0,
		"arg_schema_coercion":  0,
		"brace_extraction":     0,
		"closed_unbalanced":    0,
	}
	e.byModel = make(map[string]*ModelRescueStats)
	e.recentLogs = make([]RescueLogEntry, 0, 100)
}

func makeRescueDiff(original, repaired string) string {
	orig := strings.ReplaceAll(strings.ReplaceAll(original, "\n", " "), "\r", "")
	rep := strings.ReplaceAll(strings.ReplaceAll(repaired, "\n", " "), "\r", "")
	if len(orig) > 80 {
		orig = orig[:77] + "..."
	}
	if len(rep) > 80 {
		rep = rep[:77] + "..."
	}
	return orig + " -> " + rep
}

func makeRescueSummary(repairTypes []string) string {
	var parts []string
	for _, rt := range repairTypes {
		switch rt {
		case "fenced_markdown_json":
			parts = append(parts, "extracted JSON from markdown fence/text")
		case "escaped_json_string":
			parts = append(parts, "unescaped JSON string literal/quotes")
		case "arg_schema_coercion":
			parts = append(parts, "coerced/renamed argument keys against schema")
		case "brace_extraction":
			parts = append(parts, "extracted JSON object span from narrated text")
		case "closed_unbalanced":
			parts = append(parts, "closed unclosed braces/quotes in truncated JSON")
		default:
			parts = append(parts, rt)
		}
	}
	return strings.Join(parts, "; ")
}

// tryUnescapeJSONString detects and unescapes double-encoded or quote-escaped JSON strings.
func tryUnescapeJSONString(s string) (string, bool) {
	trimmed := strings.TrimSpace(s)
	// Outer double quotes enclosing an escaped JSON object: e.g. "{\"a\": 1}"
	if strings.HasPrefix(trimmed, "\"") && strings.HasSuffix(trimmed, "\"") && len(trimmed) >= 2 {
		var unquoted string
		if err := json.Unmarshal([]byte(trimmed), &unquoted); err == nil {
			unquoted = strings.TrimSpace(unquoted)
			if strings.HasPrefix(unquoted, "{") {
				return unquoted, true
			}
		}
	}
	// Raw escaped quotes without outer quotes: e.g. {\"a\": 1}
	if strings.Contains(trimmed, `\"`) {
		unescaped := strings.ReplaceAll(trimmed, `\"`, `"`)
		if strings.HasPrefix(strings.TrimSpace(unescaped), "{") {
			return unescaped, true
		}
	}
	return "", false
}

// RescueToolArgsDetailed attempts to salvage a tool-arguments string.
//
// Returns (repairedJSON, ok, tier, repairTypes).
func RescueToolArgsDetailed(raw string, schemaProps []string) (string, bool, string, []string) {
	trimmed := strings.TrimSpace(raw)
	if trimmed == "" {
		return "{}", true, "exact", nil
	}
	// 1. Exact: valid JSON object already.
	if isJSONObject(trimmed) {
		if fixed, renamed := fuzzyFixKeys(trimmed, schemaProps); renamed {
			if isJSONObject(fixed) {
				return fixed, true, "fuzzy", []string{"arg_schema_coercion"}
			}
			return trimmed, true, "exact", nil
		}
		return trimmed, true, "exact", nil
	}
	// 2. Escaped JSON string handling: e.g. "{\"location\":\"Paris\"}" or {\"key\": \"value\"}
	if unescaped, ok := tryUnescapeJSONString(trimmed); ok {
		repairs := []string{"escaped_json_string"}
		if isJSONObject(unescaped) {
			if fixed, renamed := fuzzyFixKeys(unescaped, schemaProps); renamed && isJSONObject(fixed) {
				return fixed, true, "fuzzy", append(repairs, "arg_schema_coercion")
			}
			return unescaped, true, "rescued", repairs
		}
		if closed, ok := RepairToolArgsJSON(unescaped); ok && isJSONObject(closed) {
			repairs = append(repairs, "closed_unbalanced")
			if fixed, renamed := fuzzyFixKeys(closed, schemaProps); renamed && isJSONObject(fixed) {
				return fixed, true, "fuzzy", append(repairs, "arg_schema_coercion")
			}
			return closed, true, "rescued", repairs
		}
	}
	// 3. Tier-1 close on the raw string.
	if closed, ok := RepairToolArgsJSON(trimmed); ok && isJSONObject(closed) {
		repairs := []string{"closed_unbalanced"}
		if fixed, renamed := fuzzyFixKeys(closed, schemaProps); renamed {
			if isJSONObject(fixed) {
				return fixed, true, "fuzzy", append(repairs, "arg_schema_coercion")
			}
			return closed, true, "closed", repairs
		}
		return closed, true, "closed", repairs
	}
	// 4. Rescue-extract: fenced blocks first, then largest {...} span.
	for _, cand := range extractFencedBlocks(trimmed) {
		candTrimmed := strings.TrimSpace(cand)
		if candTrimmed == "" {
			continue
		}
		if isJSONObject(candTrimmed) {
			repairs := []string{"fenced_markdown_json"}
			if fixed, renamed := fuzzyFixKeys(candTrimmed, schemaProps); renamed && isJSONObject(fixed) {
				return fixed, true, "fuzzy", append(repairs, "arg_schema_coercion")
			}
			return candTrimmed, true, "rescued", repairs
		}
		closed, ok := RepairToolArgsJSON(candTrimmed)
		if ok && isJSONObject(closed) {
			repairs := []string{"fenced_markdown_json", "closed_unbalanced"}
			if fixed, renamed := fuzzyFixKeys(closed, schemaProps); renamed && isJSONObject(fixed) {
				return fixed, true, "fuzzy", append(repairs, "arg_schema_coercion")
			}
			return closed, true, "rescued", repairs
		}
	}
	if span, ok := extractLargestBraceSpan(trimmed); ok {
		spanTrimmed := strings.TrimSpace(span)
		if isJSONObject(spanTrimmed) {
			repairs := []string{"brace_extraction"}
			if fixed, renamed := fuzzyFixKeys(spanTrimmed, schemaProps); renamed && isJSONObject(fixed) {
				return fixed, true, "fuzzy", append(repairs, "arg_schema_coercion")
			}
			return spanTrimmed, true, "rescued", repairs
		}
		closed, ok := RepairToolArgsJSON(spanTrimmed)
		if ok && isJSONObject(closed) {
			repairs := []string{"brace_extraction", "closed_unbalanced"}
			if fixed, renamed := fuzzyFixKeys(closed, schemaProps); renamed && isJSONObject(fixed) {
				return fixed, true, "fuzzy", append(repairs, "arg_schema_coercion")
			}
			return closed, true, "rescued", repairs
		}
	}
	return raw, false, "fail", nil
}

// RescueToolArgs attempts to salvage a tool-arguments string.
//
// Returns (repairedJSON, ok, tier) where tier is one of:
// "exact" (already valid), "closed" (Tier-1 brace/quote close sufficed),
// "rescued" (fence/brace extraction + close sufficed),
// "fuzzy" (a top-level key was renamed via levenshtein<=2),
// "fail" (downgrade signal — garbage, caller should not trust args).
func RescueToolArgs(raw string, schemaProps []string) (string, bool, string) {
	repaired, ok, tier, _ := RescueToolArgsDetailed(raw, schemaProps)
	return repaired, ok, tier
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

// --- CORRECTION 5 TOOL RESCUE security gating ---
//
// Rescue may fire ONLY on text the model itself produced in the assistant
// turn, ONLY for tools in the declared tool list (exact name match), and
// ONLY when args validate against the declared input_schema.
//
// Rationale: file contents, web results, and tool results arrive as
// user/tool messages or tool_result blocks — never as the assistant's own
// OpenAIResponseMessage (role=assistant) or assistant delta stream.
// Scanning anything else would let untrusted content inject tool_use blocks.
// The allowlist + schema check further ensures a poisoned fence that names
// an undeclared tool (or carries invalid args) is dropped as text, never
// emitted as tool_use. Every successful rescue is logged via RecordRescue
// (timestamp/model/tool/repair_type/diff/summary) and surfaced via
// GET /admin/toolrescue + X-Tool-Rescue header.

// allowedToolMap indexes declared tools by exact name.
func allowedToolMap(tools []AnthropicTool) map[string]AnthropicTool {
	m := make(map[string]AnthropicTool, len(tools))
	for _, t := range tools {
		if t.Name == "" {
			continue
		}
		if _, dup := m[t.Name]; !dup {
			m[t.Name] = t
		}
	}
	return m
}

// isAssistantRescueSource reports whether an OpenAI message role is the
// model's own assistant turn. Empty role defaults to assistant (upstream
// omits it); any other role (tool/user/system/developer) must never rescue.
func isAssistantRescueSource(role string) bool {
	r := strings.ToLower(strings.TrimSpace(role))
	return r == "" || r == "assistant"
}

// validateToolInput checks argsJSON against a declared input_schema.
// Rules: args must be a JSON object; required fields must be present;
// present fields with a declared primitive type must match; when
// additionalProperties is explicitly false, unknown keys are rejected.
// Empty/missing schema accepts any JSON object (still rejects non-objects).
func validateToolInput(argsJSON string, schema json.RawMessage) (bool, string) {
	var args map[string]interface{}
	if err := json.Unmarshal([]byte(argsJSON), &args); err != nil {
		return false, "args not a JSON object"
	}
	if args == nil {
		// "null" unmarshals without error to nil map.
		return false, "args is null, not an object"
	}
	if len(schema) == 0 {
		return true, ""
	}
	var s struct {
		Type                 string `json:"type"`
		Properties           map[string]struct {
			Type string `json:"type"`
		} `json:"properties"`
		Required             []string `json:"required"`
		AdditionalProperties *bool    `json:"additionalProperties"`
	}
	if err := json.Unmarshal(schema, &s); err != nil {
		// Unparseable schema: fail open for objects (still gated by allowlist).
		return true, ""
	}
	for _, req := range s.Required {
		if _, ok := args[req]; !ok {
			return false, "missing required field: " + req
		}
	}
	for name, prop := range s.Properties {
		val, present := args[name]
		if !present {
			continue
		}
		want := strings.ToLower(strings.TrimSpace(prop.Type))
		if want == "" {
			continue
		}
		switch want {
		case "string":
			if _, ok := val.(string); !ok {
				return false, "field " + name + " must be string"
			}
		case "number":
			if _, ok := val.(float64); !ok {
				return false, "field " + name + " must be number"
			}
		case "integer":
			f, ok := val.(float64)
			if !ok {
				return false, "field " + name + " must be integer"
			}
			if f != float64(int64(f)) {
				return false, "field " + name + " must be integer"
			}
		case "boolean", "bool":
			if _, ok := val.(bool); !ok {
				return false, "field " + name + " must be boolean"
			}
		case "array":
			if _, ok := val.([]interface{}); !ok {
				return false, "field " + name + " must be array"
			}
		case "object":
			if _, ok := val.(map[string]interface{}); !ok {
				return false, "field " + name + " must be object"
			}
		}
	}
	if s.AdditionalProperties != nil && !*s.AdditionalProperties && len(s.Properties) > 0 {
		for k := range args {
			if _, ok := s.Properties[k]; !ok {
				return false, "unknown field rejected: " + k
			}
		}
	}
	return true, ""
}

// gatedFencedCall validates a single (name, params) candidate against the
// allowlist + schema and returns the final args JSON. It runs arg repair
// (fuzzy/close) then re-validates; invalid candidates return ok=false.
func gatedFencedCall(name string, params interface{}, allowed map[string]AnthropicTool) (string, bool) {
	tool, ok := allowed[name]
	if !ok || name == "" {
		return "", false
	}
	argBytes, _ := json.Marshal(params)
	if len(argBytes) == 0 || string(argBytes) == "null" {
		argBytes = []byte("{}")
	}
	raw := string(argBytes)
	// Repair then validate so truncated/fuzzy args still pass when fixable.
	props := schemaPropertyNames(tool.InputSchema)
	if repaired, ok, _, _ := RescueToolArgsDetailed(raw, props); ok {
		raw = repaired
	}
	if ok, _ := validateToolInput(raw, tool.InputSchema); !ok {
		return "", false
	}
	return raw, true
}

// extractFencedToolCalls attempts to parse tool calls embedded in assistant text (e.g. ```json [...] ```).
// SECURITY (CORRECTION 5): only text the model itself produced in the
// assistant turn may be passed as `text` (callers enforce
// isAssistantRescueSource); only tools in `tools` (exact name match) are
// returned; each call's args must validate against its declared
// input_schema. Undeclared tools and schema-invalid args are skipped so
// fenced text inside file contents / web results / tool results never
// executes. Pass nil/empty tools to disable fenced rescue entirely.
func extractFencedToolCalls(text string, tools []AnthropicTool) []OpenAIToolCall {
	if text == "" || len(tools) == 0 {
		return nil
	}
	allowed := allowedToolMap(tools)
	candidates := extractionCandidates(text)
	for _, cand := range candidates {
		trimmed := strings.TrimSpace(cand)
		// Check array candidate: [{"tool": "...", "parameters": {...}}, ...]
		if strings.HasPrefix(trimmed, "[") {
			var list []map[string]interface{}
			if err := json.Unmarshal([]byte(trimmed), &list); err == nil && len(list) > 0 {
				var out []OpenAIToolCall
				for i, item := range list {
					name, _ := item["name"].(string)
					if name == "" {
						name, _ = item["tool"].(string)
					}
					if name == "" {
						name, _ = item["type"].(string)
					}
					if name == "" {
						name, _ = item["action"].(string)
					}
					if name == "" {
						name, _ = item["function"].(string)
					}
					if name == "" {
						continue
					}
					params := item["parameters"]
					if params == nil {
						params = item["arguments"]
					}
					if params == nil {
						params = item["input"]
					}
					if params == nil {
						rawParams := make(map[string]interface{})
						for k, v := range item {
							switch strings.ToLower(k) {
							case "name", "tool", "type", "action", "function", "description", "thought", "reasoning":
							default:
								rawParams[k] = v
							}
						}
						if len(rawParams) > 0 {
							params = rawParams
						}
					}
					if params == nil {
						continue
					}
					// CORRECTION 5: allowlist + schema validation; skip undeclared/invalid.
					finalArgs, ok := gatedFencedCall(name, params, allowed)
					if !ok {
						continue
					}
					out = append(out, OpenAIToolCall{
						ID:   fmt.Sprintf("call_rescued_%d", i+1),
						Type: "function",
						Function: OpenAIToolFunction{
							Name:      name,
							Arguments: finalArgs,
						},
					})
				}
				if len(out) > 0 {
					return out
				}
			}
		} else if strings.HasPrefix(trimmed, "{") {
			// Check single object candidate: {"tool": "...", "parameters": {...}}
			var item map[string]interface{}
			if err := json.Unmarshal([]byte(trimmed), &item); err == nil {
				name, _ := item["name"].(string)
				if name == "" {
					name, _ = item["tool"].(string)
				}
				if name == "" {
					name, _ = item["type"].(string)
				}
				if name == "" {
					name, _ = item["action"].(string)
				}
				if name == "" {
					name, _ = item["function"].(string)
				}
				params := item["parameters"]
				if params == nil {
					params = item["arguments"]
				}
				if params == nil {
					params = item["input"]
				}
				if params == nil {
					rawParams := make(map[string]interface{})
					for k, v := range item {
						switch strings.ToLower(k) {
						case "name", "tool", "type", "action", "function", "description", "thought", "reasoning":
						default:
							rawParams[k] = v
						}
					}
					if len(rawParams) > 0 {
						params = rawParams
					}
				}
				if name == "" || params == nil {
					continue
				}
				// CORRECTION 5: allowlist + schema validation; skip undeclared/invalid.
				finalArgs, ok := gatedFencedCall(name, params, allowed)
				if !ok {
					continue
				}
				return []OpenAIToolCall{
					{
						ID:   "call_rescued_1",
						Type: "function",
						Function: OpenAIToolFunction{
							Name:      name,
							Arguments: finalArgs,
						},
					},
				}
			}
		}
	}
	return nil
}

// TranslateResponseWithTools maps an OpenAI chat completion to Anthropic
// messages format, rescuing tool arguments with Tier-2 logic. Schema
// property names are taken from the AnthropicTool whose name matches the
// tool call, when available; pass nil tools to rescue without fuzzy repair.
// On total rescue failure (tier "fail") the original args are preserved and
// the block id/name still pass through — the "fail" tier from RescueToolArgs
// is the downgrade signal for callers that need to branch (e.g. render the
// call as text instead).
// TranslateResponse maps an OpenAI chat completion to Anthropic messages format,
// optionally performing tool rescue via the emulation layer. Returns the translated
// response and a list of repair types applied.
func (e *ToolRescueEmulation) TranslateResponse(or *OpenAIChatResponse, model string, tools []AnthropicTool, enabled bool) (*AnthropicResponse, []string) {
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
	allowed := allowedToolMap(tools)
	schemaByName := make(map[string]json.RawMessage, len(tools))
	for _, t := range tools {
		if _, dup := propsByName[t.Name]; !dup {
			propsByName[t.Name] = schemaPropertyNames(t.InputSchema)
			schemaByName[t.Name] = t.InputSchema
		}
	}
	var accumulatedRepairs []string
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
		rawContent := openAIContentText(ch.Message.Content)
		toolCalls := ch.Message.ToolCalls
		// CORRECTION 5 gating: fenced rescue fires ONLY on assistant-produced
		// text (role=assistant/empty). File contents, web results, and tool
		// results arrive as user/tool/tool_result messages — never here —
		// so passing only ch.Message.Content provably excludes them.
		// extractFencedToolCalls additionally enforces declared-tool
		// allowlist + input_schema validation.
		if enabled && len(toolCalls) == 0 && len(tools) > 0 && isAssistantRescueSource(ch.Message.Role) {
			if rescued := extractFencedToolCalls(rawContent, tools); len(rescued) > 0 {
				toolCalls = rescued
				ar.StopReason = "tool_use"
				for _, tc := range rescued {
					e.RecordAttempt(model)
					e.RecordRescue(model, tc.Function.Name, []string{"fenced_markdown_json"}, rawContent, tc.Function.Arguments)
				}
				accumulatedRepairs = append(accumulatedRepairs, "fenced_markdown_json")
			}
		}
		if rawContent != "" && len(toolCalls) == 0 {
			ar.Content = append(ar.Content, ContentBlock{Type: "text", Text: rawContent})
		}
		if ch.Message.Refusal != "" {
			ar.Content = append(ar.Content, ContentBlock{Type: "text", Text: ch.Message.Refusal})
		}
		for _, tc := range toolCalls {
			args := tc.Function.Arguments
			if enabled {
				// CORRECTION 5: arg rescue fires ONLY for declared tools.
				// Undeclared tool names pass through untouched with no
				// repair and no rescue logging.
				if _, declared := allowed[tc.Function.Name]; declared {
					e.RecordAttempt(model)
					if repaired, ok, _, repairs := RescueToolArgsDetailed(args, propsByName[tc.Function.Name]); ok {
						// Schema-validate repaired args; on validation
						// failure keep original args but do not log rescue.
						if valid, _ := validateToolInput(repaired, schemaByName[tc.Function.Name]); valid {
							if len(repairs) > 0 {
								e.RecordRescue(model, tc.Function.Name, repairs, args, repaired)
								accumulatedRepairs = append(accumulatedRepairs, repairs...)
							}
							args = repaired
						} else if validOrig, _ := validateToolInput(args, schemaByName[tc.Function.Name]); !validOrig {
							// Both repaired and original fail schema: keep
							// original text but do not claim a rescue.
							args = repaired
						} else {
							if len(repairs) > 0 {
								e.RecordRescue(model, tc.Function.Name, repairs, args, repaired)
								accumulatedRepairs = append(accumulatedRepairs, repairs...)
							}
							args = repaired
						}
					}
				}
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
	seen := make(map[string]bool)
	var uniqueRepairs []string
	for _, r := range accumulatedRepairs {
		if !seen[r] {
			seen[r] = true
			uniqueRepairs = append(uniqueRepairs, r)
		}
	}
	return ar, uniqueRepairs
}

// TranslateResponseWithTools maps an OpenAI chat completion to Anthropic
// messages format, rescuing tool arguments with Tier-2 logic.
func TranslateResponseWithTools(or *OpenAIChatResponse, model string, tools []AnthropicTool) *AnthropicResponse {
	resp, _ := DefaultToolRescue.TranslateResponse(or, model, tools, true)
	return resp
}
