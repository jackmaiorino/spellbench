// Command spellbench-gorge-agent serves gorge's default or lethal-pressure bot
// in the Spellbench v2 agent role over stdio.
package main

import (
	"bufio"
	"flag"
	"fmt"
	"os"

	"github.com/jackmaiorino/spellbench/engines/gorge/internal/agent"
)

func main() {
	policy := flag.String("policy", "bot", "bot or lethal-pressure")
	flag.Parse()
	s, err := agent.New(*policy)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}
	if err := agent.Serve(os.Stdin, &flushWriter{bufio.NewWriter(os.Stdout)}, s); err != nil {
		fmt.Fprintln(os.Stderr, "spellbench-gorge-agent:", err)
		os.Exit(1)
	}
}

type flushWriter struct{ w *bufio.Writer }

func (f *flushWriter) Write(p []byte) (int, error) {
	n, err := f.w.Write(p)
	if err == nil {
		err = f.w.Flush()
	}
	return n, err
}
