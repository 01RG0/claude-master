package main

// hookhost: keep-alive host (TCP loopback) holding ONE upstream conn to the
// brain daemon. Newline-JSON in/out, same protocol as brain.

import (
	"bufio"
	"bytes"
	"io"
	"net"
	"os"
	"sync"
	"time"
)

const (
	defaultHostAddr = "127.0.0.1:7773"
	envHookHost     = "CLAUDE_HOOK_HOST"
)

var failsafeLine = []byte(`{"allow":true,"additional_context":""}`)

func hookHostAddr(flagVal string) string {
	if flagVal != "" {
		return normaliseTCP(flagVal)
	}
	if v := os.Getenv(envHookHost); v != "" {
		return normaliseTCP(v)
	}
	return ""
}
func defaultHostListen(hostFlag, tcpFlag string) string {
	if hostFlag != "" {
		return normaliseTCP(hostFlag)
	}
	if tcpFlag != "" {
		return normaliseTCP(tcpFlag)
	}
	if v := os.Getenv(envHookHost); v != "" {
		return normaliseTCP(v)
	}
	return defaultHostAddr
}
func emitResp(out io.Writer, payload []byte, resp brainResponse) int {
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

func runWithHost(in io.Reader, out io.Writer, network, addr, hostAddr string, to time.Duration) int {
	payload, err := io.ReadAll(in)
	if err != nil {
		return exitAllow
	}
	payload = bytes.TrimSpace(payload)
	if len(payload) == 0 {
		return exitAllow
	}
	if hostAddr != "" {
		ht := to
		if ht > 50*time.Millisecond {
			ht = 50 * time.Millisecond
		}
		if resp, ok := queryBrainEndpoint("tcp", hostAddr, payload, ht); ok {
			return emitResp(out, payload, resp)
		}
	}
	resp, ok := queryBrainEndpoint(network, addr, payload, to)
	if !ok {
		return exitAllow
	}
	return emitResp(out, payload, resp)
}

// upstream holds ONE conn to the brain (dropped + redialled in background
// after each reply; conns idle >4s are redialled, the brain closes at 5s).
type upstream struct {
	mu      sync.Mutex
	network string
	addr    string
	timeout time.Duration
	conn    net.Conn
	reader  *bufio.Reader
	idle    time.Time
}

func (u *upstream) dial() bool {
	d := net.Dialer{Timeout: u.timeout}
	c, err := d.Dial(u.network, u.addr)
	if err != nil {
		return false
	}
	u.conn, u.reader, u.idle = c, bufio.NewReader(c), time.Now()
	return true
}

func (u *upstream) close() {
	if u.conn != nil {
		_ = u.conn.Close()
		u.conn = nil
		u.reader = nil
	}
}
func (u *upstream) query(payload []byte) []byte {
	u.mu.Lock()
	defer u.mu.Unlock()
	msg := payload
	if !bytes.HasSuffix(msg, []byte("\n")) {
		msg = append(append([]byte(nil), payload...), '\n')
	}
	for attempt := 0; attempt < 2; attempt++ {
		if u.conn == nil || time.Since(u.idle) > 4*time.Second {
			u.close()
			if !u.dial() {
				time.Sleep(10 * time.Millisecond)
				continue
			}
		}
		_ = u.conn.SetDeadline(time.Now().Add(u.timeout))
		if _, err := u.conn.Write(msg); err != nil {
			u.close()
			continue
		}
		line, err := u.reader.ReadBytes('\n')
		if err != nil || len(bytes.TrimSpace(line)) == 0 {
			u.close()
			continue
		}
		u.close()
		go u.refill()
		return bytes.TrimSpace(line)
	}
	return failsafeLine
}

func (u *upstream) refill() {
	d := net.Dialer{Timeout: u.timeout}
	c, err := d.Dial(u.network, u.addr)
	if err != nil {
		return
	}
	u.mu.Lock()
	defer u.mu.Unlock()
	if u.conn != nil {
		_ = c.Close()
		return
	}
	u.conn = c
	u.reader = bufio.NewReader(c)
	u.idle = time.Now()
}
func handleHostConn(down net.Conn, up *upstream) {
	defer down.Close()
	br := bufio.NewReader(down)
	for {
		line, err := br.ReadBytes('\n')
		trimmed := bytes.TrimSpace(line)
		if len(trimmed) == 0 {
			if err != nil {
				return
			}
			continue
		}
		resp := up.query(trimmed)
		if !bytes.HasSuffix(resp, []byte("\n")) {
			resp = append(resp, '\n')
		}
		_, werr := down.Write(resp)
		if werr != nil || err != nil {
			return
		}
	}
}

// serveHost forwards downstream lines over the shared upstream conn (keep-alive).
func serveHost(listenAddr, upstreamNetwork, upstreamAddr string, to time.Duration) error {
	ln, err := net.Listen("tcp", listenAddr)
	if err != nil {
		return err
	}
	defer ln.Close()
	up := &upstream{network: upstreamNetwork, addr: upstreamAddr, timeout: to}
	go up.refill()
	for {
		c, err := ln.Accept()
		if err != nil {
			continue
		}
		go handleHostConn(c, up)
	}
}
