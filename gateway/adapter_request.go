// adapter_request.go — Anthropic /v1/messages ↔ OpenAI chat.completions request translation.
//
// Concept attribution (MIT): BerriAI/litellm anthropic transformation; Portkey-AI/gateway.
// Clean-room Go reimplementation — no source copied.
package gateway

import (
	"encoding/json"
	"fmt"
	"strings"
)

// AnthropicRequest is the body of POST /v1/messages.
type AnthropicRequest struct {
	Model         string                 `json:"model"`
	Messages      []AnthropicMessage     `json:"messages"`
	System        json.RawMessage        `json:"system,omitempty"`
	MaxTokens     int                    `json:"max_tokens,omitempty"`
	Stream        bool                   `json:"stream,omitempty"`
	Tools         []AnthropicTool        `json:"tools,omitempty"`
	ToolChoice    json.RawMessage        `json:"tool_choice,omitempty"`
	Thinking      json.RawMessage        `json:"thinking,omitempty"`
	Temperature   *float64               `json:"temperature,omitempty"`
	TopP          *float64               `json:"top_p,omitempty"`
	TopK          *int                   `json:"top_k,omitempty"`
	StopSequences []string               `json:"stop_sequences,omitempty"`
	Metadata      map[string]interface{} `json:"metadata,omitempty"`
}

// PrivacyClass extracts the "privacy_class" field from metadata if present.
func (r *AnthropicRequest) PrivacyClass() PrivacyClass {
	if r.Metadata == nil {
		return PrivacyClassPublic
	}
	v, ok := r.Metadata["privacy_class"]
	if !ok {
		return PrivacyClassPublic
	}
	s, _ := v.(string)
	if strings.ToLower(s) == string(PrivacyClassInternal) {
		return PrivacyClassInternal
	}
	return PrivacyClassPublic
}

// AnthropicMessage is a single turn in the conversation.
type AnthropicMessage struct {
	Role    string          `json:"role"`
	Content json.RawMessage `json:"content"`
}

// ContentBlock is a typed block inside a message's content array.
type ContentBlock struct {
	Type         string          `json:"type"`
	Text         string          `json:"text,omitempty"`
	ID           string          `json:"id,omitempty"`
	Name         string          `json:"name,omitempty"`
	Input        json.RawMessage `json:"input,omitempty"`
	ToolUseID    string          `json:"tool_use_id,omitempty"`
	Content      json.RawMessage `json:"content,omitempty"`
	Source       json.RawMessage `json:"source,omitempty"`       // image/document source
	CacheControl json.RawMessage `json:"cache_control,omitempty"` // accepted; passed only to native providers
	Thinking     string          `json:"thinking,omitempty"`      // thinking block text (not sent upstream)
	Signature    string          `json:"signature,omitempty"`     // integrity; round-tripped client-side only
}

// AnthropicTool describes a tool in the Anthropic format.
type AnthropicTool struct {
	Name         string          `json:"name"`
	Description  string          `json:"description,omitempty"`
	InputSchema  json.RawMessage `json:"input_schema,omitempty"`
	CacheControl json.RawMessage `json:"cache_control,omitempty"`
}

// OpenAIRequest is the body of POST /v1/chat/completions.
type OpenAIRequest struct {
	Model       string          `json:"model"`
	Messages    []OpenAIMessage `json:"messages"`
	MaxTokens   int             `json:"max_tokens,omitempty"`
	Stream      bool            `json:"stream,omitempty"`
	Tools       []OpenAITool    `json:"tools,omitempty"`
	ToolChoice  interface{}     `json:"tool_choice,omitempty"`
	Temperature *float64        `json:"temperature,omitempty"`
	TopP        *float64        `json:"top_p,omitempty"`
	Stop        []string        `json:"stop,omitempty"`
}

// OpenAIContentPart is one element of a multi-part message (vision).
type OpenAIContentPart struct {
	Type     string                 `json:"type"`
	Text     string                 `json:"text,omitempty"`
	ImageURL *OpenAIImageURL        `json:"image_url,omitempty"`
}

// OpenAIImageURL carries a vision payload.
type OpenAIImageURL struct {
	URL string `json:"url"`
}

// OpenAIMessage is one chat turn in OpenAI format.
type OpenAIMessage struct {
	Role       string           `json:"role"`
	Content    interface{}      `json:"content,omitempty"`
	ToolCalls  []OpenAIToolCall `json:"tool_calls,omitempty"`
	ToolCallID string           `json:"tool_call_id,omitempty"`
	Name       string           `json:"name,omitempty"`
}

// OpenAIToolCall represents a model-initiated tool invocation.
type OpenAIToolCall struct {
	ID       string             `json:"id"`
	Type     string             `json:"type"`
	Function OpenAIToolFunction `json:"function"`
}

// OpenAIToolFunction is the function part of an OpenAI tool call.
type OpenAIToolFunction struct {
	Name      string `json:"name"`
	Arguments string `json:"arguments"`
}

// OpenAITool describes a function tool in OpenAI format.
type OpenAITool struct {
	Type     string           `json:"type"`
	Function OpenAIToolSchema `json:"function"`
}

// OpenAIToolSchema is the function schema in an OpenAI tool definition.
type OpenAIToolSchema struct {
	Name        string          `json:"name"`
	Description string          `json:"description,omitempty"`
	Parameters  json.RawMessage `json:"parameters,omitempty"`
}

func strPtr(s string) *string { return &s }

// TranslateRequest converts an AnthropicRequest to an OpenAIRequest.
// blocksDropped counts content that cannot be represented upstream (thinking
// signatures, server-side tools) — the caller logs the count, never content.
func TranslateRequest(ar *AnthropicRequest, upstreamModel string) (*OpenAIRequest, []string) {
	var notes []string
	var msgs []OpenAIMessage

	if ar.System != nil && len(ar.System) > 0 && string(ar.System) != "null" {
		text, err := extractSystemText(ar.System)
		if err == nil && text != "" {
			msgs = append(msgs, OpenAIMessage{Role: "system", Content: text})
		}
	}

	for _, am := range ar.Messages {
		converted, dropped, err := translateMessage(am)
		if err != nil {
			return nil, []string{"translating message role=" + am.Role + ": " + err.Error()}
		}
		notes = append(notes, dropped...)
		msgs = append(msgs, converted...)
	}

	var tools []OpenAITool
	for _, t := range ar.Tools {
		tools = append(tools, OpenAITool{
			Type: "function",
			Function: OpenAIToolSchema{
				Name:        t.Name,
				Description: t.Description,
				Parameters:  t.InputSchema,
			},
		})
	}

	or := &OpenAIRequest{
		Model:     upstreamModel,
		Messages:  msgs,
		MaxTokens: ar.MaxTokens,
		Stream:    ar.Stream,
		Tools:     tools,
	}
	or.Temperature = ar.Temperature
	or.TopP = ar.TopP
	or.Stop = ar.StopSequences
	if tc := mapToolChoice(ar.ToolChoice); tc != nil {
		or.ToolChoice = tc
	}
	// Thinking is never sent upstream (no OpenAI equivalent at this layer);
	// providers with native reasoning are handled by capability config.
	if len(ar.Thinking) > 0 && string(ar.Thinking) != "null" && string(ar.Thinking) != "{}" {
		notes = append(notes, "thinking config accepted but not forwarded to OpenAI-dialect upstream (emulated client-side)")
	}
	return or, notes
}

// mapToolChoice converts Anthropic tool_choice to the OpenAI equivalent.
func mapToolChoice(raw json.RawMessage) interface{} {
	if len(raw) == 0 || string(raw) == "null" {
		return nil
	}
	var m map[string]interface{}
	if err := json.Unmarshal(raw, &m); err != nil {
		return nil
	}
	t, _ := m["type"].(string)
	switch t {
	case "auto":
		return "auto"
	case "any":
		return "required"
	case "none":
		return "none"
	case "tool":
		if name, _ := m["name"].(string); name != "" {
			return map[string]interface{}{"type": "function", "function": map[string]string{"name": name}}
		}
	}
	return nil
}

func extractSystemText(raw json.RawMessage) (string, error) {
	var s string
	if err := json.Unmarshal(raw, &s); err == nil {
		return s, nil
	}
	var blocks []ContentBlock
	if err := json.Unmarshal(raw, &blocks); err != nil {
		return "", err
	}
	var parts []string
	for _, b := range blocks {
		if b.Type == "text" && b.Text != "" {
			parts = append(parts, b.Text)
		}
	}
	return strings.Join(parts, "\n"), nil
}

func translateMessage(am AnthropicMessage) ([]OpenAIMessage, []string, error) {
	role := am.Role
	var dropped []string

	var strContent string
	if err := json.Unmarshal(am.Content, &strContent); err == nil {
		return []OpenAIMessage{{Role: role, Content: strContent}}, nil, nil
	}

	var blocks []ContentBlock
	if err := json.Unmarshal(am.Content, &blocks); err != nil {
		return nil, nil, fmt.Errorf("unmarshalling content: %w", err)
	}

	var out []OpenAIMessage
	var textParts []string
	var richParts []OpenAIContentPart
	var toolCalls []OpenAIToolCall

	flush := func() {
		if len(textParts) == 0 && len(richParts) == 0 && len(toolCalls) == 0 {
			return
		}
		out = append(out, flushAssistant(role, textParts, richParts, toolCalls))
		textParts = nil
		richParts = nil
		toolCalls = nil
	}

	for _, b := range blocks {
		switch b.Type {
		case "text":
			if len(richParts) > 0 {
				richParts = append(richParts, OpenAIContentPart{Type: "text", Text: b.Text})
			} else {
				textParts = append(textParts, b.Text)
			}
		case "image":
			part, note := imageBlockToPart(b)
			if note != "" {
				dropped = append(dropped, note)
			}
			if part != nil {
				if len(textParts) > 0 {
					for _, t := range textParts {
						richParts = append(richParts, OpenAIContentPart{Type: "text", Text: t})
					}
					textParts = nil
				}
				richParts = append(richParts, *part)
			}
		case "document":
			dropped = append(dropped, "document block converted to text placeholder (no upstream document API at this layer)")
			if len(richParts) > 0 {
				richParts = append(richParts, OpenAIContentPart{Type: "text", Text: "[document omitted by gateway]"})
			} else {
				textParts = append(textParts, "[document omitted by gateway]")
			}
		case "thinking":
			dropped = append(dropped, "thinking input block not forwarded upstream (signatures stay client-side)")
		case "server_tool_use", "web_search_tool_result":
			dropped = append(dropped, b.Type+" block not forwarded upstream (server-side tools are gateway-emulated, see docs)")
		case "tool_use":
			args := "{}"
			if b.Input != nil {
				args = string(b.Input)
			}
			toolCalls = append(toolCalls, OpenAIToolCall{
				ID:   b.ID,
				Type: "function",
				Function: OpenAIToolFunction{
					Name:      b.Name,
					Arguments: args,
				},
			})
		case "tool_result":
			flush()
			content := extractToolResultContent(b.Content)
			out = append(out, OpenAIMessage{
				Role:       "tool",
				ToolCallID: b.ToolUseID,
				Content:    content,
			})
		default:
			dropped = append(dropped, "unknown block type "+b.Type+" dropped")
		}
	}

	flush()
	if len(out) == 0 {
		out = append(out, OpenAIMessage{Role: role, Content: ""})
	}
	return out, dropped, nil
}

// imageBlockToPart converts an Anthropic image/document source to an OpenAI
// image_url part. Returns (nil, note) when the block carries no usable bytes.
func imageBlockToPart(b ContentBlock) (*OpenAIContentPart, string) {
	if len(b.Source) == 0 {
		return nil, "image block without source dropped"
	}
	var src struct {
		Type      string `json:"type"`
		MediaType string `json:"media_type"`
		Data      string `json:"data"`
		URL       string `json:"url"`
	}
	if err := json.Unmarshal(b.Source, &src); err != nil {
		return nil, "unparsable image source dropped"
	}
	switch src.Type {
	case "base64":
		mt := src.MediaType
		if mt == "" {
			mt = "image/jpeg"
		}
		return &OpenAIContentPart{Type: "image_url",
			ImageURL: &OpenAIImageURL{URL: "data:" + mt + ";base64," + src.Data}}, ""
	case "url":
		return &OpenAIContentPart{Type: "image_url",
			ImageURL: &OpenAIImageURL{URL: src.URL}}, ""
	default:
		return nil, "image source type " + src.Type + " dropped"
	}
}

func flushAssistant(role string, textParts []string, richParts []OpenAIContentPart, toolCalls []OpenAIToolCall) OpenAIMessage {
	// OpenAI rejects role=user carrying tool_calls: coerce to assistant.
	if role != "assistant" && role != "system" && len(toolCalls) > 0 {
		role = "assistant"
	}
	m := OpenAIMessage{Role: role}
	if len(richParts) > 0 {
		if len(textParts) > 0 {
			joined := strings.Join(textParts, "\n")
			richParts = append([]OpenAIContentPart{{Type: "text", Text: joined}}, richParts...)
		}
		m.Content = richParts
	} else if len(textParts) > 0 {
		m.Content = strings.Join(textParts, "\n")
	} else {
		m.Content = nil
	}
	if len(toolCalls) > 0 {
		m.ToolCalls = toolCalls
	}
	return m
}

func extractToolResultContent(raw json.RawMessage) string {
	if raw == nil {
		return ""
	}
	var s string
	if err := json.Unmarshal(raw, &s); err == nil {
		return s
	}
	var blocks []ContentBlock
	if err := json.Unmarshal(raw, &blocks); err == nil {
		var parts []string
		for _, b := range blocks {
			if b.Type == "text" {
				parts = append(parts, b.Text)
			}
		}
		return strings.Join(parts, "\n")
	}
	return string(raw)
}

// OpenAIChatResponse is a non-streaming chat.completions response.
type OpenAIChatResponse struct {
	ID      string `json:"id"`
	Model   string `json:"model"`
	Choices []struct {
		Index        int `json:"index"`
		Message      OpenAIResponseMessage `json:"message"`
		FinishReason string `json:"finish_reason"`
	} `json:"choices"`
	Usage *struct {
		PromptTokens     int `json:"prompt_tokens"`
		CompletionTokens int `json:"completion_tokens"`
		CachedTokens     int `json:"cached_tokens"`
		PromptDetails    *struct {
			CachedTokens int `json:"cached_tokens"`
		} `json:"prompt_tokens_details,omitempty"`
	} `json:"usage,omitempty"`
}

// OpenAIResponseMessage is an assistant message in a chat response.
type OpenAIResponseMessage struct {
	Role      string           `json:"role"`
	Content   interface{}      `json:"content"`
	Refusal   string           `json:"refusal,omitempty"`
	ToolCalls []OpenAIToolCall `json:"tool_calls,omitempty"`
}

// AnthropicResponse is a non-streaming /v1/messages response.
type AnthropicResponse struct {
	ID         string         `json:"id"`
	Type       string         `json:"type"`
	Role       string         `json:"role"`
	Model      string         `json:"model"`
	Content    []ContentBlock `json:"content"`
	StopReason string         `json:"stop_reason"`
	Usage      map[string]int `json:"usage,omitempty"`
}

// TranslateResponse maps an OpenAI chat completion to Anthropic messages format.
func TranslateResponse(or *OpenAIChatResponse, model string) *AnthropicResponse {
	ar := &AnthropicResponse{
		ID:         or.ID,
		Type:       "message",
		Role:       "assistant",
		Model:      model,
		StopReason: "end_turn",
		Content:    nil,
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
		if text := openAIContentText(ch.Message.Content); text != "" {
			ar.Content = append(ar.Content, ContentBlock{Type: "text", Text: text})
		}
		if ch.Message.Refusal != "" {
			ar.Content = append(ar.Content, ContentBlock{Type: "text", Text: ch.Message.Refusal})
		}
		for _, tc := range ch.Message.ToolCalls {
			args := tc.Function.Arguments
			if repaired, ok := RepairToolArgsJSON(args); ok {
				args = repaired
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
		// Honest cache reporting: only when the provider reports it.
		cached := or.Usage.CachedTokens
		if or.Usage.PromptDetails != nil && or.Usage.PromptDetails.CachedTokens > cached {
			cached = or.Usage.PromptDetails.CachedTokens
		}
		if cached > 0 {
			ar.Usage["cache_read_input_tokens"] = cached
		}
	}
	return ar
}

// openAIContentText extracts text from a string or multi-part content value.
func openAIContentText(v interface{}) string {
	switch c := v.(type) {
	case nil:
		return ""
	case string:
		return c
	case *string:
		if c == nil {
			return ""
		}
		return *c
	case []interface{}:
		var parts []string
		for _, p := range c {
			if m, ok := p.(map[string]interface{}); ok {
				if m["type"] == "text" {
					if t, _ := m["text"].(string); t != "" {
						parts = append(parts, t)
					}
				}
			}
		}
		return strings.Join(parts, "\n")
	default:
		return ""
	}
}
