package main

import (
	"context"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

func TestHealthyAndUnhealthy(t *testing.T) {
	var healthy atomic.Bool
	healthy.Store(true)
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/health" {
			http.NotFound(w, r)
			return
		}
		if !healthy.Load() {
			http.Error(w, "down", http.StatusServiceUnavailable)
			return
		}
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(`{"status":"ok","uptime_s":1,"db_size_bytes":0}`))
	}))
	defer srv.Close()

	w := &Watchdog{
		APIURL: srv.URL,
		Client: srv.Client(),
		Now:    time.Now,
	}
	ctx := context.Background()
	if !w.Healthy(ctx) {
		t.Fatal("expected healthy")
	}
	healthy.Store(false)
	if w.Healthy(ctx) {
		t.Fatal("expected unhealthy")
	}
}

func TestRestartWithinOneSecond(t *testing.T) {
	// Mock daemon: a tiny script that writes a ready file then sleeps.
	dir := t.TempDir()
	ready := filepath.Join(dir, "ready")
	script := filepath.Join(dir, "mock_daemon.sh")
	content := fmt.Sprintf("#!/bin/sh\ntouch %q\nexec sleep 5\n", ready)
	if err := os.WriteFile(script, []byte(content), 0o755); err != nil {
		t.Fatal(err)
	}

	var hits atomic.Int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/health":
			// Healthy only after mock daemon created ready file.
			if _, err := os.Stat(ready); err == nil {
				hits.Add(1)
				w.WriteHeader(http.StatusOK)
				_, _ = w.Write([]byte(`{"status":"ok","uptime_s":0,"db_size_bytes":0}`))
				return
			}
			http.Error(w, "starting", http.StatusServiceUnavailable)
		default:
			http.NotFound(w, r)
		}
	}))
	defer srv.Close()

	var (
		alertMu sync.Mutex
		alerts  []string
	)
	wd := &Watchdog{
		APIURL:         srv.URL,
		DaemonCmd:      []string{script},
		HealthInterval: 50 * time.Millisecond,
		Client:         srv.Client(),
		Now:            time.Now,
		Alert: func(msg string) {
			alertMu.Lock()
			alerts = append(alerts, msg)
			alertMu.Unlock()
		},
	}

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	start := time.Now()
	go wd.Run(ctx)

	deadline := time.Now().Add(1 * time.Second)
	for time.Now().Before(deadline) {
		if wd.Restarts.Load() >= 1 {
			if _, err := os.Stat(ready); err == nil {
				elapsed := time.Since(start)
				alertMu.Lock()
				alertCopy := append([]string(nil), alerts...)
				alertMu.Unlock()
				t.Logf("restart detected in %v (restarts=%d alerts=%v)", elapsed, wd.Restarts.Load(), alertCopy)
				if elapsed > time.Second {
					t.Fatalf("restart took %v > 1s", elapsed)
				}
				cancel()
				wd.mu.Lock()
				if wd.cmd != nil && wd.cmd.Process != nil {
					_ = wd.cmd.Process.Kill()
				}
				wd.mu.Unlock()
				return
			}
		}
		time.Sleep(10 * time.Millisecond)
	}
	cancel()
	wd.mu.Lock()
	if wd.cmd != nil && wd.cmd.Process != nil {
		_ = wd.cmd.Process.Kill()
	}
	wd.mu.Unlock()
	t.Fatalf("daemon not restarted within 1s (restarts=%d)", wd.Restarts.Load())
}

func TestTriggerSleep(t *testing.T) {
	var called atomic.Bool
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodPost && r.URL.Path == "/sleep/trigger" {
			called.Store(true)
			w.WriteHeader(http.StatusAccepted)
			_, _ = w.Write([]byte(`{"run_id":"sleep-1"}`))
			return
		}
		http.NotFound(w, r)
	}))
	defer srv.Close()

	wd := &Watchdog{APIURL: srv.URL, Client: srv.Client(), Now: time.Now}
	if err := wd.TriggerSleep(context.Background()); err != nil {
		t.Fatal(err)
	}
	if !called.Load() {
		t.Fatal("sleep not triggered")
	}
}

func TestMaybeSleepOncePerDay(t *testing.T) {
	var calls atomic.Int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/sleep/trigger" {
			calls.Add(1)
			w.WriteHeader(http.StatusAccepted)
			return
		}
		http.NotFound(w, r)
	}))
	defer srv.Close()

	fixed := time.Date(2026, 9, 30, 3, 15, 0, 0, time.Local)
	wd := &Watchdog{
		APIURL:      srv.URL,
		Client:      srv.Client(),
		SleepHour:   3,
		SleepMinute: 15,
		Now:         func() time.Time { return fixed },
	}
	ctx := context.Background()
	wd.maybeSleep(ctx)
	wd.maybeSleep(ctx)
	if calls.Load() != 1 {
		t.Fatalf("calls=%d want 1", calls.Load())
	}
}

func TestConfigFromEnv(t *testing.T) {
	t.Setenv("BRAIN_API_URL", "http://127.0.0.1:9999")
	t.Setenv("BRAIN_DAEMON_CMD", "python -m brain")
	t.Setenv("BRAIN_HEALTH_INTERVAL_MS", "100")
	t.Setenv("BRAIN_SLEEP_HOUR", "2")
	t.Setenv("BRAIN_SLEEP_MINUTE", "30")
	w := ConfigFromEnv()
	if w.APIURL != "http://127.0.0.1:9999" {
		t.Fatalf("api=%q", w.APIURL)
	}
	if len(w.DaemonCmd) != 3 || w.DaemonCmd[0] != "python" {
		t.Fatalf("cmd=%v", w.DaemonCmd)
	}
	if w.HealthInterval != 100*time.Millisecond {
		t.Fatalf("interval=%v", w.HealthInterval)
	}
	if w.SleepHour != 2 || w.SleepMinute != 30 {
		t.Fatalf("sleep=%d:%d", w.SleepHour, w.SleepMinute)
	}
}

func TestEnsureRunningNoOpWhenHealthy(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(`{"status":"ok","uptime_s":1,"db_size_bytes":0}`))
	}))
	defer srv.Close()

	wd := &Watchdog{
		APIURL:    srv.URL,
		Client:    srv.Client(),
		DaemonCmd: []string{"/bin/false"},
		Now:       time.Now,
	}
	if err := wd.EnsureRunning(context.Background()); err != nil {
		t.Fatal(err)
	}
	if wd.Restarts.Load() != 0 {
		t.Fatalf("unexpected restart")
	}
}

func TestRestartRequiresCmd(t *testing.T) {
	wd := &Watchdog{DaemonCmd: nil, Now: time.Now, Client: http.DefaultClient}
	err := wd.Restart(context.Background())
	if err == nil {
		t.Fatal("expected error")
	}
}

func TestSplitCmd(t *testing.T) {
	got := splitCmd("  /usr/bin/python3  -m  brain.server ")
	if len(got) != 3 {
		t.Fatalf("%v", got)
	}
}

// Ensure mock daemon binary exists so Restart path is smoke-tested.
func TestRestartKillsPrevious(t *testing.T) {
	dir := t.TempDir()
	script := filepath.Join(dir, "d.sh")
	if err := os.WriteFile(script, []byte("#!/bin/sh\nexec sleep 5\n"), 0o755); err != nil {
		t.Fatal(err)
	}
	wd := &Watchdog{DaemonCmd: []string{script}, Now: time.Now, Client: http.DefaultClient}
	ctx := context.Background()
	if err := wd.Restart(ctx); err != nil {
		t.Fatal(err)
	}
	firstPID := wd.cmd.Process.Pid
	if err := wd.Restart(ctx); err != nil {
		t.Fatal(err)
	}
	if wd.Restarts.Load() != 2 {
		t.Fatalf("restarts=%d", wd.Restarts.Load())
	}
	// First process should be gone (killed). kill -0 succeeds only if alive.
	if err := exec.Command("kill", "-0", fmt.Sprintf("%d", firstPID)).Run(); err == nil {
		t.Fatalf("first process pid=%d still alive", firstPID)
	}
	// Kill second child so the test package can exit promptly.
	wd.mu.Lock()
	if wd.cmd != nil && wd.cmd.Process != nil {
		_ = wd.cmd.Process.Kill()
	}
	wd.mu.Unlock()
}
