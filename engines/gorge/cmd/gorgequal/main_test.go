package main

import (
	"reflect"
	"slices"
	"testing"

	"github.com/adams-shaun/gorge/decision"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/catalog"
)

func TestScalingSampleKeepsItsOriginalSeedAndCannotQualifyTheRoster(t *testing.T) {
	var jobs []job
	for _, deck := range catalog.Decks() {
		for _, pairing := range policyPairings([]string{"bot"}) {
			jobs = append(jobs, job{uint64(len(jobs)), deck, pairing})
		}
	}
	want := []job{jobs[0], jobs[14]}
	selected, err := selectQualificationJobs(slices.Clone(jobs), []uint64{14, 0})
	if err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(selected, want) {
		t.Fatalf("selected seeds/decks/pairings changed: %+v, want %+v", selected, want)
	}
	a := Report{ScheduledGames: len(jobs), SelectedGames: []uint64{0, 14}, Totals: Totals{Games: 2}}
	if a.Clean() {
		t.Fatal("partial scaling sample qualified the full roster")
	}
	for _, indices := range [][]uint64{{0, 0}, {15}, {}} {
		if _, err := selectQualificationJobs(slices.Clone(jobs), indices); err == nil {
			t.Fatalf("invalid selection %v was accepted", indices)
		}
	}
}

func TestPaymentParityComparesTheWitness(t *testing.T) {
	a := decision.Intent{Payment: &decision.PaymentSelection{ActionID: "a", Plan: decision.PaymentPlan{ID: "p"}}}
	b := decision.CloneIntent(a)
	if !sameIntent(decision.KPriority, a, b) {
		t.Fatal("equal witnesses differ")
	}
	b.Payment.Plan.ID = "different"
	if sameIntent(decision.KPriority, a, b) || sameIntent(decision.KPriority, a, decision.Intent{}) {
		t.Fatal("empty choices concealed a changed payment")
	}
}

func TestCleanRejectsRedealWithoutFallbackWorldsOrWithRefusedRoots(t *testing.T) {
	r := Report{Policies: []string{"search-redeal"}, Totals: Totals{Games: 1}, SearchCoverage: map[string]SearchCoverage{}}
	for _, deck := range catalog.Decks() {
		r.SearchCoverage[deck.CatalogID+"/search-redeal"] = SearchCoverage{Eligible: 1, Covered: 1}
	}
	if r.Clean() {
		t.Fatal("ordinary replay alone qualified the redeal mode")
	}
	key := catalog.Decks()[0].CatalogID + "/search-redeal"
	coverage := r.SearchCoverage[key]
	coverage.Redealt = 8
	r.SearchCoverage[key] = coverage
	if !r.Clean() {
		t.Fatal("covered redeal with completed fallback worlds failed")
	}
	coverage.RedealRefusals = map[string]int{"no public replay completion": 1}
	r.SearchCoverage[key] = coverage
	if r.Clean() {
		t.Fatal("a refused public root qualified")
	}
	coverage.RedealRefusals = nil
	coverage.ReconstructionBudgetExhausted = 1
	r.SearchCoverage[key] = coverage
	if r.Clean() {
		t.Fatal("public reconstruction exhaustion qualified")
	}
}

func TestCleanRejectsSearchWithoutCoveredDecisions(t *testing.T) {
	if (Report{Policies: []string{"search"}, Totals: Totals{Games: 1}}).Clean() {
		t.Fatal("declared search without observations passed")
	}
	r := Report{Totals: Totals{Games: 1}, SearchCoverage: map[string]SearchCoverage{"Burn/search": {Eligible: 3}}}
	if r.Clean() {
		t.Fatal("fallback-only search passed qualification")
	}
	r.SearchCoverage["Burn/search"] = SearchCoverage{Covered: 1}
	if r.Clean() {
		t.Fatal("coverage without eligible decisions passed")
	}
	r.SearchCoverage["Burn/search"] = SearchCoverage{Eligible: 3, Covered: 1}
	if !r.Clean() {
		t.Fatal("covered search failed the coverage gate")
	}
}

// Full native search qualification is a separate guarded evaluation. CI tests
// its public bridge against native Choose with bounded synthetic games.
func TestSmallOrdinaryQualificationIsClean(t *testing.T) {
	rep, err := qualify(options{games: 1, resample: 3, workers: 1, audit: true,
		policyKeys: []string{"bot", "bot-auto-pay", "lethal-pressure", "lethal-pressure-auto-pay", "ar8", "blocks", "explore", "legacy"}})
	if err != nil {
		t.Fatal(err)
	}
	if !rep.Clean() {
		t.Fatalf("qualification not clean: %+v %+v", rep.Totals, rep.Gates)
	}
	if rep.Totals.ResampleChecks == 0 || rep.Totals.ParityCompared == 0 {
		t.Fatalf("checks did not run: %+v", rep.Totals)
	}
}
