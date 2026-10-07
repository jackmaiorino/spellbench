// Package testcorpus shares one pinned registry across a test binary. Tests
// fail, never skip, when the corpus is missing: a skipped engine test is a
// silent coverage hole.
package testcorpus

import (
	"os"
	"sync"
	"testing"

	"github.com/adams-shaun/gorge/cards"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/gorgepin"
)

var (
	once sync.Once
	reg  *cards.Registry
	err  error
)

func Dir(t testing.TB) string {
	t.Helper()
	d := os.Getenv("GORGE_CARDS")
	if d == "" {
		t.Fatal("GORGE_CARDS is not set: source scripts/env.sh")
	}
	return d
}

func Registry(t testing.TB) *cards.Registry {
	t.Helper()
	dir := Dir(t)
	once.Do(func() { reg, err = gorgepin.OpenRegistry(dir) })
	if err != nil {
		t.Fatal(err)
	}
	return reg
}
