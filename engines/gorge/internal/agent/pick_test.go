package agent_test

import (
	"testing"

	"github.com/adams-shaun/gorge/decision"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/agent"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/mapping"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/xview"
)

func TestPickFollowsAScryAnswer(t *testing.T) {
	pl := agent.NewPlan(1, decision.Intent{Choices: []int{2}, Rest: []int{0, 1}})
	none := func(decision.Decision) decision.Intent { return decision.Intent{} }
	sems := []map[string]any{{"kind": "arrange_card"}, {"kind": "arrange_card"}}
	part := xview.Payload{Ops: []mapping.NativeOp{
		{Op: "dest", Option: 0, List: "top", Position: 0},
		{Op: "dest", Option: 0, List: "bottom", Position: 0},
	}}
	if i, miss := agent.Pick(part, sems, pl, none); i != 1 || miss != "" {
		t.Fatalf("card 0 went to candidate %d (%q), want the bottom", i, miss)
	}
	order := xview.Payload{Ops: []mapping.NativeOp{
		{Op: "list", Option: 1, List: "rest", Position: 0},
		{Op: "list", Option: 0, List: "rest", Position: 0},
	}}
	if i, miss := agent.Pick(order, sems, pl, none); i != 1 || miss != "" {
		t.Fatalf("first bottom card is candidate %d (%q), want option 0", i, miss)
	}
	// Nothing matches a single candidate: it is forced, never a fallback (G2-7).
	lone := xview.Payload{Ops: []mapping.NativeOp{{Op: "list", Option: 1, List: "choices", Position: 0}}}
	if i, miss := agent.Pick(lone, sems[:1], pl, none); i != 0 || miss != "forced" {
		t.Fatalf("lone unmatched candidate %d (%q), want 0 forced", i, miss)
	}
}
