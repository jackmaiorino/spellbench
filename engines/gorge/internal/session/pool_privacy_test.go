package session

import (
	"bytes"
	"encoding/json"
	"testing"

	"github.com/adams-shaun/gorge/cards"
	"github.com/adams-shaun/gorge/state"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/catalog"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/secrets"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/testcorpus"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/xview"
)

// This compares newly captured histories, rather than cloning an already
// captured history while resampling just its current board. Every catalog
// card occupies the opponent's hidden hand and library in a real genesis.
// It covers the initial mulligan and the actor's first priority boundary;
// effect-resolution coverage is supplied by the separate history regressions.
func TestFullPoolHiddenCardsDoNotChangePublicHistory(t *testing.T) {
	reg := testcorpus.Registry(t)
	mountain, ok := reg.Lookup("Mountain")
	if !ok {
		t.Fatal("pinned registry has no Mountain")
	}
	var actor [60]*cards.Card
	for i := range actor {
		actor[i] = mountain
	}
	capture := func(t *testing.T, card *cards.Card) []byte {
		t.Helper()
		var opponent [60]*cards.Card
		for i := range opponent {
			opponent[i] = card
		}
		seat := "p0"
		req := &protocol.ResetReq{GameID: "pool-privacy", Format: "pauper-bo1", MaxDecisions: 1000, MaxSteps: 1000,
			Rules: protocol.Rules{Mulligan: "london", StartingPlayer: "host_assigned", StartingSeat: &seat, Names: catalog.PoolNames()}}
		g, err := Start(Config{Reg: reg, AutoPay: true, Search: true, Ext: xview.New(), Audit: true},
			req.GameID, req, secrets.NewGame(make([]byte, 32)), [2][]*cards.Card{actor[:], opponent[:]})
		if err != nil {
			t.Fatal(err)
		}
		var snapshots []protocol.SeatDecision
		for step := 0; step < 3; step++ {
			dec, terminal := g.Pending()
			if terminal != nil || dec == nil {
				t.Fatalf("unexpected terminal before first priority: %+v", terminal)
			}
			if dec.SeatDecision.ActingSeat == "p0" {
				snapshots = append(snapshots, dec.SeatDecision)
			}
			if step == 2 {
				if dec.SeatDecision.Context.Kind != "priority" || dec.SeatDecision.ActingSeat != "p0" {
					t.Fatalf("expected first actor priority, got %+v", dec.SeatDecision.Context)
				}
				break
			}
			found := false
			for _, candidate := range dec.SeatDecision.Candidates {
				if candidate.Semantic.Kind == "mulligan" && candidate.Semantic.Fields["keep"] == true {
					encoded, err := json.Marshal(candidate.Semantic)
					if err != nil {
						t.Fatal(err)
					}
					if e := g.Step(&protocol.StepReq{GameID: req.GameID, ExpectedStep: dec.Step,
						CandidateID: uint64(candidate.CandidateID), Echo: encoded}); e != nil {
						t.Fatal(e)
					}
					found = true
					break
				}
			}
			if !found {
				t.Fatal("no legal keep action")
			}
		}
		if g.Leaks() != 0 || g.Inconsistent() != 0 || len(snapshots) != 2 {
			t.Fatalf("leaks=%d inconsistent=%d snapshots=%d", g.Leaks(), g.Inconsistent(), len(snapshots))
		}
		// The event-chain head excludes genesis card definitions, so it
		// cannot prove that these hidden-card variants differ. Check the
		// actual engine's hidden hand and library instead.
		count := 0
		for _, zone := range []state.Zone{state.ZHand, state.ZLibrary} {
			for _, id := range g.g.E.G.Zone(zone, 1) {
				if object := g.g.E.G.Obj(id); object == nil || object.Card != card {
					t.Fatal("fixture did not install the requested hidden card")
				}
				count++
			}
		}
		if count != len(opponent) || len(g.g.E.G.Zone(state.ZHand, 1)) != 7 {
			t.Fatal("fixture did not retain seven hidden hand cards and the remaining library")
		}
		encoded, err := json.Marshal(snapshots)
		if err != nil {
			t.Fatal(err)
		}
		return encoded
	}
	want := capture(t, mountain)
	for _, name := range catalog.PoolNames() {
		t.Run(name, func(t *testing.T) {
			card, ok := reg.Lookup(name)
			if !ok {
				t.Fatal("pool card missing")
			}
			got := capture(t, card)
			if !bytes.Equal(got, want) {
				t.Fatal("hidden pool card changed the actor's whole seat decision or freshly captured search history")
			}
		})
	}
}
