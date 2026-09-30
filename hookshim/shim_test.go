package main

import (
	"bytes"
	"encoding/json"
	"io"
	"net"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func startMockBrain(t *testing.T, handler func(payload []byte) []byte) (sock string, cleanup func()) {
	t.Helper()
	dir := t.TempDir()
	sock = filepath.Join(dir, "brain.sock")
	ln, err := net.Listen("unix", sock)
	if err != nil {
		t.Fatalf("listen: %v", err)
	}
	done := make(chan struct{})
	go func() {
		defer close(done)
		for {
			conn, err := ln.Accept()
			if err != nil {
				return
			}
			go func(c net.Conn) {
				defer c.Close()
				buf := make([]byte, 1<<20)
				n, _ := c.Read(buf)
				resp := handler(buf[:n])
				if !bytes.HasSuffix(resp, []byte("\n")) {
					resp = append(resp, '\n')
				}
				_, _ = c.Write(resp)
			}(conn)
		}
	}()
	return sock, func() {
		ln.Close()
		<-done
	}
}

func TestFailOpenMissingSocket(t *testing.T) {
	var out bytes.Buffer
	code := run(bytes.NewReader([]byte(`{"hook_event_name":"PreToolUse"}`)), &out,
		filepath.Join(t.TempDir(), "missing.sock"), 50*time.Millisecond)
	if code != 0 {
		t.Fatalf("exit=%d want 0", code)
	}
	if out.Len() != 0 {
		t.Fatalf("stdout not empty on fail-open: %q", out.Bytes())
	}
}

func TestFailOpenSlowDaemon(t *testing.T) {
	sock, cleanup := startMockBrain(t, func(payload []byte) []byte {
		time.Sleep(80 * time.Millisecond)
		return []byte(`{"allow":false,"block_reason":"too late"}`)
	})
	defer cleanup()

	var out bytes.Buffer
	code := run(bytes.NewReader([]byte(`{"hook_event_name":"PreToolUse","tool_name":"Bash"}`)), &out,
		sock, 50*time.Millisecond)
	if code != 0 {
		t.Fatalf("exit=%d want 0 (fail-open on slow daemon)", code)
	}
	if out.Len() != 0 {
		t.Fatalf("stdout should be empty on fail-open, got %q", out.Bytes())
	}
}

func TestBlockExitCode2(t *testing.T) {
	sock, cleanup := startMockBrain(t, func(payload []byte) []byte {
		return []byte(`{"allow":false,"block_reason":"force push blocked"}`)
	})
	defer cleanup()

	in := []byte(`{"hook_event_name":"PreToolUse","tool_name":"Bash","session_id":"s1"}`)
	var out bytes.Buffer
	code := run(bytes.NewReader(in), &out, sock, 50*time.Millisecond)
	if code != 2 {
		t.Fatalf("exit=%d want 2", code)
	}
	var body map[string]any
	if err := json.Unmarshal(out.Bytes(), &body); err != nil {
		t.Fatalf("stdout json: %v (%q)", err, out.Bytes())
	}
	hso, _ := body["hookSpecificOutput"].(map[string]any)
	if hso["permissionDecision"] != "deny" {
		t.Fatalf("decision=%v", hso["permissionDecision"])
	}
	if hso["permissionDecisionReason"] != "force push blocked" {
		t.Fatalf("reason=%v", hso["permissionDecisionReason"])
	}
}

func TestAllowWithContext(t *testing.T) {
	sock, cleanup := startMockBrain(t, func(payload []byte) []byte {
		return []byte(`{"allow":true,"additional_context":"prefer go fmt"}`)
	})
	defer cleanup()

	in := []byte(`{"hook_event_name":"UserPromptSubmit","prompt":"hi"}`)
	var out bytes.Buffer
	code := run(bytes.NewReader(in), &out, sock, 50*time.Millisecond)
	if code != 0 {
		t.Fatalf("exit=%d want 0", code)
	}
	var body map[string]any
	if err := json.Unmarshal(out.Bytes(), &body); err != nil {
		t.Fatalf("stdout json: %v", err)
	}
	if body["systemMessage"] != "prefer go fmt" {
		t.Fatalf("systemMessage=%v", body["systemMessage"])
	}
}

func TestAllowEmpty(t *testing.T) {
	sock, cleanup := startMockBrain(t, func(payload []byte) []byte {
		return []byte(`{"allow":true}`)
	})
	defer cleanup()

	var out bytes.Buffer
	code := run(bytes.NewReader([]byte(`{"hook_event_name":"PostToolUse"}`)), &out, sock, 50*time.Millisecond)
	if code != 0 || out.Len() != 0 {
		t.Fatalf("exit=%d out=%q", code, out.Bytes())
	}
}

func TestSocketPathFromEnv(t *testing.T) {
	t.Setenv("CLAUDE_BRAIN_SOCKET", "/tmp/custom_brain.sock")
	t.Setenv("BRAIN_SOCKET", "")
	if got := socketPath(); got != "/tmp/custom_brain.sock" {
		t.Fatalf("got %q", got)
	}
	t.Setenv("CLAUDE_BRAIN_SOCKET", "")
	t.Setenv("BRAIN_SOCKET", "/tmp/alt.sock")
	if got := socketPath(); got != "/tmp/alt.sock" {
		t.Fatalf("got %q", got)
	}
}

func TestTimeoutFromEnv(t *testing.T) {
	t.Setenv("CLAUDE_BRAIN_TIMEOUT_MS", "25")
	if got := dialTimeout(); got != 25*time.Millisecond {
		t.Fatalf("got %v", got)
	}
}

func TestForwardPayloadIntact(t *testing.T) {
	var got []byte
	sock, cleanup := startMockBrain(t, func(payload []byte) []byte {
		got = append([]byte(nil), bytes.TrimSpace(payload)...)
		return []byte(`{"allow":true}`)
	})
	defer cleanup()

	in := []byte(`{"hook_event_name":"Stop","session_id":"abc","last_assistant_message":"done"}`)
	code := run(bytes.NewReader(in), io.Discard, sock, 50*time.Millisecond)
	if code != 0 {
		t.Fatalf("exit=%d", code)
	}
	if !bytes.Equal(got, in) {
		t.Fatalf("forwarded=%s want=%s", got, in)
	}
}

// MeasureIPCRoundTrip times an in-process query against a fast mock (not cold-start).
func TestIPCRoundTripBudget(t *testing.T) {
	sock, cleanup := startMockBrain(t, func(payload []byte) []byte {
		return []byte(`{"allow":true}`)
	})
	defer cleanup()

	in := []byte(`{"hook_event_name":"PreToolUse"}`)
	start := time.Now()
	code := run(bytes.NewReader(in), io.Discard, sock, 50*time.Millisecond)
	elapsed := time.Since(start)
	if code != 0 {
		t.Fatalf("exit=%d", code)
	}
	if elapsed > 20*time.Millisecond {
		t.Fatalf("IPC round-trip too slow: %v", elapsed)
	}
	t.Logf("IPC round-trip: %v", elapsed)
}

func TestMainBinaryUsesEnv(t *testing.T) {
	// Smoke: ensure default socket is not a home path.
	_ = os.Unsetenv("CLAUDE_BRAIN_SOCKET")
	_ = os.Unsetenv("BRAIN_SOCKET")
	p := socketPath()
	if filepath.Base(p) != "claude_brain.sock" {
		t.Fatalf("unexpected default socket %q", p)
	}
}
