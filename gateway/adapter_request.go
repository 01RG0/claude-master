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
	Model     string                 `json:"model"`
	Messages  []AnthropicMessage     `json:"messages"`
	System    json.RawMessage        `json:"system,omitempty"`
	MaxTokens int                    `json:"max_tokens,omitempty"`
	Stream    bool                   `json:"stream,omitempty"`
	Tools     []AnthropicTool        `json:"tools,omitempty"`
	Metadata  map[string]interface{} `json:"metadata,omitempty"`
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
	Type      string          `json:"type"`
	Text      string          `json:"text,omitempty"`
	ID        string          `json:"id,omitempty"`
	Name      string          `json:"name,omitempty"`
	Input     json.RawMessage `json:"input,omitempty"`
	ToolUseID string          `json:"tool_use_id,omitempty"`
	Content   json.RawMessage `json:"content,omitempty"`
}

// AnthropicTool describes a tool in the Anthropic format.
type AnthropicTool struct {
	Name        string          `json:"name"`
	Description string          `json:"description,omitempty"`
	InputSchema json.RawMessage `json:"input_schema,omitempty"`
}

// OpenAIRequest is the body of POST /v1/chat/completions.
type OpenAIRequest struct {
	Model       string          `json:"model"`
	Messages    []OpenAIMessage `json:"messages"`
	MaxTokens   int             `json:"max_tokens,omitempty"`
	Stream      bool            `json:"stream,omitempty"`
	Tools       []OpenAITool    `json:"tools,omitempty"`
	Temperature *float64        `json:"temperature,omitempty"`
}

// OpenAIMessage is one chat turn in OpenAI format.
type OpenAIMessage struct {
	Role       string           `json:"role"`
	Content    *string          `json:"content"`
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
func TranslateRequest(ar *AnthropicRequest, upstreamModel string) (*OpenAIRequest, error) {
	var msgs []OpenAIMessage

	if ar.System != nil && len(ar.System) > 0 && string(ar.System) != "null" {
		text, err := extractSystemText(ar.System)
		if err != nil {
			return nil, fmt.Errorf("parsing system: %w", err)
		}
		if text != "" {
			msgs = append(msgs, OpenAIMessage{Role: "system", Content: strPtr(text)})
		}
	}

	for _, am := range ar.Messages {
		converted, err := translateMessage(am)
		if err != nil {
			return nil, fmt.Errorf("translating message role=%s: %w", am.Role, err)
		}
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

	return &OpenAIRequest{
		Model:     upstreamModel,
		Messages:  msgs,
		MaxTokens: ar.MaxTokens,
		Stream:    ar.Stream,
		Tools:     tools,
	}, nil
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

func translateMessage(am AnthropicMessage) ([]OpenAIMessage, error) {
	role := am.Role

	var strContent string
	if err := json.Unmarshal(am.Content, &strContent); err == nil {
		return []OpenAIMessage{{Role: role, Content: strPtr(strContent)}}, nil
	}

	var blocks []ContentBlock
	if err := json.Unmarshal(am.Content, &blocks); err != nil {
		return nil, fmt.Errorf("unmarshalling content: %w", err)
	}

	var out []OpenAIMessage
	var textParts []string
	var toolCalls []OpenAIToolCall

	for _, b := range blocks {
		switch b.Type {
		case "text":
			textParts = append(textParts, b.Text)
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
			if len(textParts) > 0 || len(toolCalls) > 0 {
				out = append(out, flushAssistant(role, textParts, toolCalls))
				textParts = nil
				toolCalls = nil
			}
			content := extractToolResultContent(b.Content)
			out = append(out, OpenAIMessage{
				Role:       "tool",
				ToolCallID: b.ToolUseID,
				Content:    strPtr(content),
			})
		}
	}

	if len(textParts) > 0 || len(toolCalls) > 0 {
		out = append(out, flushAssistant(role, textParts, toolCalls))
	}
	if len(out) == 0 {
		out = append(out, OpenAIMessage{Role: role, Content: strPtr("")})
	}
	return out, nil
}

func flushAssistant(role string, textParts []string, toolCalls []OpenAIToolCall) OpenAIMessage {
	joined := strings.Join(textParts, "\n")
	m := OpenAIMessage{Role: role}
	if joined != "" {
		m.Content = strPtr(joined)
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
		Message      OpenAIMessage `json:"message"`
		FinishReason string `json:"finish_reason"`
	} `json:"choices"`
	Usage *struct {
		PromptTokens     int `json:"prompt_tokens"`
		CompletionTokens int `json:"completion_tokens"`
	} `json:"usage,omitempty"`
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
		if ch.FinishReason == "tool_calls" {
			ar.StopReason = "tool_use"
		} else if ch.FinishReason == "length" {
			ar.StopReason = "max_tokens"
		}
		if ch.Message.Content != nil && *ch.Message.Content != "" {
			ar.Content = append(ar.Content, ContentBlock{Type: "text", Text: *ch.Message.Content})
		}
		for _, tc := range ch.Message.ToolCalls {
			ar.Content = append(ar.Content, ContentBlock{
				Type:  "tool_use",
				ID:    tc.ID,
				Name:  tc.Function.Name,
				Input: json.RawMessage(tc.Function.Arguments),
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
	}
	return ar
}
