// Command spellbench-gorge-env serves the Spellbench v2 environment role over stdio.
package main

import (
	"bufio"
	"flag"
	"fmt"
	"os"

	"github.com/jackmaiorino/spellbench/engines/gorge/internal/catalog"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/gorgepin"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/server"
)

func main() {
	corpus := flag.String("corpus", os.Getenv("GORGE_CARDS"), "compiled Forge corpus directory (never shipped)")
	rev := flag.String("source-revision", "", "adapter source revision reported in hello_ok")
	autoPay := flag.Bool("auto-pay", false, "offer native payment-plan casts and declare engine_autopay")
	search := flag.Bool("search", false, "offer actor-redacted native search history (requires a published identity audit)")
	flag.Parse()
	reg, err := gorgepin.OpenRegistry(*corpus)
	if err != nil {
		fmt.Fprintln(os.Stderr, "spellbench-gorge-env:", err)
		os.Exit(2)
	}
	if err := catalog.Preflight(reg); err != nil {
		fmt.Fprintln(os.Stderr, "spellbench-gorge-env:", err)
		os.Exit(2)
	}
	var sr *string
	if *rev != "" {
		sr = rev
	}
	out := bufio.NewWriter(os.Stdout)
	w := &flushWriter{out}
	srv := server.New(reg, sr)
	if *autoPay {
		srv.EnableAutoPay()
	}
	if *search {
		srv.EnableSearch()
	}
	if err := server.Serve(os.Stdin, w, srv); err != nil {
		fmt.Fprintln(os.Stderr, "spellbench-gorge-env:", err)
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
