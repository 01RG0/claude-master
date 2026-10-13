//go:build !windows

package gateway

import "fmt"

// Non-Windows fallback: NO encryption. Runtime keys should come from env;
// the file backend exists only for API compat and warns loudly.
func protectPlatform(plain []byte) ([]byte, error) {
	if len(plain) == 0 {
		return nil, fmt.Errorf("empty secret")
	}
	return append([]byte("plain:"), plain...), nil
}

func unprotectPlatform(blob []byte) ([]byte, error) {
	if len(blob) <= 6 || string(blob[:6]) != "plain:" {
		return nil, fmt.Errorf("not a fallback blob (was it written on Windows?)")
	}
	return blob[6:], nil
}
