package observe_test

import (
	"encoding/json"
	"strconv"
	"strings"
	"testing"

	"github.com/adams-shaun/gorge/events"
	"github.com/adams-shaun/gorge/rules"
	"github.com/adams-shaun/gorge/state"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/identity"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/observe"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/testcorpus"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/testgame"
)

func TestObservationHidesTheOtherHandAndLibraries(t *testing.T) {
	reg := testcorpus.Registry(t)
	g := testgame.New(t, reg, "Burn", "CawGates", 4, "none")
	p := &observe.Projector{E: g.E, IDs: identity.New(g.E, g.Secret)}
	obs, err := p.Observation(0, observe.State{})
	if err != nil {
		t.Fatal(err)
	}
	if obs.Players[1].Hand != nil || len(obs.Players[0].Hand) != 7 || obs.Players[1].HandCount != 7 {
		t.Fatalf("hands: %d own, other %v", len(obs.Players[0].Hand), obs.Players[1].Hand)
	}
	if obs.Players[0].LibraryCount != 53 || obs.PhaseStep == "" || obs.Known == nil || obs.PendingTriggers == nil {
		t.Fatalf("observation %+v", obs)
	}
	b, _ := json.Marshal(obs)
	if strings.Contains(string(b), `"zone":"library"`) {
		t.Fatal("a zone array holds a library object")
	}
	// No card of p1's hand or library may be named anywhere, unless the same
	// name is in a zone p0 sees. (Burn and CawGates share no card.)
	seen := map[string]bool{}
	for _, pl := range obs.Players {
		for _, zone := range [][]protocol.ObjectRecord{pl.Hand, pl.Battlefield, pl.Graveyard, pl.Exile, pl.Command} {
			for _, rec := range zone {
				if rec.CardName != nil {
					seen[*rec.CardName] = true
				}
			}
		}
	}
	hidden := 0
	for _, z := range []state.Zone{state.ZHand, state.ZLibrary} {
		for _, id := range g.E.G.Zone(z, 1) {
			name := g.E.G.Obj(id).Face().Name
			if seen[name] {
				continue
			}
			hidden++
			if strings.Contains(string(b), strconv.Quote(name)) {
				t.Fatalf("hidden card %s is named in p0's observation", name)
			}
		}
	}
	if hidden != 60 {
		t.Fatalf("scanned %d hidden cards, want p1's 60", hidden)
	}
}

func TestCharacteristicsOfBasicLandAndBolt(t *testing.T) {
	reg := testcorpus.Registry(t)
	g := testgame.New(t, reg, "Burn", "Burn", 5, "none")
	p := &observe.Projector{E: g.E, IDs: identity.New(g.E, g.Secret)}
	for _, id := range g.E.G.Zone(state.ZHand, 0) {
		rec, err := p.Record(0, id)
		if err != nil {
			t.Fatal(err)
		}
		c := rec.Characteristics
		switch *rec.CardName {
		case "Mountain":
			if c.Supertypes[0] != "basic" || c.Types[0] != "land" || c.Subtypes[0] != "mountain" || c.ManaValue != 0 || c.Power != nil {
				t.Errorf("Mountain %+v", c)
			}
		case "Lightning Bolt":
			if c.Types[0] != "instant" || c.Colors[0] != "red" || c.ManaValue != 1 {
				t.Errorf("Lightning Bolt %+v", c)
			}
		}
		if rec.Permanent != nil || rec.Token || rec.Copy {
			t.Errorf("%s in hand has permanent fields", *rec.CardName)
		}
	}
}

// observe.Visible decides which objects take a visible id, and identity's
// LookID refuses exactly those: identity cannot import observe, so it keeps a
// copy of the rule. The two must agree for both viewers on every kind of
// object, or an object could get two ids or none.
func TestVisibleAgreesWithLookIDRefusal(t *testing.T) {
	reg := testcorpus.Registry(t)
	g := testgame.New(t, reg, "Burn", "CawGates", 4, "none")
	tr := identity.New(g.E, g.Secret)
	hand := g.E.G.Zone(state.ZHand, 0)
	own, up, down, dead, exiled, spell := hand[0], hand[1], hand[2], hand[3], hand[4], hand[5]
	other, top := g.E.G.Zone(state.ZHand, 1)[0], g.E.G.Zone(state.ZLibrary, 0)[0]
	for _, ev := range []events.Event{
		{Kind: events.MoveZone, Obj: up, From: state.ZHand, To: state.ZBattlefield},
		{Kind: events.MoveZone, Obj: down, From: state.ZHand, To: state.ZBattlefield, Counter: events.FaceDownEntryCounter},
		{Kind: events.MoveZone, Obj: dead, From: state.ZHand, To: state.ZGraveyard},
		{Kind: events.MoveZone, Obj: exiled, From: state.ZHand, To: state.ZExile, Counter: "exiled_with_face_down"},
		{Kind: events.PutOnStack, Obj: spell, From: state.ZHand, To: state.ZStack},
		{Kind: events.Note, Player: 0, IDs: []state.ObjID{top}}, // a public reveal, as gorge's Dig emits
	} {
		events.Emit(g.E.G, g.E.L, ev)
	}
	if err := tr.Sync(g.E); err != nil {
		t.Fatal(err)
	}
	for _, c := range []struct {
		what     string
		id       state.ObjID
		zone     state.Zone
		faceDown bool
		sees     [2]bool // Visible to p0, to p1
	}{
		{"p0's hand", own, state.ZHand, false, [2]bool{true, false}},
		{"p1's hand", other, state.ZHand, false, [2]bool{false, true}},
		{"battlefield, face up", up, state.ZBattlefield, false, [2]bool{true, true}},
		{"battlefield, face down", down, state.ZBattlefield, true, [2]bool{true, true}},
		// A revealed library card stays in its hidden zone: it keeps taking
		// look ids, never a visible id.
		{"library top, revealed", top, state.ZLibrary, false, [2]bool{false, false}},
		{"graveyard", dead, state.ZGraveyard, false, [2]bool{true, true}},
		{"exile, face down", exiled, state.ZExile, true, [2]bool{true, true}},
		{"stack", spell, state.ZStack, false, [2]bool{true, true}},
	} {
		if o := g.E.G.Obj(c.id); o.Zone != c.zone || o.FaceDown != c.faceDown {
			t.Fatalf("%s: object %d is in %s, face down %v", c.what, c.id, o.Zone, o.FaceDown)
		}
		for v := state.PlayerID(0); v < 2; v++ {
			tr.OpenLook(v)
			_, err := tr.LookID(v, c.id)
			tr.CloseLook(v)
			if sees := observe.Visible(v, g.E.G.Obj(c.id)); sees != c.sees[v] || (err != nil) != sees {
				t.Errorf("%s, viewer p%d: Visible %v, want %v; LookID error %v", c.what, v, sees, c.sees[v], err)
			}
		}
	}
}

// listed returns the ids of obs's zone records.
func listed(obs protocol.Observation) map[string]bool {
	ids := map[string]bool{}
	for _, pl := range obs.Players {
		for _, zone := range [][]protocol.ObjectRecord{pl.Hand, pl.Battlefield, pl.Graveyard, pl.Exile, pl.Command} {
			for _, rec := range zone {
				ids[rec.ObjectID] = true
			}
		}
	}
	return ids
}

// Ref is null for an object the observation does not list (Section 5.1: a
// reference to an absent object is null), although its zone is public: gorge
// parks a resolved ability in exile, leaves a token that left the battlefield
// in its new zone until a state-based check, and keeps a phased-out permanent
// on the battlefield, and its seat view omits all three. A stack object, an
// ability included, keeps its reference (Task 12 lists the stack).
func TestRefIsNullForObjectsTheObservationOmits(t *testing.T) {
	reg := testcorpus.Registry(t)
	g := testgame.New(t, reg, "Burn", "Wildfire", 5, "none")
	tr := identity.New(g.E, g.Secret)
	p := &observe.Projector{E: g.E, IDs: tr}
	var stacked, parked bool // an ability on the stack had a Ref; a resolved one parked in exile had none
	var token state.ObjID    // a token on the battlefield
	check := func(e *rules.Engine) {
		for v := state.PlayerID(0); v < 2; v++ {
			obs, err := p.Observation(v, observe.State{})
			if err != nil {
				t.Fatal(err)
			}
			ids := listed(obs)
			for i := range e.G.Objs {
				o := &e.G.Objs[i]
				ref, err := p.Ref(v, o.ID)
				if err != nil {
					t.Fatal(err)
				}
				switch {
				case o.Zone == state.ZStack:
					if ref == nil {
						t.Fatalf("p%d: stack object %d has no Ref", v, o.ID)
					}
					stacked = stacked || o.Ability != nil
				case ref != nil && !ids[ref.ObjectID]:
					t.Fatalf("p%d: Ref of object %d in %s is %s, which the observation does not list", v, o.ID, o.Zone, ref.ObjectID)
				case ref == nil && o.Zone == state.ZExile && o.Ability != nil:
					parked = true
				}
				if o.IsToken && o.Zone == state.ZBattlefield {
					token = o.ID
				}
			}
		}
	}
	if !testgame.RunUntil(t, g, testgame.Bots(5), func(e *rules.Engine) bool {
		if err := tr.Sync(e); err != nil {
			t.Fatal(err)
		}
		token = 0
		check(e)
		return stacked && parked && token != 0
	}, 20000) {
		t.Fatalf("ability on the stack %v, parked in exile %v, token %d: pick another seed", stacked, parked, token)
	}
	var perm state.ObjID // a permanent that is not the token
	for _, id := range g.E.G.Zone(state.ZBattlefield, 0) {
		if id != token {
			perm = id
		}
	}
	if perm == 0 {
		t.Fatal("p0 has no permanent to phase out: pick another seed")
	}
	events.Emit(g.E.G, g.E.L, events.Event{Kind: events.MoveZone, Obj: token, Player: g.E.G.Obj(token).Owner, From: state.ZBattlefield, To: state.ZGraveyard})
	events.Emit(g.E.G, g.E.L, events.Event{Kind: events.PhaseOut, Obj: perm, Amount: 1})
	if err := tr.Sync(g.E); err != nil {
		t.Fatal(err)
	}
	if z := g.E.G.Obj(token).Zone; z != state.ZGraveyard || !g.E.G.Obj(perm).PhasedOut {
		t.Fatalf("token %d in %s, permanent %d phased out %v", token, z, perm, g.E.G.Obj(perm).PhasedOut)
	}
	check(g.E)
	for v := state.PlayerID(0); v < 2; v++ {
		for _, id := range []state.ObjID{token, perm} {
			if ref, err := p.Ref(v, id); ref != nil || err != nil {
				t.Fatalf("p%d: object %d in %s has Ref %+v, error %v", v, id, g.E.G.Obj(id).Zone, ref, err)
			}
		}
	}
}
