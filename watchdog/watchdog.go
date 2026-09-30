// Package main implements the brain daemon watchdog.
// It health-checks the brain HTTP API, restarts a dead daemon within ~1s,
// schedules nightly sleep consolidation, and emits alerts.
package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"time"
)

const (
	envAPIURL          = "BRAIN_API_URL"
	envDaemonCmd       = "BRAIN_DAEMON_CMD"
	envHealthInterval  = "BRAIN_HEALTH_INTERVAL_MS"
	envSleepHour       = "BRAIN_SLEEP_HOUR"
	envSleepMinute     = "BRAIN_SLEEP_MINUTE"
	envAlertWebhook    = "BRAIN_ALERT_WEBHOOK"
	defaultAPIURL      = "http://127.0.0.1:7700"
	defaultHealthMS    = 250
)

// AlertFunc receives human-readable alert messages.
type AlertFunc func(msg string)

// Watchdog monitors brain health and manages restart / sleep.
type Watchdog struct {
	APIURL         string
	DaemonCmd      []string
	HealthInterval time.Duration
	SleepHour      int // local hour 0-23; -1 disables
	SleepMinute    int
	Client         *http.Client
	Alert          AlertFunc
	Now            func() time.Time // injectable clock

	mu           sync.Mutex
	cmd          *exec.Cmd
	Restarts     atomic.Int32
	lastSleepDay int // year*1000+yday of last sleep trigger
	started      bool
}

// ConfigFromEnv builds a Watchdog from environment variables.
func ConfigFromEnv() *Watchdog {
	api := os.Getenv(envAPIURL)
	if api == "" {
		api = defaultAPIURL
	}
	intervalMS := defaultHealthMS
	if v := os.Getenv(envHealthInterval); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n > 0 {
			intervalMS = n
		}
	}
	hour, minute := -1, 0
	if v := os.Getenv(envSleepHour); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n >= 0 && n <= 23 {
			hour = n
		}
	}
	if v := os.Getenv(envSleepMinute); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n >= 0 && n <= 59 {
			minute = n
		}
	}

	var daemonCmd []string
	if raw := strings.TrimSpace(os.Getenv(envDaemonCmd)); raw != "" {
		daemonCmd = splitCmd(raw)
	}

	w := &Watchdog{
		APIURL:         strings.TrimRight(api, "/"),
		DaemonCmd:      daemonCmd,
		HealthInterval: time.Duration(intervalMS) * time.Millisecond,
		SleepHour:      hour,
		SleepMinute:    minute,
		Client:         &http.Client{Timeout: 400 * time.Millisecond},
		Now:            time.Now,
		Alert:          defaultAlert,
	}
	if wh := os.Getenv(envAlertWebhook); wh != "" {
		w.Alert = webhookAlert(wh, w.Client)
	}
	return w
}

func splitCmd(raw string) []string {
	// Simple whitespace split; callers should pass a single executable + args.
	return strings.Fields(raw)
}

func defaultAlert(msg string) {
	fmt.Fprintf(os.Stderr, "watchdog alert: %s\n", msg)
}

func webhookAlert(url string, client *http.Client) AlertFunc {
	return func(msg string) {
		defaultAlert(msg)
		body, _ := json.Marshal(map[string]string{"text": msg})
		req, err := http.NewRequest(http.MethodPost, url, bytes.NewReader(body))
		if err != nil {
			return
		}
		req.Header.Set("Content-Type", "application/json")
		resp, err := client.Do(req)
		if err != nil {
			return
		}
		io.Copy(io.Discard, resp.Body)
		resp.Body.Close()
	}
}

// Healthy returns true when GET /health succeeds with 2xx.
func (w *Watchdog) Healthy(ctx context.Context) bool {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, w.APIURL+"/health", nil)
	if err != nil {
		return false
	}
	resp, err := w.Client.Do(req)
	if err != nil {
		return false
	}
	defer resp.Body.Close()
	io.Copy(io.Discard, resp.Body)
	return resp.StatusCode >= 200 && resp.StatusCode < 300
}

// Restart stops any tracked child and starts BRAIN_DAEMON_CMD.
func (w *Watchdog) Restart(ctx context.Context) error {
	w.mu.Lock()
	defer w.mu.Unlock()

	if w.cmd != nil && w.cmd.Process != nil {
		_ = w.cmd.Process.Kill()
		_, _ = w.cmd.Process.Wait()
		w.cmd = nil
	}

	if len(w.DaemonCmd) == 0 {
		return fmt.Errorf("BRAIN_DAEMON_CMD not set")
	}

	cmd := exec.CommandContext(ctx, w.DaemonCmd[0], w.DaemonCmd[1:]...)
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	if err := cmd.Start(); err != nil {
		return err
	}
	w.cmd = cmd
	w.Restarts.Add(1)
	w.started = true

	// Reap in background so zombie processes don't accumulate.
	go func(c *exec.Cmd) {
		_ = c.Wait()
	}(cmd)

	return nil
}

// EnsureRunning restarts the daemon when health checks fail.
func (w *Watchdog) EnsureRunning(ctx context.Context) error {
	if w.Healthy(ctx) {
		return nil
	}
	if w.Alert != nil {
		w.Alert("brain daemon unhealthy; restarting")
	}
	return w.Restart(ctx)
}

// TriggerSleep POSTs /sleep/trigger.
func (w *Watchdog) TriggerSleep(ctx context.Context) error {
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, w.APIURL+"/sleep/trigger", nil)
	if err != nil {
		return err
	}
	resp, err := w.Client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	io.Copy(io.Discard, resp.Body)
	if resp.StatusCode >= 300 {
		return fmt.Errorf("sleep trigger status %d", resp.StatusCode)
	}
	return nil
}

// maybeSleep fires sleep once per local calendar day at the configured time.
func (w *Watchdog) maybeSleep(ctx context.Context) {
	if w.SleepHour < 0 {
		return
	}
	now := w.Now()
	if now.Hour() != w.SleepHour || now.Minute() != w.SleepMinute {
		return
	}
	dayKey := now.Year()*1000 + now.YearDay()
	w.mu.Lock()
	if w.lastSleepDay == dayKey {
		w.mu.Unlock()
		return
	}
	w.lastSleepDay = dayKey
	w.mu.Unlock()

	if err := w.TriggerSleep(ctx); err != nil && w.Alert != nil {
		w.Alert(fmt.Sprintf("sleep trigger failed: %v", err))
	}
}

// Run loops until ctx is cancelled.
func (w *Watchdog) Run(ctx context.Context) {
	ticker := time.NewTicker(w.HealthInterval)
	defer ticker.Stop()

	// Immediate check so dead daemons restart without waiting a full interval.
	_ = w.EnsureRunning(ctx)
	w.maybeSleep(ctx)

	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			_ = w.EnsureRunning(ctx)
			w.maybeSleep(ctx)
		}
	}
}
