package main

import (
	"context"
	"os"
	"os/signal"
	"syscall"
)

func main() {
	w := ConfigFromEnv()
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	w.Run(ctx)
}
