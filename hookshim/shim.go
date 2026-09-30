// Package main implements the Claude Code hook shim.
// It forwards stdin hook JSON to the brain daemon over a Unix socket
// and maps the response to Claude Code stdout / exit codes.
//
// Fail-open: any dial/read failure or timeout (>50ms default) exits 0
// with empty stdout so Claude Code is never blocked by a dead brain.
package main

import (
	"bufio"
	"bytes"
	"encoding/json"
	"io"
	"net"
	"os"
	"strconv"
	"time"
)

const (
	defaultSocket     = "/tmp/claude_brain.sock"
	defaultTimeout    = 50 * time.Millisecond
	exitAllow         = 0
	exitBlock         = 2
	envSocket         = "CLAUDE_BRAIN_SOCKET"
	envSocketAlt      = "BRAIN_SOCKET"
	envTimeoutMS      = "CLAUDE_BRAIN_TIMEOUT_MS"
)

// brainResponse is the JSON line returned by brain/guard socket_server.
type brainResponse struct {
	Allow             *bool   `json:"allow"`
	BlockReason       string  `json:"block_reason"`
	AdditionalContext string  `json:"additional_context"`
	OutcomeReward     float64 `json:"outcome_reward"`
}

// socketPath resolves the Unix socket path from env (no hardcoded home paths).
func socketPath() string {
	if p := os.Getenv(envSocket); p != "" {
		return p
	}
	if p := os.Getenv(envSocketAlt); p != "" {
		return p
	}
	return defaultSocket
}

// dialTimeout returns the total IPC budget (dial + write + read).
func dialTimeout() time.Duration {
	if ms := os.Getenv(envTimeoutMS); ms != "" {
		if n, err := strconv.Atoi(ms); err == nil && n > 0 {
			return time.Duration(n) * time.Millisecond
		}
	}
	return defaultTimeout
}

// run is the testable entry: read stdin → query brain → write stdout → exit code.
func run(in io.Reader, out io.Writer, sock string, to time.Duration) int {
	payload, err := io.ReadAll(in)
	if err != nil {
		return exitAllow
	}
	payload = bytes.TrimSpace(payload)
	if len(payload) == 0 {
		return exitAllow
	}

	resp, ok := queryBrain(sock, payload, to)
	if !ok {
		// Daemon down / slow / malformed → fail-open.
		return exitAllow
	}

	allow := true
	if resp.Allow != nil {
		allow = *resp.Allow
	}

	if !allow {
		writeBlock(out, payload, resp.BlockReason)
		return exitBlock
	}

	if resp.AdditionalContext != "" {
		writeContext(out, payload, resp.AdditionalContext)
	}
	return exitAllow
}

// queryBrain sends a newline-terminated JSON payload and reads one JSON line back.
// Returns ok=false on any error or timeout (caller fail-opens).
func queryBrain(sock string, payload []byte, to time.Duration) (brainResponse, bool) {
	deadline := time.Now().Add(to)

	d := net.Dialer{Timeout: to}
	conn, err := d.Dial("unix", sock)
	if err != nil {
		return brainResponse{}, false
	}
	defer conn.Close()

	if err := conn.SetDeadline(deadline); err != nil {
		return brainResponse{}, false
	}

	msg := payload
	if !bytes.HasSuffix(msg, []byte("\n")) {
		msg = append(append([]byte(nil), payload...), '\n')
	}
	if _, err := conn.Write(msg); err != nil {
		return brainResponse{}, false
	}

	line, err := bufio.NewReader(conn).ReadBytes('\n')
	if err != nil && len(bytes.TrimSpace(line)) == 0 {
		return brainResponse{}, false
	}

	var resp brainResponse
	if err := json.Unmarshal(bytes.TrimSpace(line), &resp); err != nil {
		return brainResponse{}, false
	}
	return resp, true
}

func extractEventName(input []byte) string {
	var m struct {
		HookEventName string `json:"hook_event_name"`
	}
	_ = json.Unmarshal(input, &m)
	if m.HookEventName == "" {
		return "PreToolUse"
	}
	return m.HookEventName
}

func writeBlock(out io.Writer, input []byte, reason string) {
	if reason == "" {
		reason = "blocked by brain"
	}
	event := extractEventName(input)
	body := map[string]any{
		"hookSpecificOutput": map[string]any{
			"hookEventName":            event,
			"permissionDecision":       "deny",
			"permissionDecisionReason": reason,
		},
		"systemMessage": reason,
	}
	enc, err := json.Marshal(body)
	if err != nil {
		return
	}
	_, _ = out.Write(enc)
	_, _ = out.Write([]byte("\n"))
}

func writeContext(out io.Writer, input []byte, ctx string) {
	event := extractEventName(input)
	body := map[string]any{
		"systemMessage": ctx,
		"hookSpecificOutput": map[string]any{
			"hookEventName":     event,
			"additionalContext": ctx,
		},
	}
	enc, err := json.Marshal(body)
	if err != nil {
		return
	}
	_, _ = out.Write(enc)
	_, _ = out.Write([]byte("\n"))
}
