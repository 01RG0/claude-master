// frontdoor_openai.go — OpenAI-compatible doors + Anthropic count_tokens.
//
// POST /v1/chat/completions accepts OpenAI requests, converts to the internal
// Anthropic form, routes through the same providers, and returns OpenAI
// responses. POST /v1/responses offers a minimal Responses mapping.
// POST /v1/messages/count_tokens returns measured-or-labeled-estimate counts.
package gateway

import (
	"encoding/json"
	"io"
	"net/http"
)

// handleOpenAIChat serves POST /v1/chat/completions.
func (s *Server) handleOpenAIChat(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeOpenAIError(w, 405, "invalid_request_error", "method not allowed")
		return
	}
	body, err := io.ReadAll(io.LimitReader(r.Body, 4<<20))
	if err != nil {
		writeOpenAIError(w, 400, "invalid_request_error", "reading body failed")
		return
	}
	var cr OpenAIChatIn
	if err := json.Unmarshal(body, &cr); err != nil {
		writeOpenAIError(w, 400, "invalid_request_error", "invalid request")
		return
	}
	ar := cr.toAnthropic()
	ar.Model = ResolveModel(cr.Model, s.cfg.ModelAliases, s.cfg.Roles, s.allCandidateModels())
	privClass := EffectivePrivacyClass(ar)
	primary, gh := EligibleProviders(s.cfg, privClass)
	providers := append(append([]Provider{}, primary...), gh...)
	if len(providers) == 0 {
		writeOpenAIError(w, 503, "overloaded_error", "no eligible providers available")
		return
	}
	s.logRequest("openai-chat", cr.Model, ar, nil)
	resp, upstreamModel, stats, err := s.tryProviders(r.Context(), providers, ar)
	if err != nil {
		writeOpenAIError(w, 502, "api_error", "all providers failed: "+redactForLog(err.Error()))
		return
	}
	defer resp.Body.Close()
	s.recordCall(upstreamModel, true, stats)
	if cr.Stream {
		s.streamOpenAIResponse(w, resp, upstreamModel)
		return
	}
	var oai OpenAIChatResponse
	raw, err := io.ReadAll(resp.Body)
	if err != nil {
		writeOpenAIError(w, 502, "api_error", "upstream read failed")
		return
	}
	if err := json.Unmarshal(raw, &oai); err != nil {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(resp.StatusCode)
		_, _ = w.Write(raw)
		return
	}
	if oai.Model == "" {
		oai.Model = upstreamModel
	}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	_ = json.NewEncoder(w).Encode(oai)
}

// OpenAIChatIn is the inbound OpenAI chat request (superset-tolerant).
type OpenAIChatIn struct {
	Model       string          `json:"model"`
	Messages    []OpenAIMessage `json:"messages"`
	MaxTokens   int             `json:"max_tokens"`
	MaxCompToks int             `json:"max_completion_tokens"`
	Stream      bool            `json:"stream"`
	Tools       []OpenAITool    `json:"tools"`
	Temperature *float64        `json:"temperature"`
}

func (c *OpenAIChatIn) toAnthropic() *AnthropicRequest {
	ar := &AnthropicRequest{Model: c.Model, Stream: c.Stream, Temperature: c.Temperature}
	ar.MaxTokens = c.MaxTokens
	if ar.MaxTokens == 0 {
		ar.MaxTokens = c.MaxCompToks
	}
	for _, m := range c.Messages {
		switch m.Role {
		case "system":
			ar.System = json.RawMessage(strconvQuote(openAIMessageText(m)))
		case "tool":
			ar.Messages = append(ar.Messages, AnthropicMessage{
				Role: "user",
				Content: mustJSONRaw([]ContentBlock{{
					Type: "tool_result", ToolUseID: m.ToolCallID, Content: mustJSONRaw(m.Content),
				}}),
			})
		default:
			role := m.Role
			if role == "" {
				role = "user"
			}
			var blocks []ContentBlock
			if t := openAIMessageText(m); t != "" {
				blocks = append(blocks, ContentBlock{Type: "text", Text: t})
			}
			for _, tc := range m.ToolCalls {
				blocks = append(blocks, ContentBlock{
					Type: "tool_use", ID: tc.ID, Name: tc.Function.Name,
					Input: json.RawMessage(orDefault(tc.Function.Arguments, "{}")),
				})
			}
			if len(blocks) == 0 {
				blocks = append(blocks, ContentBlock{Type: "text", Text: ""})
			}
			ar.Messages = append(ar.Messages, AnthropicMessage{Role: role, Content: mustJSONRaw(blocks)})
		}
	}
	for _, t := range c.Tools {
		ar.Tools = append(ar.Tools, AnthropicTool{
			Name: t.Function.Name, Description: t.Function.Description, InputSchema: t.Function.Parameters,
		})
	}
	return ar
}

func openAIMessageText(m OpenAIMessage) string { return openAIContentText(m.Content) }

func orDefault(s, d string) string {
	if s == "" {
		return d
	}
	return s
}

func mustJSONRaw(v interface{}) json.RawMessage {
	b, _ := json.Marshal(v)
	return b
}

func strconvQuote(s string) string {
	b, _ := json.Marshal(s)
	return string(b)
}

func writeOpenAIError(w http.ResponseWriter, status int, typ, msg string) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(map[string]interface{}{
		"error": map[string]interface{}{"message": msg, "type": typ, "code": status},
	})
}

// handleOpenAIResponses serves POST /v1/responses (minimal mapping).
func (s *Server) handleOpenAIResponses(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeOpenAIError(w, 405, "invalid_request_error", "method not allowed")
		return
	}
	body, err := io.ReadAll(io.LimitReader(r.Body, 4<<20))
	if err != nil {
		writeOpenAIError(w, 400, "invalid_request_error", "reading body failed")
		return
	}
	var in struct {
		Model string `json:"model"`
		Input interface{} `json:"input"`
		MaxTokens int `json:"max_output_tokens"`
		Stream  bool `json:"stream"`
	}
	if err := json.Unmarshal(body, &in); err != nil {
		writeOpenAIError(w, 400, "invalid_request_error", "invalid request")
		return
	}
	text := openAIContentText(in.Input)
	if text == "" {
		if b, err := json.Marshal(in.Input); err == nil {
			text = string(b)
		}
	}
	ar := &AnthropicRequest{
		Model: in.Model, MaxTokens: in.MaxTokens, Stream: in.Stream,
		Messages: []AnthropicMessage{{Role: "user", Content: mustJSONRaw(text)}},
	}
	if ar.MaxTokens == 0 {
		ar.MaxTokens = 1024
	}
	ar.Model = ResolveModel(in.Model, s.cfg.ModelAliases, s.cfg.Roles, s.allCandidateModels())
	privClass := EffectivePrivacyClass(ar)
	primary, gh := EligibleProviders(s.cfg, privClass)
	providers := append(append([]Provider{}, primary...), gh...)
	if len(providers) == 0 {
		writeOpenAIError(w, 503, "overloaded_error", "no eligible providers available")
		return
	}
	resp, upstreamModel, stats, err := s.tryProviders(r.Context(), providers, ar)
	if err != nil {
		writeOpenAIError(w, 502, "api_error", "all providers failed")
		return
	}
	defer resp.Body.Close()
	s.recordCall(upstreamModel, true, stats)
	var oai OpenAIChatResponse
	raw, err := io.ReadAll(resp.Body)
	if err != nil {
		writeOpenAIError(w, 502, "api_error", "upstream read failed")
		return
	}
	if err := json.Unmarshal(raw, &oai); err != nil {
		writeOpenAIError(w, 502, "api_error", "unparseable upstream response")
		return
	}
	out := map[string]interface{}{
		"id": oai.ID, "object": "response", "model": upstreamModel,
		"output": []interface{}{map[string]interface{}{
			"type": "message", "role": "assistant",
			"content": []interface{}{map[string]interface{}{
				"type": "output_text", "text": firstChoiceText(&oai),
			}},
		}},
	}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	_ = json.NewEncoder(w).Encode(out)
}

func firstChoiceText(oai *OpenAIChatResponse) string {
	if len(oai.Choices) == 0 {
		return ""
	}
	return openAIContentText(oai.Choices[0].Message.Content)
}

// handleCountTokens serves POST /v1/messages/count_tokens.
func (s *Server) handleCountTokens(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeAnthropicError(w, 405, "invalid_request_error", "method not allowed")
		return
	}
	body, err := io.ReadAll(io.LimitReader(r.Body, 4<<20))
	if err != nil {
		writeAnthropicError(w, 400, "invalid_request_error", "reading body failed")
		return
	}
	var ar AnthropicRequest
	if err := json.Unmarshal(body, &ar); err != nil {
		writeAnthropicError(w, 400, "invalid_request_error", "invalid request")
		return
	}
	chars := 0
	if ar.System != nil {
		chars += len(ar.System)
	}
	for _, m := range ar.Messages {
		chars += len(m.Content)
	}
	for _, t := range ar.Tools {
		chars += len(t.Name) + len(t.Description) + len(t.InputSchema)
	}
	// Heuristic estimate (chars/4); labeled as estimate — no tokenizer vendored.
	est := (chars + 3) / 4
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	_ = json.NewEncoder(w).Encode(map[string]interface{}{
		"input_tokens": est,
		"estimate":     true,
		"method":       "chars/4 heuristic (no provider tokenizer; use provider /models metadata when available)",
	})
}

// handleModels serves GET /v1/models: configured models + roles + aliases.
func (s *Server) handleModels(w http.ResponseWriter, r *http.Request) {
	type entry struct {
		ID     string `json:"id"`
		Owned  string `json:"owned_by"`
		Role   string `json:"role,omitempty"`
		Active bool   `json:"active"`
	}
	var out []entry
	roleOf := map[string]string{}
	if s.cfg.Roles != nil {
		for _, m := range []string{s.cfg.Roles.Main} {
			roleOf[m] = "main"
		}
		for _, m := range []string{s.cfg.Roles.Fast, s.cfg.Roles.Subagent, s.cfg.Roles.Vision, s.cfg.Roles.Summarizer} {
			if m != "" {
				if _, ok := roleOf[m]; !ok {
					roleOf[m] = "role"
				}
			}
		}
	}
	for _, p := range s.cfg.Providers {
		if !p.IsEnabled() {
			continue
		}
		for _, m := range p.Models {
			banned, isSet := s.pinned[m]
			out = append(out, entry{ID: m, Owned: p.Name, Role: roleOf[m], Active: !isSet || !banned})
		}
	}
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(map[string]interface{}{"data": out, "aliases": s.cfg.ModelAliases})
}

// streamOpenAIResponse proxies upstream SSE chunks back as OpenAI SSE.
func (s *Server) streamOpenAIResponse(w http.ResponseWriter, resp *http.Response, model string) {
	flusher, ok := w.(http.Flusher)
	if !ok {
		writeOpenAIError(w, 500, "api_error", "streaming not supported")
		return
	}
	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.WriteHeader(http.StatusOK)
	buf := make([]byte, 32*1024)
	for {
		n, err := resp.Body.Read(buf)
		if n > 0 {
			_, _ = w.Write(buf[:n])
			flusher.Flush()
		}
		if err != nil {
			break
		}
	}
	_, _ = w.Write([]byte("data: [DONE]\n\n"))
	flusher.Flush()
}
