// adapter_stream.go — OpenAI SSE chunks → Anthropic SSE events.
package gateway

import "encoding/json"

// StreamChunk is a parsed OpenAI streaming delta chunk.
type StreamChunk struct {
	ID      string         `json:"id"`
	Object  string         `json:"object"`
	Model   string         `json:"model"`
	Choices []StreamChoice `json:"choices"`
}

// StreamChoice is one choice in a streaming chunk.
type StreamChoice struct {
	Index        int         `json:"index"`
	Delta        StreamDelta `json:"delta"`
	FinishReason *string     `json:"finish_reason"`
}

// StreamDelta holds the incremental content in a streaming choice.
type StreamDelta struct {
	Role      string           `json:"role,omitempty"`
	Content   string           `json:"content,omitempty"`
	ToolCalls []OpenAIToolCall `json:"tool_calls,omitempty"`
}

// AnthropicSSEEvent is a single SSE line pair (event + data).
type AnthropicSSEEvent struct {
	Event string
	Data  interface{}
}

// TranslateStreamChunk converts an OpenAI streaming chunk into Anthropic SSE events.
//
// Sequence: message_start → content_block_start → content_block_delta* →
// content_block_stop → message_delta → message_stop
func TranslateStreamChunk(chunk *StreamChunk, isFirst bool) []AnthropicSSEEvent {
	var events []AnthropicSSEEvent

	for _, choice := range chunk.Choices {
		if isFirst {
			events = append(events,
				AnthropicSSEEvent{"message_start", map[string]interface{}{
					"type": "message_start",
					"message": map[string]interface{}{
						"id": chunk.ID, "type": "message", "role": "assistant", "model": chunk.Model,
					},
				}},
				AnthropicSSEEvent{"content_block_start", map[string]interface{}{
					"type": "content_block_start", "index": 0,
					"content_block": map[string]interface{}{"type": "text", "text": ""},
				}},
			)
		}

		if choice.Delta.Content != "" {
			events = append(events, AnthropicSSEEvent{"content_block_delta", map[string]interface{}{
				"type": "content_block_delta", "index": 0,
				"delta": map[string]interface{}{"type": "text_delta", "text": choice.Delta.Content},
			}})
		}

		// Incremental tool_use deltas (simplified: emit tool_use blocks on finish).
		if choice.FinishReason != nil {
			stop := *choice.FinishReason
			anthStop := "end_turn"
			if stop == "tool_calls" {
				anthStop = "tool_use"
			} else if stop == "length" {
				anthStop = "max_tokens"
			}
			events = append(events,
				AnthropicSSEEvent{"content_block_stop", map[string]interface{}{
					"type": "content_block_stop", "index": 0,
				}},
				AnthropicSSEEvent{"message_delta", map[string]interface{}{
					"type":  "message_delta",
					"delta": map[string]interface{}{"stop_reason": anthStop},
				}},
				AnthropicSSEEvent{"message_stop", map[string]interface{}{
					"type": "message_stop",
				}},
			)
		}
	}
	return events
}

// EncodeSSE formats an Anthropic SSE event as wire bytes.
func EncodeSSE(ev AnthropicSSEEvent) []byte {
	data, err := json.Marshal(ev.Data)
	if err != nil {
		return nil
	}
	out := make([]byte, 0, len(ev.Event)+len(data)+16)
	out = append(out, "event: "...)
	out = append(out, ev.Event...)
	out = append(out, '\n')
	out = append(out, "data: "...)
	out = append(out, data...)
	out = append(out, '\n', '\n')
	return out
}
