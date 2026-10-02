package main

import "testing"

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
