// Command spellbench-gorge-agent serves gorge's shipped policies
// in the Spellbench v2 agent role over stdio.
package main

import (
	"bufio"
	"encoding/json"
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
	registry := flag.String("registry", "", "frozen registry file (search, and the neutral world)")
	registrySHA := flag.String("registry-sha256", "", "expected SHA-256 of the frozen registry")
	auditDir := flag.String("audit-dir", os.Getenv("GORGE_AGENT_AUDIT_DIR"), "optional directory for aggregate policy coverage after the process closes")
	world := flag.String("world", "gorge", "gorge (read x_gorge_view_v1 from gorge's engine) or neutral (translate the v2 observation and candidates of any engine; needs the registry)")
	flag.Parse()
	s, err := agent.New(*policy)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}
	switch *world {
	case "gorge":
	case "neutral":
		reg, err := gorgepin.OpenInput(*corpus, *registry, *registrySHA)
		if err != nil {
			fmt.Fprintln(os.Stderr, "spellbench-gorge-agent:", err)
			os.Exit(2)
		}
		s.SetRegistry(reg)
		if err := s.EnableNeutral(); err != nil {
			fmt.Fprintln(os.Stderr, "spellbench-gorge-agent:", err)
			os.Exit(2)
		}
	default:
		fmt.Fprintf(os.Stderr, "spellbench-gorge-agent: unknown world %q\n", *world)
		os.Exit(2)
	}
	if *world == "gorge" && strings.HasPrefix(s.PolicyKey(), "search") {
		reg, err := gorgepin.OpenInput(*corpus, *registry, *registrySHA)
		if err != nil {
			fmt.Fprintln(os.Stderr, "spellbench-gorge-agent:", err)
			os.Exit(2)
		}
		s.SetRegistry(reg)
	}
	err = agent.Serve(os.Stdin, &flushWriter{bufio.NewWriter(os.Stdout)}, s)
	if *auditDir != "" {
		if auditErr := writeAudit(*auditDir, s.Audit()); auditErr != nil {
			fmt.Fprintln(os.Stderr, "spellbench-gorge-agent audit:", auditErr)
			os.Exit(1)
		}
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, "spellbench-gorge-agent:", err)
		os.Exit(1)
	}
}

func writeAudit(dir string, value agent.PolicyAudit) error {
	if err := os.MkdirAll(dir, 0700); err != nil {
		return err
	}
	f, err := os.CreateTemp(dir, "gorge-agent-*.json")
	if err != nil {
		return err
	}
	if err := json.NewEncoder(f).Encode(value); err != nil {
		f.Close()
		return err
	}
	return f.Close()
}

type flushWriter struct{ w *bufio.Writer }

func (f *flushWriter) Write(p []byte) (int, error) {
	n, err := f.w.Write(p)
	if err == nil {
		err = f.w.Flush()
	}
	return n, err
}
