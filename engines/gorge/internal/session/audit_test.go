package session_test

import (
	"testing"

	"github.com/adams-shaun/gorge/cards"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/catalog"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/secrets"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/session"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/testcorpus"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/xview"
)

func TestLeakScanCountsAPlantedName(t *testing.T) {
	hidden := map[string]bool{"Lightning Bolt": true}
	clean := []byte(`{"observation":{"players":[{"hand":[{"card_name":"Mountain"}]}]},` +
		`"candidates":[{"semantic":{"kind":"choose_name","purpose":"card_name","value":"Lightning Bolt"}}],` +
		`"extensions":{"x_gorge_view_v1":{"view":{"label":"Lightning Bolt deals 3"}}}}`)
	if n := session.LeakHits(clean, hidden); n != 0 {
		t.Fatalf("clean decision scored %d", n)
	}
	planted := []byte(`{"observation":{"players":[{"hand":[{"card_name":"Mountain"}]}]},` +
		`"extensions":{"x_gorge_view_v1":{"view":{"players":[{"hand":[{"name":"Lightning Bolt"}]}]}}}}`)
	if n := session.LeakHits(planted, hidden); n != 1 {
		t.Fatalf("planted leak scored %d, want 1", n)
	}
}

func TestAuditedGameHasNoLeaksAndRecordsIntents(t *testing.T) {
	reg := testcorpus.Registry(t)
	d, _ := catalog.ByID("CawGates")
	cs, err := catalog.Resolve(reg, d)
	if err != nil {
		t.Fatal(err)
	}
	seat := "p0"
	req := &protocol.ResetReq{GameID: "g-a", Format: "pauper-bo1", MaxDecisions: 100000, MaxSteps: 3000,
		Rules: protocol.Rules{Mulligan: "london", StartingPlayer: "host_assigned", StartingSeat: &seat, Names: catalog.PoolNames()}}
	g, err := session.Start(session.Config{Reg: reg, Ext: xview.New(), Audit: true}, "g-a", req,
		secrets.NewGame(make([]byte, 32)), [2][]*cards.Card{cs, cs})
	if err != nil {
		t.Fatal(err)
	}
	for {
		dec, term := g.Pending()
		if term != nil {
			if term.Classification == "halted" {
				t.Fatalf("halted: %s", term.Reason)
			}
			break
		}
		c := dec.SeatDecision.Candidates[len(dec.SeatDecision.Candidates)-1] // the last candidate acts more than pass does
		if perr := g.Step(&protocol.StepReq{GameID: "g-a", ExpectedStep: dec.Step, CandidateID: uint64(c.CandidateID),
			Echo: echo(t, c.Semantic)}); perr != nil {
			t.Fatal(perr)
		}
	}
	if g.Leaks() != 0 || g.Inconsistent() != 0 {
		t.Fatalf("%d leak-scan hits, %d inconsistent candidates", g.Leaks(), g.Inconsistent())
	}
	if len(g.Realized()) == 0 {
		t.Fatal("no realized intents recorded")
	}
}
