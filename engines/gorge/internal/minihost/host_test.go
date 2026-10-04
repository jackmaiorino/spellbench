package minihost_test

import (
	"testing"

	"github.com/jackmaiorino/spellbench/engines/gorge/internal/catalog"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/minihost"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/observe"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/server"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/testcorpus"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/validate"
)

func host(t *testing.T) *minihost.Host {
	kinds := map[string]bool{}
	for _, k := range server.DecisionKinds {
		kinds[k] = true
	}
	run := make([]byte, 32)
	return &minihost.Host{RunSecret: run, Engine: &minihost.EngineLink{S: server.New(testcorpus.Registry(t), nil)},
		Profile:  validate.Profile{Kinds: kinds, Flags: observe.Flags, Extensions: map[string]bool{"x_gorge_view_v1": true}},
		MaxSteps: 20000, MaxDecisions: 9999}
}

func TestUniformGamesOnEveryDeckValidateAndReplay(t *testing.T) {
	for i, d := range catalog.Decks() {
		agents := [2]minihost.Link{&minihost.Uniform{}, &minihost.Uniform{}}
		a, err := host(t).Play(uint64(i), d, "london", []string{"x_gorge_view_v1"}, agents)
		if err != nil {
			t.Fatalf("%s: %v", d.CatalogID, err)
		}
		if a.Terminal.Classification == "halted" {
			t.Fatalf("%s halted: %s", d.CatalogID, a.Terminal.Reason)
		}
		b, _ := host(t).Play(uint64(i), d, "london", []string{"x_gorge_view_v1"}, [2]minihost.Link{&minihost.Uniform{}, &minihost.Uniform{}})
		if a.Digest != b.Digest {
			t.Fatalf("%s: rerun digest %s != %s", d.CatalogID, b.Digest, a.Digest)
		}
	}
}
