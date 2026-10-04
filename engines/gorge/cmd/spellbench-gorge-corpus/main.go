// Command spellbench-gorge-corpus freezes verified card sources into a single
// runtime registry file for the reference launcher's existing file-pinning path.
package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"

	"github.com/jackmaiorino/spellbench/engines/gorge/internal/gorgepin"
)

func main() {
	dir := flag.String("corpus", os.Getenv("GORGE_CARDS"), "pinned Forge source corpus")
	out := flag.String("out", "", "new registry file in the job's registered artifact tree")
	flag.Parse()
	if *out == "" {
		fmt.Fprintln(os.Stderr, "-out is required")
		os.Exit(2)
	}
	receipt, err := gorgepin.FreezeRegistry(*dir, *out)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}
	if err := json.NewEncoder(os.Stdout).Encode(receipt); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
