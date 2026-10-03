// Command gorgequal runs the adapter's qualification: games per deck and
// pairing through the mini-host, with determinism, validator, resample,
// leak, semantic-consistency, parity and throughput checks.
package main

import (
	"bytes"
	"encoding/json"
	"flag"
	"fmt"
	"maps"
	"math/rand/v2"
	"os"
	"reflect"
	"runtime"
	"slices"
	"strings"
	"sync"
	"time"

	"github.com/adams-shaun/gorge/cards"
	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/spellbench-strategies"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/agent"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/catalog"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/gorgepin"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/minihost"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/observe"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/server"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/session"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/validate"
)

type options struct {
	games, resample, workers  int
	audit                     bool
	policyKeys                []string // nil: every integrated strategy
	registryPath, registrySHA string
}

type Totals struct {
	CompletedGames                                           int
	Games, Halts, Truncations, Violations, DigestMismatch    int
	ResampleChecks, ResampleFailures, LeakHits, Inconsistent int
	ParityCompared, ParityMismatch, Fallbacks, Forced        int
	GamesPerSecond                                           float64
	GoMemoryMB                                               uint64
}

// DeckGate counts, per deck, the native decisions the gorge agents answered
// and those with a forced or fallback substep, with their reasons. Parity
// never compares those decisions, so the gate bounds them instead.
type DeckGate struct {
	AgentNatives, ForcedNatives, FallbackNatives int
	Reasons                                      map[string]int
}

// Pass: forced plus fallback native decisions stay under 1% of the deck's
// agent native decisions.
func (g DeckGate) Pass() bool {
	return 100*(g.ForcedNatives+g.FallbackNatives) < g.AgentNatives || g.AgentNatives == 0
}

type Report struct {
	Policies       []string                  `json:"policies"`
	Totals         Totals                    `json:"totals"`
	Gates          map[string]DeckGate       `json:"gates"`
	PolicyGates    map[string]DeckGate       `json:"policy_gates"`
	SearchCoverage map[string]SearchCoverage `json:"search_coverage"`
	Rows           []map[string]any          `json:"rows"`
}

// SearchCoverage distinguishes native search delegation from adapter mapping
// fallbacks. A clean mapping alone does not prove that search ran.
type SearchCoverage = agent.SearchCoverage

func mergeSearch(dst *SearchCoverage, src SearchCoverage) {
	dst.Natives += src.Natives
	dst.Eligible += src.Eligible
	dst.Attempted += src.Attempted
	dst.Covered += src.Covered
	dst.Attempts += src.Attempts
	dst.Accepted += src.Accepted
	dst.Worlds += src.Worlds
	dst.Rollouts += src.Rollouts
	dst.Submits += src.Submits
	dst.Terminal += src.Terminal
	dst.Capped += src.Capped
	dst.Redealt += src.Redealt
	dst.ReconstructionAttempts += src.ReconstructionAttempts
	dst.ReconstructionSubmits += src.ReconstructionSubmits
	dst.ReconstructionNodes += src.ReconstructionNodes
	dst.ReconstructionBudgetExhausted += src.ReconstructionBudgetExhausted
	if dst.RedealRefusals == nil {
		dst.RedealRefusals = map[string]int{}
	}
	for k, n := range src.RedealRefusals {
		dst.RedealRefusals[k] += n
	}
	if dst.Reasons == nil {
		dst.Reasons = map[string]int{}
	}
	if dst.Kinds == nil {
		dst.Kinds = map[string]int{}
	}
	for k, n := range src.Reasons {
		dst.Reasons[k] += n
	}
	for k, n := range src.Kinds {
		dst.Kinds[k] += n
	}
}

func searchCoverage(records map[uint64]*agent.Record) SearchCoverage {
	return agent.SummarizeSearch(records)
}

func (r Report) Clean() bool {
	t := r.Totals
	for _, p := range r.Policies {
		if strings.HasPrefix(p, "search") {
			redealt := 0
			for _, d := range catalog.Decks() {
				coverage := r.SearchCoverage[d.CatalogID+"/"+p]
				if !coverage.Pass() {
					return false
				}
				redealt += coverage.Redealt
				if strings.HasSuffix(p, "redeal") && (coverage.ReconstructionBudgetExhausted != 0 || len(coverage.RedealRefusals) != 0) {
					return false
				}
			}
			if strings.HasSuffix(p, "redeal") && redealt == 0 {
				return false
			}
		}
	}
	for _, g := range r.Gates {
		if !g.Pass() {
			return false
		}
	}
	for _, g := range r.PolicyGates {
		if !g.Pass() {
			return false
		}
	}
	for _, s := range r.SearchCoverage {
		if !s.Pass() {
			return false
		}
	}
	return t.Games > 0 && t.Halts == 0 && t.Violations == 0 && t.DigestMismatch == 0 &&
		t.Truncations == 0 && t.ResampleFailures == 0 && t.LeakHits == 0 && t.Inconsistent == 0 && t.ParityMismatch == 0
}

func mergeGate(dst *DeckGate, src DeckGate) {
	if dst.Reasons == nil {
		dst.Reasons = map[string]int{}
	}
	dst.AgentNatives += src.AgentNatives
	dst.ForcedNatives += src.ForcedNatives
	dst.FallbackNatives += src.FallbackNatives
	for k, v := range src.Reasons {
		dst.Reasons[k] += v
	}
}

func policyPairings(keys []string) []string {
	out := []string{"uniform/uniform", "bot/lethal-pressure"}
	for _, p := range agent.Policies() {
		if keys == nil || slices.Contains(keys, p.Key) {
			out = append(out, p.Key+"/uniform")
		}
	}
	return out
}

// auditLink runs a resample check before every k-th step it forwards.
type auditLink struct {
	srv            *server.Server
	r              *rand.Rand
	every, n       int
	checks, failed int
}

func (a *auditLink) Round(req []byte) ([]byte, error) {
	if a.every > 0 && bytes.Contains(req, []byte(`"request_type":"step"`)) {
		if a.n++; a.n%a.every == 0 {
			a.checks++
			if err := a.srv.ResampleCheck(a.r); err != nil {
				fmt.Fprintln(os.Stderr, "gorgequal:", err)
				a.failed++
			}
		}
	}
	return a.srv.Handle(req), nil
}

func link(name string, reg *cards.Registry) minihost.Link {
	if name == "uniform" {
		return &minihost.Uniform{}
	}
	a, err := agent.New(name)
	if err != nil {
		panic(err)
	}
	a.SetRegistry(reg)
	return a
}

func sameIntent(k decision.Kind, got, want decision.Intent) bool {
	g, w := slices.Clone(got.Choices), slices.Clone(want.Choices)
	if k == decision.KAttackers || k == decision.KBlockers {
		slices.Sort(g)
		slices.Sort(w)
	}
	return slices.Equal(g, w) && reflect.DeepEqual(got.Payment, want.Payment) && (len(want.Rest) == 0 || slices.Equal(got.Rest, want.Rest))
}

// parity compares each realized native decision of an agent seat with the
// agent's record of it: the top-level intent and every folded follow-up
// answer. Decisions the agent answered forced or by fallback are skipped;
// the deck gate bounds them.
func parity(realized []session.Realized, seats [2]minihost.Link) (compared, mismatched int) {
	for _, r := range realized {
		a, ok := seats[r.Seat].(*agent.Server)
		if !ok {
			continue
		}
		rec := a.Records()[r.Native]
		if rec != nil && (rec.Forced > 0 || rec.Fallbacks > 0) {
			continue
		}
		compared++
		same := rec != nil && sameIntent(r.Kind, r.Intent, rec.Intent)
		for key, got := range r.Followups {
			if !same {
				break
			}
			want, ok := rec.Followups[key]
			same = ok && slices.Equal(got.Choices, want.Choices)
		}
		if !same {
			mismatched++
			fmt.Fprintf(os.Stderr, "gorgequal: parity seat %d native %d %s: realized %v %v, planned %+v\n",
				r.Seat, r.Native, r.Kind, r.Intent, r.Followups, rec)
		}
	}
	return compared, mismatched
}

type job struct {
	i       uint64
	deck    catalog.Deck
	pairing string
}

func qualify(o options) (Report, error) {
	reg, err := gorgepin.OpenInput(os.Getenv("GORGE_CARDS"), o.registryPath, o.registrySHA)
	if err != nil {
		return Report{}, err
	}
	kinds := map[string]bool{}
	for _, k := range server.DecisionKinds {
		kinds[k] = true
	}
	var jobs []job
	for _, d := range catalog.Decks() {
		for _, p := range policyPairings(o.policyKeys) {
			for g := 0; g < o.games; g++ {
				jobs = append(jobs, job{uint64(len(jobs)), d, p})
			}
		}
	}
	play := func(j job, audit bool) (minihost.Result, *auditLink, [2]minihost.Link, error) {
		srv := server.New(reg, nil)
		srv.EnableAutoPay()
		srv.SetAudit(audit)
		al := &auditLink{srv: srv, r: rand.New(rand.NewPCG(j.i, 7))}
		if audit {
			al.every = o.resample
		}
		names := strings.Split(j.pairing, "/")
		exts := []string{"x_gorge_view_v1"}
		if strings.HasPrefix(names[0], "search") || strings.HasPrefix(names[1], "search") {
			srv.EnableSearch()
			exts = append(exts, strategies.Extension)
		}
		seats := [2]minihost.Link{link(names[0], reg), link(names[1], reg)}
		h := &minihost.Host{RunSecret: []byte("gorge-qualification-run-secret!!"), Engine: al,
			Profile:  validate.Profile{Kinds: kinds, Flags: observe.Flags, Extensions: map[string]bool{}},
			MaxSteps: 100000, MaxDecisions: 49999}
		res, err := h.Play(j.i, j.deck, "london", exts, seats)
		return res, al, seats, err
	}
	rep := Report{Gates: map[string]DeckGate{}, PolicyGates: map[string]DeckGate{}, SearchCoverage: map[string]SearchCoverage{}}
	for _, p := range agent.Policies() {
		if o.policyKeys == nil || slices.Contains(o.policyKeys, p.Key) {
			rep.Policies = append(rep.Policies, p.Key)
		}
	}
	for _, key := range o.policyKeys {
		if !slices.Contains(rep.Policies, key) {
			return Report{}, fmt.Errorf("unknown qualification policy %q", key)
		}
	}
	var mu sync.Mutex
	start := time.Now()
	work := make(chan job)
	var wg sync.WaitGroup
	for w := 0; w < max(1, o.workers); w++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for j := range work {
				a, al, seats, errA := play(j, o.audit)
				b, _, _, errB := play(j, false)
				fb, forced := 0, 0
				gate := DeckGate{Reasons: map[string]int{}}
				policyGates := map[string]DeckGate{}
				searchGates := map[string]SearchCoverage{}
				for _, l := range seats {
					ag, ok := l.(*agent.Server)
					if !ok {
						continue
					}
					fb += ag.Fallbacks()
					forced += ag.Forced()
					pg := DeckGate{Reasons: map[string]int{}}
					for _, rec := range ag.Records() {
						pg.AgentNatives++
						switch {
						case rec.Fallbacks > 0:
							pg.FallbackNatives++
						case rec.Forced > 0:
							pg.ForcedNatives++
						}
						if rec.Reason != "" {
							pg.Reasons[rec.Reason]++
						}
					}
					mergeGate(&gate, pg)
					key := j.deck.CatalogID + "/" + ag.PolicyKey()
					old := policyGates[key]
					mergeGate(&old, pg)
					policyGates[key] = old
					if strings.HasPrefix(ag.PolicyKey(), "search") {
						searchGates[key] = searchCoverage(ag.Records())
					}
				}
				compared, mismatched := parity(al.srv.Realized(), seats)
				leaks, inconsistent := al.srv.Leaks(), al.srv.Inconsistent()
				row := map[string]any{"deck": j.deck.CatalogID, "pairing": j.pairing, "game": j.i, "steps": a.Steps,
					"classification": a.Terminal.Classification, "reason": a.Terminal.Reason,
					"outcome": a.Terminal.Outcome, "digest": a.Digest, "leaks": leaks, "inconsistent": inconsistent,
					"parity_mismatch": mismatched, "fallbacks": fb, "forced": forced, "search_coverage": searchGates}
				mu.Lock()
				t := &rep.Totals
				t.Games++
				if errA == nil && a.Terminal.Classification == "natural" {
					t.CompletedGames++
				}
				if errB == nil && b.Terminal.Classification == "natural" {
					t.CompletedGames++
				}
				switch {
				case errA != nil:
					t.Violations++
					row["error"] = errA.Error()
				case a.Terminal.Classification == "halted":
					t.Halts++
					row["halt"] = a.Terminal.Reason
				case a.Terminal.Classification == "truncated":
					t.Truncations++
				}
				if errA == nil && (errB != nil || a.Digest != b.Digest) {
					t.DigestMismatch++
				}
				t.ResampleChecks += al.checks
				t.ResampleFailures += al.failed
				t.LeakHits += leaks
				t.Inconsistent += inconsistent
				t.ParityCompared += compared
				t.ParityMismatch += mismatched
				t.Fallbacks += fb
				t.Forced += forced
				dg := rep.Gates[j.deck.CatalogID]
				if dg.Reasons == nil {
					dg.Reasons = map[string]int{}
				}
				dg.AgentNatives += gate.AgentNatives
				dg.ForcedNatives += gate.ForcedNatives
				dg.FallbackNatives += gate.FallbackNatives
				for k, v := range gate.Reasons {
					dg.Reasons[k] += v
				}
				rep.Gates[j.deck.CatalogID] = dg
				for key, pg := range policyGates {
					combined := rep.PolicyGates[key]
					mergeGate(&combined, pg)
					rep.PolicyGates[key] = combined
				}
				for key, sg := range searchGates {
					combined := rep.SearchCoverage[key]
					mergeSearch(&combined, sg)
					rep.SearchCoverage[key] = combined
				}
				rep.Rows = append(rep.Rows, row)
				mu.Unlock()
			}
		}()
	}
	for _, j := range jobs {
		work <- j
	}
	close(work)
	wg.Wait()
	slices.SortFunc(rep.Rows, func(a, b map[string]any) int {
		x, y := a["game"].(uint64), b["game"].(uint64)
		if x < y {
			return -1
		}
		if x > y {
			return 1
		}
		return 0
	})
	rep.Totals.GamesPerSecond = float64(rep.Totals.CompletedGames) / time.Since(start).Seconds()
	var ms runtime.MemStats
	runtime.ReadMemStats(&ms)
	rep.Totals.GoMemoryMB = ms.Sys >> 20
	return rep, nil
}

func main() {
	var o options
	flag.IntVar(&o.games, "games", 4, "games per deck and pairing")
	flag.IntVar(&o.resample, "resample", 7, "run the resample self-check before every K-th step (0: never)")
	flag.IntVar(&o.workers, "workers", max(1, runtime.NumCPU()/2), "concurrent games")
	flag.BoolVar(&o.audit, "audit", true, "leak scan, consistency, parity and resample checks on the first run of each game")
	policies := flag.String("policies", "all", "all integrated policies, or an explicit comma-separated subset recorded in the report")
	flag.StringVar(&o.registryPath, "registry", "", "frozen registry file")
	flag.StringVar(&o.registrySHA, "registry-sha256", "", "expected frozen registry SHA-256")
	outPath := flag.String("out", "gorgequal-report.json", "report path")
	flag.Parse()
	if *policies != "all" {
		o.policyKeys = strings.Split(*policies, ",")
	}
	rep, err := qualify(o)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	b, _ := json.MarshalIndent(rep, "", " ")
	if err := os.WriteFile(*outPath, b, 0o644); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	t := rep.Totals
	fmt.Printf("games %d halts %d truncated %d violations %d digest_mismatch %d resample_failed %d/%d leak_hits %d inconsistent %d parity_mismatch %d/%d fallbacks %d forced %d games/s %.2f clean=%v\n",
		t.Games, t.Halts, t.Truncations, t.Violations, t.DigestMismatch, t.ResampleFailures, t.ResampleChecks,
		t.LeakHits, t.Inconsistent, t.ParityMismatch, t.ParityCompared, t.Fallbacks, t.Forced, t.GamesPerSecond, rep.Clean())
	for _, d := range slices.Sorted(maps.Keys(rep.Gates)) {
		g := rep.Gates[d]
		fmt.Printf("gate %s: %d agent native decisions, %d forced, %d fallback, pass=%v\n", d, g.AgentNatives, g.ForcedNatives, g.FallbackNatives, g.Pass())
	}
	for _, key := range slices.Sorted(maps.Keys(rep.SearchCoverage)) {
		s := rep.SearchCoverage[key]
		fmt.Printf("search %s: eligible %d attempted %d covered %d worlds %d rollouts %d pass=%v\n",
			key, s.Eligible, s.Attempted, s.Covered, s.Worlds, s.Rollouts, s.Pass())
	}
	if !rep.Clean() {
		os.Exit(1)
	}
}
