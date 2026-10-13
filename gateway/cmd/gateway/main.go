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
	"syscall"

	"github.com/01RG0/claude-master/gateway"
)

func main() {
	configPath := flag.String("config", "gateway/config.json", "path to JSON gateway config")
	logReqs := flag.String("log-requests", "", "directory for redacted request logs (overrides config)")
	listen := flag.String("listen", "", "listen addr override (default from config)")
	flag.Parse()

	cfg, err := gateway.LoadConfig(*configPath)
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

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	if err := srv.ListenAndServe(ctx); err != nil {
		log.Fatalf("gateway: %v", err)
	}
}
