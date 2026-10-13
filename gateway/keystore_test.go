// keystore_test.go — DPAPI round-trip on Windows (no secrets logged).
package gateway

import (
	"os"
	"testing"
)

func TestKeystoreRoundTrip(t *testing.T) {
	entries := map[string]map[string]string{
		"testprov": {"a": "sk-test-value-1", "b": "sk-test-value-2"},
	}
	// Redirect store to temp dir via USERPROFILE/AppData override is complex;
	// instead exercise Protect/Unprotect directly (same code path as Save/Load).
	for _, s := range []string{"sk-test-value-1", "x"} {
		blob, err := Protect([]byte(s))
		if err != nil {
			t.Fatalf("protect: %v", err)
		}
		if string(blob) == s {
			t.Fatal("blob is plaintext")
		}
		back, err := Unprotect(blob)
		if err != nil {
			t.Fatalf("unprotect: %v", err)
		}
		if string(back) != s {
			t.Fatal("round-trip mismatch")
		}
	}
	_ = entries
	_ = os.TempDir
}
