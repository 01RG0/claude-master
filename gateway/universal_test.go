// universal_test.go — conformance unit tests for the universal gateway.
package gateway

import (
	"encoding/json"
	"strings"
	"testing"
)

func TestStreamTranslatorToolArgsIncremental(t *testing.T) {
	tr := NewStreamTranslator("m", "msg_1")
	stopStr := "tool_calls"
	mk := func(args string, idx int, id, name string, finish *string) *StreamChunk {
		return &StreamChunk{ID: "c", Model: "m", Choices: []StreamChoice{{
			Index: 0,
			Delta: StreamDelta{ToolCalls: []ToolCallDelta{{
				Index: idx, ID: id, Function: OpenAIToolFunction{Name: name, Arguments: args},
			}}},
			FinishReason: finish,
		}}}
	}
	evs := tr.Translate(mk(`{"a":`, 0, "call_1", "calc", nil))
	var starts, deltas int
	for _, e := range evs {
		if e.Event == "content_block_start" {
			starts++
		}
		if e.Event == "content_block_delta" {
			deltas++
			d, _ := json.Marshal(e.Data)
			if !strings.Contains(string(d), "input_json_delta") {
				t.Fatalf("delta is not input_json_delta: %s", d)
			}
		}
	}
	if starts != 1 || deltas != 1 {
		t.Fatalf("starts=%d deltas=%d", starts, deltas)
	}
	evs = tr.Translate(mk(`1}`, 0, "", "", &stopStr))
	for _, e := range evs {
		if e.Event == "content_block_start" {
			t.Fatal("duplicate tool_use start for same index")
		}
	}
	fin := tr.Finish(10, 5, 0)
	var stops, md, ms int
	for _, e := range fin {
		switch e.Event {
		case "content_block_stop":
			stops++
		case "message_delta":
			md++
			d, _ := json.Marshal(e.Data)
			if !strings.Contains(string(d), "tool_use") {
				t.Fatalf("message_delta missing tool_use stop: %s", d)
			}
		case "message_stop":
			ms++
		}
	}
	if stops != 1 || md != 1 || ms != 1 {
		t.Fatalf("stops=%d delta=%d stop=%d", stops, md, ms)
	}
}

func TestStreamTranslatorParallelTools(t *testing.T) {
	tr := NewStreamTranslator("m", "msg_2")
	stop := "tool_calls"
	ch := &StreamChunk{ID: "c", Model: "m", Choices: []StreamChoice{{
		Delta: StreamDelta{ToolCalls: []ToolCallDelta{
			{Index: 0, ID: "a", Function: OpenAIToolFunction{Name: "echo", Arguments: `{"w":"a"}`}},
			{Index: 1, ID: "b", Function: OpenAIToolFunction{Name: "echo", Arguments: `{"w":"b"}`}},
		}},
		FinishReason: &stop,
	}}}
	evs := tr.Translate(ch)
	starts := 0
	for _, e := range evs {
		if e.Event == "content_block_start" {
			starts++
		}
	}
	if starts != 2 {
		t.Fatalf("parallel tools starts=%d want 2", starts)
	}
}

func TestRepairTruncatedArgs(t *testing.T) {
	fixed, ok := RepairToolArgsJSON(`{"a": 1, "b": "x`)
	if !ok {
		t.Fatalf("repair failed: %q", fixed)
	}
	if _, bad := RepairToolArgsJSON(`{{{`); bad {
		t.Fatal("garbage should not parse")
	}
}

func TestResolveModelNeverEmpty(t *testing.T) {
	cands := []string{"mistral/open-mistral-7b", "pollinations/openai"}
	aliases := map[string]string{"opus": "mistral/open-mistral-7b"}
	roles := &RoleMapping{Main: "pollinations/openai", Fast: "mistral/open-mistral-7b"}
	for _, req := range []string{"claude-opus-5-5", "opus", "sonnet", "haiku", "claude-haiku-9",
		"mistral/open-mistral-7b", "something-unknown-xyz", ""} {
		if got := ResolveModel(req, aliases, roles, cands); got == "" {
			t.Fatalf("empty mapping for %q", req)
		}
	}
	if got := ResolveModel("claude-haiku-1", aliases, roles, cands); got != "mistral/open-mistral-7b" {
		t.Fatalf("haiku should map to fast role, got %q", got)
	}
}

func TestValidateAdapter(t *testing.T) {
	if errs := ValidateAdapter(AdapterSpec{}); len(errs) != 0 {
		t.Fatalf("empty spec should validate with defaults: %v", errs)
	}
	errs := ValidateAdapter(AdapterSpec{Dialect: "telepathy", AuthStyle: "carrier-pigeon"})
	if len(errs) < 2 {
		t.Fatalf("expected dialect+auth errors, got %v", errs)
	}
}

func TestSanitizeToolDropsKeywords(t *testing.T) {
	tool := AnthropicTool{Name: "my tool!", InputSchema: json.RawMessage(
		`{"type":"object","properties":{"x":{"type":"string","format":"email"}}}`)}
	fixed, notes := SanitizeTool(tool, 64, []string{"format"})
	if fixed.Function.Name != "my_tool_" {
		t.Fatalf("name not sanitized: %q", fixed.Function.Name)
	}
	if len(notes) == 0 {
		t.Fatal("expected sanitizer notes")
	}
	var schema map[string]interface{}
	if err := json.Unmarshal(fixed.Function.Parameters, &schema); err != nil {
		t.Fatal(err)
	}
}

func TestMapUpstreamStatus(t *testing.T) {
	cases := map[int][2]interface{}{
		429: {429, "rate_limit_error"},
		500: {529, "overloaded_error"},
		401: {401, "authentication_error"},
		404: {404, "not_found_error"},
		400: {400, "invalid_request_error"},
	}
	for in, want := range cases {
		st, typ, _ := mapUpstreamStatus(in, "")
		if st != want[0].(int) || typ != want[1].(string) {
			t.Fatalf("%d → %d/%s", in, st, typ)
		}
	}
}

func TestImageBlockToOpenAIParts(t *testing.T) {
	ar := &AnthropicRequest{
		Model: "x", MaxTokens: 8,
		Messages: []AnthropicMessage{{Role: "user", Content: json.RawMessage(
			`[{"type":"text","text":"see"},{"type":"image","source":{"type":"base64","media_type":"image/png","data":"AAAA"}}]`)}},
	}
	or, _ := TranslateRequest(ar, "m", AdapterSpec{})
	if len(or.Messages) != 1 {
		t.Fatalf("messages=%d", len(or.Messages))
	}
	parts, ok := or.Messages[0].Content.([]OpenAIContentPart)
	if !ok || len(parts) != 2 || parts[1].ImageURL == nil {
		t.Fatalf("content parts missing: %#v", or.Messages[0].Content)
	}
}

func TestRoleCoercedForToolCalls(t *testing.T) {
	ar := &AnthropicRequest{
		Model: "x", MaxTokens: 8,
		Messages: []AnthropicMessage{{Role: "user", Content: json.RawMessage(
			`[{"type":"tool_use","id":"t1","name":"b","input":{}}]`)}},
	}
	or, _ := TranslateRequest(ar, "m", AdapterSpec{})
	if or.Messages[0].Role != "assistant" {
		t.Fatalf("role=%q, OpenAI rejects user+tool_calls", or.Messages[0].Role)
	}
}

func TestToolChoiceMapping(t *testing.T) {
	if got := mapToolChoice(json.RawMessage(`{"type":"any"}`)); got != "required" {
		t.Fatalf("any → %v", got)
	}
	if got := mapToolChoice(json.RawMessage(`{"type":"none"}`)); got != "none" {
		t.Fatalf("none → %v", got)
	}
}
