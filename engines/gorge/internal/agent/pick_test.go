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

// A multi-pick answer is committed in the bot's answer order (target slots,
// cards put on the library), not by membership: the first substep takes the
// intent's first choice wherever that candidate sits.
func TestPickKeepsTheBotsAnswerOrder(t *testing.T) {
	pl := agent.NewPlan(1, decision.Intent{Choices: []int{1, 2}})
	none := func(decision.Decision) decision.Intent { return decision.Intent{} }
	sems := []map[string]any{{"kind": "choose_card"}, {"kind": "choose_card"}}
	p := xview.Payload{Ops: []mapping.NativeOp{
		{Op: "choose", Option: 2},
		{Op: "choose", Option: 1},
	}}
	if i, miss := agent.Pick(p, sems, pl, none); i != 1 || miss != "" {
		t.Fatalf("first pick is candidate %d (%q), want 1, the bot's first choice", i, miss)
	}
	if i, miss := agent.Pick(p, sems, pl, none); i != 0 || miss != "" {
		t.Fatalf("second pick is candidate %d (%q), want 0, the bot's second choice", i, miss)
	}
}

// finish matches exactly when every intended pick is done: not with a pick
// outstanding, and a lone finish once the last pick is in is a match, never
// a forced answer.
func TestPickFinishesOnlyWhenThePickIsComplete(t *testing.T) {
	pl := agent.NewPlan(1, decision.Intent{Choices: []int{0, 1}})
	none := func(decision.Decision) decision.Intent { return decision.Intent{} }
	sems := []map[string]any{{"kind": "finish_selection"}, {"kind": "choose_card"}}
	open := xview.Payload{Ops: []mapping.NativeOp{
		{Op: "finish"},
		{Op: "choose", Option: 0},
	}}
	if i, miss := agent.Pick(open, sems, pl, none); i != 1 || miss != "" {
		t.Fatalf("no pick done, candidate %d (%q), want the choose at 1", i, miss)
	}
	open2 := xview.Payload{Ops: []mapping.NativeOp{
		{Op: "finish"},
		{Op: "choose", Option: 1},
	}}
	if i, miss := agent.Pick(open2, sems, pl, none); i != 1 || miss != "" {
		t.Fatalf("one pick short, candidate %d (%q), want the choose at 1", i, miss)
	}
	done := xview.Payload{Ops: []mapping.NativeOp{{Op: "finish"}}}
	if i, miss := agent.Pick(done, sems[:1], pl, none); i != 0 || miss != "" {
		t.Fatalf("pick complete, candidate %d (%q), want 0 with no miss", i, miss)
	}
}

// A cast candidate matches only when its Covers hold an intended option.
func TestPickCastsOnlyACoveredOption(t *testing.T) {
	pl := agent.NewPlan(1, decision.Intent{Choices: []int{2}})
	none := func(decision.Decision) decision.Intent { return decision.Intent{} }
	sems := []map[string]any{{"kind": "cast_spell"}, {"kind": "cast_spell"}}
	p := xview.Payload{Ops: []mapping.NativeOp{
		{Op: "cast", Option: 0, Covers: []int{5, 6}},
		{Op: "cast", Option: 1, Covers: []int{6, 2}},
	}}
	if i, miss := agent.Pick(p, sems, pl, none); i != 1 || miss != "" {
		t.Fatalf("cast candidate %d (%q), want 1, the candidate covering the intended option", i, miss)
	}
}

// No op matches and several candidates stand: the fallback prefers pay:false
// (an unless window the pool cannot cover) over finish over candidate 0.
func TestPickFallsBackToPayFalse(t *testing.T) {
	pl := agent.NewPlan(1, decision.Intent{Choices: []int{9}})
	none := func(decision.Decision) decision.Intent { return decision.Intent{} }
	sems := []map[string]any{
		{"kind": "optional_cost", "pay": true},
		{"kind": "optional_cost", "pay": false},
		{"kind": "finish_selection"},
	}
	p := xview.Payload{Ops: []mapping.NativeOp{
		{Op: "choose", Option: 0},
		{Op: "choose", Option: 1},
		{Op: "finish"},
	}}
	if i, miss := agent.Pick(p, sems, pl, none); i != 1 || miss != "fallback" {
		t.Fatalf("fell back to candidate %d (%q), want 1 (pay:false) as a fallback", i, miss)
	}
}
