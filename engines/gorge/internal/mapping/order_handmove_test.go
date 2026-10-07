package mapping_test

// Live chain test for the Task 18/19a linkage: a real CawGates game is
// driven to Brainstorm's put-two-back ask, Begin must route it through the
// builders map to the order handler (never ErrUnmapped), the order pose must
// offer the selected hand cards as order_picks, and the picked order must
// replay into the live engine with the library top in that order.

import (
	"errors"
	"reflect"
	"slices"
	"testing"

	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/rules"
	"github.com/adams-shaun/gorge/state"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/mapping"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
)

func TestHandMoveLibraryLinksToTheOrderHandler(t *testing.T) {
	g := untilPending(t, "CawGates", 1, func(d *decision.Decision, e *rules.Engine) bool {
		return mapping.Route(d) == "choose/hand_move" && d.ResumeSA != nil &&
			d.ResumeSA.Params["Destination"] == "Library" && d.Min == 2 && d.Max == 2 && len(d.Options) >= 3
	})
	d := g.E.Pending()
	env := envFor(t, g)
	tx, err := mapping.Begin(env, d)
	if errors.Is(err, mapping.ErrUnmapped) {
		t.Fatalf("the hand_move/library chain is not linked: %v", err)
	}
	if err != nil {
		t.Fatal(err)
	}

	// The select phase poses each hand card as a select_object, one pick per
	// decision; the handler intercepts the completed pick and never emits it.
	var chosen []int
	for len(chosen) < 2 {
		p, err := tx.Pose()
		if err != nil {
			t.Fatal(err)
		}
		if p.SubstepIndex != uint32(len(chosen)) || p.SubstepCount != 2 {
			t.Fatalf("select pose: substep %d of %d after %d picks", p.SubstepIndex, p.SubstepCount, len(chosen))
		}
		if len(p.Candidates) != len(d.Options)-len(chosen) {
			t.Fatalf("select pose: %d candidates for %d options after %d picks", len(p.Candidates), len(d.Options), len(chosen))
		}
		for _, c := range p.Candidates {
			if c.Sem.Kind != "select_object" || c.Op.Op != "choose" {
				t.Fatalf("select candidate %s %s", semJSON(c.Sem), semJSON(c.Op))
			}
			choice, ok := c.Sem.Fields["choice"].(protocol.TargetRef)
			if !ok || choice.Object == nil || choice.Object.Zone != "hand" {
				t.Fatalf("select candidate choice %s", semJSON(c.Sem))
			}
			r, err := env.Obs.Ref(d.Player, d.Options[c.Op.Option].Obj)
			if err != nil || r == nil {
				t.Fatal(r, err)
			}
			if !reflect.DeepEqual(choice.Object, r) {
				t.Fatalf("select candidate %v, want the hand card %v", choice.Object, r)
			}
		}
		commit, done, err := tx.Answer(0)
		if err != nil || done || commit != nil {
			t.Fatalf("select pick %d: commit %v, done %v, err %v", len(chosen), commit, done, err)
		}
		chosen = append(chosen, p.Candidates[0].Op.Option)
	}

	// The order phase offers exactly the selected cards as order_picks.
	p, err := tx.Pose()
	if err != nil {
		t.Fatal(err)
	}
	if !p.GroupStart || p.SubstepIndex != 0 || p.SubstepCount != 1 {
		t.Fatalf("order pose: group start %v, substep %d of %d", p.GroupStart, p.SubstepIndex, p.SubstepCount)
	}
	if p.Context.Purpose == nil || *p.Context.Purpose != "library_top" {
		t.Fatalf("order pose context %s", semJSON(p.Context))
	}
	if len(p.Candidates) != len(chosen) {
		t.Fatalf("order pose: %d candidates for %d selected cards", len(p.Candidates), len(chosen))
	}
	pick := -1
	for i, c := range p.Candidates {
		if c.Sem.Kind != "order_pick" || c.Op.Op != "list" || c.Op.List != "choices" || c.Op.Position != 0 {
			t.Fatalf("order candidate %s %s", semJSON(c.Sem), semJSON(c.Op))
		}
		if err := c.Sem.Check(); err != nil {
			t.Fatalf("order candidate fails the protocol shape: %v", err)
		}
		if c.Sem.Fields["purpose"] != "library_top" || c.Sem.Fields["position"] != uint32(0) || c.Sem.Fields["count"] != uint32(len(chosen)) {
			t.Fatalf("order candidate fields %s", semJSON(c.Sem))
		}
		item, ok := c.Sem.Fields["item"].(protocol.OrderItem)
		if !ok || item.Object == nil {
			t.Fatalf("order item %s", semJSON(c.Sem))
		}
		if !slices.Contains(chosen, c.Op.Option) {
			t.Fatalf("order candidate option %d was not selected: %v", c.Op.Option, chosen)
		}
		r, err := env.Obs.Ref(d.Player, d.Options[c.Op.Option].Obj)
		if err != nil || r == nil {
			t.Fatal(r, err)
		}
		if !reflect.DeepEqual(item.Object, r) {
			t.Fatalf("order item %v, want the selected hand card %v", item.Object, r)
		}
		if c.Op.Option == chosen[1] {
			pick = i
		}
	}
	if pick < 0 {
		t.Fatalf("the second selected card is not an order candidate: %s", semJSON(p.Candidates))
	}

	// Picking the second selected card first commits one intent in that
	// order; the live engine tops its library with it.
	commit, done, err := tx.Answer(pick)
	if err != nil || !done {
		t.Fatalf("order answer: done %v, err %v", done, err)
	}
	want := []int{chosen[1], chosen[0]} // the last position is implied
	if len(commit) != 1 || !reflect.DeepEqual(commit[0].Choices, want) {
		t.Fatalf("commit %v, want one intent choosing %v", commit, want)
	}
	if err := g.Submit(commit[0]); err != nil {
		t.Fatalf("the live game refused the commit: %v", err)
	}
	lib := g.E.G.Zone(state.ZLibrary, d.Player)
	if len(lib) < len(want) {
		t.Fatalf("the library holds %d cards after Brainstorm", len(lib))
	}
	for i, opt := range want {
		id := d.Options[opt].Obj
		if lib[i] != id {
			t.Fatalf("library[%d] = %s, want %s (picked order %v)",
				i, g.E.G.Obj(lib[i]).Face().Name, g.E.G.Obj(id).Face().Name, want)
		}
		if o := g.E.G.Obj(id); o.Zone != state.ZLibrary {
			t.Fatalf("%s is in %s, want the library", o.Face().Name, o.Zone)
		}
	}
}
