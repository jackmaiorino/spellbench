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

func TestRouteNamesEveryPoolShape(t *testing.T) {
	cases := map[string]*decision.Decision{
		"choose/cost":            {Kind: decision.KChoose, Source: 9, Options: []decision.Option{{Kind: "sacrifice"}}},
		"choose/cleanup_discard": {Kind: decision.KChoose, Options: []decision.Option{{Kind: "discard"}}},
		"choose/mana_window":     {Kind: decision.KChoose, Options: []decision.Option{{Kind: "activate"}, {Kind: "done"}}},
		"choose/pay_pip":         {Kind: decision.KChoose, Options: []decision.Option{{Kind: "pay_R"}, {Kind: "pay_G"}}},
		"modes/unless":           {Kind: decision.KModes, Options: []decision.Option{{Kind: "mode", Mode: decision.ModeUnlessPay}}},
		"mulligan/bottom":        {Kind: decision.KMulligan, Options: []decision.Option{{Kind: "bottom"}}},
		"unmapped:choose/vote":   {Kind: decision.KChoose, Options: []decision.Option{{Kind: "vote"}}},
	}
	for want, d := range cases {
		if got := mapping.Route(d); got != want {
			t.Errorf("Route = %q, want %q", got, want)
		}
	}
}
