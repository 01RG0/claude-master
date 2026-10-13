// keystore.go — encrypted runtime key store (rewrite).
//
// Runtime-added keys (POST /v1/admin/keys) persist encrypted at rest:
//   - Windows: DPAPI CryptProtectData (user scope) — keystore_windows.go
//   - other OS: base64 file with 0600 perms + loud warning (not encrypted;
//     set secrets via env instead). See docs/adding-a-provider.md.
//
// The file never holds plaintext on Windows. Nothing here is ever logged.
package gateway

import (
	"encoding/base64"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
)

// KeystoreFile is the encrypted blob map on disk.
type KeystoreFile struct {
	Version int                         `json:"version"`
	Entries map[string]map[string]string `json:"entries"` // provider -> label -> protected b64
}

func keystorePath() (string, error) {
	dir, err := os.UserConfigDir()
	if err != nil || dir == "" {
		dir = os.TempDir()
	}
	p := filepath.Join(dir, "claude-master", "keys.json")
	return p, nil
}

// Protect encrypts one secret (platform implementation).
func Protect(plain []byte) ([]byte, error) { return protectPlatform(plain) }

// Unprotect decrypts one secret (platform implementation).
func Unprotect(blob []byte) ([]byte, error) { return unprotectPlatform(blob) }

// KeystoreSave persists entries (plaintext in memory only).
func KeystoreSave(entries map[string]map[string]string) error {
	path, err := keystorePath()
	if err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return err
	}
	out := KeystoreFile{Version: 1, Entries: map[string]map[string]string{}}
	for prov, labels := range entries {
		out.Entries[prov] = map[string]string{}
		for label, secret := range labels {
			blob, err := Protect([]byte(secret))
			if err != nil {
				return fmt.Errorf("protecting %s/%s: %w", prov, label, err)
			}
			out.Entries[prov][label] = base64.StdEncoding.EncodeToString(blob)
		}
	}
	b, _ := json.MarshalIndent(out, "", "  ")
	return os.WriteFile(path, b, 0o600)
}

// KeystoreLoad reads entries back into memory.
func KeystoreLoad() (map[string]map[string]string, error) {
	path, err := keystorePath()
	if err != nil {
		return nil, err
	}
	b, err := os.ReadFile(path)
	if err != nil {
		if os.IsNotExist(err) {
			return map[string]map[string]string{}, nil
		}
		return nil, err
	}
	var f KeystoreFile
	if err := json.Unmarshal(b, &f); err != nil {
		return nil, err
	}
	out := map[string]map[string]string{}
	for prov, labels := range f.Entries {
		out[prov] = map[string]string{}
		for label, enc := range labels {
			blob, err := base64.StdEncoding.DecodeString(enc)
			if err != nil {
				return nil, fmt.Errorf("decoding %s/%s: %w", prov, label, err)
			}
			plain, err := Unprotect(blob)
			if err != nil {
				return nil, fmt.Errorf("unprotecting %s/%s: %w", prov, label, err)
			}
			out[prov][label] = string(plain)
		}
	}
	return out, nil
}
