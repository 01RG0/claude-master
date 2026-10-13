// stream_translator.go — stateful OpenAI SSE → Anthropic SSE translation.
//
// Unlike TranslateStreamChunk (single-chunk, text-only), StreamTranslator keeps
// per-response state across chunks so tool calls stream incrementally:
// content_block_start{tool_use} once per call, then input_json_delta per
// argument fragment, then content_block_stop. Text streams as text_delta.
// Parity: message_start → blocks → message_delta (cumulative usage) →
// message_stop, plus error mapping. Unknown chunks are skipped, never fatal.
package gateway

import (
	"encoding/json"
	"fmt"
	"strconv"
	"strings"
	"sync"
)

// toolStreamState tracks one in-flight tool call block.
type toolStreamState struct {
	blockIndex int
	id         string
	name       string
	started    bool
	argBytes   int
}

// StreamTranslator accumulates one upstream streaming response.
type StreamTranslator struct {
	mu            sync.Mutex
	model         string
	msgID         string
	started       bool
	textStarted   bool
	textStopped   bool
	textIndex     int
	thinkingStarted bool
	thinkingStopped bool
	thinkingIndex   int
	nextIndex     int
	tools         map[int]*toolStreamState // upstream tool index → state
	finished      bool
	finishStop    string
	promptTokens  int
	completionTok int
	cachedTokens  int
}

// NewStreamTranslator creates a translator for one response.
func NewStreamTranslator(model, msgID string) *StreamTranslator {
	if msgID == "" {
		msgID = "msg_gateway_0000"
	}
	return &StreamTranslator{
		model: model, msgID: msgID,
		tools: make(map[int]*toolStreamState),
	}
}

// Translate consumes one parsed OpenAI chunk and returns Anthropic SSE events.
func (t *StreamTranslator) Translate(chunk *StreamChunk) []AnthropicSSEEvent {
	var events []AnthropicSSEEvent
	t.mu.Lock()
	defer t.mu.Unlock()
	if t.finished {
		return nil
	}
	model := chunk.Model
	if model == "" {
		model = t.model
	}
	emit := func(ev AnthropicSSEEvent) { events = append(events, ev) }

	for _, choice := range chunk.Choices {
		if !t.started {
			t.started = true
			emit(AnthropicSSEEvent{"message_start", map[string]interface{}{
				"type": "message_start",
				"message": map[string]interface{}{
					"id": chunkIDOr(chunk.ID, t.msgID), "type": "message",
					"role": "assistant", "model": model,
					"content": []interface{}{},
				},
			}})
		}
		d := choice.Delta
		// Reasoning deltas (OpenAI-style reasoning_content) → Anthropic
		// thinking block. The block opens on first reasoning, streams as
		// thinking_delta, and closes with an emulated signature_delta
		// (never a real Anthropic signature) before text/tools/finish.
		reasoning := d.ReasoningContent
		if reasoning == "" {
			reasoning = d.Reasoning
		}
		if reasoning != "" {
			if !t.thinkingStarted {
				t.thinkingStarted = true
				t.thinkingIndex = t.nextIndex
				t.nextIndex++
				emit(AnthropicSSEEvent{"content_block_start", map[string]interface{}{
					"type": "content_block_start", "index": t.thinkingIndex,
					"content_block": map[string]interface{}{"type": "thinking", "thinking": "", "signature": ""},
				}})
			} else if t.thinkingStopped {
				// Reasoning resumed after a close (e.g. interleaved text):
				// open a fresh thinking block to preserve deltas.
				t.thinkingStopped = false
				t.thinkingStarted = true
				t.thinkingIndex = t.nextIndex
				t.nextIndex++
				emit(AnthropicSSEEvent{"content_block_start", map[string]interface{}{
					"type": "content_block_start", "index": t.thinkingIndex,
					"content_block": map[string]interface{}{"type": "thinking", "thinking": "", "signature": ""},
				}})
			}
			emit(AnthropicSSEEvent{"content_block_delta", map[string]interface{}{
				"type": "content_block_delta", "index": t.thinkingIndex,
				"delta": map[string]interface{}{"type": "thinking_delta", "thinking": reasoning},
			}})
		}
		// Text delta → ensure text block open. Close an open thinking block
		// first so Anthropic order (thinking → text) holds when reasoning
		// streams before content.
		if d.Content != "" {
			if t.thinkingStarted && !t.thinkingStopped {
				t.thinkingStopped = true
				emit(AnthropicSSEEvent{"content_block_delta", map[string]interface{}{
					"type": "content_block_delta", "index": t.thinkingIndex,
					"delta": map[string]interface{}{"type": "signature_delta", "signature": emulatedThinkingSignature},
				}})
				emit(AnthropicSSEEvent{"content_block_stop", map[string]interface{}{
					"type": "content_block_stop", "index": t.thinkingIndex,
				}})
			}
			if !t.textStarted {
				t.textStarted = true
				t.textStopped = false
				t.textIndex = t.nextIndex
				t.nextIndex++
				emit(AnthropicSSEEvent{"content_block_start", map[string]interface{}{
					"type": "content_block_start", "index": t.textIndex,
					"content_block": map[string]interface{}{"type": "text", "text": ""},
				}})
			} else if t.textStopped && reasoning == "" {
				// Text resumed after a stop (e.g. second text span):
				// reopen a fresh text block.
				t.textStopped = false
				t.textStarted = true
				t.textIndex = t.nextIndex
				t.nextIndex++
				emit(AnthropicSSEEvent{"content_block_start", map[string]interface{}{
					"type": "content_block_start", "index": t.textIndex,
					"content_block": map[string]interface{}{"type": "text", "text": ""},
				}})
			}
			emit(AnthropicSSEEvent{"content_block_delta", map[string]interface{}{
				"type": "content_block_delta", "index": t.textIndex,
				"delta": map[string]interface{}{"type": "text_delta", "text": d.Content},
			}})
		}
		// Tool deltas → per-index tool_use blocks with incremental args.
		for _, tc := range d.ToolCalls {
			st, ok := t.tools[tc.Index]
			if !ok {
				st = &toolStreamState{blockIndex: t.nextIndex}
				t.nextIndex++
				t.tools[tc.Index] = st
			}
			if tc.ID != "" {
				st.id = tc.ID
			}
			if tc.Function.Name != "" {
				st.name = tc.Function.Name
			}
			if !st.started && st.name != "" {
				st.started = true
				// Close thinking/text blocks before the first tool block
				// (Anthropic order: thinking → text → tools).
				if t.thinkingStarted && !t.thinkingStopped {
					t.thinkingStopped = true
					emit(AnthropicSSEEvent{"content_block_delta", map[string]interface{}{
						"type": "content_block_delta", "index": t.thinkingIndex,
						"delta": map[string]interface{}{"type": "signature_delta", "signature": emulatedThinkingSignature},
					}})
					emit(AnthropicSSEEvent{"content_block_stop", map[string]interface{}{
						"type": "content_block_stop", "index": t.thinkingIndex,
					}})
				}
				if t.textStarted && !t.textStopped {
					t.textStopped = true
					emit(AnthropicSSEEvent{"content_block_stop", map[string]interface{}{
						"type": "content_block_stop", "index": t.textIndex,
					}})
				}
				emit(AnthropicSSEEvent{"content_block_start", map[string]interface{}{
					"type": "content_block_start", "index": st.blockIndex,
					"content_block": map[string]interface{}{
						"type": "tool_use", "id": toolIDOr(st.id, tc.Index),
						"name": st.name, "input": map[string]interface{}{},
					},
				}})
			}
			if frag := tc.Function.Arguments; frag != "" {
				st.argBytes += len(frag)
				emit(AnthropicSSEEvent{"content_block_delta", map[string]interface{}{
					"type": "content_block_delta", "index": st.blockIndex,
					"delta": map[string]interface{}{"type": "input_json_delta", "partial_json": frag},
				}})
			}
		}
		if choice.FinishReason != nil {
			t.finishStop = mapStop(*choice.FinishReason)
		}
	}
	// Usage trailer some providers send as a final chunk with usage but no choices.
	return events
}

// Finish emits block stops + message_delta + message_stop. usage may carry
// prompt/completion/cached token counts (0 when unknown — never faked).
// The optional fourth argument preserves cache creation tokens
// (cache_creation_input_tokens) when the provider reports them.
func (t *StreamTranslator) Finish(promptTokens, completionTokens, cachedTokens int, cacheCreation ...int) []AnthropicSSEEvent {
	t.mu.Lock()
	defer t.mu.Unlock()
	if t.finished {
		return nil
	}
	t.finished = true
	var events []AnthropicSSEEvent
	if !t.started {
		events = append(events, AnthropicSSEEvent{"message_start", map[string]interface{}{
			"type": "message_start",
			"message": map[string]interface{}{
				"id": t.msgID, "type": "message", "role": "assistant",
				"model": t.model, "content": []interface{}{},
			},
		}})
	}
	if t.thinkingStarted && !t.thinkingStopped {
		t.thinkingStopped = true
		events = append(events,
			AnthropicSSEEvent{"content_block_delta", map[string]interface{}{
				"type": "content_block_delta", "index": t.thinkingIndex,
				"delta": map[string]interface{}{"type": "signature_delta", "signature": emulatedThinkingSignature},
			}},
			AnthropicSSEEvent{"content_block_stop", map[string]interface{}{
				"type": "content_block_stop", "index": t.thinkingIndex,
			}},
		)
	}
	if t.textStarted && !t.textStopped {
		t.textStopped = true
		events = append(events, AnthropicSSEEvent{"content_block_stop", map[string]interface{}{
			"type": "content_block_stop", "index": t.textIndex,
		}})
	}
	// Tool blocks with no args still need start/stop (provider sent call with {}).
	for idx, st := range t.tools {
		if !st.started {
			if t.textStarted && !t.textStopped {
				t.textStopped = true
				events = append(events, AnthropicSSEEvent{"content_block_stop", map[string]interface{}{
					"type": "content_block_stop", "index": t.textIndex,
				}})
			}
			events = append(events, AnthropicSSEEvent{"content_block_start", map[string]interface{}{
				"type": "content_block_start", "index": st.blockIndex,
				"content_block": map[string]interface{}{
					"type": "tool_use", "id": toolIDOr(st.id, idx),
					"name": st.name, "input": map[string]interface{}{},
				},
			}})
		}
		events = append(events, AnthropicSSEEvent{"content_block_stop", map[string]interface{}{
			"type": "content_block_stop", "index": st.blockIndex,
		}})
	}
	stop := t.finishStop
	if stop == "" {
		stop = "end_turn"
	}
	usage := map[string]interface{}{"output_tokens": completionTokens}
	if promptTokens > 0 {
		usage["input_tokens"] = promptTokens
	}
	if cachedTokens > 0 {
		usage["cache_read_input_tokens"] = cachedTokens
	}
	creationTokens := 0
	if len(cacheCreation) > 0 {
		creationTokens = cacheCreation[0]
	}
	if creationTokens > 0 {
		usage["cache_creation_input_tokens"] = creationTokens
	}
	events = append(events,
		AnthropicSSEEvent{"message_delta", map[string]interface{}{
			"type": "message_delta",
			"delta": map[string]interface{}{"stop_reason": stop},
			"usage": usage,
		}},
		AnthropicSSEEvent{"message_stop", map[string]interface{}{"type": "message_stop"}},
	)
	return events
}

// ToolArgs returns accumulated arg sizes (for logging/repair metrics).
func (t *StreamTranslator) ToolArgs() map[int]int {
	t.mu.Lock()
	defer t.mu.Unlock()
	out := make(map[int]int, len(t.tools))
	for k, v := range t.tools {
		out[k] = v.argBytes
	}
	return out
}

func mapStop(s string) string {
	switch s {
	case "tool_calls":
		return "tool_use"
	case "length":
		return "max_tokens"
	case "stop":
		return "end_turn"
	default:
		return "end_turn"
	}
}

func chunkIDOr(id, fallback string) string {
	if id != "" {
		return id
	}
	return fallback
}

func toolIDOr(id string, idx int) string {
	if id != "" {
		return id
	}
	return "call_" + strconv.Itoa(idx)
}

// RepairToolArgsJSON attempts to salvage truncated streamed arguments:
// it closes open braces/quotes so a best-effort object survives. Returns the
// repaired string and whether it parses.
func RepairToolArgsJSON(frag string) (string, bool) {
	s := strings.TrimSpace(frag)
	if s == "" {
		return "{}", true
	}
	var out map[string]interface{}
	if err := json.Unmarshal([]byte(s), &out); err == nil {
		return s, true
	}
	// Close unterminated string then open braces/brackets.
	inStr := false
	esc := false
	depth := []rune{}
	for _, r := range s {
		if esc {
			esc = false
			continue
		}
		if r == '\\' && inStr {
			esc = true
			continue
		}
		if r == '"' {
			inStr = !inStr
			continue
		}
		if inStr {
			continue
		}
		switch r {
		case '{', '[':
			depth = append(depth, r)
		case '}':
			if len(depth) > 0 && depth[len(depth)-1] == '{' {
				depth = depth[:len(depth)-1]
			}
		case ']':
			if len(depth) > 0 && depth[len(depth)-1] == '[' {
				depth = depth[:len(depth)-1]
			}
		}
	}
	if inStr {
		s += "\""
	}
	for i := len(depth) - 1; i >= 0; i-- {
		if depth[i] == '{' {
			s += "}"
		} else {
			s += "]"
		}
	}
	var repaired map[string]interface{}
	if err := json.Unmarshal([]byte(s), &repaired); err != nil {
		return frag, false
	}
	_ = repaired
	_ = fmt.Sprintf
	return s, true
}
