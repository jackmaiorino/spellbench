// Command spellbench-gorge-audit lists the pinned benchmark pool's behavior
// symbols, including token dependencies. It emits no card scripts or IR.
package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"sort"
	"strings"

	"github.com/adams-shaun/gorge/cards"
	"github.com/adams-shaun/gorge/effects"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/catalog"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/gorgepin"
)

type entry struct {
	Name       string   `json:"name"`
	Primitives []string `json:"primitives"`
}

func census(reg *cards.Registry) ([]entry, []entry, []string, error) {
	if err := catalog.Preflight(reg); err != nil {
		return nil, nil, nil, err
	}
	var pool, tokens []entry
	primitives := map[string]bool{}
	wanted, visited := map[string]bool{}, map[string]bool{}
	inspect := func(card *cards.Card) {
		for _, primitive := range card.Primitives() {
			primitives[primitive] = true
			// Investigate uses this fixed native dependency rather than a
			// TokenScript parameter (effects/investigate.go).
			if primitive == "api:Investigate" {
				wanted["c_a_clue_draw"] = true
			}
		}
		for _, face := range card.Faces {
			seen := map[*cards.SA]bool{}
			var walk func(*cards.SA)
			walk = func(sa *cards.SA) {
				if sa == nil || seen[sa] {
					return
				}
				seen[sa] = true
				for _, name := range strings.Split(sa.Params["TokenScript"], ",") {
					if name = strings.TrimSpace(name); name != "" {
						wanted[name] = true
					}
				}
				walk(sa.Sub)
			}
			for _, sa := range face.Abilities {
				walk(sa)
			}
			for _, trigger := range face.Triggers {
				walk(trigger.Effect)
			}
			for _, replacement := range face.Repls {
				walk(replacement.With)
			}
			face.EachSVarAbility(walk)
		}
	}
	for _, name := range catalog.PoolNames() {
		card, ok := reg.Lookup(name)
		if !ok {
			return nil, nil, nil, fmt.Errorf("missing pool card %q", name)
		}
		pool = append(pool, entry{Name: name, Primitives: card.Primitives()})
		inspect(card)
	}
	for {
		var pending []string
		for name := range wanted {
			if !visited[name] {
				pending = append(pending, name)
			}
		}
		if len(pending) == 0 {
			break
		}
		sort.Strings(pending)
		for _, name := range pending {
			card := reg.Tokens[name]
			if card == nil {
				return nil, nil, nil, fmt.Errorf("missing token %q", name)
			}
			if missing := reg.Unsupported(card, effects.Supported()); len(missing) != 0 {
				return nil, nil, nil, fmt.Errorf("token %q needs %v", name, missing)
			}
			visited[name] = true
			tokens = append(tokens, entry{Name: name, Primitives: card.Primitives()})
			inspect(card)
		}
	}
	sort.Slice(tokens, func(i, j int) bool { return tokens[i].Name < tokens[j].Name })
	var symbols []string
	for name := range primitives {
		symbols = append(symbols, name)
	}
	sort.Strings(symbols)
	return pool, tokens, symbols, nil
}

func main() {
	registry := flag.String("registry", "", "hash-pinned runtime registry")
	digest := flag.String("registry-sha256", "", "expected registry SHA-256")
	flag.Parse()
	reg, err := gorgepin.OpenFrozenRegistry(*registry, *digest)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}
	pool, tokens, symbols, err := census(reg)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}
	result := map[string]any{
		"schema": "spellbench-gorge-card-pool-census/v1", "gorge_commit": gorgepin.GorgeCommit,
		"forge_commit": gorgepin.ForgeRef, "registry_sha256": strings.ToLower(*digest),
		"cards": pool, "tokens": tokens, "primitives": symbols,
	}
	if err := json.NewEncoder(os.Stdout).Encode(result); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
