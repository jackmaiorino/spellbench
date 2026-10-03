package mapping_test

import (
	"reflect"
	"strconv"
	"strings"
	"testing"

	"github.com/adams-shaun/gorge/cards"
	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/rules"
	"github.com/adams-shaun/gorge/state"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/mapping"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
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

// A dig whose bottom set is a single card asks no dig_bottom (gorge moves a
// lone remainder without asking): the lone remainder's ordering pick carries
// the presentational dest op, never a followup:dig_bottom op, and the commit
// is the bare dig intent, which the live game accepts.
func TestDigLoneRemainderCarriesPresentationalDestOp(t *testing.T) {
	g := untilPending(t, "Spy", 1, func(d *decision.Decision, e *rules.Engine) bool {
		if d.Kind != decision.KChoose || len(d.Options) == 0 || d.Options[0].Kind != "dig" || d.ResumeSA == nil {
			return false
		}
		n, err := strconv.Atoi(strings.TrimSpace(d.ResumeSA.Params["DigNum"]))
		if err != nil || n <= 0 {
			return false
		}
		lib := e.G.Zone(state.ZLibrary, d.Player)
		if len(lib) < n || d.Max < len(d.Options) {
			return false
		}
		eligible := map[state.ObjID]bool{}
		for _, o := range d.Options {
			eligible[o.Obj] = true
		}
		rest := 0
		for _, id := range lib[:n] {
			if !eligible[id] {
				rest++
			}
		}
		return rest == 1 // a window engineered to leave exactly one bottom card
	})
	env := envFor(t, g)
	tx, err := mapping.Begin(env, g.E.Pending())
	if err != nil {
		t.Fatal(err)
	}
	loneOps := 0
	commit := answerAll(t, tx, func(p *mapping.Pose) int {
		if p.Followups["dig_bottom"] != nil {
			t.Fatalf("a lone remainder asks no dig_bottom: %v", p.Followups)
		}
		for i, c := range p.Candidates {
			if c.Op.Op == "list" && c.Op.List == "followup:dig_bottom" {
				t.Fatalf("dangling follow-up op without a follow-up: %+v", c.Op)
			}
			if c.Sem.Kind == "order_pick" && c.Op.Op == "dest" && c.Op.List == "bottom" {
				loneOps++
				want := mapping.NativeOp{Op: "dest", Option: -1, List: "bottom"}
				if len(p.Candidates) != 1 || !reflect.DeepEqual(c.Op, want) {
					t.Fatalf("lone remainder op %+v among %d candidates, want exactly %+v", c.Op, len(p.Candidates), want)
				}
			}
			if c.Sem.Kind == "arrange_card" && c.Sem.Fields["destination"] == "hand" {
				return i // take every eligible card, leaving one on the bottom
			}
		}
		return 0
	})
	if loneOps != 1 {
		t.Fatalf("%d lone-remainder ordering picks, want 1", loneOps)
	}
	if len(commit) != 1 {
		t.Fatalf("a lone remainder commits the bare dig intent: %v", commit)
	}
	if _, err := g.Probe(commit...); err != nil {
		t.Fatalf("lone-remainder dig commit rejected: %v", err)
	}
}

// A non-Restable arrange (surveil's shape) has the engine fix pile B's order
// to the offered order: each ordering pick for that destination offers
// exactly one candidate, in offered order.
func TestNonRestableArrangeFixesTheRestOrder(t *testing.T) {
	g := untilPending(t, "CawGates", 1, func(d *decision.Decision, e *rules.Engine) bool {
		return d.Kind == decision.KPriority
	})
	env := envFor(t, g)
	seat := state.PlayerID(0)
	lib := g.E.G.Zone(state.ZLibrary, seat)
	if len(lib) < 2 {
		t.Fatal("library too small")
	}
	d := &decision.Decision{Kind: decision.KArrange, Player: seat, Min: 0, Max: 2, // Restable false
		Options: []decision.Option{
			{Kind: "bottom", Obj: lib[0], Index: 0, Player: seat},
			{Kind: "bottom", Obj: lib[1], Index: 1, Player: seat},
		}}
	tx, err := mapping.Begin(env, d)
	if err != nil {
		t.Fatal(err)
	}
	orderPicks := 0
	commit := answerAll(t, tx, func(p *mapping.Pose) int {
		if p.SubstepCount != 3 {
			t.Fatalf("group size %d, want 3", p.SubstepCount)
		}
		if p.Candidates[0].Sem.Kind == "arrange_card" {
			for i, c := range p.Candidates {
				if c.Sem.Fields["destination"] == "bottom" {
					return i // both cards to the bottom
				}
			}
			t.Fatal("no bottom candidate")
		}
		orderPicks++
		if len(p.Candidates) != 1 {
			t.Fatalf("restOnly ordering pick offered %d candidates, want 1", len(p.Candidates))
		}
		want := mapping.NativeOp{Op: "list", Option: 0, List: "rest", Position: 0}
		if c := p.Candidates[0]; !reflect.DeepEqual(c.Op, want) {
			t.Fatalf("restOnly ordering op %+v, want %+v (offered order)", c.Op, want)
		}
		return 0
	})
	if orderPicks != 1 {
		t.Fatalf("%d ordering picks, want 1 (n-1 with n=2)", orderPicks)
	}
	if len(commit) != 1 || len(commit[0].Choices) != 0 || len(commit[0].Rest) != 0 {
		t.Fatalf("commit %v, want one intent with empty Choices and no Rest", commit)
	}
}

// The scry Min-feasibility branches: with Min 1 over two cards, bottoming the
// first card leaves "top" as the second card's only legal destination, and
// keeping the first on top leaves only "bottom".
func TestScryMinFeasibilityFiltersDeadEnds(t *testing.T) {
	g := untilPending(t, "CawGates", 1, func(d *decision.Decision, e *rules.Engine) bool {
		return d.Kind == decision.KPriority
	})
	env := envFor(t, g)
	seat := state.PlayerID(0)
	lib := g.E.G.Zone(state.ZLibrary, seat)
	if len(lib) < 2 {
		t.Fatal("library too small")
	}
	newTx := func() mapping.Transaction {
		d := &decision.Decision{Kind: decision.KArrange, Player: seat, Min: 1, Max: 1, Restable: true,
			Options: []decision.Option{
				{Kind: "bottom", Obj: lib[0], Index: 0, Player: seat},
				{Kind: "bottom", Obj: lib[1], Index: 1, Player: seat},
			}}
		tx, err := mapping.Begin(env, d)
		if err != nil {
			t.Fatal(err)
		}
		return tx
	}
	destsAfter := func(first string) []string {
		t.Helper()
		tx := newTx()
		p, err := tx.Pose()
		if err != nil {
			t.Fatal(err)
		}
		pick := -1
		for i, c := range p.Candidates {
			if c.Sem.Fields["destination"] == first {
				pick = i
			}
		}
		if pick < 0 {
			t.Fatalf("no %s candidate in the first pose", first)
		}
		if _, done, err := tx.Answer(pick); err != nil || done {
			t.Fatalf("first partition answer: done %v, err %v", done, err)
		}
		p, err = tx.Pose()
		if err != nil {
			t.Fatal(err)
		}
		var out []string
		for _, c := range p.Candidates {
			out = append(out, c.Sem.Fields["destination"].(string))
		}
		return out
	}
	if got := destsAfter("bottom"); !reflect.DeepEqual(got, []string{"top"}) {
		t.Fatalf("after bottoming card 0: destinations %v, want [top]", got)
	}
	if got := destsAfter("top"); !reflect.DeepEqual(got, []string{"bottom"}) {
		t.Fatalf("after keeping card 0 on top: destinations %v, want [bottom]", got)
	}
}

// The dig Min-feasibility branch: with Min 1 and one eligible card remaining,
// bottoming the last eligible card dead-ends the ask, so it is not offered.
func TestDigMinFeasibilityFiltersDeadEnds(t *testing.T) {
	g := untilPending(t, "CawGates", 1, func(d *decision.Decision, e *rules.Engine) bool {
		return d.Kind == decision.KPriority
	})
	env := envFor(t, g)
	seat := state.PlayerID(0)
	lib := g.E.G.Zone(state.ZLibrary, seat)
	if len(lib) < 3 {
		t.Fatal("library too small")
	}
	d := &decision.Decision{Kind: decision.KChoose, Player: seat, Min: 1, Max: 2,
		ResumeSA: &cards.SA{Params: map[string]string{"DigNum": "3"}},
		Options: []decision.Option{
			{Kind: "dig", Obj: lib[0], Index: 0, Player: seat},
			{Kind: "dig", Obj: lib[1], Index: 1, Player: seat},
		}}
	tx, err := mapping.Begin(env, d)
	if err != nil {
		t.Fatal(err)
	}
	p, err := tx.Pose()
	if err != nil {
		t.Fatal(err)
	}
	pick := -1
	for i, c := range p.Candidates {
		if c.Sem.Fields["destination"] == "bottom" {
			pick = i // bottom the first eligible card while the second can still meet Min
		}
	}
	if pick < 0 {
		t.Fatal("no bottom candidate for the first card")
	}
	if _, done, err := tx.Answer(pick); err != nil || done {
		t.Fatalf("first partition answer: done %v, err %v", done, err)
	}
	p, err = tx.Pose()
	if err != nil {
		t.Fatal(err)
	}
	for _, c := range p.Candidates {
		if c.Sem.Fields["destination"] == "bottom" {
			t.Fatalf("bottoming the last eligible card dead-ends Min 1: %v", p.Candidates)
		}
	}
}

// A two-card scry to the bottom lands in placement order: the first ordering
// pick ends up closer to the top, the implied last pick at the very bottom
// (gorge's rules/arrange.go: pileB in Rest order below the remainder).
func TestScryBottomOrderIsPlacementOrder(t *testing.T) {
	g := untilPending(t, "CawGates", 1, func(d *decision.Decision, e *rules.Engine) bool {
		return d.Kind == decision.KArrange && d.Restable && len(d.Options) == 2 // Preordain's scry 2
	})
	env := envFor(t, g)
	d := g.E.Pending()
	lib := g.E.G.Zone(state.ZLibrary, d.Player)
	top0, top1 := lib[0], lib[1]
	tx, _ := mapping.Begin(env, d)
	commit := answerAll(t, tx, func(p *mapping.Pose) int {
		if p.Candidates[0].Sem.Kind == "arrange_card" {
			for i, c := range p.Candidates {
				if c.Sem.Fields["destination"] == "bottom" {
					return i // both cards to the bottom
				}
			}
			t.Fatal("no bottom candidate")
		}
		at := map[string]uint32{} // look id -> distance from the top
		for _, k := range p.Known {
			if k.ObjectID != nil && k.PositionFromTop != nil {
				at[*k.ObjectID] = *k.PositionFromTop
			}
		}
		for i, c := range p.Candidates {
			item := c.Sem.Fields["item"].(protocol.OrderItem)
			if at[item.Object.ObjectID] == 1 {
				return i // the deeper card first
			}
		}
		t.Fatal("no ordering candidate for the deeper card")
		return 0
	})
	c, err := g.Probe(commit...)
	if err != nil {
		t.Fatal(err)
	}
	// Preordain draws after its scry; the draw comes off the remainder, so the
	// bottom pair is the scry order: the first pick above the second.
	newLib := c.G.Zone(state.ZLibrary, d.Player)
	if newLib[len(newLib)-2] != top1 || newLib[len(newLib)-1] != top0 {
		t.Fatalf("library bottom pair %d, %d, want first pick %d above second pick %d",
			newLib[len(newLib)-2], newLib[len(newLib)-1], top1, top0)
	}
}
