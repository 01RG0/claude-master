// Command gateway is the Anthropic-compatible proxy binary.
//
// Usage:
//
//	gateway --config gateway/config.json
//
// The gateway reads a JSON config (see gateway/config.json), routes
// POST /v1/messages to free providers with key-pool cascade + Thompson
// bandit, and exposes /health and /v1/outcome. Point Claude Code at it:
//
//	ANTHROPIC_BASE_URL=http://localhost:8080 ANTHROPIC_API_KEY=dummy claude
package main

import (
	"context"
	"flag"
	"log"
	"os"
	"os/signal"
	"path/filepath"
	"strings"
	"syscall"

	"github.com/01RG0/claude-master/gateway"
)

func main() {
	configPath := flag.String("config", "gateway/config.json", "path to JSON gateway config")
	logReqs := flag.String("log-requests", "", "directory for redacted request logs (overrides config)")
	listen := flag.String("listen", "", "listen addr override (default from config)")
	dotenv := flag.String("env-file", "", ".env file to import (default: auto-find repo .env)")
	flag.Parse()

	finalConfigPath := *configPath
	if envCfg := os.Getenv("CLAUDE_MASTER_GATEWAY_CONFIG"); envCfg != "" && finalConfigPath == "gateway/config.json" {
		finalConfigPath = envCfg
	}

	loadDotEnv(*dotenv, finalConfigPath)

	cfg, err := gateway.LoadConfig(finalConfigPath)
	if err != nil {
		log.Fatalf("gateway: %v", err)
	}
	if *logReqs != "" {
		cfg.Logging = &gateway.LoggingConfig{RequestsDir: *logReqs, MaxBody: 4096}
	}
	if *listen != "" {
		cfg.ListenAddr = *listen
	}
	srv := gateway.NewServer(cfg)
	srv.ApplyRoutingState(gateway.CapsPathBesideConfig(finalConfigPath))

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	if err := srv.ListenAndServe(ctx); err != nil {
		log.Fatalf("gateway: %v", err)
	}
}

// loadDotEnv imports KEY=VALUE from a .env file into process env so a fresh
// clone works with one start command. Values are never printed. Explicit
// --env-file wins; otherwise repo-root .env next to the config, then ./.env.
// Existing process env always wins over the file.
func loadDotEnv(explicit, configPath string) {
	cands := []string{}
	if explicit != "" {
		cands = append(cands, explicit)
	}
	cands = append(cands,
		filepath.Join(filepath.Dir(configPath), "..", ".env"),
		filepath.Join(filepath.Dir(configPath), ".env"),
		".env",
	)
	for _, cand := range cands {
		b, err := os.ReadFile(cand)
		if err != nil {
			continue
		}
		for _, line := range strings.Split(string(b), "\n") {
			line = strings.TrimSpace(line)
			if line == "" || strings.HasPrefix(line, "#") || !strings.Contains(line, "=") {
				continue
			}
			line = strings.TrimSpace(strings.TrimPrefix(line, "export "))
			k, v, _ := strings.Cut(line, "=")
			k = strings.TrimSpace(k)
			v = strings.TrimSpace(strings.Trim(strings.TrimSpace(v), "\"'"))
			if k == "" || v == "" {
				continue
			}
			if _, exists := os.LookupEnv(k); !exists {
				_ = os.Setenv(k, v)
			}
		}
		return
	}
}
