package identity_test

import (
	"errors"
	"testing"

	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/rules"
	"github.com/adams-shaun/gorge/state"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/identity"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/testcorpus"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/testgame"
)

func TestIDsAreFreshPerZoneAndPerViewer(t *testing.T) {
	reg := testcorpus.Registry(t)
	g := testgame.New(t, reg, "Burn", "Burn", 1, "none")
	tr := identity.New(g.E, g.Secret)
	hand := g.E.G.Zone(state.ZHand, 0)
	card := hand[0]
	inHand, _ := tr.VisibleID(0, card)
	other, _ := tr.VisibleID(1, card)
	if inHand == other {
		t.Fatal("the same object has the same id for both viewers")
	}
	moved := testgame.RunUntil(t, g, testgame.Bots(5), func(e *rules.Engine) bool {
		o := e.G.Obj(card)
		return o.Zone != state.ZHand
	}, 5000)
	if !moved {
		t.Fatal("card never left hand in this seed: pick another seed")
	}
	if err := tr.Sync(g.E); err != nil {
		t.Fatal(err)
	}
	after, _ := tr.VisibleID(0, card)
	if after == inHand {
		t.Fatalf("id %s survived a zone change", after)
	}
}

// gorge defers every London redraw until each seat has declared
// (rules/mulligan.go: handleMulligan counts, resolveMulliganRedraws runs after
// the pass), so the mulliganing seat's hand moves only once the other seat
// has answered. Secret byte 8 redraws two cards of the first hand, so the
// test sees a hand to library to hand round trip inside one Submit.
func TestMulliganRoundTripGivesFreshIDs(t *testing.T) {
	reg := testcorpus.Registry(t)
	g := testgame.New(t, reg, "Spy", "Spy", 8, "london")
	tr := identity.New(g.E, g.Secret)
	d := g.E.Pending()
	if d.Kind != decision.KMulligan {
		t.Fatalf("first decision %s, want mulligan", d.Kind)
	}
	seat := d.Player
	first := map[state.ObjID]bool{}
	before := map[string]bool{}
	for _, id := range g.E.G.Zone(state.ZHand, seat) {
		first[id] = true
		oid, _ := tr.VisibleID(seat, id)
		before[oid] = true
	}
	answer := func(d *decision.Decision, kind string) {
		for _, o := range d.Options {
			if o.Kind == kind {
				if err := g.Submit(decision.Intent{Seq: d.Seq, Player: d.Player, Choices: []int{o.Index}}); err != nil {
					t.Fatal(err)
				}
				return
			}
		}
		t.Fatalf("no %s option in %+v", kind, d.Options)
	}
	answer(d, "mulligan")
	for d = g.E.Pending(); d != nil && d.Player != seat; d = g.E.Pending() {
		answer(d, "keep")
	}
	if d == nil || d.Kind != decision.KMulligan {
		t.Fatalf("after the redraw the seat is asked %+v, want its next mulligan ask", d)
	}
	if err := tr.Sync(g.E); err != nil {
		t.Fatal(err)
	}
	hand := g.E.G.Zone(state.ZHand, seat)
	if len(hand) != 7 {
		t.Fatalf("redrawn hand has %d cards", len(hand))
	}
	roundTrips := 0
	for _, id := range hand {
		if first[id] {
			roundTrips++
		}
		oid, _ := tr.VisibleID(seat, id)
		if before[oid] {
			t.Fatalf("id %s is reused in the redrawn hand", oid)
		}
	}
	if roundTrips == 0 {
		t.Fatal("no card went hand to library to hand, so a missed round trip would pass: pick another seed")
	}
}

func TestLooksAreStableWithinAndFreshAcross(t *testing.T) {
	reg := testcorpus.Registry(t)
	g := testgame.New(t, reg, "Burn", "Burn", 3, "none")
	tr := identity.New(g.E, g.Secret)
	top := g.E.G.Zone(state.ZLibrary, 0)[0]
	tr.OpenLook(0)
	a, _ := tr.LookID(0, top)
	b, _ := tr.LookID(0, top)
	tr.CloseLook(0)
	tr.OpenLook(0)
	c, _ := tr.LookID(0, top)
	tr.OpenLook(0) // a second open without a close still starts a fresh look
	d, _ := tr.LookID(0, top)
	tr.CloseLook(0)
	if a != b || a == c || d == c || d == a {
		t.Fatalf("look ids %s %s %s %s", a, b, c, d)
	}
}

// A look id is only for an object in a zone hidden from its viewer (a library,
// or the other seat's hand): an object the viewer sees already has its visible
// id, and a look id would give it two. Checked for every object and both
// viewers at every step of a whole game.
func TestLookIDRefusesAnObjectItsViewerSees(t *testing.T) {
	reg := testcorpus.Registry(t)
	g := testgame.New(t, reg, "Burn", "Burn", 4, "none")
	tr := identity.New(g.E, g.Secret)
	card := g.E.G.Zone(state.ZHand, 0)[0]
	if _, err := tr.LookID(1, card); err == nil {
		t.Fatal("LookID minted without an open look")
	}
	checked := map[state.Zone]int{}
	testgame.RunUntil(t, g, testgame.Bots(7), func(e *rules.Engine) bool {
		if err := tr.Sync(e); err != nil {
			t.Fatal(err)
		}
		for v := state.PlayerID(0); v < 2; v++ {
			tr.OpenLook(v)
			for i := range e.G.Objs {
				o := &e.G.Objs[i]
				hidden := o.Zone == state.ZLibrary || (o.Zone == state.ZHand && o.Owner != v)
				seen := o.Zone == state.ZHand && o.Owner == v
				switch o.Zone {
				case state.ZBattlefield, state.ZGraveyard, state.ZExile, state.ZStack, state.ZCommand:
					seen = true
				}
				_, err := tr.LookID(v, o.ID)
				if hidden && err != nil {
					t.Fatalf("p%d looking at object %d in %s: %v", v, o.ID, o.Zone, err)
				}
				if seen && err == nil {
					t.Fatalf("p%d got a look id for object %d in %s", v, o.ID, o.Zone)
				}
				if hidden || seen {
					checked[o.Zone]++
				}
			}
			tr.CloseLook(v)
		}
		return false
	}, 20000)
	for _, z := range []state.Zone{state.ZLibrary, state.ZHand, state.ZBattlefield, state.ZGraveyard, state.ZStack} {
		if checked[z] == 0 {
			t.Fatalf("no object in %s was checked: pick another seed", z)
		}
	}
	if _, err := tr.LookID(1, card); err == nil {
		t.Fatal("LookID minted after its look closed")
	}
}

// A state change that bypasses the event log must halt, never mint ids from a
// stale zone count.
func TestSyncReportsADivergedShadow(t *testing.T) {
	reg := testcorpus.Registry(t)
	g := testgame.New(t, reg, "Burn", "Burn", 5, "none")
	tr := identity.New(g.E, g.Secret)
	if err := tr.Sync(g.E); err != nil {
		t.Fatal(err)
	}
	g.E.G.Obj(g.E.G.Zone(state.ZHand, 0)[0]).Zone = state.ZGraveyard
	if err := tr.Sync(g.E); !errors.Is(err, identity.ErrShadowDiverged) {
		t.Fatalf("Sync after an unlogged move: %v, want ErrShadowDiverged", err)
	}
}

func TestShadowNeverDivergesOverWholeGames(t *testing.T) {
	reg := testcorpus.Registry(t)
	for i, deck := range []string{"Wildfire", "Rally", "Spy", "Burn", "CawGates"} {
		g := testgame.New(t, reg, deck, deck, byte(10+i), "london")
		tr := identity.New(g.E, g.Secret)
		testgame.RunUntil(t, g, testgame.Bots(uint64(i)), func(e *rules.Engine) bool {
			if err := tr.Sync(e); err != nil {
				t.Fatalf("%s: %v", deck, err)
			}
			return false
		}, 20000)
	}
}
