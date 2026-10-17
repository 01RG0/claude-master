package gateway

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"
	"time"
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

func TestResolveModelDynamicRolesWhenConfigRolesEmpty(t *testing.T) {
	cands := []string{"groq/openai/gpt-oss-120b", "gemini-2.5-flash", "mistral-small-latest"}
	emptyAliases := map[string]string{}
	emptyRoles := &RoleMapping{}

	// Test with nil and empty maps
	for _, tc := range []struct {
		name    string
		aliases map[string]string
		roles   *RoleMapping
	}{
		{"nil-maps", nil, nil},
		{"empty-structs", emptyAliases, emptyRoles},
	} {
		t.Run(tc.name, func(t *testing.T) {
			// Haiku should dynamically match flash or small
			haikuModel := ResolveModel("haiku", tc.aliases, tc.roles, cands)
			if haikuModel == "" {
				t.Fatal("haiku dynamic model resolution returned empty")
			}
			if !strings.Contains(haikuModel, "flash") && !strings.Contains(haikuModel, "small") {
				t.Fatalf("haiku should match fast/small candidate, got %s", haikuModel)
			}

			// Opus should dynamically match large / pro / 120b
			opusModel := ResolveModel("opus", tc.aliases, tc.roles, cands)
			if opusModel != "groq/openai/gpt-oss-120b" {
				t.Fatalf("opus should match 120b reasoning candidate, got %s", opusModel)
			}

			// Sonnet should dynamically match flash/coding
			sonnetModel := ResolveModel("sonnet", tc.aliases, tc.roles, cands)
			if sonnetModel == "" {
				t.Fatal("sonnet dynamic model resolution returned empty")
			}

			// RoleForTask should dynamically resolve
			fastTask := RoleForTask("fast", tc.roles, cands)
			if fastTask == "" {
				t.Fatal("fast task dynamic resolution returned empty")
			}

			summaryTask := RoleForTask("summarizer", tc.roles, cands)
			if summaryTask == "" {
				t.Fatal("summarizer task dynamic resolution returned empty")
			}
		})
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

func TestClampMaxTokensDefaultCap(t *testing.T) {
	ar := &AnthropicRequest{Model: "x", MaxTokens: 128000,
		Messages: []AnthropicMessage{{Role: "user", Content: json.RawMessage(`"hi"`)}}}
	or, notes := TranslateRequest(ar, "m", AdapterSpec{})
	if or.MaxTokens != 8192 {
		t.Fatalf("clamped=%d want 8192", or.MaxTokens)
	}
	found := false
	for _, n := range notes {
		if strings.Contains(n, "max_tokens clamped") && strings.Contains(n, "adapter default") {
			found = true
			break
		}
	}
	if !found {
		t.Fatalf("expected clamp note with adapter default provenance, got %v", notes)
	}
}

func TestClampMaxTokensMeasuredProbeProvenance(t *testing.T) {
	ar := &AnthropicRequest{Model: "openai/gpt-oss-120b", MaxTokens: 128000,
		Messages: []AnthropicMessage{{Role: "user", Content: json.RawMessage(`"hi"`)}}}
	or, notes := TranslateRequest(ar, "openai/gpt-oss-120b", AdapterSpec{ProviderName: "groq"})
	if or.MaxTokens != 8192 {
		t.Fatalf("clamped=%d want 8192", or.MaxTokens)
	}
	found := false
	for _, n := range notes {
		if strings.Contains(n, "max_tokens clamped 128000->8192 (provenance: groq/openai/gpt-oss-120b measured limit)") {
			found = true
			break
		}
	}
	if !found {
		t.Fatalf("expected measured probe clamp note, got %v", notes)
	}
}

func TestClampMaxTokensContextWindowHeadroom(t *testing.T) {
	RegisterModelLimit("test/window-model", ModelLimit{
		MaxOutputTokens: 500,
		ContextWindow:   1000,
		Source:          "measured_probe",
		Detail:          "test/window-model measured limit",
	})
	hugeText := strings.Repeat("abcd", 220)
	ar := &AnthropicRequest{Model: "test/window-model", MaxTokens: 500,
		Messages: []AnthropicMessage{{Role: "user", Content: json.RawMessage(`"` + hugeText + `"` )}}}
	or, _ := TranslateRequest(ar, "test/window-model", AdapterSpec{})
	if or.MaxTokens != 500 {
		t.Fatalf("got %d want 500", or.MaxTokens)
	}

	massiveText := strings.Repeat("abcd", 900)
	arMassive := &AnthropicRequest{Model: "test/window-model", MaxTokens: 500,
		Messages: []AnthropicMessage{{Role: "user", Content: json.RawMessage(`"` + massiveText + `"` )}}}
	orMassive, notesMassive := TranslateRequest(arMassive, "test/window-model", AdapterSpec{})
	if orMassive.MaxTokens > 110 || orMassive.MaxTokens < 90 {
		t.Fatalf("expected clamped to remaining context (~100), got %d", orMassive.MaxTokens)
	}
	found := false
	for _, n := range notesMassive {
		if strings.Contains(n, "max_tokens clamped") {
			found = true
			break
		}
	}
	if !found {
		t.Fatalf("expected clamp note, got %v", notesMassive)
	}
}

func TestClampMaxTokensAdapterOverride(t *testing.T) {
	ar := &AnthropicRequest{Model: "x", MaxTokens: 128000,
		Messages: []AnthropicMessage{{Role: "user", Content: json.RawMessage(`"hi"`)}}}
	or, _ := TranslateRequest(ar, "m", AdapterSpec{MaxTokens: 4096})
	if or.MaxTokens != 4096 {
		t.Fatalf("got %d", or.MaxTokens)
	}
	or2, notes := TranslateRequest(&AnthropicRequest{Model: "x", MaxTokens: 100,
		Messages: []AnthropicMessage{{Role: "user", Content: json.RawMessage(`"hi"`)}}}, "m", AdapterSpec{})
	if or2.MaxTokens != 100 {
		t.Fatalf("under-cap should pass through, got %d", or2.MaxTokens)
	}
	for _, n := range notes {
		if strings.Contains(n, "clamped") {
			t.Fatalf("unexpected clamp note: %v", notes)
		}
	}
}

func TestPickModelWildcardPassthrough(t *testing.T) {
	s := NewServer(&Config{Providers: []Provider{{Name: "wild", Models: []string{"*"}}},
		Routing: RoutingConfig{Strategy: "priority"}})
	got := s.pickModel(s.cfg.Providers[0], &AnthropicRequest{Model: "openai/gpt-oss-20b"})
	if got != "openai/gpt-oss-20b" {
		t.Fatalf("wildcard provider should pass resolved model, got %q", got)
	}
	got = s.pickModel(Provider{Name: "empty", Models: []string{"*", ""}}, &AnthropicRequest{Model: "*"})
	if got != "" {
		t.Fatalf("no real model available → empty, got %q", got)
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

func TestStageLatencyBreakdownFormat(t *testing.T) {
	sl := StageLatency{
		GatewayOverheadMs: 1.25,
		RouterMs:          0.45,
		ProviderTTFTMs:    120.30,
		ProviderGenMs:     450.10,
		RescueMs:          0.85,
	}
	header := sl.HeaderValue()
	expected := "gw=1.25,router=0.45,ttft=120.30,gen=450.10,rescue=0.85"
	if header != expected {
		t.Fatalf("HeaderValue mismatch: got %q, want %q", header, expected)
	}

	st := StageTimings{
		GatewayOverhead: 2 * time.Millisecond,
		Router:          500 * time.Microsecond,
		TTFT:            100 * time.Millisecond,
		Generation:      300 * time.Millisecond,
		Rescue:          1 * time.Millisecond,
	}
	slFromTimings := st.StageLatency()
	if slFromTimings.GatewayOverheadMs != 2.0 || slFromTimings.RouterMs != 0.5 || slFromTimings.ProviderTTFTMs != 100.0 {
		t.Fatalf("StageLatency conversion mismatch: %+v", slFromTimings)
	}
}

func TestHTTPStageLatencyAndRescueHeaders(t *testing.T) {
	os.Setenv("TEST_KEY_RESCUE", "sk-test-key-rescue")
	t.Cleanup(func() { os.Unsetenv("TEST_KEY_RESCUE") })

	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{
			"id":"chatcmpl-test",
			"model":"mock-model",
			"choices":[{
				"index":0,
				"message":{
					"role":"assistant",
					"tool_calls":[{
						"id":"call_test_1",
						"type":"function",
						"function":{
							"name":"get_weather",
							"arguments":"{\"locaton\":\"Paris\"}"
						}
					}]
				},
				"finish_reason":"tool_calls"
			}]
		}`))
	}))
	defer upstream.Close()

	en := true
	cfg := &Config{
		ListenAddr: "127.0.0.1:0",
		Providers: []Provider{{
			Name: "mock", BaseURL: upstream.URL, PrivacyPolicy: PrivacyZeroRetention,
			Enabled: &en,
			Models:  []string{"mock-model"},
			KeyPools: []KeyPool{
				{AccountLabel: "personal", EnvVar: "TEST_KEY_RESCUE", Priority: 10},
			},
		}},
		Routing: RoutingConfig{Strategy: "priority"},
	}
	s := NewServer(cfg)

	reqBody := `{
		"model": "mock-model",
		"messages": [{"role": "user", "content": "weather in paris"}],
		"tools": [{
			"name": "get_weather",
			"description": "get weather",
			"input_schema": {
				"type": "object",
				"properties": {
					"location": {"type": "string"}
				}
			}
		}]
	}`

	// 1. Request with rescue enabled:
	req1 := httptest.NewRequest("POST", "/v1/messages", strings.NewReader(reqBody))
	req1.Header.Set("Content-Type", "application/json")
	rec1 := httptest.NewRecorder()
	s.Handler().ServeHTTP(rec1, req1)

	if rec1.Code != 200 {
		t.Fatalf("expected 200 OK, got %d: %s", rec1.Code, rec1.Body.String())
	}
	stageLatency1 := rec1.Header().Get("X-Stage-Latency")
	if stageLatency1 == "" || !strings.Contains(stageLatency1, "gw=") || !strings.Contains(stageLatency1, "router=") ||
		!strings.Contains(stageLatency1, "ttft=") || !strings.Contains(stageLatency1, "gen=") || !strings.Contains(stageLatency1, "rescue=") {
		t.Fatalf("missing or malformed X-Stage-Latency header: %q", stageLatency1)
	}

	rescueHeader1 := rec1.Header().Get("X-Tool-Rescue")
	if rescueHeader1 != "arg_schema_coercion" {
		t.Fatalf("expected X-Tool-Rescue: arg_schema_coercion, got %q", rescueHeader1)
	}

	var anthResp1 AnthropicResponse
	if err := json.Unmarshal(rec1.Body.Bytes(), &anthResp1); err != nil {
		t.Fatalf("unmarshal response: %v", err)
	}
	if len(anthResp1.Content) == 0 || anthResp1.Content[0].Type != "tool_use" {
		t.Fatalf("expected tool_use block, got %+v", anthResp1.Content)
	}
	if !strings.Contains(string(anthResp1.Content[0].Input), `"location"`) {
		t.Fatalf("expected rescued argument 'location', got %s", anthResp1.Content[0].Input)
	}

	// 2. Request with X-Tool-Rescue-Disabled: true
	req2 := httptest.NewRequest("POST", "/v1/messages", strings.NewReader(reqBody))
	req2.Header.Set("Content-Type", "application/json")
	req2.Header.Set("X-Tool-Rescue-Disabled", "true")
	rec2 := httptest.NewRecorder()
	s.Handler().ServeHTTP(rec2, req2)

	if rec2.Code != 200 {
		t.Fatalf("expected 200 OK, got %d: %s", rec2.Code, rec2.Body.String())
	}
	stageLatency2 := rec2.Header().Get("X-Stage-Latency")
	if stageLatency2 == "" {
		t.Fatal("expected X-Stage-Latency header even when rescue is disabled")
	}
	rescueHeader2 := rec2.Header().Get("X-Tool-Rescue")
	if rescueHeader2 != "" {
		t.Fatalf("X-Tool-Rescue header must NOT be emitted when disabled, got %q", rescueHeader2)
	}

	var anthResp2 AnthropicResponse
	if err := json.Unmarshal(rec2.Body.Bytes(), &anthResp2); err != nil {
		t.Fatalf("unmarshal response: %v", err)
	}
	if !strings.Contains(string(anthResp2.Content[0].Input), `"locaton"`) {
		t.Fatalf("raw unrescued argument should have survived when rescue disabled, got %s", anthResp2.Content[0].Input)
	}

	// 3. Admin endpoint GET /admin/toolrescue
	reqAdmin := httptest.NewRequest("GET", "/admin/toolrescue", nil)
	recAdmin := httptest.NewRecorder()
	s.Handler().ServeHTTP(recAdmin, reqAdmin)

	if recAdmin.Code != 200 {
		t.Fatalf("GET /admin/toolrescue failed with code %d: %s", recAdmin.Code, recAdmin.Body.String())
	}
	var snap ToolRescueSnapshot
	if err := json.Unmarshal(recAdmin.Body.Bytes(), &snap); err != nil {
		t.Fatalf("unmarshal admin toolrescue: %v", err)
	}
	if snap.RescueAttemptedTotal == 0 {
		t.Fatalf("expected >0 rescue attempts in admin snapshot, got %d", snap.RescueAttemptedTotal)
	}
	if snap.RescuedCallsTotal != 1 {
		t.Fatalf("expected 1 rescued call in admin snapshot, got %d", snap.RescuedCallsTotal)
	}
	if snap.RepairsByType["arg_schema_coercion"] != 1 {
		t.Fatalf("expected 1 arg_schema_coercion in repairs_by_type, got %d", snap.RepairsByType["arg_schema_coercion"])
	}
	if len(snap.RecentRepairs) != 1 {
		t.Fatalf("expected 1 recent repair, got %d", len(snap.RecentRepairs))
	}
}

func TestServerConfigToolRescueDisabled(t *testing.T) {
	os.Setenv("TEST_KEY_RESCUE_CFG", "sk-test-key-rescue-cfg")
	t.Cleanup(func() { os.Unsetenv("TEST_KEY_RESCUE_CFG") })

	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{
			"id":"chatcmpl-test2",
			"model":"mock-model2",
			"choices":[{
				"index":0,
				"message":{
					"role":"assistant",
					"tool_calls":[{
						"id":"call_test_2",
						"type":"function",
						"function":{
							"name":"get_weather",
							"arguments":"{\"locaton\":\"Paris\"}"
						}
					}]
				},
				"finish_reason":"tool_calls"
			}]
		}`))
	}))
	defer upstream.Close()

	en := true
	dis := false
	cfg := &Config{
		ListenAddr: "127.0.0.1:0",
		ToolRescueEnabled: &dis, // Disabled via config!
		Providers: []Provider{{
			Name: "mock", BaseURL: upstream.URL, PrivacyPolicy: PrivacyZeroRetention,
			Enabled: &en,
			Models:  []string{"mock-model2"},
			KeyPools: []KeyPool{
				{AccountLabel: "personal", EnvVar: "TEST_KEY_RESCUE_CFG", Priority: 10},
			},
		}},
		Routing: RoutingConfig{Strategy: "priority"},
	}
	s := NewServer(cfg)

	reqBody := `{
		"model": "mock-model2",
		"messages": [{"role": "user", "content": "weather in paris"}],
		"tools": [{
			"name": "get_weather",
			"description": "get weather",
			"input_schema": {
				"type": "object",
				"properties": {
					"location": {"type": "string"}
				}
			}
		}]
	}`

	req := httptest.NewRequest("POST", "/v1/messages", strings.NewReader(reqBody))
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()
	s.Handler().ServeHTTP(rec, req)

	if rec.Code != 200 {
		t.Fatalf("expected 200 OK, got %d: %s", rec.Code, rec.Body.String())
	}
	if rec.Header().Get("X-Tool-Rescue") != "" {
		t.Fatalf("X-Tool-Rescue must not be emitted when tool_rescue_enabled is false in config")
	}
	var anthResp AnthropicResponse
	_ = json.Unmarshal(rec.Body.Bytes(), &anthResp)
	if !strings.Contains(string(anthResp.Content[0].Input), `"locaton"`) {
		t.Fatalf("expected raw args when tool rescue is disabled in config")
	}
}
