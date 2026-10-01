package mapping_test

import (
	"testing"

	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/rules"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/mapping"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
)

func TestBoltTargetsAreSlotZeroWithStackSource(t *testing.T) {
	g := untilPending(t, "Burn", 1, func(d *decision.Decision, e *rules.Engine) bool {
		return d.Kind == decision.KTarget && e.G.Obj(d.Source) != nil && e.G.Obj(d.Source).Face().Name == "Lightning Bolt"
	})
	env := envFor(t, g)
	tx, _ := mapping.Begin(env, g.E.Pending())
	p, err := tx.Pose()
	if err != nil {
		t.Fatal(err)
	}
	for _, c := range p.Candidates {
		f := c.Sem.Fields
		if c.Sem.Kind != "choose_target" || f["slot"] != uint32(0) || f["minimum"] != uint32(1) || f["maximum"] != uint32(1) {
			t.Fatalf("candidate %+v", c.Sem)
		}
		if src := f["source"].(protocol.ObjectRef); src.Zone != "stack" {
			t.Fatalf("source zone %s", src.Zone)
		}
	}
}

func TestFireblastSacrificeIsAFixedCostGroup(t *testing.T) {
	g := untilPending(t, "Burn", 1, func(d *decision.Decision, e *rules.Engine) bool {
		return d.Kind == decision.KChoose && len(d.Options) > 0 && d.Options[0].Kind == "sacrifice" && d.Min == 2 && d.Max == 2
	})
	env := envFor(t, g)
	tx, _ := mapping.Begin(env, g.E.Pending())
	var sizes []uint32
	commit := answerAll(t, tx, func(p *mapping.Pose) int {
		sizes = append(sizes, p.SubstepCount)
		if p.Candidates[0].Sem.Kind != "choose_cost_target" || p.Candidates[0].Sem.Fields["cost_kind"] != "sacrifice" {
			t.Fatalf("candidate %+v", p.Candidates[0].Sem)
		}
		return 0
	})
	if len(sizes) != 2 || sizes[0] != 2 || len(commit) != 1 || len(commit[0].Choices) != 2 {
		t.Fatalf("sizes %v commit %v", sizes, commit)
	}
}
