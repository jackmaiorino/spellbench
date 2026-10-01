package mapping_test

import (
	"testing"

	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/rules"
	"github.com/adams-shaun/gorge/state"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/mapping"
)

func TestScryIsTwoNMinusOneAndLandsCardsWhereChosen(t *testing.T) {
	g := untilPending(t, "CawGates", 1, func(d *decision.Decision, e *rules.Engine) bool {
		return d.Kind == decision.KArrange && d.Restable && len(d.Options) == 2 // Preordain's scry 2
	})
	env := envFor(t, g)
	d := g.E.Pending()
	lib := g.E.G.Zone(state.ZLibrary, d.Player)
	top0, top1 := lib[0], lib[1]
	tx, _ := mapping.Begin(env, d)
	decisions := 0
	commit := answerAll(t, tx, func(p *mapping.Pose) int {
		decisions++
		if p.SubstepCount != 3 {
			t.Fatalf("group size %d, want 3", p.SubstepCount)
		}
		if p.Candidates[0].Sem.Kind == "arrange_card" {
			for i, c := range p.Candidates { // send card 0 to the bottom, keep card 1 on top
				if (decisions == 1) == (c.Sem.Fields["destination"] == "bottom") {
					return i
				}
			}
		}
		return 0
	})
	if decisions != 3 {
		t.Fatalf("%d decisions", decisions)
	}
	c, err := g.Probe(commit...)
	if err != nil {
		t.Fatal(err)
	}
	// Preordain draws after its scry, so the card kept on top is now the last
	// card added to the hand, and the other is the library's bottom card.
	hand, newLib := c.G.Zone(state.ZHand, d.Player), c.G.Zone(state.ZLibrary, d.Player)
	if hand[len(hand)-1] != top1 || newLib[len(newLib)-1] != top0 {
		t.Fatalf("drawn %d, library bottom %d, want %d and %d", hand[len(hand)-1], newLib[len(newLib)-1], top1, top0)
	}
}

func TestDigMergesDigAndDigBottomIntoOneArrangement(t *testing.T) {
	g := untilPending(t, "Spy", 1, func(d *decision.Decision, e *rules.Engine) bool {
		return d.Kind == decision.KChoose && len(d.Options) > 0 && d.Options[0].Kind == "dig"
	})
	env := envFor(t, g)
	tx, _ := mapping.Begin(env, g.E.Pending())
	var count uint32
	followOps := 0
	commit := answerAll(t, tx, func(p *mapping.Pose) int {
		count = p.SubstepCount
		for i, c := range p.Candidates {
			if c.Sem.Kind == "arrange_card" && c.Sem.Fields["destination"] == "bottom" {
				return i // every card to the bottom, so gorge asks dig_bottom for the order
			}
			if c.Op.Op == "list" && c.Op.List == "followup:dig_bottom" && p.Followups["dig_bottom"] != nil {
				followOps++
			}
		}
		return 0
	})
	if count != 2*5-1 {
		t.Fatalf("Lead the Stampede arrangement size %d, want 9", count)
	}
	if followOps == 0 || len(commit) != 2 {
		t.Fatalf("bottom order not carried by the dig_bottom follow-up: %d ops, commit %v", followOps, commit)
	}
	if _, err := g.Probe(commit...); err != nil {
		t.Fatalf("dig commit rejected: %v", err)
	}
}
