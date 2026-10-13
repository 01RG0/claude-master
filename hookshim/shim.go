// Package main implements the Claude Code hook shim.
// It forwards stdin hook JSON to the brain daemon over TCP loopback
// (Windows default) or a Unix socket (POSIX default) and maps the
// response to Claude Code stdout / exit codes.
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
	"runtime"
	"strconv"
	"strings"
	"time"
)

const (
	defaultSocket     = "/tmp/claude_brain.sock"
	defaultTCP        = "127.0.0.1:7772"
	defaultTimeout    = 50 * time.Millisecond
	exitAllow         = 0
	exitBlock         = 2
	envSocket         = "CLAUDE_BRAIN_SOCKET"
	envSocketAlt      = "BRAIN_SOCKET"
	envTCP            = "CLAUDE_BRAIN_TCP"
	envTCPAlt         = "BRAIN_TCP"
	envTimeoutMS      = "CLAUDE_BRAIN_TIMEOUT_MS"
	flagSocket        = "socket"
	flagTCP           = "tcp"
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

// tcpAddr resolves the TCP hook address from env, "" when unset.
func tcpAddr() string {
	if p := os.Getenv(envTCP); p != "" {
		return normaliseTCP(p)
	}
	if p := os.Getenv(envTCPAlt); p != "" {
		return normaliseTCP(p)
	}
	return ""
}

// defaultEndpoint returns network,address: TCP on Windows (or when the socket
// looks like host:port), Unix socket otherwise.
func defaultEndpoint(sock, tcp string) (network, addr string) {
	if tcp != "" {
		return "tcp", normaliseTCP(tcp)
	}
	if isTCPAddr(sock) {
		return "tcp", normaliseTCP(sock)
	}
	if sock == "" || sock == defaultSocket {
		if runtime.GOOS == "windows" {
			return "tcp", defaultTCP
		}
		if sock == "" {
			return "unix", defaultSocket
		}
	}
	return "unix", sock
}

func normaliseTCP(a string) string {
	a = strings.TrimSpace(strings.Trim(a, "\"'"))
	a = strings.TrimPrefix(a, "tcp://")
	a = strings.TrimPrefix(a, "TCP://")
	return a
}

func isTCPAddr(v string) bool {
	v = strings.TrimSpace(v)
	if strings.HasPrefix(strings.ToLower(v), "tcp://") {
		return true
	}
	if strings.HasPrefix(v, "/") || strings.HasPrefix(v, `\\`) {
		return false
	}
	// Windows drive path C:\... is a file, not TCP.
	if len(v) >= 3 && v[1] == ':' && isAlpha(v[0]) && (v[2] == '\\' || v[2] == '/') {
		return false
	}
	i := strings.LastIndex(v, ":")
	if i < 0 {
		return false
	}
	port := v[i+1:]
	if port == "" {
		return false
	}
	for _, c := range port {
		if c < '0' || c > '9' {
			return false
		}
	}
	return true
}

func isAlpha(c byte) bool {
	return (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z')
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
	return runEndpoint(in, out, "unix", sock, to)
}

// runTCP is the testable TCP entry.
func runTCP(in io.Reader, out io.Writer, addr string, to time.Duration) int {
	return runEndpoint(in, out, "tcp", normaliseTCP(addr), to)
}

func runEndpoint(in io.Reader, out io.Writer, network, addr string, to time.Duration) int {
	payload, err := io.ReadAll(in)
	if err != nil {
		return exitAllow
	}
	payload = bytes.TrimSpace(payload)
	if len(payload) == 0 {
		return exitAllow
	}

	resp, ok := queryBrainEndpoint(network, addr, payload, to)
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
	return queryBrainEndpoint("unix", sock, payload, to)
}

func queryBrainEndpoint(network, addr string, payload []byte, to time.Duration) (brainResponse, bool) {
	deadline := time.Now().Add(to)

	d := net.Dialer{Timeout: to}
	conn, err := d.Dial(network, addr)
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
