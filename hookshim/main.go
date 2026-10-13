package main

import (
	"flag"
	"os"
	"time"
)

func main() {
	sockFlag := flag.String("socket", "", "Unix socket path (POSIX; overrides "+envSocket+")")
	tcpFlag := flag.String("tcp", "", "Hook TCP address host:port (overrides "+envTCP+"; in --serve mode: local listen if --host empty)")
	hostFlag := flag.String("host", "", "Hook host local address host:port (overrides "+envHookHost+")")
	serveFlag := flag.Bool("serve", false, "Run persistent keep-alive host instead of one-shot hook")
	timeoutFlag := flag.Int("timeout-ms", 0, "IPC budget in ms (overrides "+envTimeoutMS+")")
	flag.Parse()

	to := dialTimeout()
	if *timeoutFlag > 0 {
		to = time.Duration(*timeoutFlag) * time.Millisecond
	}

	if *serveFlag {
		listen := defaultHostListen(*hostFlag, *tcpFlag)
		sock := *sockFlag
		if sock == "" {
			sock = socketPath()
		}
		upstreamTCP := tcpAddr()
		if *hostFlag != "" && *tcpFlag != "" {
			upstreamTCP = normaliseTCP(*tcpFlag)
		}
		network, addr := defaultEndpoint(sock, upstreamTCP)
		if err := serveHost(listen, network, addr, to); err != nil {
			os.Stderr.WriteString("hookhost: " + err.Error() + "\n")
			os.Exit(1)
		}
		return
	}

	sock := *sockFlag
	if sock == "" {
		sock = socketPath()
	}
	tcp := *tcpFlag
	if tcp == "" {
		tcp = tcpAddr()
	}
	network, addr := defaultEndpoint(sock, tcp)
	host := hookHostAddr(*hostFlag)
	if host == "" {
		os.Exit(runEndpoint(os.Stdin, os.Stdout, network, addr, to))
	}
	os.Exit(runWithHost(os.Stdin, os.Stdout, network, addr, host, to))
}
