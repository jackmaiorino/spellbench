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
	"runtime"
	"slices"
	"strings"
	"sync"
	"time"

	"github.com/adams-shaun/gorge/decision"
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
	games, resample, workers int
	audit                    bool
}

type Totals struct {
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
	Totals Totals              `json:"totals"`
	Gates  map[string]DeckGate `json:"gates"`
	Rows   []map[string]any    `json:"rows"`
}

func (r Report) Clean() bool {
	t := r.Totals
	for _, g := range r.Gates {
		if !g.Pass() {
			return false
		}
	}
	return t.Games > 0 && t.Halts == 0 && t.Violations == 0 && t.DigestMismatch == 0 &&
		t.ResampleFailures == 0 && t.LeakHits == 0 && t.Inconsistent == 0 && t.ParityMismatch == 0
}

var pairings = policyPairings()

func policyPairings() []string {
	out := []string{"uniform/uniform", "bot/lethal-pressure"}
	for _, p := range agent.Policies() {
		out = append(out, p.Key+"/uniform")
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

func link(name string) minihost.Link {
	if name == "uniform" {
		return &minihost.Uniform{}
	}
	a, err := agent.New(name)
	if err != nil {
		panic(err)
	}
	return a
}

func sameIntent(k decision.Kind, got, want decision.Intent) bool {
	g, w := slices.Clone(got.Choices), slices.Clone(want.Choices)
	if k == decision.KAttackers || k == decision.KBlockers {
		slices.Sort(g)
		slices.Sort(w)
	}
	return slices.Equal(g, w) && (len(want.Rest) == 0 || slices.Equal(got.Rest, want.Rest))
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
	reg, err := gorgepin.OpenRegistry(os.Getenv("GORGE_CARDS"))
	if err != nil {
		return Report{}, err
	}
	kinds := map[string]bool{}
	for _, k := range server.DecisionKinds {
		kinds[k] = true
	}
	var jobs []job
	for _, d := range catalog.Decks() {
		for _, p := range pairings {
			for g := 0; g < o.games; g++ {
				jobs = append(jobs, job{uint64(len(jobs)), d, p})
			}
		}
	}
	play := func(j job, audit bool) (minihost.Result, *auditLink, [2]minihost.Link, error) {
		srv := server.New(reg, nil)
		srv.SetAudit(audit)
		al := &auditLink{srv: srv, r: rand.New(rand.NewPCG(j.i, 7))}
		if audit {
			al.every = o.resample
		}
		names := strings.Split(j.pairing, "/")
		seats := [2]minihost.Link{link(names[0]), link(names[1])}
		h := &minihost.Host{RunSecret: []byte("gorge-qualification-run-secret!!"), Engine: al,
			Profile:  validate.Profile{Kinds: kinds, Flags: observe.Flags, Extensions: map[string]bool{}},
			MaxSteps: 100000, MaxDecisions: 49999}
		res, err := h.Play(j.i, j.deck, "london", []string{"x_gorge_view_v1"}, seats)
		return res, al, seats, err
	}
	rep := Report{Gates: map[string]DeckGate{}}
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
				for _, l := range seats {
					ag, ok := l.(*agent.Server)
					if !ok {
						continue
					}
					fb += ag.Fallbacks()
					forced += ag.Forced()
					for _, rec := range ag.Records() {
						gate.AgentNatives++
						switch {
						case rec.Fallbacks > 0:
							gate.FallbackNatives++
						case rec.Forced > 0:
							gate.ForcedNatives++
						}
						if rec.Reason != "" {
							gate.Reasons[rec.Reason]++
						}
					}
				}
				compared, mismatched := parity(al.srv.Realized(), seats)
				leaks, inconsistent := al.srv.Leaks(), al.srv.Inconsistent()
				row := map[string]any{"deck": j.deck.CatalogID, "pairing": j.pairing, "game": j.i, "steps": a.Steps,
					"outcome": a.Terminal.Outcome, "digest": a.Digest, "leaks": leaks, "inconsistent": inconsistent,
					"parity_mismatch": mismatched, "fallbacks": fb, "forced": forced}
				mu.Lock()
				t := &rep.Totals
				t.Games++
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
	rep.Totals.GamesPerSecond = float64(2*rep.Totals.Games) / time.Since(start).Seconds()
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
	outPath := flag.String("out", "gorgequal-report.json", "report path")
	flag.Parse()
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
	if !rep.Clean() {
		os.Exit(1)
	}
}
