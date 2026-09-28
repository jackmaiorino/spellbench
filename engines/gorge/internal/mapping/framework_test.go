package mapping_test

import (
	"errors"
	"testing"

	"github.com/adams-shaun/gorge/decision"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/mapping"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
)

func str(s string) *string { return &s }

func ref(id, name string) protocol.ObjectRef {
	return protocol.ObjectRef{ObjectID: id, CardName: str(name), OwnerSeat: "p0", ControllerSeat: "p0", Zone: "library"}
}

func TestFinalizePutsPassFirstAndOrdersHiddenCandidates(t *testing.T) {
	p := &mapping.Pose{Context: protocol.Context{Kind: "choice"}, Candidates: []mapping.Cand{
		{Sem: protocol.SelectObject(nil, "search", protocol.ObjectTarget(ref("o-b", "Swamp")), 0, 0, 1), Hidden: true, SortName: "Swamp", SortID: "o-b"},
		{Sem: protocol.FinishSelection(nil, "search", 0)},
		{Sem: protocol.SelectObject(nil, "search", protocol.ObjectTarget(ref("o-a", "Forest")), 0, 0, 1), Hidden: true, SortName: "Forest", SortID: "o-a"},
	}}
	if err := mapping.Finalize(p); err != nil {
		t.Fatal(err)
	}
	if p.Candidates[0].SortName != "Forest" || p.Candidates[2].SortName != "Swamp" || p.Candidates[1].Sem.Kind != "finish_selection" {
		t.Fatalf("order %v %v %v", p.Candidates[0].SortName, p.Candidates[1].Sem.Kind, p.Candidates[2].SortName)
	}
	q := &mapping.Pose{Context: protocol.Context{Kind: "priority"}, Candidates: []mapping.Cand{
		{Sem: protocol.PlayLand(ref("o-1", "Mountain"), 0)}, {Sem: protocol.Pass()}}}
	mapping.Finalize(q)
	if q.Candidates[0].Sem.Kind != "pass" {
		t.Fatal("pass is not candidate 0")
	}
	dup := &mapping.Pose{Context: protocol.Context{Kind: "priority"}, Candidates: []mapping.Cand{{Sem: protocol.Pass()}, {Sem: protocol.Pass()}}}
	if err := mapping.Finalize(dup); !errors.Is(err, mapping.ErrDuplicate) {
		t.Fatalf("duplicates: %v", err)
	}
}

func TestFinalizeEnforcesCandidateLimitAndDeadEnd(t *testing.T) {
	if err := mapping.Finalize(&mapping.Pose{}); !errors.Is(err, mapping.ErrDeadEnd) {
		t.Fatalf("empty pose: %v", err)
	}
	pose := func(n int) *mapping.Pose {
		p := &mapping.Pose{Context: protocol.Context{Kind: "choice"}}
		for i := 0; i < n; i++ {
			p.Candidates = append(p.Candidates, mapping.Cand{Sem: protocol.ChooseNumber(nil, "other", int32(i), 0, 4096)})
		}
		return p
	}
	if err := mapping.Finalize(pose(4097)); !errors.Is(err, mapping.ErrCandidateLimit) {
		t.Fatalf("4097 candidates: %v", err)
	}
	if err := mapping.Finalize(pose(4096)); err != nil {
		t.Fatalf("4096 candidates (the cap): %v", err)
	}
}

func TestRouteNamesEveryPoolShape(t *testing.T) {
	cases := []struct {
		want string
		d    *decision.Decision
	}{
		// The five direct kinds.
		{"priority", &decision.Decision{Kind: decision.KPriority}},
		{"attackers", &decision.Decision{Kind: decision.KAttackers}},
		{"blockers", &decision.Decision{Kind: decision.KBlockers}},
		{"target", &decision.Decision{Kind: decision.KTarget}},
		{"trigger_order", &decision.Decision{Kind: decision.KTriggerOrder}},
		// Modes: an unless option beats the option-kind checks.
		{"modes/unless", &decision.Decision{Kind: decision.KModes, Options: []decision.Option{{Kind: "mode", Mode: decision.ModeUnlessPay}}}},
		{"modes/unless", &decision.Decision{Kind: decision.KModes, Options: []decision.Option{{Kind: "mode", Mode: decision.ModeUnlessDecline}}}},
		{"modes/discard", &decision.Decision{Kind: decision.KModes, Options: []decision.Option{{Kind: "discard"}}}},
		{"modes/mode", &decision.Decision{Kind: decision.KModes, Options: []decision.Option{{Kind: "mode"}}}},
		// Mulligan.
		{"mulligan/bottom", &decision.Decision{Kind: decision.KMulligan, Options: []decision.Option{{Kind: "bottom"}}}},
		{"mulligan/keep", &decision.Decision{Kind: decision.KMulligan, Options: []decision.Option{{Kind: "keep"}}}},
		// Optional triggers and replacements.
		{"trigger_optional/madness", &decision.Decision{Kind: decision.KTriggerOptional, ResumeKind: "madness", Options: []decision.Option{{Kind: "yes"}, {Kind: "no"}}}},
		{"trigger_optional/optional", &decision.Decision{Kind: decision.KTriggerOptional, Options: []decision.Option{{Kind: "yes"}, {Kind: "no"}}}},
		{"replacement/madness", &decision.Decision{Kind: decision.KReplacement, Options: []decision.Option{{Kind: "madness_exile"}, {Kind: "madness_graveyard"}}}},
		{"replacement/order", &decision.Decision{Kind: decision.KReplacement, Options: []decision.Option{{Kind: "replacement"}, {Kind: "replacement"}}}},
		// An arrangement routes on its first option's kind.
		{"arrange/bottom", &decision.Decision{Kind: decision.KArrange, Options: []decision.Option{{Kind: "bottom"}, {Kind: "bottom"}}}},
		// The choose classes, in the switch's own order.
		{"choose/mana_window", &decision.Decision{Kind: decision.KChoose, Options: []decision.Option{{Kind: "activate"}, {Kind: "done"}}}},
		{"choose/mana_window", &decision.Decision{Kind: decision.KChoose, Options: []decision.Option{{Kind: "done"}}}},
		{"choose/trigger_cost", &decision.Decision{Kind: decision.KChoose, Options: []decision.Option{{Kind: "trigger_cost_pay"}, {Kind: "trigger_cost_decline"}}}},
		{"choose/cost", &decision.Decision{Kind: decision.KChoose, Source: 9, Options: []decision.Option{{Kind: "sacrifice"}}}},
		{"choose/cost", &decision.Decision{Kind: decision.KChoose, Options: []decision.Option{{Kind: "tapcost"}}}},
		{"choose/cost", &decision.Decision{Kind: decision.KChoose, Options: []decision.Option{{Kind: "returncost"}}}},
		{"choose/cost", &decision.Decision{Kind: decision.KChoose, Options: []decision.Option{{Kind: "exile_cost"}}}},
		{"choose/cost", &decision.Decision{Kind: decision.KChoose, Options: []decision.Option{{Kind: "exile"}}}},
		{"choose/cost", &decision.Decision{Kind: decision.KChoose, Source: 9, Options: []decision.Option{{Kind: "discard"}}}},
		{"choose/cleanup_discard", &decision.Decision{Kind: decision.KChoose, Options: []decision.Option{{Kind: "discard"}}}},
		{"choose/yesno", &decision.Decision{Kind: decision.KChoose, Options: []decision.Option{{Kind: "yes"}, {Kind: "no"}}}},
		{"choose/explore", &decision.Decision{Kind: decision.KChoose, Options: []decision.Option{{Kind: "graveyard"}, {Kind: "top"}}}},
		{"choose/pay_pip", &decision.Decision{Kind: decision.KChoose, Options: []decision.Option{{Kind: "pay_R"}, {Kind: "pay_G"}}}},
		// Every single-option-kind class.
		{"choose/search", &decision.Decision{Kind: decision.KChoose, Options: []decision.Option{{Kind: "search"}}}},
		{"choose/hand_move", &decision.Decision{Kind: decision.KChoose, Options: []decision.Option{{Kind: "hand_move"}}}},
		{"choose/dig", &decision.Decision{Kind: decision.KChoose, Options: []decision.Option{{Kind: "dig"}}}},
		{"choose/untap", &decision.Decision{Kind: decision.KChoose, Options: []decision.Option{{Kind: "untap"}}}},
		{"choose/keep", &decision.Decision{Kind: decision.KChoose, Options: []decision.Option{{Kind: "keep"}}}},
		{"choose/x", &decision.Decision{Kind: decision.KChoose, Options: []decision.Option{{Kind: "x"}}}},
		{"choose/number", &decision.Decision{Kind: decision.KChoose, Options: []decision.Option{{Kind: "number"}}}},
		{"choose/color", &decision.Decision{Kind: decision.KChoose, Options: []decision.Option{{Kind: "color"}}}},
		{"choose/type", &decision.Decision{Kind: decision.KChoose, Options: []decision.Option{{Kind: "type"}}}},
		{"choose/name", &decision.Decision{Kind: decision.KChoose, Options: []decision.Option{{Kind: "name"}}}},
		{"choose/division", &decision.Decision{Kind: decision.KChoose, Options: []decision.Option{{Kind: "division"}}}},
		{"choose/mana", &decision.Decision{Kind: decision.KChoose, Options: []decision.Option{{Kind: "mana"}}}},
		// The fallback names the kind and the sorted option kinds.
		{"unmapped:choose/vote", &decision.Decision{Kind: decision.KChoose, Options: []decision.Option{{Kind: "vote"}}}},
	}
	seen := map[string]bool{}
	for _, tc := range cases {
		seen[tc.want] = true
		if got := mapping.Route(tc.d); got != tc.want {
			t.Errorf("Route(%v) = %q, want %q", tc.d, got, tc.want)
		}
	}
	if len(seen) != 35 {
		t.Errorf("table names %d distinct shapes, want 35", len(seen))
	}
}
