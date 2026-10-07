package session_test

import (
	"bytes"
	"encoding/json"
	"maps"
	"slices"
	"testing"

	"github.com/adams-shaun/gorge/cards"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/catalog"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/observe"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/secrets"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/session"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/testcorpus"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/validate"
)

func start(t *testing.T, deck string, maxSteps uint64) *session.Game {
	reg := testcorpus.Registry(t)
	d, _ := catalog.ByID(deck)
	cs, err := catalog.Resolve(reg, d)
	if err != nil {
		t.Fatal(err)
	}
	seat := "p0"
	req := &protocol.ResetReq{GameID: "g-t", Format: "pauper-bo1", MaxDecisions: 100000, MaxSteps: maxSteps,
		Rules: protocol.Rules{Mulligan: "london", StartingPlayer: "host_assigned", StartingSeat: &seat, Names: catalog.PoolNames()}}
	s := make([]byte, 32)
	g, err := session.Start(session.Config{Reg: reg}, "g-t", req, secrets.NewGame(s), [2][]*cards.Card{cs, cs})
	if err != nil {
		t.Fatal(err)
	}
	return g
}

func echo(t *testing.T, s protocol.Semantic) json.RawMessage {
	b, err := json.Marshal(s)
	if err != nil {
		t.Fatal(err)
	}
	return b
}

func profile() validate.Profile {
	kinds := map[string]bool{}
	for k := range protocol.KindFields {
		kinds[k] = true
	}
	return validate.Profile{Kinds: kinds, Flags: observe.Flags, Extensions: map[string]bool{}}
}

func TestFirstCandidateGameEndsWithConsistentCounts(t *testing.T) {
	g := start(t, "Burn", 4000)
	streams := [2]*validate.Stream{validate.NewStream(profile()), validate.NewStream(profile())}
	steps := uint64(0)
	for {
		dec, term := g.Pending()
		if term != nil {
			if term.StepCount != steps || term.DecisionCount > steps || term.Reason == "" {
				t.Fatalf("terminal %+v after %d steps", term, steps)
			}
			if term.Classification == "halted" {
				t.Fatalf("halted: %s", term.Reason)
			}
			return
		}
		sd := dec.SeatDecision
		seat := 0
		if sd.ActingSeat == "p1" {
			seat = 1
		}
		if err := streams[seat].Check(sd); err != nil {
			t.Fatalf("step %d: %v", steps, err)
		}
		if perr := g.Step(&protocol.StepReq{GameID: "g-t", ExpectedStep: dec.Step, CandidateID: 0, Echo: echo(t, sd.Candidates[0].Semantic)}); perr != nil {
			t.Fatalf("step %d: %v", steps, perr)
		}
		steps++
	}
}

// reversedJSON writes a decoded JSON value with every object's keys in
// reverse sorted order, a layout no encoder produces on its own.
func reversedJSON(v any) []byte {
	var b bytes.Buffer
	switch x := v.(type) {
	case map[string]any:
		keys := slices.Sorted(maps.Keys(x))
		slices.Reverse(keys)
		b.WriteByte('{')
		for i, k := range keys {
			if i > 0 {
				b.WriteByte(',')
			}
			kb, _ := json.Marshal(k)
			b.Write(kb)
			b.WriteByte(':')
			b.Write(reversedJSON(x[k]))
		}
		b.WriteByte('}')
	case []any:
		b.WriteByte('[')
		for i, e := range x {
			if i > 0 {
				b.WriteByte(',')
			}
			b.Write(reversedJSON(e))
		}
		b.WriteByte(']')
	default:
		eb, _ := json.Marshal(x)
		b.Write(eb)
	}
	return b.Bytes()
}

func decoded(t *testing.T, raw []byte) map[string]any {
	d := json.NewDecoder(bytes.NewReader(raw))
	d.UseNumber()
	var m map[string]any
	if err := d.Decode(&m); err != nil {
		t.Fatal(err)
	}
	return m
}

func TestEchoComparesParsedFieldsNotBytes(t *testing.T) {
	g := start(t, "Burn", 4000)
	// Pass until a candidate carries a nested object reference (a play_land
	// or cast_spell source).
	var dec *protocol.DecisionResponse
	id := -1
	for n := 0; id < 0; n++ {
		d, term := g.Pending()
		if term != nil || n > 200 {
			t.Fatal("no candidate with a nested object reference")
		}
		for i, c := range d.SeatDecision.Candidates {
			if _, ok := c.Semantic.Fields["source"].(protocol.ObjectRef); ok {
				dec, id = d, i
				break
			}
		}
		if id < 0 {
			if perr := g.Step(&protocol.StepReq{GameID: "g-t", ExpectedStep: d.Step, CandidateID: 0, Echo: echo(t, d.SeatDecision.Candidates[0].Semantic)}); perr != nil {
				t.Fatal(perr)
			}
		}
	}
	c := dec.SeatDecision.Candidates[id].Semantic
	raw := echo(t, c)
	reordered := reversedJSON(decoded(t, raw))
	if bytes.Equal(reordered, raw) {
		t.Fatal("the reversed layout equals the engine's bytes")
	}
	if !session.EchoEqual(reordered, c) {
		t.Fatalf("echo with reversed keys at every level rejected: %s", reordered)
	}
	extra := decoded(t, raw)
	extra["x_extra"] = 1
	changed := decoded(t, raw)
	changed["source"].(map[string]any)["zone"] = "graveyard"
	for what, m := range map[string]map[string]any{"an extra field": extra, "a changed nested field": changed} {
		b := reversedJSON(m)
		if session.EchoEqual(b, c) {
			t.Fatalf("echo with %s accepted", what)
		}
		if perr := g.Step(&protocol.StepReq{GameID: "g-t", ExpectedStep: dec.Step, CandidateID: uint64(id), Echo: b}); perr == nil || perr.Code != protocol.CodeSemanticEchoMismatch {
			t.Fatalf("echo with %s: got %v", what, perr)
		}
	}
	if perr := g.Step(&protocol.StepReq{GameID: "g-t", ExpectedStep: dec.Step, CandidateID: uint64(id), Echo: reordered}); perr != nil {
		t.Fatalf("reordered echo refused by Step: %v", perr)
	}
}

// last answers every decision with its last candidate: it takes mulligans
// until the rule forces a keep, then bottoms several cards, an order_pick
// group of two or more substeps (Section 8).
func last(sd protocol.SeatDecision) int { return len(sd.Candidates) - 1 }

func TestCapNeverSplitsAGroup(t *testing.T) {
	g := start(t, "Rally", 4000)
	var groupStep uint64
	for found := false; !found; {
		dec, term := g.Pending()
		if term != nil {
			t.Fatal("the game ended before a multi-substep group")
		}
		sd := dec.SeatDecision
		if sd.Group.SubstepIndex == 0 && sd.Group.SubstepCount >= 2 {
			groupStep, found = dec.Step, true
			break
		}
		k := last(sd)
		if perr := g.Step(&protocol.StepReq{GameID: "g-t", ExpectedStep: dec.Step, CandidateID: uint64(k), Echo: echo(t, sd.Candidates[k].Semantic)}); perr != nil {
			t.Fatal(perr)
		}
	}
	h := start(t, "Rally", groupStep+1) // room for one more decision, not for the group
	for {
		dec, term := h.Pending()
		if term != nil {
			if term.Outcome != "truncated" || term.StepCount != groupStep {
				t.Fatalf("terminal %+v, want truncated at %d", term, groupStep)
			}
			return
		}
		k := last(dec.SeatDecision)
		if perr := h.Step(&protocol.StepReq{GameID: "g-t", ExpectedStep: dec.Step, CandidateID: uint64(k), Echo: echo(t, dec.SeatDecision.Candidates[k].Semantic)}); perr != nil {
			t.Fatal(perr)
		}
	}
}

func TestTerminalGameRejectsSteps(t *testing.T) {
	g := start(t, "Burn", 0)
	if _, term := g.Pending(); term == nil || term.Outcome != "truncated" {
		t.Fatalf("max_steps 0 must truncate at reset, got %+v", term)
	}
	if perr := g.Step(&protocol.StepReq{GameID: "g-t"}); perr == nil || perr.Code != protocol.CodeGameAlreadyTerminal {
		t.Fatalf("got %v", perr)
	}
}
