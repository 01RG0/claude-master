package main

import (
	"flag"
	"os"
	"time"
)

func main() {
	sockFlag := flag.String("socket", "", "Unix socket path (POSIX; overrides "+envSocket+")")
	tcpFlag := flag.String("tcp", "", "Hook TCP address host:port (overrides "+envTCP+")")
	timeoutFlag := flag.Int("timeout-ms", 0, "IPC budget in ms (overrides "+envTimeoutMS+")")
	flag.Parse()

	sock := *sockFlag
	if sock == "" {
		sock = socketPath()
	}
	tcp := *tcpFlag
	if tcp == "" {
		tcp = tcpAddr()
	}
	to := dialTimeout()
	if *timeoutFlag > 0 {
		to = time.Duration(*timeoutFlag) * time.Millisecond
	}
	network, addr := defaultEndpoint(sock, tcp)
	os.Exit(runEndpoint(os.Stdin, os.Stdout, network, addr, to))
}
