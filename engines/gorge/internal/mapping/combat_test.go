package mapping_test

import (
	"slices"
	"testing"

	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/rules"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/mapping"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
)

func TestAttackGroupHasOneDecisionPerCreature(t *testing.T) {
	g := untilPending(t, "Rally", 1, func(d *decision.Decision, e *rules.Engine) bool {
		seen := map[any]bool{}
		for _, o := range d.Options {
			seen[o.Obj] = true
		}
		return d.Kind == decision.KAttackers && len(seen) >= 2
	})
	env := envFor(t, g)
	d := g.E.Pending()
	creatures := map[any]bool{}
	for _, o := range d.Options {
		creatures[o.Obj] = true
	}
	tx, _ := mapping.Begin(env, d)
	substeps := 0
	commit := answerAll(t, tx, func(p *mapping.Pose) int {
		if p.SubstepCount != uint32(len(creatures)) || p.SubstepIndex != uint32(substeps) {
			t.Fatalf("substep %d/%d, want %d/%d", p.SubstepIndex, p.SubstepCount, substeps, len(creatures))
		}
		substeps++
		for i, c := range p.Candidates {
			if c.Sem.Kind != "declare_attack" {
				t.Fatalf("candidate kind %s", c.Sem.Kind)
			}
			if def, _ := c.Sem.Fields["defender"].(*protocol.TargetRef); def != nil {
				return i // attack with everything the engine allows
			}
		}
		return 0
	})
	if substeps != len(creatures) || len(commit) != 1 {
		t.Fatalf("substeps %d commit %v", substeps, commit)
	}
	if !mapping.Accepts(env, commit[0]) {
		t.Fatal("the assembled declaration is rejected")
	}
}

func TestCompositionsMatchGorgeOrder(t *testing.T) {
	got := mapping.Compositions(2, 2)
	want := [][]int32{{0, 2}, {1, 1}, {2, 0}}
	if len(got) != len(want) {
		t.Fatalf("%v", got)
	}
	for i := range want {
		if got[i][0] != want[i][0] || got[i][1] != want[i][1] {
			t.Fatalf("%v", got)
		}
	}
}

// Section 7.6's engine_order split, which the engine applies to gorge's
// division ask instead of posing distribute (combat_damage_assignment is
// declared "engine_order"): lethal to each blocker in order, the rest to the
// last blocker.
func TestEngineOrderSplit(t *testing.T) {
	for _, c := range []struct {
		power  int32
		lethal []int32
		want   []int32
	}{
		{5, []int32{2, 2, 2}, []int32{2, 2, 1}},
		{7, []int32{2, 2}, []int32{2, 5}},
		{1, []int32{2, 2}, []int32{1, 0}},
		{3, []int32{1, 1, 1}, []int32{1, 1, 1}},
	} {
		if got := mapping.EngineOrderSplit(c.power, c.lethal); !slices.Equal(got, c.want) {
			t.Errorf("EngineOrderSplit(%d, %v) = %v, want %v", c.power, c.lethal, got, c.want)
		}
	}
	d := &decision.Decision{Kind: decision.KChoose, Options: []decision.Option{{Kind: "division"}}}
	if mapping.Route(d) != "choose/division" {
		t.Fatalf("route %s", mapping.Route(d))
	}
	if _, ok, _ := mapping.Internal(nil, &decision.Decision{Kind: decision.KAttackers}); ok {
		t.Fatal("an attack declaration is answered internally")
	}
}
