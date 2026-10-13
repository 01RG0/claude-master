// thinking_test.go — unit tests for thinking/reasoning handling (no live calls).
package gateway

import (
	"encoding/json"
	"strings"
	"testing"
)

func mustAnthropicThinking(t *testing.T, body string) *AnthropicRequest {
	t.Helper()
	var ar AnthropicRequest
	if err := json.Unmarshal([]byte(body), &ar); err != nil {
		t.Fatalf("unmarshal request: %v", err)
	}
	return &ar
}

func upstreamText(t *testing.T, or *OpenAIRequest) string {
	t.Helper()
	if len(or.Messages) == 0 {
		t.Fatal("no upstream messages")
		return ""
	}
	switch c := or.Messages[0].Content.(type) {
	case string:
		return c
	case []OpenAIContentPart:
		var parts []string
		for _, p := range c {
			if p.Type == "text" {
				parts = append(parts, p.Text)
			}
		}
		return strings.Join(parts, "\n")
	default:
		b, _ := json.Marshal(or.Messages[0].Content)
		return string(b)
	}
}

// 1. Thinking input becomes a compact redacted marker, still noted as dropped.
func TestThinkingInputBecomesRedactedMarker(t *testing.T) {
	ar := mustAnthropicThinking(t, `{
		"model":"m","max_tokens":8,
		"messages":[{"role":"user","content":[
			{"type":"thinking","thinking":"secret plan","signature":"SIG-ABC"},
			{"type":"text","text":"hello"}
		]}]
	}`)
	or, notes := TranslateRequest(ar, "m", AdapterSpec{})
	if len(notes) == 0 {
		t.Fatal("expected dropped-note for thinking block")
	}
	found := false
	for _, n := range notes {
		if strings.Contains(n, "thinking") {
			found = true
		}
	}
	if !found {
		t.Fatalf("dropped notes missing thinking entry: %v", notes)
	}
	text := upstreamText(t, or)
	if !strings.Contains(text, thinkingRedactedMarker) {
		t.Fatalf("upstream text missing redacted marker: %q", text)
	}
	if strings.Contains(text, "secret plan") {
		t.Fatalf("thinking content leaked upstream: %q", text)
	}
}

// 2. Order preserved: text + thinking + text keeps sequence.
func TestThinkingOrderPreserved(t *testing.T) {
	ar := mustAnthropicThinking(t, `{
		"model":"m","max_tokens":8,
		"messages":[{"role":"user","content":[
			{"type":"text","text":"hello"},
			{"type":"thinking","thinking":"inner","signature":"S1"},
			{"type":"text","text":"world"}
		]}]
	}`)
	or, _ := TranslateRequest(ar, "m", AdapterSpec{})
	text := upstreamText(t, or)
	hi := strings.Index(text, "hello")
	mi := strings.Index(text, thinkingRedactedMarker)
	wi := strings.Index(text, "world")
	if hi < 0 || mi < 0 || wi < 0 {
		t.Fatalf("order parts missing: %q", text)
	}
	if !(hi < mi && mi < wi) {
		t.Fatalf("order not preserved: %q", text)
	}
}

// 3. Multi-turn thinking chains don't silently vanish.
func TestThinkingMultiTurnChainPreserved(t *testing.T) {
	ar := mustAnthropicThinking(t, `{
		"model":"m","max_tokens":8,
		"messages":[
			{"role":"user","content":[{"type":"thinking","thinking":"t1","signature":"S1"},{"type":"text","text":"first"}]},
			{"role":"assistant","content":[{"type":"thinking","thinking":"t2","signature":"S2"},{"type":"text","text":"second"}]}
		]
	}`)
	or, notes := TranslateRequest(ar, "m", AdapterSpec{})
	if len(or.Messages) != 2 {
		t.Fatalf("messages=%d want 2", len(or.Messages))
	}
	markers := 0
	for _, m := range or.Messages {
		b, _ := json.Marshal(m)
		markers += strings.Count(string(b), thinkingRedactedMarker)
		if strings.Contains(string(b), "t1") && strings.Contains(string(b), `"thinking"`) {
			t.Fatalf("raw thinking leaked: %s", b)
		}
	}
	if markers != 2 {
		t.Fatalf("expected 2 redacted markers across turns, got %d", markers)
	}
	if len(notes) < 2 {
		t.Fatalf("expected >=2 dropped notes for chain, got %v", notes)
	}
}

// 4. `thinking` request param stays accepted-but-not-forwarded.
func TestThinkingParamAcceptedNotForwarded(t *testing.T) {
	ar := mustAnthropicThinking(t, `{
		"model":"m","max_tokens":8,
		"thinking":{"type":"enabled","budget_tokens":1000},
		"messages":[{"role":"user","content":"hi"}]
	}`)
	or, notes := TranslateRequest(ar, "m", AdapterSpec{})
	found := false
	for _, n := range notes {
		if strings.Contains(n, "thinking config accepted but not forwarded") {
			found = true
		}
	}
	if !found {
		t.Fatalf("thinking param note missing: %v", notes)
	}
	b, _ := json.Marshal(or)
	if strings.Contains(string(b), "budget_tokens") {
		t.Fatalf("thinking param forwarded upstream: %s", b)
	}
}

// 5. Signature strings never forwarded upstream.
func TestSignatureNeverForwarded(t *testing.T) {
	ar := mustAnthropicThinking(t, `{
		"model":"m","max_tokens":8,
		"messages":[{"role":"assistant","content":[
			{"type":"thinking","thinking":"plan","signature":"TOP-SECRET-SIG-12345"},
			{"type":"text","text":"answer"}
		]}]
	}`)
	or, _ := TranslateRequest(ar, "m", AdapterSpec{})
	b, _ := json.Marshal(or)
	if strings.Contains(string(b), "TOP-SECRET-SIG-12345") {
		t.Fatalf("signature leaked upstream: %s", b)
	}
	if strings.Contains(string(b), `"signature"`) {
		t.Fatalf("signature field forwarded upstream: %s", b)
	}
}

// 6. Stream: reasoning_content deltas emit thinking start/delta.
func TestStreamReasoningEmitsThinkingDelta(t *testing.T) {
	tr := NewStreamTranslator("m", "msg_think_1")
	ch := &StreamChunk{ID: "c", Model: "m", Choices: []StreamChoice{{
		Delta: StreamDelta{ReasoningContent: "let me think"},
	}}}
	evs := tr.Translate(ch)
	var starts, deltas int
	for _, e := range evs {
		b, _ := json.Marshal(e.Data)
		s := string(b)
		if e.Event == "content_block_start" && strings.Contains(s, `"thinking"`) {
			starts++
		}
		if e.Event == "content_block_delta" && strings.Contains(s, "thinking_delta") {
			deltas++
			if !strings.Contains(s, "let me think") {
				t.Fatalf("thinking_delta missing text: %s", s)
			}
		}
	}
	if starts != 1 || deltas != 1 {
		t.Fatalf("starts=%d deltas=%d want 1/1", starts, deltas)
	}
}

// 7. Stream: thinking closes with signature_delta before text; order holds.
func TestStreamThinkingThenTextOrder(t *testing.T) {
	tr := NewStreamTranslator("m", "msg_think_2")
	evs := tr.Translate(&StreamChunk{ID: "c", Model: "m", Choices: []StreamChoice{{
		Delta: StreamDelta{ReasoningContent: "reasoning-part"},
	}}})
	evs = append(evs, tr.Translate(&StreamChunk{ID: "c", Model: "m", Choices: []StreamChoice{{
		Delta: StreamDelta{Content: "final answer"},
	}}})...)
	fin := tr.Finish(10, 5, 0)
	evs = append(evs, fin...)

	var seq []string
	for _, e := range evs {
		b, _ := json.Marshal(e.Data)
		s := string(b)
		switch {
		case e.Event == "content_block_start" && strings.Contains(s, `"thinking"`):
			seq = append(seq, "think_start")
		case e.Event == "content_block_delta" && strings.Contains(s, "thinking_delta"):
			seq = append(seq, "think_delta")
		case strings.Contains(s, "signature_delta"):
			seq = append(seq, "sig_delta")
			if !strings.Contains(s, emulatedThinkingSignature) {
				t.Fatalf("signature_delta missing emulated marker: %s", s)
			}
		case e.Event == "content_block_start" && strings.Contains(s, `"text"`):
			seq = append(seq, "text_start")
		case strings.Contains(s, "text_delta"):
			seq = append(seq, "text_delta")
		}
	}
	joined := strings.Join(seq, ",")
	for _, want := range []string{"think_start", "think_delta", "sig_delta", "text_start", "text_delta"} {
		if !strings.Contains(joined, want) {
			t.Fatalf("sequence missing %s: %s", want, joined)
		}
	}
	// Order: thinking must precede text, signature before text start.
	tsi := strings.Index(joined, "think_start")
	sdi := strings.Index(joined, "sig_delta")
	txti := strings.Index(joined, "text_start")
	if !(tsi < sdi && sdi < txti) {
		t.Fatalf("bad order (think->sig->text required): %s", joined)
	}
}

// 8. Stream Finish preserves cache creation field alongside cache read.
func TestStreamFinishPreservesCacheCreation(t *testing.T) {
	tr := NewStreamTranslator("m", "msg_cache")
	fin := tr.Finish(10, 5, 2, 7)
	var md string
	for _, e := range fin {
		if e.Event == "message_delta" {
			b, _ := json.Marshal(e.Data)
			md = string(b)
		}
	}
	if !strings.Contains(md, "cache_read_input_tokens") {
		t.Fatalf("missing cache_read: %s", md)
	}
	if !strings.Contains(md, "cache_creation_input_tokens") {
		t.Fatalf("missing cache_creation: %s", md)
	}
	var parsed struct {
		Usage map[string]int `json:"usage"`
	}
	// find the message_delta event and unmarshal its data
	for _, e := range fin {
		if e.Event == "message_delta" {
			b, _ := json.Marshal(e.Data)
			if err := json.Unmarshal(b, &parsed); err != nil {
				t.Fatal(err)
			}
		}
	}
	if parsed.Usage["cache_creation_input_tokens"] != 7 {
		t.Fatalf("creation=%d want 7 (%v)", parsed.Usage["cache_creation_input_tokens"], parsed.Usage)
	}
	if parsed.Usage["cache_read_input_tokens"] != 2 {
		t.Fatalf("read=%d want 2 (%v)", parsed.Usage["cache_read_input_tokens"], parsed.Usage)
	}
	// Backward compat: 3-arg Finish still works and omits creation.
	tr2 := NewStreamTranslator("m", "msg_cache2")
	fin2 := tr2.Finish(10, 5, 0)
	for _, e := range fin2 {
		if e.Event == "message_delta" {
			b, _ := json.Marshal(e.Data)
			if strings.Contains(string(b), "cache_creation_input_tokens") {
				t.Fatalf("3-arg Finish must not fabricate creation: %s", b)
			}
		}
	}
}

// 9. Non-stream: reasoning_content maps to thinking block first.
func TestNonStreamReasoningMapsToThinking(t *testing.T) {
	or := &OpenAIChatResponse{ID: "chat_1", Model: "m"}
	or.Choices = []struct {
		Index        int                   `json:"index"`
		Message      OpenAIResponseMessage `json:"message"`
		FinishReason string                `json:"finish_reason"`
	}{{
		Message: OpenAIResponseMessage{
			Role:             "assistant",
			Content:          "hello",
			ReasoningContent: "internal reasoning trace",
		},
		FinishReason: "stop",
	}}
	ar := TranslateResponse(or, "m")
	if len(ar.Content) < 2 {
		t.Fatalf("expected thinking+text, got %#v", ar.Content)
	}
	if ar.Content[0].Type != "thinking" {
		t.Fatalf("first block must be thinking, got %q", ar.Content[0].Type)
	}
	if ar.Content[0].Thinking != "internal reasoning trace" {
		t.Fatalf("thinking text wrong: %q", ar.Content[0].Thinking)
	}
	if ar.Content[1].Type != "text" || ar.Content[1].Text != "hello" {
		t.Fatalf("second block must be text hello: %#v", ar.Content[1])
	}
}

// 10. Non-stream thinking signature is emulated marker, not a real signature.
func TestNonStreamThinkingSignatureEmulated(t *testing.T) {
	or := &OpenAIChatResponse{ID: "chat_2", Model: "m"}
	or.Choices = []struct {
		Index        int                   `json:"index"`
		Message      OpenAIResponseMessage `json:"message"`
		FinishReason string                `json:"finish_reason"`
	}{{
		Message: OpenAIResponseMessage{
			Role:             "assistant",
			Content:          "done",
			ReasoningContent: "r",
		},
		FinishReason: "stop",
	}}
	ar := TranslateResponse(or, "m")
	if ar.Content[0].Signature != emulatedThinkingSignature {
		t.Fatalf("signature=%q want emulated marker %q", ar.Content[0].Signature, emulatedThinkingSignature)
	}
	if ar.Content[0].Signature == "" {
		t.Fatal("signature must carry emulated marker, not empty-anonymous")
	}
	// Must not look like a real Anthropic signature (opaque crypto blob).
	// Our marker is a fixed human-readable constant.
	if len(ar.Content[0].Signature) > 64 {
		t.Fatalf("emulated signature suspiciously long: %q", ar.Content[0].Signature)
	}
	b, _ := json.Marshal(ar.Content[0])
	if !strings.Contains(string(b), emulatedThinkingSignature) {
		t.Fatalf("marker missing in JSON: %s", b)
	}
}

// 11. Thinking inside rich (image) messages still redacts in order.
func TestThinkingWithImagePreservesMarker(t *testing.T) {
	ar := mustAnthropicThinking(t, `{
		"model":"m","max_tokens":8,
		"messages":[{"role":"user","content":[
			{"type":"text","text":"see"},
			{"type":"image","source":{"type":"base64","media_type":"image/png","data":"AAAA"}},
			{"type":"thinking","thinking":"hmm","signature":"S9"},
			{"type":"text","text":"after"}
		]}]
	}`)
	or, notes := TranslateRequest(ar, "m", AdapterSpec{})
	if len(notes) == 0 {
		t.Fatal("expected dropped note")
	}
	parts, ok := or.Messages[0].Content.([]OpenAIContentPart)
	if !ok {
		t.Fatalf("expected rich parts, got %#v", or.Messages[0].Content)
	}
	foundMarker := false
	for _, p := range parts {
		if p.Type == "text" && strings.Contains(p.Text, thinkingRedactedMarker) {
			foundMarker = true
		}
		if strings.Contains(p.Text, "hmm") && !strings.Contains(p.Text, thinkingRedactedMarker) {
			t.Fatalf("raw thinking leaked in rich part: %q", p.Text)
		}
	}
	if !foundMarker {
		b, _ := json.Marshal(parts)
		t.Fatalf("marker missing in rich parts: %s", b)
	}
}
