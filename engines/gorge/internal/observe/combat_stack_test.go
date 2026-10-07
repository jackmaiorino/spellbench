package observe_test

import (
	"slices"
	"testing"

	"github.com/adams-shaun/gorge/events"
	"github.com/adams-shaun/gorge/rules"
	"github.com/adams-shaun/gorge/state"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/gamecfg"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/identity"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/observe"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/testcorpus"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/testgame"
)

func TestBlockingIsInvertedFromBlockedBy(t *testing.T) {
	reg := testcorpus.Registry(t)
	g := testgame.New(t, reg, "Wildfire", "Wildfire", 6, "none")
	found := testgame.RunUntil(t, g, testgame.Bots(21), func(e *rules.Engine) bool {
		for i := range e.G.Objs {
			// a live blocker: gorge leaves zero tombstones for removed ones
			if e.G.Objs[i].IsAttacking && slices.ContainsFunc(e.G.Objs[i].BlockedBy, func(b state.ObjID) bool { return b != 0 }) {
				return true
			}
		}
		return false
	}, 30000)
	if !found {
		t.Fatal("no blocked attacker in this seed")
	}
	tr := identity.New(g.E, g.Secret)
	p := &observe.Projector{E: g.E, IDs: tr}
	obs, err := p.Observation(g.E.Pending().Player, observe.State{})
	if err != nil {
		t.Fatal(err)
	}
	var attackers, blockers int
	for _, pl := range obs.Players {
		for _, rec := range pl.Battlefield {
			pm := rec.Permanent
			if pm.Attacking {
				attackers++
				if pm.AttackTarget == nil {
					t.Errorf("%s attacks nothing", rec.ObjectID)
				}
			}
			if pm.Blocking {
				blockers++
				if len(pm.BlockedAttackers) == 0 {
					t.Errorf("%s blocks no attacker", rec.ObjectID)
				}
			}
		}
	}
	if attackers == 0 || blockers == 0 {
		t.Fatalf("attackers %d blockers %d", attackers, blockers)
	}
}

func TestStackEntryForASpell(t *testing.T) {
	reg := testcorpus.Registry(t)
	g := testgame.New(t, reg, "Burn", "Burn", 7, "none")
	if !testgame.RunUntil(t, g, testgame.Bots(3), func(e *rules.Engine) bool { return len(e.G.Stack) > 0 }, 20000) {
		t.Fatal("nothing was cast")
	}
	p := &observe.Projector{E: g.E, IDs: identity.New(g.E, g.Secret)}
	obs, err := p.Observation(0, observe.State{})
	if err != nil {
		t.Fatal(err)
	}
	top := obs.Stack[len(obs.Stack)-1]
	if top.Zone != "stack" || top.StackKind == "" || top.Targets == nil {
		t.Fatalf("stack entry %+v", top)
	}
	if top.StackKind == "spell" && top.Characteristics == nil {
		t.Fatal("spell without characteristics")
	}
	if top.StackKind != "spell" && top.Characteristics != nil {
		t.Fatal("ability with characteristics")
	}
	_ = state.ZStack
}

func TestSortKnownOrder(t *testing.T) {
	zero, one := uint32(0), uint32(1)
	id := "o-2"
	ks := []protocol.Known{
		{OwnerSeat: "p1", Zone: "hand", CardName: "Counterspell", How: "revealed"},
		{OwnerSeat: "p0", Zone: "library", CardName: "Island", PositionFromTop: &one, How: "looked_at"},
		{OwnerSeat: "p0", Zone: "library", CardName: "Island", PositionFromTop: &zero, How: "looked_at", ObjectID: &id},
		{OwnerSeat: "p0", Zone: "library", CardName: "Brainstorm", PositionFromTop: &one, How: "looked_at"},
	}
	observe.SortKnown(ks)
	got := []string{ks[0].CardName, ks[1].CardName, ks[2].CardName, ks[3].OwnerSeat}
	want := []string{"Brainstorm", "Island", "Island", "p1"}
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("order %v", got)
		}
	}
	if *ks[1].PositionFromTop != 0 {
		t.Fatal("position_from_top must break the tie")
	}

	// position_from_bottom breaks a tie once owner_seat, zone, card_name and
	// position_from_top (both nil here) all agree.
	bottom := []protocol.Known{
		{OwnerSeat: "p0", Zone: "library", CardName: "Mountain", How: "revealed", PositionFromBottom: &one},
		{OwnerSeat: "p0", Zone: "library", CardName: "Mountain", How: "revealed", PositionFromBottom: &zero},
	}
	observe.SortKnown(bottom)
	if *bottom[0].PositionFromBottom != 0 || *bottom[1].PositionFromBottom != 1 {
		t.Fatalf("position_from_bottom must break the tie: %+v", bottom)
	}

	// how breaks a tie once both position fields also agree (both nil here).
	how := []protocol.Known{
		{OwnerSeat: "p0", Zone: "library", CardName: "Swamp", How: "revealed"},
		{OwnerSeat: "p0", Zone: "library", CardName: "Swamp", How: "looked_at"},
	}
	observe.SortKnown(how)
	if how[0].How != "looked_at" || how[1].How != "revealed" {
		t.Fatalf("how must break the tie: %+v", how)
	}

	// object_id breaks a tie once how also agrees; nulls first.
	oid := "o-9"
	objID := []protocol.Known{
		{OwnerSeat: "p0", Zone: "library", CardName: "Forest", How: "revealed", ObjectID: &oid},
		{OwnerSeat: "p0", Zone: "library", CardName: "Forest", How: "revealed"},
	}
	observe.SortKnown(objID)
	if objID[0].ObjectID != nil || objID[1].ObjectID == nil {
		t.Fatalf("object_id must break the tie, null first: %+v", objID)
	}
}

// tracked plays bot games from their start, syncing a tracker after every
// intent as the session does, until pred holds. It tries each deck with
// several seeds and fails, never skips, when no game gets there.
func tracked(t *testing.T, decks []string, pred func(*rules.Engine, *identity.Tracker) bool) (*gamecfg.Game, *identity.Tracker) {
	reg := testcorpus.Registry(t)
	for _, deck := range decks {
		for s := byte(1); s <= 20; s++ {
			g := testgame.New(t, reg, deck, deck, s, "none")
			tr := identity.New(g.E, g.Secret)
			if testgame.RunUntil(t, g, testgame.Bots(uint64(s)), func(e *rules.Engine) bool {
				if err := tr.Sync(e); err != nil {
					t.Fatal(err)
				}
				return pred(e, tr)
			}, 30000) {
				return g, tr
			}
		}
	}
	t.Fatalf("no %v game reached the wanted state", decks)
	return nil, nil
}

// entry returns the viewer's stack entry for stack object id.
func entry(t *testing.T, g *gamecfg.Game, tr *identity.Tracker, id state.ObjID) protocol.StackEntry {
	p := &observe.Projector{E: g.E, IDs: tr}
	obs, err := p.Observation(0, observe.State{})
	if err != nil {
		t.Fatal(err)
	}
	for i, sid := range g.E.G.Stack {
		if sid == id {
			return obs.Stack[i]
		}
	}
	t.Fatalf("stack object %d not in the observation", id)
	return protocol.StackEntry{}
}

// A cycled card is discarded before its ability is put on the stack, so the
// ability's source has left: Section 6.5 makes it null.
func TestCycledSourceIsNull(t *testing.T) {
	var ability state.ObjID
	g, tr := tracked(t, []string{"Spy", "CawGates", "Wildfire"}, func(e *rules.Engine, tr *identity.Tracker) bool {
		for _, id := range e.G.Stack {
			o := e.G.Obj(id)
			if src := e.G.Obj(o.Source); o.Ability != nil && o.StackKind == state.StackKindActivated && src != nil && src.Zone == state.ZGraveyard {
				ability = id
				return true
			}
		}
		return false
	})
	if se := entry(t, g, tr, ability); se.Source != nil || se.StackKind != "activated_ability" {
		t.Fatalf("ability %+v: source %+v, want null", se.ObjectRef, se.Source)
	}
}

// A target that changed zones after it was chosen (a land sacrificed in
// response to Cleansing Wildfire) is a null target, even though the card is
// visible in its new zone.
func TestTargetThatLeftIsNull(t *testing.T) {
	var spell state.ObjID
	var slot int
	g, tr := tracked(t, []string{"Wildfire", "Rally", "Burn"}, func(e *rules.Engine, tr *identity.Tracker) bool {
		for _, id := range e.G.Stack {
			for i, tg := range e.G.Obj(id).Targets {
				if key, ok := tr.TargetKey(id, i); ok && !tg.IsPlayer && e.G.Obj(tg.Obj) != nil && key != tr.Key(tg.Obj) {
					spell, slot = id, i
					return true
				}
			}
		}
		return false
	})
	if se := entry(t, g, tr, spell); se.Targets[slot] != nil {
		t.Fatalf("target %d of %+v is %+v, want null", slot, se.ObjectRef, se.Targets[slot].Object)
	}
}

// Writhing Chrysalis's cast trigger resolves above the spell it came from:
// that source is still on the stack and stays referenced.
func TestCastTriggerKeepsItsStackSource(t *testing.T) {
	var trigger state.ObjID
	g, tr := tracked(t, []string{"Wildfire"}, func(e *rules.Engine, tr *identity.Tracker) bool {
		for _, id := range e.G.Stack {
			o := e.G.Obj(id)
			if src := e.G.Obj(o.Source); o.Ability != nil && src != nil && src.Zone == state.ZStack && src.Face().Name == "Writhing Chrysalis" {
				trigger = id
				return true
			}
		}
		return false
	})
	se := entry(t, g, tr, trigger)
	if se.StackKind != "triggered_ability" || se.Source == nil || se.Source.Zone != "stack" || *se.Source.CardName != "Writhing Chrysalis" {
		t.Fatalf("cast trigger %+v with source %+v", se.ObjectRef, se.Source)
	}
}

// CR 509.1h: a blocker whose attacker left combat is still a blocking
// creature, with no blocked attackers left to list.
func TestBlockerStaysBlockingAfterItsAttackerLeaves(t *testing.T) {
	var blocker state.ObjID
	g, tr := tracked(t, []string{"CawGates", "Rally", "Wildfire"}, func(e *rules.Engine, tr *identity.Tracker) bool {
		for i := range e.G.Objs {
			b := &e.G.Objs[i]
			if b.Zone != state.ZBattlefield || !tr.Blocking(b.ID) {
				continue
			}
			alone := true
			for j := range e.G.Objs {
				if a := &e.G.Objs[j]; a.IsAttacking && slices.Contains(a.BlockedBy, b.ID) {
					alone = false
				}
			}
			if alone {
				blocker = b.ID
				return true
			}
		}
		return false
	})
	rec, err := (&observe.Projector{E: g.E, IDs: tr}).Record(0, blocker)
	if err != nil {
		t.Fatal(err)
	}
	if !rec.Permanent.Blocking || len(rec.Permanent.BlockedAttackers) != 0 {
		t.Fatalf("blocker %s: blocking %v, attackers %v", rec.ObjectID, rec.Permanent.Blocking, rec.Permanent.BlockedAttackers)
	}
}

// Section 6.5: a dies trigger's recorded source key is taken when the trigger
// is put on the stack, and the source is already in the graveyard then. That
// source has left, so it is null, although the card is visible there and its
// key still matches (a stale-key check alone would keep it). Real cases from
// the catalog decks: Nihil Spellbomb and Ichor Wellspring (Wildfire),
// Clockwork Percussionist (Rally), Mesmeric Fiend (Spy), Outlaw Medic
// (CawGates).
func TestDiesTriggerSourceIsNull(t *testing.T) {
	dead := map[string]bool{"Nihil Spellbomb": true, "Ichor Wellspring": true, "Clockwork Percussionist": true,
		"Mesmeric Fiend": true, "Outlaw Medic": true}
	var ability state.ObjID
	var name string
	g, tr := tracked(t, []string{"Wildfire", "Rally", "Spy", "CawGates"}, func(e *rules.Engine, tr *identity.Tracker) bool {
		for _, id := range e.G.Stack {
			o := e.G.Obj(id)
			src := e.G.Obj(o.Source)
			if o.Ability == nil || o.StackKind != state.StackKindTriggered || src == nil ||
				src.Zone != state.ZGraveyard || src.Face() == nil || !dead[src.Face().Name] {
				continue
			}
			if key, ok := tr.SourceKey(id); ok && key == tr.Key(o.Source) {
				ability, name = id, src.Face().Name
				return true
			}
		}
		return false
	})
	se := entry(t, g, tr, ability)
	if se.StackKind != "triggered_ability" || se.Source != nil {
		t.Fatalf("%s's trigger %+v: source %+v, want null", name, se.ObjectRef, se.Source)
	}
}

// Mesmeric Fiend's leaves-the-battlefield trigger carries no Destination$ in
// its own text (Forge's Origin$ Battlefield with no Destination$: it returns
// the exiled card no matter where the Fiend goes), unlike the five
// Destination$-Graveyard-only cards TestDiesTriggerSourceIsNull covers, and
// the Fiend has two T: lines (its enter trigger and this one), so this pins
// looksBackTrigger to the trigger actually on the stack (matched by Effect),
// not to a card's first trigger. The catalog's mirror matches never remove a
// live creature except by dying, so the reachable case still ends in a
// graveyard; Journey to Nowhere (CawGates) and Experimental Synthesizer
// (Rally) are the same Destination$-unrestricted shape and were checked too,
// but neither deck has anything that removes its own or an opponent's such
// permanent other than dying, so the Fiend is the corpus's only reachable
// instance of this shape.
func TestUnrestrictedDestinationTriggerSourceIsNull(t *testing.T) {
	var trigger state.ObjID
	g, tr := tracked(t, []string{"Spy"}, func(e *rules.Engine, tr *identity.Tracker) bool {
		for _, id := range e.G.Stack {
			o := e.G.Obj(id)
			src := e.G.Obj(o.Source)
			if o.Ability == nil || o.StackKind != state.StackKindTriggered || src == nil ||
				src.Zone != state.ZGraveyard || src.Face() == nil || src.Face().Name != "Mesmeric Fiend" {
				continue
			}
			if key, ok := tr.SourceKey(id); ok && key == tr.Key(o.Source) {
				trigger = id
				return true
			}
		}
		return false
	})
	se := entry(t, g, tr, trigger)
	if se.StackKind != "triggered_ability" || se.Source != nil {
		t.Fatalf("Mesmeric Fiend's leaves trigger %+v: source %+v, want null", se.ObjectRef, se.Source)
	}
}

// Krark-Clan Shaman's activated ability: the Shaman is on the battlefield
// (incarnation 1) while gorge leaves the ability's SourceIncarnation 0, so a
// guard comparing them would null a live source. Section 6.5 keeps it. The
// predicate accepts only a case where that guard would fire, so the test
// stays pinned to the ruling.
func TestActivatedAbilityKeepsItsBattlefieldSource(t *testing.T) {
	var ability state.ObjID
	g, tr := tracked(t, []string{"Wildfire"}, func(e *rules.Engine, tr *identity.Tracker) bool {
		for _, id := range e.G.Stack {
			o := e.G.Obj(id)
			src := e.G.Obj(o.Source)
			if o.Ability != nil && o.StackKind == state.StackKindActivated && src != nil &&
				src.Zone == state.ZBattlefield && src.Face() != nil && src.Face().Name == "Krark-Clan Shaman" &&
				src.Incarnation != o.SourceIncarnation {
				ability = id
				return true
			}
		}
		return false
	})
	se := entry(t, g, tr, ability)
	if se.StackKind != "activated_ability" || se.Source == nil || se.Source.Zone != "battlefield" ||
		se.Source.CardName == nil || *se.Source.CardName != "Krark-Clan Shaman" {
		t.Fatalf("ability %+v: source %+v, want the live Shaman", se.ObjectRef, se.Source)
	}
}

// Squadron Hawk's enter-the-battlefield trigger: the Hawk is on the
// battlefield (incarnation 1) while the trigger waits on the stack with
// SourceIncarnation 0. Same guard, same ruling: the live source stays.
func TestEnterTriggerKeepsItsBattlefieldSource(t *testing.T) {
	var trigger state.ObjID
	g, tr := tracked(t, []string{"CawGates"}, func(e *rules.Engine, tr *identity.Tracker) bool {
		for _, id := range e.G.Stack {
			o := e.G.Obj(id)
			src := e.G.Obj(o.Source)
			if o.Ability != nil && o.StackKind == state.StackKindTriggered && src != nil &&
				src.Zone == state.ZBattlefield && src.Face() != nil && src.Face().Name == "Squadron Hawk" &&
				src.Incarnation != o.SourceIncarnation {
				trigger = id
				return true
			}
		}
		return false
	})
	se := entry(t, g, tr, trigger)
	if se.StackKind != "triggered_ability" || se.Source == nil || se.Source.Zone != "battlefield" ||
		se.Source.CardName == nil || *se.Source.CardName != "Squadron Hawk" {
		t.Fatalf("trigger %+v: source %+v, want the live Hawk", se.ObjectRef, se.Source)
	}
}

// gorge's own status markers (the regeneration Shield and the Deathtouched
// lethal mark) ride ordinary counters for want of a status field. They are
// engine internals, never one of Section 6.10's counters, so the counters map
// skips them.
func TestInternalCounterMarkersAreSkipped(t *testing.T) {
	reg := testcorpus.Registry(t)
	g := testgame.New(t, reg, "Burn", "Burn", 5, "none")
	tr := identity.New(g.E, g.Secret)
	id := g.E.G.Zone(state.ZHand, 0)[0]
	events.Emit(g.E.G, g.E.L, events.Event{Kind: events.MoveZone, Obj: id, From: state.ZHand, To: state.ZBattlefield})
	for _, c := range []struct {
		kind string
		n    int32
	}{{"Shield", 1}, {"Deathtouched", 1}, {"P1P1", 2}} {
		events.Emit(g.E.G, g.E.L, events.Event{Kind: events.CounterChange, Obj: id, Counter: c.kind, Amount: c.n})
	}
	if err := tr.Sync(g.E); err != nil {
		t.Fatal(err)
	}
	rec, err := (&observe.Projector{E: g.E, IDs: tr}).Record(0, id)
	if err != nil {
		t.Fatal(err)
	}
	if rec.Permanent == nil {
		t.Fatal("a battlefield object has no permanent record")
	}
	if rec.Permanent.Counters["p1p1"] != 2 {
		t.Fatalf("counters %v: p1p1 must survive", rec.Permanent.Counters)
	}
	for _, marker := range []string{"shield", "deathtouched"} {
		if _, ok := rec.Permanent.Counters[marker]; ok {
			t.Fatalf("internal marker mapped as %s: %v", marker, rec.Permanent.Counters)
		}
	}
}

// Section 6.6: a pending trigger's source and source_name are populated when
// that source sits in a zone visible to the viewer. Any optional trigger
// (Nihil Spellbomb's dies draw, Gatecreeper Vine's or Squadron Hawk's search)
// pauses with a non-empty pending-trigger queue while its controller is
// asked (CR 603.3b/603.5), so a real catalog game reaches this without any
// state manipulation.
func TestPendingTriggerSourceIsPopulatedWhenVisible(t *testing.T) {
	g, tr := tracked(t, []string{"Wildfire", "Spy", "CawGates"}, func(e *rules.Engine, _ *identity.Tracker) bool {
		return len(e.PendingTriggers()) > 0
	})
	pts := g.E.PendingTriggers()
	pt := pts[0]
	src := g.E.G.Obj(pt.Source)
	if src == nil || src.Face() == nil {
		t.Fatal("pending trigger source is gone")
	}
	p := &observe.Projector{E: g.E, IDs: tr}
	obs, err := p.Observation(0, observe.State{})
	if err != nil {
		t.Fatal(err)
	}
	if len(obs.PendingTriggers) == 0 {
		t.Fatal("observation lists no pending triggers")
	}
	got := obs.PendingTriggers[0]
	wantRef, err := p.Ref(0, pt.Source)
	if err != nil {
		t.Fatal(err)
	}
	if wantRef == nil {
		t.Fatal("the trigger's own source has no reference from p0")
	}
	if got.ControllerSeat != observe.Seat(pt.Controller) {
		t.Fatalf("controller_seat %s, want %s", got.ControllerSeat, observe.Seat(pt.Controller))
	}
	if got.Source == nil || got.Source.ObjectID != wantRef.ObjectID {
		t.Fatalf("source %+v, want %+v", got.Source, wantRef)
	}
	if got.SourceName == nil || *got.SourceName != src.Face().Name {
		t.Fatalf("source_name %v, want %q", got.SourceName, src.Face().Name)
	}
}

// Section 6.6: a pending trigger whose source sits in a zone hidden from the
// viewer (a hand, unrevealed) is omitted from that viewer's list. No catalog
// card's own trigger fires while its source already sits in a hand, so this
// relocates a real trigger's source directly (as
// TestInternalCounterMarkersAreSkipped relocates a card to build its
// scenario). The omission check reads the source's zone fresh from the game
// at observation time (Visible(b.viewer, g.Obj(pt.Source))), so moving the
// same real trigger's source after the fact exercises exactly the code a
// naturally hand-sourced trigger would.
func TestPendingTriggerFromAHiddenHandIsOmitted(t *testing.T) {
	g, tr := tracked(t, []string{"Wildfire", "Spy", "CawGates"}, func(e *rules.Engine, _ *identity.Tracker) bool {
		return len(e.PendingTriggers()) > 0
	})
	pts := g.E.PendingTriggers()
	before := len(pts)
	pt := pts[0]
	src := g.E.G.Obj(pt.Source)
	if src == nil {
		t.Fatal("pending trigger source is gone")
	}
	viewer := 1 - src.Owner
	events.Emit(g.E.G, g.E.L, events.Event{Kind: events.MoveZone, Obj: pt.Source, From: src.Zone, To: state.ZHand})
	if err := tr.Sync(g.E); err != nil {
		t.Fatal(err)
	}
	p := &observe.Projector{E: g.E, IDs: tr}
	obs, err := p.Observation(viewer, observe.State{})
	if err != nil {
		t.Fatal(err)
	}
	if len(obs.PendingTriggers) != before-1 {
		t.Fatalf("pending_triggers has %d entries, want %d (the hand-hidden source omitted): %+v",
			len(obs.PendingTriggers), before-1, obs.PendingTriggers)
	}
}
