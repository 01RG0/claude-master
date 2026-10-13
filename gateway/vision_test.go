package gateway

import (
	"encoding/json"
	"strings"
	"testing"
)

// Regression (2026-10-13): Claude Code delivers screenshots/files as
// tool_result blocks containing image blocks. The old translator kept only
// text, so vision silently degraded to "guess from the filename" and the
// conformance/E2E runs produced FALSE PASSES.
func TestToolResultImageBecomesImagePart(t *testing.T) {
	ar := &AnthropicRequest{Model: "m", MaxTokens: 64, Messages: []AnthropicMessage{
		{Role: "user", Content: json.RawMessage(`[{"type":"text","text":"look"}]`)},
		{Role: "assistant", Content: json.RawMessage(`[{"type":"tool_use","id":"t1","name":"read","input":{}}]`)},
		{Role: "user", Content: json.RawMessage(`[{"type":"tool_result","tool_use_id":"t1","content":[
			{"type":"image","source":{"type":"base64","media_type":"image/png","data":"AAA"}}]}]`)},
	}}
	or, notes := TranslateRequest(ar, "m", AdapterSpec{})
	if or == nil {
		t.Fatalf("translate failed: %v", notes)
	}
	var toolMsg *OpenAIMessage
	for i := range or.Messages {
		if or.Messages[i].Role == "tool" {
			toolMsg = &or.Messages[i]
		}
	}
	if toolMsg == nil {
		t.Fatal("no tool message produced")
	}
	parts, ok := toolMsg.Content.([]OpenAIContentPart)
	if !ok {
		t.Fatalf("tool content is %T, want image parts", toolMsg.Content)
	}
	if len(parts) != 1 || parts[0].ImageURL == nil {
		t.Fatalf("image part missing: %#v", parts)
	}
	if parts[0].ImageURL.URL != "data:image/png;base64,AAA" {
		t.Fatalf("image payload mangled: %q", parts[0].ImageURL.URL)
	}
	if toolMsg.ToolCallID != "t1" {
		t.Fatalf("tool_call_id lost: %q", toolMsg.ToolCallID)
	}
}

func TestToolResultTextPlusImageKeepsBoth(t *testing.T) {
	ar := &AnthropicRequest{Model: "m", MaxTokens: 64, Messages: []AnthropicMessage{
		{Role: "user", Content: json.RawMessage(`[{"type":"tool_result","tool_use_id":"t2","content":[
			{"type":"text","text":"caption here"},
			{"type":"image","source":{"type":"url","url":"http://x/y.png"}}]}]`)},
	}}
	or, _ := TranslateRequest(ar, "m", AdapterSpec{})
	parts, ok := or.Messages[0].Content.([]OpenAIContentPart)
	if !ok || len(parts) != 2 {
		t.Fatalf("want text+image parts, got %#v", or.Messages[0].Content)
	}
	if parts[0].Text != "caption here" || parts[1].ImageURL == nil {
		t.Fatalf("parts wrong: %#v", parts)
	}
}

func TestToolResultPlainTextStillString(t *testing.T) {
	ar := &AnthropicRequest{Model: "m", MaxTokens: 32, Messages: []AnthropicMessage{
		{Role: "user", Content: json.RawMessage(`[{"type":"tool_result","tool_use_id":"t3","content":"plain"}]`)},
	}}
	or, _ := TranslateRequest(ar, "m", AdapterSpec{})
	if s, ok := or.Messages[0].Content.(string); !ok || s != "plain" {
		t.Fatalf("plain tool_result must stay a string, got %#v", or.Messages[0].Content)
	}
}

func TestTrafficLogSeesToolResultImages(t *testing.T) {
	ar := &AnthropicRequest{Messages: []AnthropicMessage{
		{Role: "user", Content: json.RawMessage(`[{"type":"tool_result","tool_use_id":"t1","content":[
			{"type":"text","text":"x"},{"type":"image","source":{"type":"url","url":"http://x"}}]}]`)},
	}}
	blocks := messageBlockTypes(ar)
	seen := map[string]bool{}
	for _, b := range blocks {
		seen[b] = true
	}
	if !seen["tool_result/image"] {
		t.Fatalf("traffic log must expose tool_result/image, got %v", blocks)
	}
}

// Regression (2026-10-13): Gemini's OpenAI endpoint rejects image_url parts
// inside tool messages ("Invalid content part type: image_url"), so providers
// that 400 on that shape must downgrade here rather than fail the whole turn.
func TestToolResultImageDowngradeOnGemini(t *testing.T) {
	ar := &AnthropicRequest{Model: "m", MaxTokens: 64, Messages: []AnthropicMessage{
		{Role: "user", Content: json.RawMessage(`[{"type":"text","text":"look"}]`)},
		{Role: "assistant", Content: json.RawMessage(`[{"type":"tool_use","id":"t1","name":"read","input":{}}]`)},
		{Role: "user", Content: json.RawMessage(`[{"type":"tool_result","tool_use_id":"t1","content":[
			{"type":"image","source":{"type":"base64","media_type":"image/png","data":"AAA"}}]}]`)},
	}}

	// default: keep image parts
	or, notes := TranslateRequest(ar, "m", AdapterSpec{})
	if or == nil {
		t.Fatalf("translate failed: %v", notes)
	}
	parts, ok := or.Messages[2].Content.([]OpenAIContentPart)
	if !ok || len(parts) != 1 || parts[0].ImageURL == nil {
		t.Fatalf("default should keep image part, got %#v", or.Messages[2].Content)
	}

	// gemini-style: downgrade to text placeholder, never 400
	or2, notes2 := TranslateRequest(ar, "m", AdapterSpec{ToolImages: "text"})
	if or2 == nil {
		t.Fatalf("translate2 failed: %v", notes2)
	}
	if s, ok := or2.Messages[2].Content.(string); !ok || s == "" {
		t.Fatalf("downgrade should yield a string content, got %#v", or2.Messages[2].Content)
	}
	found := false
	for _, n := range notes2 {
		if strings.Contains(n, "tool_result image downgraded") {
			found = true
		}
	}
	if !found {
		t.Fatalf("expected downgrade note, got %v", notes2)
	}
}
