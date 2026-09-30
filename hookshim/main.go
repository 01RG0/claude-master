package main

import "os"

func main() {
	os.Exit(run(os.Stdin, os.Stdout, socketPath(), dialTimeout()))
}
