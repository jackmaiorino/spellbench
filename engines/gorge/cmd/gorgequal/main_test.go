package main

import (
	"github.com/adams-shaun/gorge/decision"
	"testing"
)

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
