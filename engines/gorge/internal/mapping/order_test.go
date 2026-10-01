package mapping_test

import (
	"testing"

	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/rules"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/mapping"
)

func TestTriggerOrderImpliesTheLastPosition(t *testing.T) {
	g := untilPending(t, "Wildfire", 1, func(d *decision.Decision, e *rules.Engine) bool {
		return d.Kind == decision.KTriggerOrder
	})
	env := envFor(t, g)
	d := g.E.Pending()
	tx, _ := mapping.Begin(env, d)
	n := 0
	commit := answerAll(t, tx, func(p *mapping.Pose) int {
		n++
		if p.Candidates[0].Sem.Fields["purpose"] != "triggers" {
			t.Fatal("purpose")
		}
		return 0
	})
	if n != len(d.Options)-1 || len(commit[0].Choices) != len(d.Options) {
		t.Fatalf("posed %d for %d triggers, commit %v", n, len(d.Options), commit)
	}
}

func TestMulliganBottomPosesAllPicks(t *testing.T) {
	g := untilPendingRules(t, "Burn", 1, "london", func(d *decision.Decision, e *rules.Engine) bool {
		return d.Kind == decision.KMulligan && d.Max > 0 && d.Options[0].Kind == "bottom"
	})
	env := envFor(t, g)
	d := g.E.Pending()
	tx, _ := mapping.Begin(env, d)
	n := 0
	answerAll(t, tx, func(p *mapping.Pose) int { n++; return 0 })
	if n != d.Max {
		t.Fatalf("posed %d of %d bottom picks", n, d.Max)
	}
}
