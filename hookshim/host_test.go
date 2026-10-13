package main

import (
	"bufio"
	"bytes"
	"net"
	"testing"
	"time"
)

// TestHookHostKeepAlive: sequential calls over one conn vs close-per-reply brain.
func TestHookHostKeepAlive(t *testing.T) {
	up, done := startMockBrainTCP(t, func([]byte) []byte { return []byte(`{"allow":true}`) })
	defer done()
	a, b := net.Pipe()
	defer b.Close()
	go handleHostConn(a, &upstream{network: "tcp", addr: up, timeout: 2 * time.Second})
	br := bufio.NewReader(b)
	for i := 0; i < 3; i++ {
		_ = b.SetDeadline(time.Now().Add(5 * time.Second))
		if _, err := b.Write([]byte("{\"hook_event_name\":\"PreToolUse\"}\n")); err != nil {
			t.Fatal(err)
		}
		line, err := br.ReadBytes('\n')
		if err != nil || !bytes.Contains(line, []byte(`"allow":true`)) {
			t.Fatalf("call %d: err=%v line=%q", i, err, line)
		}
	}
}

// TestHookHostFallback: dead host fails open fast, then direct upstream runs.
func TestHookHostFallback(t *testing.T) {
	up, done := startMockBrainTCP(t, func([]byte) []byte { return []byte(`{"allow":true}`) })
	defer done()
	dead, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	addr := dead.Addr().String()
	dead.Close()
	var out bytes.Buffer
	code := runWithHost(bytes.NewReader([]byte(`{"hook_event_name":"PreToolUse"}`)),
		&out, "tcp", up, addr, 300*time.Millisecond)
	if code != 0 || out.Len() != 0 {
		t.Fatalf("exit=%d out=%q want fail-open", code, out.Bytes())
	}
}
