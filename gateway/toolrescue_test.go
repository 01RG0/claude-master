// toolrescue_test.go — Tier-2 tool-call rescue unit tests (no live API calls).
package gateway

import (
	"encoding/json"
	"strings"
	"testing"
)

func mustParseObject(t *testing.T, s string) map[string]interface{} {
	t.Helper()
	var m map[string]interface{}
	if err := json.Unmarshal([]byte(s), &m); err != nil {
		t.Fatalf("expected valid JSON object, got %q: %v", s, err)
	}
	return m
}

func TestRescueExactPassthrough(t *testing.T) {
	raw := `{"location":"Paris","units":"metric"}`
	got, ok, tier := RescueToolArgs(raw, []string{"location", "units"})
	if !ok || tier != "exact" {
		t.Fatalf("ok=%v tier=%q want ok=true tier=exact (got %q)", ok, tier, got)
	}
	m := mustParseObject(t, got)
	if m["location"] != "Paris" || m["units"] != "metric" {
		t.Fatalf("content changed: %q", got)
	}
}

func TestRescueTruncatedClose(t *testing.T) {
	raw := `{"a": 1, "b": "x`
	got, ok, tier := RescueToolArgs(raw, nil)
	if !ok || tier != "closed" {
		t.Fatalf("ok=%v tier=%q want closed (got %q)", ok, tier, got)
	}
	m := mustParseObject(t, got)
	if m["a"] != float64(1) || m["b"] != "x" {
		t.Fatalf("truncated close lost keys: %q", got)
	}
}

func TestRescueFencedExtract(t *testing.T) {
	raw := "here you go:\n```json\n{\"city\": \"Paris\"}\n```"
	got, ok, tier := RescueToolArgs(raw, nil)
	if !ok || tier != "rescued" {
		t.Fatalf("ok=%v tier=%q want rescued (got %q)", ok, tier, got)
	}
	if m := mustParseObject(t, got); m["city"] != "Paris" {
		t.Fatalf("fenced extract wrong: %q", got)
	}
}

func TestRescueNarratedExtract(t *testing.T) {
	raw := `Sure! Calling now with {"city":"Paris","n":1} hope that helps.`
	got, ok, tier := RescueToolArgs(raw, nil)
	if !ok || tier != "rescued" {
		t.Fatalf("ok=%v tier=%q want rescued (got %q)", ok, tier, got)
	}
	if m := mustParseObject(t, got); m["city"] != "Paris" {
		t.Fatalf("narrated extract wrong: %q", got)
	}
}

func TestRescueFuzzyRename(t *testing.T) {
	raw := `{"locaton":"Paris","units":"metric"}`
	got, ok, tier := RescueToolArgs(raw, []string{"location", "units"})
	if !ok || tier != "fuzzy" {
		t.Fatalf("ok=%v tier=%q want fuzzy (got %q)", ok, tier, got)
	}
	m := mustParseObject(t, got)
	if m["location"] != "Paris" {
		t.Fatalf("fuzzy rename missed: %q", got)
	}
	if _, bad := m["locaton"]; bad {
		t.Fatalf("old key survived: %q", got)
	}
}

func TestRescueUnknownKeysKeptWhenNoSchema(t *testing.T) {
	raw := `{"zzz_custom_key":1}`
	got, ok, tier := RescueToolArgs(raw, nil)
	if !ok {
		t.Fatalf("should keep unknown keys without schema: %q tier=%q", got, tier)
	}
	if m := mustParseObject(t, got); m["zzz_custom_key"] != float64(1) {
		t.Fatalf("unknown key dropped: %q", got)
	}
}

func TestRescueGarbageFails(t *testing.T) {
	for _, raw := range []string{`{{{`, `not json at all (((`, "```\nnope\n```"} {
		got, ok, tier := RescueToolArgs(raw, []string{"a"})
		if ok || tier != "fail" {
			t.Fatalf("raw=%q: want ok=false tier=fail, got ok=%v tier=%q out=%q", raw, ok, tier, got)
		}
	}
}

func TestRescueIDPassthrough(t *testing.T) {
	or := &OpenAIChatResponse{ID: "chat_1", Model: "m"}
	or.Choices = []struct {
		Index        int                   `json:"index"`
		Message      OpenAIResponseMessage `json:"message"`
		FinishReason string                `json:"finish_reason"`
	}{{
		Message: OpenAIResponseMessage{
			Role: "assistant",
			ToolCalls: []OpenAIToolCall{{
				ID:   "call_123",
				Type: "function",
				Function: OpenAIToolFunction{
					Name:      "get_weather",
					Arguments: "Result: {\"locaton\":\"Paris\"} done",
				},
			}},
		},
		FinishReason: "tool_calls",
	}}
	tools := []AnthropicTool{{
		Name:        "get_weather",
		InputSchema: json.RawMessage(`{"type":"object","properties":{"location":{"type":"string"}}}`),
	}}
	ar := TranslateResponseWithTools(or, "m", tools)
	if len(ar.Content) != 1 || ar.Content[0].Type != "tool_use" {
		t.Fatalf("content=%#v", ar.Content)
	}
	if ar.Content[0].ID != "call_123" {
		t.Fatalf("id lost: %q", ar.Content[0].ID)
	}
	var m map[string]interface{}
	if err := json.Unmarshal(ar.Content[0].Input, &m); err != nil {
		t.Fatalf("input not JSON: %s (%v)", ar.Content[0].Input, err)
	}
	if m["location"] != "Paris" {
		t.Fatalf("fuzzy rescue not applied in response path: %s", ar.Content[0].Input)
	}
}

func TestRescueEmptyYieldsEmptyObject(t *testing.T) {
	got, ok, tier := RescueToolArgs("   ", nil)
	if !ok || got != "{}" || tier != "exact" {
		t.Fatalf("empty: got %q ok=%v tier=%q", got, ok, tier)
	}
}

func TestRescueFarMisspellingNotRenamed(t *testing.T) {
	raw := `{"xyzabc":"1"}`
	got, ok, tier := RescueToolArgs(raw, []string{"location"})
	if !ok {
		t.Fatalf("should not fail distant keys: %q", got)
	}
	if tier == "fuzzy" {
		t.Fatalf("distance>2 must not trigger fuzzy: %q", got)
	}
	if m := mustParseObject(t, got); m["xyzabc"] != "1" {
		t.Fatalf("distant key altered: %q", got)
	}
}

func TestTranslateResponseBackwardCompat(t *testing.T) {
	or := &OpenAIChatResponse{ID: "c", Model: "m"}
	or.Choices = []struct {
		Index        int                   `json:"index"`
		Message      OpenAIResponseMessage `json:"message"`
		FinishReason string                `json:"finish_reason"`
	}{{
		Message: OpenAIResponseMessage{
			Role: "assistant",
			ToolCalls: []OpenAIToolCall{{
				ID: "call_9", Type: "function",
				Function: OpenAIToolFunction{Name: "echo", Arguments: `{"w":"b"}`},
			}},
		},
		FinishReason: "tool_calls",
	}}
	ar := TranslateResponse(or, "m")
	if len(ar.Content) != 1 || ar.Content[0].ID != "call_9" {
		t.Fatalf("legacy TranslateResponse broke id passthrough: %#v", ar.Content)
	}
	if !strings.Contains(string(ar.Content[0].Input), `"w"`) {
		t.Fatalf("input lost: %s", ar.Content[0].Input)
	}
}
