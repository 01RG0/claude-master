package hookshim_test

import (
	"bytes"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"testing"
	"time"
)

// TestColdStartLatency builds a static hookshim and measures median wall time
// for cold-ish exec with missing socket (fail-open path — typical when brain is down).
// Method: CGO_ENABLED=0 go build -ldflags="-s -w"; 50 timed execs; report p50/p95.
func TestColdStartLatency(t *testing.T) {
	root := findRepoRoot(t)
	bin := filepath.Join(t.TempDir(), "hookshim")
	build := exec.Command("go", "build", "-ldflags", "-s -w", "-o", bin, "./hookshim")
	build.Dir = root
	build.Env = append(os.Environ(), "CGO_ENABLED=0")
	if out, err := build.CombinedOutput(); err != nil {
		t.Fatalf("build: %v\n%s", err, out)
	}

	sock := filepath.Join(t.TempDir(), "missing.sock")
	const n = 50
	samples := make([]time.Duration, 0, n)
	payload := []byte(`{"hook_event_name":"PreToolUse","tool_name":"Bash","session_id":"bench"}`)

	// Warm one run so page-cache effects stabilize for subsequent samples.
	runOnce(t, bin, sock, payload)

	for i := 0; i < n; i++ {
		start := time.Now()
		code := runOnce(t, bin, sock, payload)
		elapsed := time.Since(start)
		if code != 0 {
			t.Fatalf("iter %d exit=%d", i, code)
		}
		samples = append(samples, elapsed)
	}

	sort.Slice(samples, func(i, j int) bool { return samples[i] < samples[j] })
	p50 := samples[n/2]
	p95 := samples[(n*95)/100]
	min := samples[0]
	max := samples[n-1]

	msg := fmt.Sprintf(
		"hookshim cold-start (fail-open, n=%d): min=%v p50=%v p95=%v max=%v target=<3ms",
		n, min, p50, p95, max,
	)
	t.Log(msg)
	fmt.Println(msg)

	// Soft assert: p50 under 10ms is required for usability; card target is <3ms.
	if p50 > 10*time.Millisecond {
		t.Fatalf("p50 cold-start %v exceeds 10ms usability budget", p50)
	}
	if p50 > 3*time.Millisecond {
		t.Logf("NOTE: p50 %v exceeds aspirational <3ms target (still usable)", p50)
	}
}

func runOnce(t *testing.T, bin, sock string, payload []byte) int {
	t.Helper()
	cmd := exec.Command(bin)
	cmd.Env = append(os.Environ(), "CLAUDE_BRAIN_SOCKET="+sock, "CLAUDE_BRAIN_TIMEOUT_MS=50")
	cmd.Stdin = bytes.NewReader(payload)
	cmd.Stdout = &bytes.Buffer{}
	cmd.Stderr = &bytes.Buffer{}
	err := cmd.Run()
	if err == nil {
		return 0
	}
	if ee, ok := err.(*exec.ExitError); ok {
		return ee.ExitCode()
	}
	t.Fatalf("run: %v", err)
	return -1
}

func findRepoRoot(t *testing.T) string {
	t.Helper()
	wd, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	dir := wd
	for i := 0; i < 6; i++ {
		if _, err := os.Stat(filepath.Join(dir, "go.mod")); err == nil {
			if _, err := os.Stat(filepath.Join(dir, "hookshim")); err == nil {
				return dir
			}
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			break
		}
		dir = parent
	}
	// When run from tests/hookshim, repo root is ../..
	candidate := filepath.Clean(filepath.Join(wd, "../.."))
	if _, err := os.Stat(filepath.Join(candidate, "hookshim")); err == nil {
		return candidate
	}
	t.Fatalf("could not find repo root from %s", wd)
	return ""
}
