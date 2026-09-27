package identity_test

import (
	"errors"
	"testing"

	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/events"
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

// sweep plays bot games from their start, syncing the tracker after every
// intent as the session does, and passes visit every object's key at the
// previous sync. It tries each deck with seeds 1 to 20 until visit reports
// true, and fails, never skips, when no game gets there.
func sweep(t *testing.T, decks []string, visit func(e *rules.Engine, tr *identity.Tracker, prev map[state.ObjID]string) bool) {
	t.Helper()
	reg := testcorpus.Registry(t)
	for _, deck := range decks {
		for s := byte(1); s <= 20; s++ {
			g := testgame.New(t, reg, deck, deck, s, "none")
			tr := identity.New(g.E, g.Secret)
			prev := map[state.ObjID]string{}
			keys := func() {
				for i := range g.E.G.Objs {
					prev[g.E.G.Objs[i].ID] = tr.Key(g.E.G.Objs[i].ID)
				}
			}
			keys()
			if testgame.RunUntil(t, g, testgame.Bots(uint64(s)), func(e *rules.Engine) bool {
				if err := tr.Sync(e); err != nil {
					t.Fatal(err)
				}
				done := visit(e, tr, prev)
				keys()
				return done
			}, 30000) {
				return
			}
		}
	}
	t.Fatalf("no %v game reached the wanted state", decks)
}

// An activated ability's source key is its key before the ability's costs (a
// cycled or sacrificed source moves before the ability is put on the stack).
// A triggered ability's is its key when the trigger is put on the stack, so
// Writhing Chrysalis's cast trigger names the spell it came from. Spells have
// none.
func TestSourceKeysAreTakenWhenPushed(t *testing.T) {
	var paid, cast bool
	sweep(t, []string{"Wildfire"}, func(e *rules.Engine, tr *identity.Tracker, prev map[state.ObjID]string) bool {
		for _, id := range e.G.Stack {
			o := e.G.Obj(id)
			key, ok := tr.SourceKey(id)
			if o.Ability == nil {
				if ok {
					t.Fatalf("spell %d has source key %s", id, key)
				}
				continue
			}
			if _, old := prev[id]; old {
				continue // pushed in an earlier batch and checked then
			}
			src := e.G.Obj(o.Source)
			before, had := prev[o.Source]
			now := tr.Key(o.Source)
			switch {
			case !ok || src == nil:
				t.Fatalf("ability %d: source %d, source key %s %v", id, o.Source, key, ok)
			case o.StackKind == state.StackKindActivated:
				if had && key != before {
					t.Fatalf("activated ability %d: source key %s, want %s from before its costs", id, key, before)
				}
				paid = paid || (had && now != before && src.Zone == state.ZGraveyard)
			case src.Zone == state.ZStack && src.Face() != nil && src.Face().Name == "Writhing Chrysalis":
				if key != now {
					t.Fatalf("cast trigger %d: source key %s, want the spell's %s", id, key, now)
				}
				cast = true
			case had && now == before && key != now:
				t.Fatalf("triggered ability %d: source key %s, want %s", id, key, now)
			}
		}
		return paid && cast
	})
}

// A target's key is its key when chosen, so a target that changed zones since
// (a land sacrificed in response to Cleansing Wildfire) no longer matches it.
// Player targets have none.
func TestTargetKeysAreTakenWhenChosen(t *testing.T) {
	type slot struct {
		id, obj state.ObjID
		i       int
	}
	var game *identity.Tracker
	var chosen map[slot]string // a target's key at the sync after it was chosen, when it did not move in that batch
	var left bool
	sweep(t, []string{"Wildfire", "Rally", "Burn"}, func(e *rules.Engine, tr *identity.Tracker, prev map[state.ObjID]string) bool {
		if tr != game { // sweep started a new game
			game, chosen = tr, map[slot]string{}
		}
		live := map[slot]bool{}
		for _, id := range e.G.Stack {
			for i, tg := range e.G.Obj(id).Targets {
				key, ok := tr.TargetKey(id, i)
				if tg.IsPlayer {
					if ok {
						t.Fatalf("player target %d of %d has key %s", i, id, key)
					}
					continue
				}
				s := slot{id, tg.Obj, i}
				live[s] = true
				want, seen := chosen[s]
				if now := tr.Key(tg.Obj); !seen && prev[tg.Obj] == now {
					want, seen = now, true
					chosen[s] = want
				}
				if !ok || (seen && key != want) {
					t.Fatalf("target %d of %d: key %s %v, want %s", i, id, key, ok, want)
				}
				left = left || (seen && key != tr.Key(tg.Obj))
			}
		}
		for s := range chosen {
			if !live[s] {
				delete(chosen, s)
			}
		}
		return left
	})
}

// A declared blocker blocks until combat ends, even after its attacker has left
// (CR 509.1h), and no object that left the battlefield blocks.
func TestBlockingFollowsDeclaredBlockers(t *testing.T) {
	var listed, orphaned bool
	sweep(t, []string{"CawGates", "Rally", "Wildfire"}, func(e *rules.Engine, tr *identity.Tracker, _ map[state.ObjID]string) bool {
		combat := e.G.Step == state.StepDeclareBlockers || e.G.Step == state.StepCombatDamage || e.G.Step == state.StepEndCombat
		blockers := map[state.ObjID]bool{}
		for i := range e.G.Objs {
			if a := &e.G.Objs[i]; a.IsAttacking {
				for _, b := range a.BlockedBy {
					if b != 0 {
						blockers[b] = true
					}
				}
			}
		}
		for i := range e.G.Objs {
			b := &e.G.Objs[i]
			blocking := tr.Blocking(b.ID)
			switch {
			case blockers[b.ID] && !blocking:
				t.Fatalf("declared blocker %d is not blocking", b.ID)
			case blocking && (!combat || b.Zone != state.ZBattlefield):
				t.Fatalf("object %d in %s blocks in step %s", b.ID, b.Zone, e.G.Step)
			case blocking && blockers[b.ID]:
				listed = true
			case blocking:
				orphaned = true // its attacker has left combat
			}
		}
		return listed && orphaned
	})
}

// A spell keeps its ObjID when it is cast again, so a recast that targets the
// same card again takes that card's current key, not the first cast's.
func TestARecastSpellTakesFreshTargetKeys(t *testing.T) {
	reg := testcorpus.Registry(t)
	g := testgame.New(t, reg, "Burn", "Burn", 6, "none")
	tr := identity.New(g.E, g.Secret)
	emit := func(evs ...events.Event) {
		for _, ev := range evs {
			events.Emit(g.E.G, g.E.L, ev)
		}
		if err := tr.Sync(g.E); err != nil {
			t.Fatal(err)
		}
	}
	spell, target := g.E.G.Zone(state.ZHand, 0)[0], g.E.G.Zone(state.ZHand, 1)[0]
	cast := func(from state.Zone) {
		emit(events.Event{Kind: events.PutOnStack, Obj: spell, Player: 0, From: from, To: state.ZStack},
			events.Event{Kind: events.TargetsChosen, Obj: spell, IDs: []state.ObjID{target}})
		if key, ok := tr.TargetKey(spell, 0); !ok || key != tr.Key(target) {
			t.Fatalf("cast from %s: target key %s %v, want %s", from, key, ok, tr.Key(target))
		}
	}
	cast(state.ZHand)
	emit(events.Event{Kind: events.MoveZone, Obj: spell, Player: 0, From: state.ZStack, To: state.ZGraveyard},
		events.Event{Kind: events.MoveZone, Obj: target, Player: 1, From: state.ZHand, To: state.ZGraveyard})
	cast(state.ZGraveyard)
}

// The pool has no battle or planeswalker, so a permanent attack and removals
// from combat are emitted directly. A reference is keyed by the referenced
// object's stay in its zone, so hand cards stand in for permanents.
func TestCombatKeysFollowCombatEvents(t *testing.T) {
	reg := testcorpus.Registry(t)
	g := testgame.New(t, reg, "Burn", "Burn", 6, "none")
	tr := identity.New(g.E, g.Secret)
	emit := func(ev events.Event) {
		events.Emit(g.E.G, g.E.L, ev)
		if err := tr.Sync(g.E); err != nil {
			t.Fatal(err)
		}
	}
	mine, theirs := g.E.G.Zone(state.ZHand, 0), g.E.G.Zone(state.ZHand, 1)
	attacker, raider := mine[0], mine[1]
	battle, removed, killed, stays := theirs[0], theirs[1], theirs[2], theirs[3]
	emit(events.Event{Kind: events.DeclareAttackers, Player: 1, IDs: []state.ObjID{attacker}, Obj: battle})
	emit(events.Event{Kind: events.DeclareAttackers, Player: 1, IDs: []state.ObjID{raider}})
	if key, ok := tr.AttackKey(attacker); !ok || key != tr.Key(battle) {
		t.Fatalf("attack key %s %v, want %s", key, ok, tr.Key(battle))
	}
	if key, ok := tr.AttackKey(raider); ok {
		t.Fatalf("a player attack has attack key %s", key)
	}
	emit(events.Event{Kind: events.DeclareBlockers, Pairs: [][2]state.ObjID{{attacker, removed}, {raider, killed}, {raider, stays}}})
	if !tr.Blocking(removed) || !tr.Blocking(killed) || !tr.Blocking(stays) {
		t.Fatal("a declared blocker is not blocking")
	}
	emit(events.Event{Kind: events.MoveZone, Obj: battle, From: state.ZHand, To: state.ZGraveyard, Player: 1})
	if key, ok := tr.AttackKey(attacker); !ok || key == tr.Key(battle) {
		t.Fatalf("attack key %s %v follows the battle into its next zone", key, ok)
	}
	emit(events.Event{Kind: events.EndCombatReset, Obj: removed})
	emit(events.Event{Kind: events.MoveZone, Obj: killed, From: state.ZHand, To: state.ZGraveyard, Player: 1})
	if tr.Blocking(removed) || tr.Blocking(killed) || !tr.Blocking(stays) {
		t.Fatalf("blocking: removed %v, moved %v, stayed %v", tr.Blocking(removed), tr.Blocking(killed), tr.Blocking(stays))
	}
	emit(events.Event{Kind: events.EndCombatReset})
	if key, ok := tr.AttackKey(attacker); ok || tr.Blocking(stays) {
		t.Fatalf("after combat: attack key %s %v, blocking %v", key, ok, tr.Blocking(stays))
	}
}
