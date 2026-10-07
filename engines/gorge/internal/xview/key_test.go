package xview

import (
	"testing"

	"github.com/adams-shaun/gorge/state"
	"github.com/adams-shaun/gorge/view"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/identity"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/mapping"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/observe"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/testcorpus"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/testgame"
)

func TestFollowKeysFollowTheRenumbering(t *testing.T) {
	perm := []int{2, 0, 1}
	fperm := map[string][]int{"1": {1, 0}}
	for in, want := range map[string]string{"1": "0", "1/0": "0/1", "dig_bottom": "dig_bottom", "7": "7"} {
		if got := followKey(in, perm, fperm); got != want {
			t.Errorf("followKey(%q) = %q, want %q", in, got, want)
		}
	}
}

// A reference to a hidden card that no look shows, or to object 0 (a Rally
// pending trigger had one), becomes 0 without failing, and a pending trigger
// left without a source is dropped (G2-2).
func TestHiddenAndZeroReferencesBecomeZero(t *testing.T) {
	g := testgame.New(t, testcorpus.Registry(t), "Rally", "Rally", 1, "none")
	tr := identity.New(g.E, g.Secret)
	env := &mapping.Env{G: g, IDs: tr, Obs: &observe.Projector{E: g.E, IDs: tr}}
	hand, lib := g.E.G.Zone(state.ZHand, 0)[0], g.E.G.Zone(state.ZLibrary, 0)[0]
	r, errp := New().rekey(env, 0, map[state.ObjID]bool{})
	v := view.View{Pending: []view.PendingView{{Source: 0}, {Source: lib}, {Source: hand}},
		Stack: []view.StackView{{ID: hand, Source: lib}}}
	r.view(&v)
	dropSourceless(&v)
	if *errp != nil {
		t.Fatal(*errp)
	}
	if len(v.Pending) != 1 || v.Pending[0].Source == 0 || v.Stack[0].Source != 0 || v.Stack[0].ID == 0 {
		t.Fatalf("pending %+v, stack %+v", v.Pending, v.Stack)
	}
}
