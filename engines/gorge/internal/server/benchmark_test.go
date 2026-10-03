package server_test

import (
	"encoding/json"
	"maps"
	"os"
	"slices"
	"testing"

	"github.com/jackmaiorino/spellbench/engines/gorge/internal/catalog"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/observe"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/server"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/testcorpus"
)

// The pauper-gorge benchmark is parsed by sub-project P's bench loader
// (schema spellbench-benchmark/v2), which fixes the information rules
// (opponent decklist visible, mulligan auto resolving to london where the
// engine supports it, host-assigned starting player with seat p0, no probe),
// so the file states no rules block. This test pins the file against the
// engine's declared profile: a drift in catalog.Decks, server.DecisionKinds
// or observe.Flags fails here loudly.
func TestBenchmarkMatchesTheEngineProfile(t *testing.T) {
	raw, err := os.ReadFile("../../../../benchmarks/pauper-gorge/benchmark.json")
	if err != nil {
		t.Fatal(err)
	}
	var b struct {
		Schema, ID, Format string
		Engine             struct {
			Name    string   `json:"name"`
			Command []string `json:"command"`
		} `json:"engine"`
		DeckPool     []string       `json:"deck_pool"`
		PairsPerDeck int            `json:"pairs_per_deck"`
		StatsSeed    int64          `json:"stats_seed"`
		Extensions   []string       `json:"extensions"`
		Limits       map[string]int `json:"limits"`
		Bots         []struct {
			Name    string `json:"name"`
			Version string `json:"version"`
			Type    string `json:"type"`
		} `json:"bots"`
	}
	if err := json.Unmarshal(raw, &b); err != nil {
		t.Fatal(err)
	}
	var ids []string
	for _, d := range catalog.Decks() {
		ids = append(ids, d.CatalogID)
	}
	if b.Schema != "spellbench-benchmark/v2" || b.ID != "pauper-gorge" || b.Format != "pauper-bo1" ||
		b.Engine.Name != "gorge" || len(b.Engine.Command) == 0 || b.PairsPerDeck < 1 || b.StatsSeed <= 0 {
		t.Fatalf("benchmark %+v", b)
	}
	if !slices.Equal(b.DeckPool, ids) {
		t.Fatalf("deck_pool %v, catalog %v", b.DeckPool, ids)
	}
	if !slices.Equal(b.Extensions, []string{"x_gorge_view_v1"}) {
		t.Fatalf("extensions %v", b.Extensions)
	}
	if 2*b.Limits["max_seat_decisions_per_game"] >= b.Limits["max_decisions"] ||
		2*b.Limits["max_seat_steps_per_game"] >= b.Limits["max_steps"] {
		t.Fatal("per-seat caps must be strictly below half of the game caps (Section 11.4)")
	}
	roster := map[string]string{}
	for _, bot := range b.Bots {
		roster[bot.Name] = bot.Type
	}
	if roster["uniform"] != "builtin" || roster["heuristic"] != "builtin" ||
		roster["gorge-bot"] != "subprocess" || roster["gorge-lethal-pressure"] != "subprocess" {
		t.Fatalf("bots %+v", b.Bots)
	}

	// The declared profile the benchmark relies on: london and host_assigned
	// so the loader's fixed rules resolve as the engine notes state, the
	// format and the extension declared, combat damage by engine order
	// (no distribute), and the observation flags of the notes.
	s := server.New(testcorpus.Registry(t), nil)
	var hello protocol.HelloOK
	if err := json.Unmarshal(s.Handle([]byte(`{"request_type":"hello","protocol":"spellbench/v2","request_id":"h-bench","protocol_minor":0}`)), &hello); err != nil {
		t.Fatal(err)
	}
	if !slices.Contains(hello.Formats, b.Format) ||
		!slices.Contains(hello.RulesSupported["mulligan"], "london") ||
		!slices.Equal(hello.RulesSupported["starting_player"], []string{"host_assigned"}) {
		t.Fatalf("rules_supported %v, formats %v", hello.RulesSupported, hello.Formats)
	}
	declared := map[string]bool{}
	for _, ext := range hello.Extensions {
		declared[ext.Name] = ext.NativeIDs
	}
	for _, ext := range b.Extensions {
		native, ok := declared[ext]
		if !ok || native {
			t.Fatalf("extension %q: declared %v native_ids %v", ext, ok, native)
		}
	}
	if len(server.DecisionKinds) != 24 || slices.Contains(server.DecisionKinds, "distribute") ||
		!slices.Contains(server.DecisionKinds, "mulligan") || !slices.Equal(hello.DecisionKinds, server.DecisionKinds) {
		t.Fatalf("decision_kinds %v", server.DecisionKinds)
	}
	var trues []string
	for flag, on := range observe.Flags {
		if on {
			trues = append(trues, flag)
		}
	}
	slices.Sort(trues)
	if len(observe.Flags) != 13 || !slices.Equal(trues, []string{"keywords", "pending_triggers"}) ||
		observe.Flags["known_cards"] || !maps.Equal(hello.Observation, observe.Flags) {
		t.Fatalf("observation flags %v", observe.Flags)
	}
}
