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

func TestSmallQualificationIsClean(t *testing.T) {
	rep, err := qualify(options{games: 1, resample: 3, workers: 1, audit: true})
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
