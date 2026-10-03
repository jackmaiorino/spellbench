// Command spellbench-gorge-agent serves gorge's shipped policies
// in the Spellbench v2 agent role over stdio.
package main

import (
	"bufio"
	"flag"
	"fmt"
	"os"
	"strings"

	"github.com/jackmaiorino/spellbench/engines/gorge/internal/agent"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/gorgepin"
)

func main() {
	policy := flag.String("policy", "bot", "bot, bot-auto-pay, lethal-pressure, lethal-pressure-auto-pay, ar8, blocks, explore, legacy, search, search-mana, search-redeal, search-mana-redeal, or cast-profile (default-bot alias)")
	corpus := flag.String("corpus", os.Getenv("GORGE_CARDS"), "pinned corpus directory (required by search)")
	registry := flag.String("registry", "", "frozen registry file for search")
	registrySHA := flag.String("registry-sha256", "", "expected SHA-256 of the frozen registry")
	flag.Parse()
	s, err := agent.New(*policy)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}
	if strings.HasPrefix(s.PolicyKey(), "search") {
		reg, err := gorgepin.OpenInput(*corpus, *registry, *registrySHA)
		if err != nil {
			fmt.Fprintln(os.Stderr, "spellbench-gorge-agent:", err)
			os.Exit(2)
		}
		s.SetRegistry(reg)
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
