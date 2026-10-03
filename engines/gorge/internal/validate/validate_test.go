package validate_test

import (
	"cmp"
	"encoding/json"
	"errors"
	"slices"
	"testing"

	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/validate"
)

func profile() validate.Profile {
	return validate.Profile{Kinds: map[string]bool{"pass": true, "play_land": true, "declare_attack": true},
		Flags: map[string]bool{"pending_triggers": true, "keywords": true}}
}

func str(s string) *string { return &s }

func base(seatStep uint64, group uint64) protocol.SeatDecision {
	obs := protocol.Observation{Viewer: "p0", PhaseStep: "precombat_main", Stack: []protocol.StackEntry{},
		PendingTriggers: []protocol.PendingTrigger{}, Known: []protocol.Known{}}
	for i := range obs.Players {
		obs.Players[i] = protocol.PlayerObs{Seat: []string{"p0", "p1"}[i], Battlefield: []protocol.ObjectRecord{},
			Graveyard: []protocol.ObjectRecord{}, Exile: []protocol.ObjectRecord{}, Command: []protocol.ObjectRecord{}}
	}
	obs.Players[0].Hand = []protocol.ObjectRecord{}
	return protocol.SeatDecision{ActingSeat: "p0", SeatStep: seatStep, Group: protocol.Group{GroupID: group, SubstepCount: 1},
		Context: protocol.Context{Kind: "priority"}, Observation: obs,
		Candidates: []protocol.Candidate{{Semantic: protocol.Pass()}}, Extensions: map[string]json.RawMessage{}}
}

func rule(err error) string {
	var v *validate.Violation
	if errors.As(err, &v) {
		return v.Rule
	}
	return ""
}

func TestValidSequencePasses(t *testing.T) {
	s := validate.NewStream(profile())
	for i := uint64(0); i < 3; i++ {
		if err := s.Check(base(i, i)); err != nil {
			t.Fatalf("decision %d: %v", i, err)
		}
	}
}

func TestViolationsNameTheirRule(t *testing.T) {
	cases := map[string]func(*protocol.SeatDecision){
		"V2": func(sd *protocol.SeatDecision) { sd.Observation.Viewer = "p1" },
		"V3": func(sd *protocol.SeatDecision) { sd.SeatStep = 5 },
		"V5": func(sd *protocol.SeatDecision) { sd.Observation.Players[1].Hand = []protocol.ObjectRecord{} },
		"V8": func(sd *protocol.SeatDecision) { sd.Observation.DayNight = str("day") },
		"V9": func(sd *protocol.SeatDecision) { sd.Context.Kind = "choice" },
		"V1": func(sd *protocol.SeatDecision) {
			sd.Candidates = append(sd.Candidates, protocol.Candidate{CandidateID: 1, Semantic: protocol.Pass()})
		},
	}
	for want, mutate := range cases {
		s := validate.NewStream(profile())
		sd := base(0, 0)
		mutate(&sd)
		if got := rule(s.Check(sd)); got != want {
			t.Errorf("mutation for %s reported %q", want, got)
		}
	}
}

func TestIDFreshnessAcrossTheSeatStream(t *testing.T) {
	s := validate.NewStream(profile())
	name := "Mountain"
	rec := protocol.ObjectRecord{ObjectRef: protocol.ObjectRef{ObjectID: "o-1", CardName: &name, OwnerSeat: "p0", ControllerSeat: "p0", Zone: "hand"}}
	sd := base(0, 0)
	sd.Observation.Players[0].Hand = []protocol.ObjectRecord{rec}
	sd.Observation.Players[0].HandCount = 1
	if err := s.Check(sd); err != nil {
		t.Fatal(err)
	}
	rec.Zone = "battlefield" // same id, new zone: forbidden (V7)
	sd = base(1, 1)
	sd.Observation.Players[0].Battlefield = []protocol.ObjectRecord{rec}
	if got := rule(s.Check(sd)); got != "V7" {
		t.Fatalf("reused id across zones reported %q", got)
	}
}

// verdict is the rule a Check result names, "" for a pass, and the error text
// for an error that is not a Violation (so it never reads as a pass).
func verdict(err error) string {
	if err == nil {
		return ""
	}
	if r := rule(err); r != "" {
		return r
	}
	return "not a Violation: " + err.Error()
}

func u32(n uint32) *uint32 { return &n }

// ref is a reference to a card its owner controls.
func ref(id, name, owner, zone string) protocol.ObjectRef {
	return protocol.ObjectRef{ObjectID: id, CardName: str(name), OwnerSeat: owner, ControllerSeat: owner, Zone: zone}
}

func chars(types ...string) *protocol.Characteristics {
	return &protocol.Characteristics{Supertypes: []string{}, Types: types, Subtypes: []string{}, Colors: []string{}, Keywords: []string{}}
}

// card is an object record off the battlefield, permanent one on it.
func card(r protocol.ObjectRef, types ...string) protocol.ObjectRecord {
	return protocol.ObjectRecord{ObjectRef: r, Characteristics: chars(types...)}
}

func permanent(r protocol.ObjectRef, types ...string) protocol.ObjectRecord {
	rec := card(r, types...)
	rec.Permanent = &protocol.Permanent{Counters: map[string]uint32{}, BlockedAttackers: []protocol.ObjectRef{}}
	return rec
}

// every declares all 30 kinds and the given observation flags.
func every(flags ...string) validate.Profile {
	p := validate.Profile{Kinds: map[string]bool{}, Flags: map[string]bool{}, Extensions: map[string]bool{}}
	for k := range protocol.KindFields {
		p.Kinds[k] = true
	}
	for _, f := range flags {
		p.Flags[f] = true
	}
	return p
}

// check runs one decision as the first of a fresh stream.
func check(p validate.Profile, sd protocol.SeatDecision) string {
	return verdict(validate.NewStream(p).Check(sd))
}

// The subset's rules the cases above leave untested (V1, V3, V5 to V8), one
// violation each; every decision before the last must pass.
func TestSubsetRulesNameTheirRule(t *testing.T) {
	mtn := card(ref("o-mtn", "Mountain", "p0", "hand"), "land")
	fullName := profile()
	fullName.Flags["full_name"] = true
	one := func(mutate func(*protocol.SeatDecision)) []protocol.SeatDecision {
		sd := base(0, 0)
		mutate(&sd)
		return []protocol.SeatDecision{sd}
	}
	groups := func(gs ...protocol.Group) (out []protocol.SeatDecision) {
		for i, g := range gs {
			sd := base(uint64(i), 0)
			sd.Group = g
			out = append(out, sd)
		}
		return out
	}
	hands := func(hs ...[]protocol.ObjectRecord) (out []protocol.SeatDecision) {
		for i, h := range hs {
			sd := base(uint64(i), uint64(i))
			sd.Observation.Players[0].Hand, sd.Observation.Players[0].HandCount = h, uint32(len(h))
			out = append(out, sd)
		}
		return out
	}
	looks := func(ks ...[]protocol.Known) (out []protocol.SeatDecision) {
		for i, k := range ks {
			sd := base(uint64(i), uint64(i))
			sd.Observation.Known = k
			out = append(out, sd)
		}
		return out
	}
	faceDown := func(seat string, name *string) protocol.ObjectRecord {
		rec := permanent(protocol.ObjectRef{ObjectID: "o-fd", CardName: name, OwnerSeat: seat, ControllerSeat: seat, Zone: "battlefield"}, "creature")
		rec.FaceDown = true
		return rec
	}
	look := []protocol.Known{{OwnerSeat: "p0", Zone: "library", CardName: "Island", ObjectID: str("o-1"), PositionFromTop: u32(0), How: "looked_at"}}
	for _, c := range []struct {
		what, want string
		p          validate.Profile
		steps      []protocol.SeatDecision
	}{
		{"no candidates", "V1", profile(), one(func(sd *protocol.SeatDecision) { sd.Candidates = nil })},
		{"a candidate id out of place", "V1", profile(), one(func(sd *protocol.SeatDecision) { sd.Candidates[0].CandidateID = 1 })},
		{"pass after another candidate", "V1", profile(), one(func(sd *protocol.SeatDecision) {
			sd.Observation.Players[0].Hand, sd.Observation.Players[0].HandCount = []protocol.ObjectRecord{mtn}, 1
			sd.Candidates = []protocol.Candidate{{CandidateID: 0, Semantic: protocol.PlayLand(mtn.ObjectRef, 0)},
				{CandidateID: 1, Semantic: protocol.Pass()}}
		})},
		{"a malformed semantic", "V1", profile(), one(func(sd *protocol.SeatDecision) {
			sd.Candidates[0].Semantic = protocol.Semantic{Kind: "pass", Fields: map[string]any{"extra": true}}
		})},
		{"an undeclared kind", "V8", profile(), one(func(sd *protocol.SeatDecision) {
			sd.Observation.Players[0].Hand, sd.Observation.Players[0].HandCount = []protocol.ObjectRecord{mtn}, 1
			sd.Candidates = append(sd.Candidates, protocol.Candidate{CandidateID: 1, Semantic: protocol.CastSpell(mtn.ObjectRef, "normal")})
		})},
		{"a viewer hand unlike hand_count", "V5", profile(), one(func(sd *protocol.SeatDecision) { sd.Observation.Players[0].HandCount = 1 })},
		{"a library object in a zone array", "V5", profile(), one(func(sd *protocol.SeatDecision) {
			sd.Observation.Players[0].Graveyard = []protocol.ObjectRecord{card(ref("o-lib", "Island", "p0", "library"), "land")}
		})},
		{"a named face-down permanent of the other seat", "V6", profile(), one(func(sd *protocol.SeatDecision) {
			sd.Observation.Players[1].Battlefield = []protocol.ObjectRecord{faceDown("p1", str("Pestermite"))}
		})},
		{"a face-down permanent of the other seat with a full_name", "V6", fullName, one(func(sd *protocol.SeatDecision) {
			rec := faceDown("p1", nil)
			rec.FullName = str("Sagu Wildling // Roost Seek")
			sd.Observation.Players[1].Battlefield = []protocol.ObjectRecord{rec}
		})},
		{"a nameless face-down permanent of the other seat", "", profile(), one(func(sd *protocol.SeatDecision) {
			sd.Observation.Players[1].Battlefield = []protocol.ObjectRecord{faceDown("p1", nil)}
		})},
		{"the viewer's own named face-down permanent", "", profile(), one(func(sd *protocol.SeatDecision) {
			sd.Observation.Players[0].Battlefield = []protocol.ObjectRecord{faceDown("p0", str("Pestermite"))}
		})},
		{"a named face-down spell of the other seat", "V6", profile(), one(func(sd *protocol.SeatDecision) {
			sd.Observation.Stack = []protocol.StackEntry{{ObjectRef: ref("o-fd", "Pestermite", "p1", "stack"), StackKind: "spell",
				FaceDown: true, Characteristics: chars("creature"), Targets: []*protocol.TargetRef{}}}
		})},
		{"the viewer's own named face-down spell", "", profile(), one(func(sd *protocol.SeatDecision) {
			sd.Observation.Stack = []protocol.StackEntry{{ObjectRef: ref("o-fd", "Pestermite", "p0", "stack"), StackKind: "spell",
				FaceDown: true, Characteristics: chars("creature"), Targets: []*protocol.TargetRef{}}}
		})},
		{"a group that skips an id", "V3", profile(), groups(protocol.Group{GroupID: 0, SubstepCount: 1}, protocol.Group{GroupID: 2, SubstepCount: 1})},
		{"a new group while one is partial", "V3", profile(), groups(protocol.Group{GroupID: 0, SubstepCount: 2}, protocol.Group{GroupID: 1, SubstepCount: 1})},
		{"a partial group that changes size", "V3", profile(), groups(protocol.Group{GroupID: 0, SubstepCount: 2},
			protocol.Group{GroupID: 0, SubstepIndex: 1, SubstepCount: 3})},
		{"a group without substeps", "V3", profile(), groups(protocol.Group{GroupID: 0})},
		{"a group that starts past substep 0", "V3", profile(), groups(protocol.Group{GroupID: 0, SubstepIndex: 1, SubstepCount: 2})},
		{"an id that returns after leaving", "V7", profile(), hands([]protocol.ObjectRecord{mtn}, []protocol.ObjectRecord{}, []protocol.ObjectRecord{mtn})},
		{"a look id that returns after leaving", "V7", profile(), looks(look, []protocol.Known{}, look)},
		{"a rewind, which this engine never declares", "V3", profile(), one(func(sd *protocol.SeatDecision) { sd.Context.Rewind = true })},
	} {
		s := validate.NewStream(c.p)
		for i, sd := range c.steps {
			want := ""
			if i == len(c.steps)-1 {
				want = c.want
			}
			if got := verdict(s.Check(sd)); got != want {
				t.Errorf("%s: decision %d reported %q, want %q", c.what, i, got, want)
				break
			}
		}
	}
}

// A candidate that Check accepts but JSON cannot encode (json.Number holding
// an invalid literal, which strconv.ParseInt reads) fails V1, so V4 and V5
// never skip its references: here a source that is not in the observation.
func TestCandidatesThatDoNotEncodeFailClosed(t *testing.T) {
	stranger := ref("o-x", "Fireball", "p0", "stack")
	for _, literal := range []string{"+1", "007"} {
		sem := protocol.ChooseNumber(&stranger, "x_value", 0, 0, 9)
		sem.Fields["value"] = json.Number(literal)
		sd := base(0, 0)
		sd.Context = protocol.Context{Kind: "choice", Purpose: str("x_value")}
		sd.Candidates = []protocol.Candidate{{CandidateID: 0, Semantic: sem}}
		if got := check(every("pending_triggers", "keywords"), sd); got != "V1" {
			t.Errorf("value %s reported %q, want V1", literal, got)
		}
	}
}

// Distinctness compares values, not bytes: a decoded twin of a Go-built
// candidate, its reference keys in another order or its number written -0,
// repeats it (V1).
func TestDistinctnessComparesValues(t *testing.T) {
	mtn := ref("o-mtn", "Mountain", "p0", "hand")
	for _, raw := range []string{
		`{"kind":"play_land","face":0,"source":{"zone":"hand","object_id":"o-mtn","card_name":"Mountain","owner_seat":"p0","controller_seat":"p0"}}`,
		`{"kind":"play_land","face":-0,"source":{"object_id":"o-mtn","card_name":"Mountain","owner_seat":"p0","controller_seat":"p0","zone":"hand"}}`,
	} {
		var twin protocol.Semantic
		if err := json.Unmarshal([]byte(raw), &twin); err != nil {
			t.Fatal(err)
		}
		sd := base(0, 0)
		sd.Observation.Players[0].Hand, sd.Observation.Players[0].HandCount = []protocol.ObjectRecord{card(mtn, "land")}, 1
		sd.Candidates = append(sd.Candidates, protocol.Candidate{CandidateID: 1, Semantic: protocol.PlayLand(mtn, 0)},
			protocol.Candidate{CandidateID: 2, Semantic: twin})
		if got := check(profile(), sd); got != "V1" {
			t.Errorf("%s beside its Go-built twin reported %q, want V1", raw, got)
		}
	}
}

// V1 and V8: extensions is an object (Sections 9.3 and 14) whose keys are x_
// names enabled for the game.
func TestExtensionsAreAnObjectOfEnabledKeys(t *testing.T) {
	p := profile()
	p.Extensions = map[string]bool{"x_gorge_view_v1": true, "gorge_view": true, "x_Gorge": true}
	payload := json.RawMessage(`{}`)
	for _, c := range []struct {
		what, want string
		ext        protocol.ExtensionMap
	}{
		{"null", "V1", nil},
		{"empty", "", protocol.ExtensionMap{}},
		{"with an enabled key", "", protocol.ExtensionMap{"x_gorge_view_v1": payload}},
		{"with a key the game did not enable", "V8", protocol.ExtensionMap{"x_other": payload}},
		{"with an enabled key lacking x_", "V8", protocol.ExtensionMap{"gorge_view": payload}},
		{"with an enabled key holding a capital", "V8", protocol.ExtensionMap{"x_Gorge": payload}},
	} {
		sd := base(0, 0)
		sd.Extensions = c.ext
		if got := check(p, sd); got != c.want {
			t.Errorf("extensions %s reported %q, want %q", c.what, got, c.want)
		}
	}
}

func TestEqualRefComparesEveryField(t *testing.T) {
	a := ref("o-1", "Island", "p0", "hand")
	b := a
	b.CardName = str("Island")
	if !validate.EqualRef(a, b) {
		t.Fatal("equal names behind distinct pointers compare unequal")
	}
	for what, change := range map[string]func(*protocol.ObjectRef){
		"object_id":       func(r *protocol.ObjectRef) { r.ObjectID = "o-2" },
		"card_name":       func(r *protocol.ObjectRef) { r.CardName = str("Forest") },
		"null card_name":  func(r *protocol.ObjectRef) { r.CardName = nil },
		"owner_seat":      func(r *protocol.ObjectRef) { r.OwnerSeat = "p1" },
		"controller_seat": func(r *protocol.ObjectRef) { r.ControllerSeat = "p1" },
		"zone":            func(r *protocol.ObjectRef) { r.Zone = "graveyard" },
	} {
		b := a
		change(&b)
		if validate.EqualRef(a, b) || validate.EqualRef(b, a) {
			t.Errorf("a different %s compares equal", what)
		}
	}
}

// board is a choice decision with a record behind every kind of reference
// V4 names: candidate and context sources, exiled_by, an attachment, an
// attack target, a blocked attacker, stack sources and targets, and a
// pending-trigger source.
func board() protocol.SeatDecision {
	bear := ref("o-bear", "Grizzly Bears", "p0", "battlefield")
	aura := ref("o-aura", "Rancor", "p0", "battlefield")
	gone := ref("o-gone", "Pestermite", "p0", "exile")
	wall := ref("o-wall", "Wall of Omens", "p1", "battlefield")
	walker := ref("o-walker", "Karn, the Great Creator", "p1", "battlefield")
	jail := ref("o-jail", "Journey to Nowhere", "p1", "battlefield")
	bolt := ref("o-bolt", "Lightning Bolt", "p1", "stack")
	pump := ref("o-pump", "Grizzly Bears", "p0", "stack")
	walkerTarget, bearTarget, p1 := protocol.ObjectTarget(walker), protocol.ObjectTarget(bear), protocol.PlayerTarget("p1")
	attacker, enchantment, blocker := permanent(bear, "creature"), permanent(aura, "enchantment"), permanent(wall, "creature")
	attacker.Permanent.Attacking, attacker.Permanent.AttackTarget = true, &walkerTarget
	enchantment.Permanent.AttachedTo = &bearTarget
	blocker.Permanent.Blocking, blocker.Permanent.BlockedAttackers = true, []protocol.ObjectRef{bear}
	exiled := card(gone, "creature")
	exiled.ExiledBy = &jail

	sd := base(0, 0)
	o := &sd.Observation
	o.Players[0].Battlefield = []protocol.ObjectRecord{attacker, enchantment}
	o.Players[0].Exile = []protocol.ObjectRecord{exiled}
	o.Players[1].Battlefield = []protocol.ObjectRecord{blocker, permanent(walker, "planeswalker"), permanent(jail, "enchantment")}
	o.Stack = []protocol.StackEntry{
		{ObjectRef: bolt, StackKind: "spell", Characteristics: chars("instant"), Targets: []*protocol.TargetRef{&bearTarget}},
		{ObjectRef: pump, StackKind: "activated_ability", Source: &bear, Targets: []*protocol.TargetRef{&p1, nil}},
	}
	o.PendingTriggers = []protocol.PendingTrigger{{Source: &walker, ControllerSeat: "p1"}}
	sd.Context = protocol.Context{Kind: "choice", Source: &pump}
	sd.Candidates = []protocol.Candidate{
		{CandidateID: 0, Semantic: protocol.ChooseTarget(pump, 0, protocol.ObjectTarget(wall), 0, 1, 1)},
		{CandidateID: 1, Semantic: protocol.ChooseTarget(pump, 0, protocol.PlayerTarget("p1"), 0, 1, 1)},
	}
	return sd
}

// V4 over every reference (G1-11), not only candidates; ids unique.
func TestEveryReferenceMatchesItsRecord(t *testing.T) {
	p := every("pending_triggers", "keywords", "exiled_by")
	if got := check(p, board()); got != "" {
		t.Fatalf("board reported %q", got)
	}
	stranger := ref("o-x", "Swamp", "p1", "battlefield")
	misrecorded := ref("o-bear", "Grizzly Bears", "p0", "battlefield")
	misrecorded.ControllerSeat = "p1"
	obj := func(r protocol.ObjectRef) *protocol.TargetRef { tr := protocol.ObjectTarget(r); return &tr }
	perm := func(sd *protocol.SeatDecision, seat, i int) *protocol.Permanent {
		return sd.Observation.Players[seat].Battlefield[i].Permanent
	}
	for _, c := range []struct {
		what, want string
		mutate     func(*protocol.SeatDecision)
	}{
		{"context.source", "V4", func(sd *protocol.SeatDecision) { sd.Context.Source = &stranger }},
		{"a candidate source", "V4", func(sd *protocol.SeatDecision) {
			sd.Candidates[1].Semantic = protocol.ChooseTarget(stranger, 0, protocol.PlayerTarget("p1"), 0, 1, 1)
		}},
		{"a candidate target", "V4", func(sd *protocol.SeatDecision) {
			sd.Candidates[0].Semantic = protocol.ChooseTarget(*sd.Context.Source, 0, protocol.ObjectTarget(stranger), 0, 1, 1)
		}},
		{"exiled_by", "V4", func(sd *protocol.SeatDecision) { sd.Observation.Players[0].Exile[0].ExiledBy = &stranger }},
		{"attached_to", "V4", func(sd *protocol.SeatDecision) { perm(sd, 0, 1).AttachedTo = obj(stranger) }},
		{"attack_target", "V4", func(sd *protocol.SeatDecision) { perm(sd, 0, 0).AttackTarget = obj(stranger) }},
		{"blocked_attackers", "V4", func(sd *protocol.SeatDecision) {
			perm(sd, 1, 0).BlockedAttackers = []protocol.ObjectRef{stranger}
		}},
		{"a stack source", "V4", func(sd *protocol.SeatDecision) { sd.Observation.Stack[1].Source = &stranger }},
		{"a stack target", "V4", func(sd *protocol.SeatDecision) {
			sd.Observation.Stack[0].Targets = []*protocol.TargetRef{obj(stranger)}
		}},
		{"a pending-trigger source", "V4", func(sd *protocol.SeatDecision) { sd.Observation.PendingTriggers[0].Source = &stranger }},
		{"a reference unlike its record", "V4", func(sd *protocol.SeatDecision) {
			perm(sd, 1, 0).BlockedAttackers = []protocol.ObjectRef{misrecorded}
		}},
		{"a record twice", "V4", func(sd *protocol.SeatDecision) {
			bf := &sd.Observation.Players[1].Battlefield
			*bf = append(*bf, (*bf)[1])
		}},
		{"a permanent's id on the stack", "V4", func(sd *protocol.SeatDecision) { sd.Observation.Stack[0].ObjectID = "o-wall" }},
		{"a permanent's id in known", "V4", func(sd *protocol.SeatDecision) {
			sd.Observation.Known = []protocol.Known{{OwnerSeat: "p0", Zone: "library", CardName: "Island",
				ObjectID: str("o-jail"), PositionFromTop: u32(0), How: "looked_at"}}
		}},
		{"an attachment that is neither player nor object", "V1", func(sd *protocol.SeatDecision) {
			perm(sd, 0, 1).AttachedTo = &protocol.TargetRef{}
		}},
		{"an attack on a player that is not a seat", "V1", func(sd *protocol.SeatDecision) {
			p2 := protocol.PlayerTarget("p2")
			perm(sd, 0, 0).AttackTarget = &p2
		}},
		{"a stack target with both members", "V1", func(sd *protocol.SeatDecision) {
			sd.Observation.Stack[1].Targets = []*protocol.TargetRef{{Player: str("p1"), Object: &stranger}}
		}},
	} {
		sd := board()
		c.mutate(&sd)
		if got := check(p, sd); got != c.want {
			t.Errorf("%s reported %q, want %s", c.what, got, c.want)
		}
	}
}

type knownCase struct {
	what, want string
	known      []protocol.Known
}

// V5: known entries obey Section 6.7's shape, count and order. known_cards is
// true here, so entries need not be current looks (V8 checks that).
func TestKnownShapeCountAndOrder(t *testing.T) {
	p := every("pending_triggers", "keywords", "known_cards")
	zero, one := u32(0), u32(1)
	lib := func(owner, name string, top, bottom *uint32, how string) protocol.Known {
		return protocol.Known{OwnerSeat: owner, Zone: "library", CardName: name, PositionFromTop: top, PositionFromBottom: bottom, How: how}
	}
	hand := func(name, how string) protocol.Known {
		return protocol.Known{OwnerSeat: "p1", Zone: "hand", CardName: name, How: how}
	}
	withID := func(k protocol.Known, id string) protocol.Known { k.ObjectID = &id; return k }
	island := lib("p0", "Island", zero, nil, "looked_at")
	cases := []knownCase{
		{"a sorted mix", "", []protocol.Known{island, lib("p0", "Island", one, nil, "looked_at"),
			hand("Counterspell", "revealed"), lib("p1", "Forest", nil, zero, "own_placement")}},
		{"an entry outside hand and library", "V5", []protocol.Known{{OwnerSeat: "p1", Zone: "graveyard", CardName: "Island", How: "revealed"}}},
		{"an unknown how", "V5", []protocol.Known{lib("p0", "Island", zero, nil, "guessed")}},
		{"an owner that is not a seat", "V5", []protocol.Known{{OwnerSeat: "p2", Zone: "hand", CardName: "Island", How: "revealed"}}},
		{"an entry without a card name", "V5", []protocol.Known{hand("", "revealed")}},
		{"the viewer's own hand", "V5", []protocol.Known{{OwnerSeat: "p0", Zone: "hand", CardName: "Island", How: "revealed"}}},
		{"a hand entry with a position", "V5", []protocol.Known{{OwnerSeat: "p1", Zone: "hand", CardName: "Island", PositionFromTop: zero, How: "revealed"}}},
		{"a library entry without a position", "V5", []protocol.Known{lib("p0", "Island", nil, nil, "looked_at")}},
		{"a library entry with two positions", "V5", []protocol.Known{lib("p0", "Island", zero, zero, "looked_at")}},
		{"a searched entry with two positions", "V5", []protocol.Known{lib("p0", "Island", zero, zero, "searching")}},
		{"a searched entry without positions", "", []protocol.Known{lib("p0", "Island", nil, nil, "searching")}},
		{"a searched entry with one position", "", []protocol.Known{lib("p0", "Island", nil, zero, "searching")}},
		{"hand entries up to hand_count", "", []protocol.Known{hand("Counterspell", "revealed"), hand("Island", "revealed")}},
		{"hand entries beyond hand_count", "V5", []protocol.Known{hand("Counterspell", "revealed"),
			hand("Island", "revealed"), hand("Island", "revealed")}},
		{"equal entries", "", []protocol.Known{hand("Island", "revealed"), hand("Island", "revealed")}},
		// An id marks a card looked at, revealed or searched in this decision.
		{"an id on a tracked entry", "V5", []protocol.Known{withID(hand("Counterspell", "tracked"), "o-1")}},
		{"an id on an entry from a public zone", "V5", []protocol.Known{withID(hand("Counterspell", "from_public_zone"), "o-1")}},
		{"an id on an own placement", "V5", []protocol.Known{withID(lib("p0", "Island", zero, nil, "own_placement"), "o-1")}},
		{"an id on a searched entry", "", []protocol.Known{withID(lib("p0", "Island", nil, nil, "searching"), "o-1")}},
		{"an id on a revealed entry", "", []protocol.Known{withID(hand("Counterspell", "revealed"), "o-1")}},
	}
	// Each pair differs first in the named key, a before b, and a later key
	// would order it the other way or not at all.
	for _, pr := range []struct {
		key  string
		a, b protocol.Known
	}{
		{"owner_seat", island, lib("p1", "Island", zero, nil, "looked_at")},
		{"zone", hand("Swamp", "revealed"), lib("p1", "Island", zero, nil, "looked_at")},
		{"card_name", lib("p0", "Forest", one, nil, "looked_at"), island},
		{"position_from_top", island, lib("p0", "Island", one, nil, "looked_at")},
		{"a null position_from_top", lib("p0", "Island", nil, zero, "looked_at"), island},
		{"position_from_bottom", lib("p0", "Island", nil, zero, "looked_at"), lib("p0", "Island", nil, one, "looked_at")},
		{"how", island, lib("p0", "Island", zero, nil, "revealed")},
		{"object_id", withID(island, "o-1"), withID(island, "o-2")},
		{"a null object_id", island, withID(island, "o-1")},
	} {
		cases = append(cases, knownCase{pr.key + " in order", "", []protocol.Known{pr.a, pr.b}},
			knownCase{pr.key + " out of order", "V5", []protocol.Known{pr.b, pr.a}})
	}
	for _, c := range cases {
		sd := base(0, 0)
		// The viewer holds a card, so only the own-hand rule rejects its entry.
		sd.Observation.Players[0].Hand = []protocol.ObjectRecord{card(ref("o-mine", "Island", "p0", "hand"), "land")}
		sd.Observation.Players[0].HandCount = 1
		sd.Observation.Players[1].HandCount = 2
		sd.Observation.Known = c.known
		if got := check(p, sd); got != c.want {
			t.Errorf("known with %s reported %q, want %q", c.what, got, c.want)
		}
	}
}

// V5: candidates that reference cards in hidden zones (a library, or the other
// seat's hand) come, among themselves, in (card_name, object_id) order
// (Section 7.1).
func TestHiddenZoneCandidatesComeInNameOrder(t *testing.T) {
	p := every("pending_triggers", "keywords")
	lib := func(id, name string) protocol.ObjectRef { return ref(id, name, "p0", "library") }
	theirs := func(id, name string) protocol.ObjectRef { return ref(id, name, "p1", "hand") }
	mine := func(id, name string) protocol.ObjectRef { return ref(id, name, "p0", "hand") }
	misrecorded := lib("o-1", "Island")
	misrecorded.ControllerSeat = "p1"
	for _, c := range []struct {
		what, want string
		refs       []protocol.ObjectRef
	}{
		{"library cards by name", "", []protocol.ObjectRef{lib("o-2", "Forest"), lib("o-1", "Swamp")}},
		{"library cards against name order", "V5", []protocol.ObjectRef{lib("o-1", "Swamp"), lib("o-2", "Forest")}},
		{"one name by object_id", "", []protocol.ObjectRef{lib("o-1", "Island"), lib("o-2", "Island")}},
		{"one name against object_id order", "V5", []protocol.ObjectRef{lib("o-2", "Island"), lib("o-1", "Island")}},
		{"the other hand against name order", "V5", []protocol.ObjectRef{theirs("o-1", "Swamp"), theirs("o-2", "Forest")}},
		{"the viewer's hand in any order", "", []protocol.ObjectRef{mine("o-1", "Swamp"), mine("o-2", "Forest")}},
		{"a visible card between hidden ones", "", []protocol.ObjectRef{lib("o-1", "Forest"), mine("o-2", "Anger"), lib("o-3", "Swamp")}},
		{"hidden order across a visible card", "V5", []protocol.ObjectRef{lib("o-1", "Swamp"), mine("o-2", "Zombie"), lib("o-3", "Forest")}},
		{"a looked-at card under another controller", "V4", []protocol.ObjectRef{misrecorded}},
	} {
		sd := base(0, 0)
		o := &sd.Observation
		sd.Context = protocol.Context{Kind: "choice", Purpose: str("other")}
		sd.Candidates = nil
		for i, r := range c.refs {
			switch {
			case r.Zone == "hand" && r.OwnerSeat == "p0":
				o.Players[0].Hand = append(o.Players[0].Hand, card(r, "land"))
				o.Players[0].HandCount++
			case r.Zone == "hand":
				o.Known = append(o.Known, protocol.Known{OwnerSeat: "p1", Zone: "hand", CardName: *r.CardName, ObjectID: str(r.ObjectID), How: "revealed"})
				o.Players[1].HandCount++
			default:
				o.Known = append(o.Known, protocol.Known{OwnerSeat: "p0", Zone: "library", CardName: *r.CardName, ObjectID: str(r.ObjectID), How: "searching"})
			}
			sd.Candidates = append(sd.Candidates, protocol.Candidate{CandidateID: uint32(i),
				Semantic: protocol.SelectObject(nil, "other", protocol.ObjectTarget(r), 0, 0, 1)})
		}
		slices.SortFunc(o.Known, func(a, b protocol.Known) int {
			return cmp.Or(cmp.Compare(a.OwnerSeat, b.OwnerSeat), cmp.Compare(a.Zone, b.Zone),
				cmp.Compare(a.CardName, b.CardName), cmp.Compare(*a.ObjectID, *b.ObjectID))
		})
		if got := check(p, sd); got != c.want {
			t.Errorf("%s reported %q, want %q", c.what, got, c.want)
		}
	}

	// One looked-at card offered to several destinations keeps its place.
	sd := base(0, 0)
	top := lib("o-1", "Island")
	sd.Observation.Known = []protocol.Known{{OwnerSeat: "p0", Zone: "library", CardName: "Island",
		ObjectID: str("o-1"), PositionFromTop: u32(0), How: "looked_at"}}
	sd.Context = protocol.Context{Kind: "choice", Purpose: str("scry")}
	sd.Candidates = []protocol.Candidate{
		{CandidateID: 0, Semantic: protocol.ArrangeCard(nil, "scry", top, 0, 1, "top")},
		{CandidateID: 1, Semantic: protocol.ArrangeCard(nil, "scry", top, 0, 1, "bottom")},
	}
	if got := check(p, sd); got != "" {
		t.Errorf("one card offered twice reported %q", got)
	}
}

var flags = []string{"poison", "player_counters", "designations", "player_progress", "day_night", "passed_seats",
	"pending_triggers", "keywords", "full_name", "exiled_by", "stack_text", "permanent_details", "known_cards"}

// either is v when on, else T's zero value (a nil pointer, slice or map).
func either[T any](on bool, v T) T {
	if on {
		return v
	}
	var zero T
	return zero
}

func players(sd *protocol.SeatDecision, f func(*protocol.PlayerObs)) {
	for i := range sd.Observation.Players {
		f(&sd.Observation.Players[i])
	}
}

func eachRecord(sd *protocol.SeatDecision, f func(*protocol.ObjectRecord)) {
	players(sd, func(p *protocol.PlayerObs) {
		for _, zone := range [][]protocol.ObjectRecord{p.Hand, p.Battlefield, p.Graveyard, p.Exile, p.Command} {
			for i := range zone {
				f(&zone[i])
			}
		}
	})
}

// optionals are Section 6.9's optional fields, each with a setter that makes
// it non-null (on) or null.
var optionals = []struct {
	flag, field string
	nullable    bool // may be null with its flag true
	set         func(sd *protocol.SeatDecision, on bool)
}{
	{"poison", "poison", false, func(sd *protocol.SeatDecision, on bool) {
		players(sd, func(p *protocol.PlayerObs) { p.Poison = either(on, u32(0)) })
	}},
	{"player_counters", "player counters", false, func(sd *protocol.SeatDecision, on bool) {
		players(sd, func(p *protocol.PlayerObs) { p.Counters = either(on, map[string]uint32{}) })
	}},
	{"designations", "designations", false, func(sd *protocol.SeatDecision, on bool) {
		players(sd, func(p *protocol.PlayerObs) { p.Designations = either(on, []string{}) })
	}},
	{"player_progress", "progress", false, func(sd *protocol.SeatDecision, on bool) {
		players(sd, func(p *protocol.PlayerObs) { p.Progress = either(on, &protocol.Progress{}) })
	}},
	{"day_night", "day_night", false, func(sd *protocol.SeatDecision, on bool) {
		sd.Observation.DayNight = either(on, str("none"))
	}},
	{"passed_seats", "passed_seats", false, func(sd *protocol.SeatDecision, on bool) {
		sd.Observation.PassedSeats = either(on, []string{})
	}},
	{"pending_triggers", "pending_triggers", false, func(sd *protocol.SeatDecision, on bool) {
		sd.Observation.PendingTriggers = either(on, []protocol.PendingTrigger{})
	}},
	{"keywords", "keywords of records", false, func(sd *protocol.SeatDecision, on bool) {
		eachRecord(sd, func(r *protocol.ObjectRecord) { r.Characteristics.Keywords = either(on, []string{}) })
	}},
	{"keywords", "keywords of stack spells", false, func(sd *protocol.SeatDecision, on bool) {
		for _, st := range sd.Observation.Stack {
			st.Characteristics.Keywords = either(on, []string{})
		}
	}},
	{"full_name", "full_name", true, func(sd *protocol.SeatDecision, on bool) {
		sd.Observation.Players[0].Hand[0].FullName = either(on, str("Sagu Wildling // Roost Seek"))
	}},
	{"exiled_by", "exiled_by", true, func(sd *protocol.SeatDecision, on bool) {
		sd.Observation.Players[0].Exile[0].ExiledBy = either(on, &sd.Observation.Players[0].Battlefield[0].ObjectRef)
	}},
	{"stack_text", "stack text", true, func(sd *protocol.SeatDecision, on bool) {
		sd.Observation.Stack[0].Text = either(on, str("Lightning Bolt deals 3 damage to any target."))
	}},
	{"permanent_details", "statuses", false, func(sd *protocol.SeatDecision, on bool) {
		sd.Observation.Players[0].Battlefield[0].Permanent.Statuses = either(on, []string{})
	}},
	{"permanent_details", "class_level", true, func(sd *protocol.SeatDecision, on bool) {
		sd.Observation.Players[0].Battlefield[0].Permanent.ClassLevel = either(on, u32(1))
	}},
	{"permanent_details", "chosen", false, func(sd *protocol.SeatDecision, on bool) {
		sd.Observation.Players[0].Battlefield[0].Permanent.Chosen = either(on, []map[string]string{})
	}},
}

// flagged is a decision holding every optional field, non-null exactly when
// its flag is on.
func flagged(on map[string]bool) protocol.SeatDecision {
	sd := base(0, 0)
	o := &sd.Observation
	o.Players[0].Hand = []protocol.ObjectRecord{card(ref("o-sagu", "Sagu Wildling", "p0", "hand"), "creature")}
	o.Players[0].HandCount = 1
	o.Players[0].Battlefield = []protocol.ObjectRecord{permanent(ref("o-mtn", "Mountain", "p0", "battlefield"), "land")}
	o.Players[0].Exile = []protocol.ObjectRecord{card(ref("o-gone", "Pestermite", "p0", "exile"), "creature")}
	o.Stack = []protocol.StackEntry{{ObjectRef: ref("o-bolt", "Lightning Bolt", "p1", "stack"), StackKind: "spell",
		Characteristics: chars("instant"), Targets: []*protocol.TargetRef{}}}
	o.Known = []protocol.Known{{OwnerSeat: "p0", Zone: "library", CardName: "Island", ObjectID: str("o-look"),
		PositionFromTop: u32(0), How: "looked_at"}}
	for _, f := range optionals {
		f.set(&sd, on[f.flag])
	}
	return sd
}

// allBut is every flag set to v except flag, set to !v.
func allBut(flag string, v bool) map[string]bool {
	m := map[string]bool{}
	for _, f := range flags {
		m[f] = (f == flag) != v
	}
	return m
}

func withFlags(on map[string]bool) validate.Profile {
	p := every()
	p.Flags = on
	return p
}

// V8 per flag (Section 6.9): a field is null with its flag false, and non-null
// with its flag true except where Section 6.9 allows null. Each field is tested
// with its flag opposite every other flag, so no check reads another's flag.
func TestOptionalFieldsFollowTheirFlags(t *testing.T) {
	for _, f := range optionals {
		for _, on := range []bool{false, true} {
			p := withFlags(allBut(f.flag, !on))
			sd := flagged(p.Flags)
			if got := check(p, sd); got != "" {
				t.Errorf("%s: a decision following the flags reported %q with %s %v", f.field, got, f.flag, on)
				continue
			}
			f.set(&sd, !on) // the field against its flag
			want, what := "V8", "set"
			if on {
				what = "null"
				if f.nullable {
					want = ""
				}
			}
			if got := check(p, sd); got != want {
				t.Errorf("%s %s with %s %v reported %q, want %q", f.field, what, f.flag, on, got, want)
			}
		}
	}
}

// V8 for known_cards (Sections 6.7 and 6.9): known is always an array, and
// with known_cards false it lists only cards looked at, revealed or searched
// in this decision, which carry fresh ids.
func TestKnownStaysAnArrayOfCurrentLooks(t *testing.T) {
	lib := func(how string, id *string) protocol.Known {
		return protocol.Known{OwnerSeat: "p0", Zone: "library", CardName: "Island", ObjectID: id, PositionFromTop: u32(0), How: how}
	}
	hand := func(how string, id *string) protocol.Known {
		return protocol.Known{OwnerSeat: "p1", Zone: "hand", CardName: "Counterspell", ObjectID: id, How: how}
	}
	for _, c := range []struct {
		what       string
		knownCards bool
		known      []protocol.Known
		want       string
	}{
		{"null", false, nil, "V8"},
		{"null", true, nil, "V8"},
		{"a card looked at", false, []protocol.Known{lib("looked_at", str("o-1"))}, ""},
		{"a card revealed", false, []protocol.Known{hand("revealed", str("o-1"))}, ""},
		{"a card searched", false, []protocol.Known{lib("searching", str("o-1"))}, ""},
		{"a card looked at without an id", false, []protocol.Known{lib("looked_at", nil)}, "V8"},
		{"a tracked card", false, []protocol.Known{hand("tracked", nil)}, "V8"},
		{"a card from a public zone", false, []protocol.Known{hand("from_public_zone", nil)}, "V8"},
		{"an own placement", false, []protocol.Known{lib("own_placement", nil)}, "V8"},
		{"a tracked card without an id", true, []protocol.Known{hand("tracked", nil)}, ""},
		{"an own placement without an id", true, []protocol.Known{lib("own_placement", nil)}, ""},
	} {
		p := every("pending_triggers", "keywords")
		p.Flags["known_cards"] = c.knownCards
		sd := base(0, 0)
		sd.Observation.Players[1].HandCount = 1
		sd.Observation.Known = c.known
		if got := check(p, sd); got != c.want {
			t.Errorf("known %s with known_cards %v reported %q, want %q", c.what, c.knownCards, got, c.want)
		}
	}
}

// V9: activate_mana_ability joins a choice decision only beside optional_cost
// candidates, under purpose mana_payment (Section 7.1).
func TestManaAbilitiesJoinOnlyOptionalCosts(t *testing.T) {
	p := every("pending_triggers", "keywords")
	land := ref("o-land", "Mountain", "p0", "battlefield")
	leak := ref("o-leak", "Mana Leak", "p1", "stack")
	mana := protocol.ActivateManaAbility(land, 0, nil, nil)
	decline, pay := protocol.OptionalCost(leak, "unless_payment", false), protocol.OptionalCost(leak, "unless_payment", true)
	for _, c := range []struct {
		what, want, kind string
		purpose          *string
		cands            []protocol.Semantic
	}{
		{"an unless payment with a mana ability", "", "choice", str("mana_payment"), []protocol.Semantic{decline, pay, mana}},
		{"an unless payment alone", "", "choice", str("mana_payment"), []protocol.Semantic{decline, pay}},
		{"a mana ability in a priority decision", "", "priority", nil, []protocol.Semantic{protocol.Pass(), mana}},
		{"a mana ability without optional_cost", "V9", "choice", str("mana_payment"), []protocol.Semantic{mana}},
		{"a mana ability beside pay:true alone", "V9", "choice", str("mana_payment"), []protocol.Semantic{pay, mana}},
		{"a mana payment re-posed without pay:false", "V9", "choice", str("mana_payment"), []protocol.Semantic{pay}},
		{"a mana payment re-posed with pay:false alone", "", "choice", str("mana_payment"), []protocol.Semantic{decline}},
		{"a mana ability without a purpose", "V9", "choice", nil, []protocol.Semantic{decline, mana}},
		{"a mana ability under another purpose", "V9", "choice", str("other"), []protocol.Semantic{decline, mana}},
		{"a mana ability beside another choice kind", "V9", "choice", str("mana_payment"),
			[]protocol.Semantic{decline, mana, protocol.ChooseBoolean(nil, "may_ability", true)}},
		{"pass in a choice decision", "V9", "choice", str("mana_payment"), []protocol.Semantic{protocol.Pass(), decline, mana}},
		{"another priority kind in a choice decision", "V9", "choice", str("mana_payment"),
			[]protocol.Semantic{decline, mana, protocol.ActivateAbility(land, 0)}},
		{"a choice kind in a priority decision", "V9", "priority", nil, []protocol.Semantic{protocol.Pass(), decline}},
		{"an unknown context kind", "V9", "turn", nil, []protocol.Semantic{protocol.Pass()}},
	} {
		sd := base(0, 0)
		sd.Observation.Players[0].Battlefield = []protocol.ObjectRecord{permanent(land, "land")}
		sd.Observation.Stack = []protocol.StackEntry{{ObjectRef: leak, StackKind: "spell", Characteristics: chars("instant"),
			Targets: []*protocol.TargetRef{}}}
		sd.Context = protocol.Context{Kind: c.kind, Purpose: c.purpose}
		sd.Candidates = nil
		for i, s := range c.cands {
			sd.Candidates = append(sd.Candidates, protocol.Candidate{CandidateID: uint32(i), Semantic: s})
		}
		if got := check(p, sd); got != c.want {
			t.Errorf("%s reported %q, want %q", c.what, got, c.want)
		}
	}
}

// InGroup is the hook for Section 8's exclusivity across seats, which a host
// checks on its two streams.
func TestInGroupMarksAPartialGroup(t *testing.T) {
	s := validate.NewStream(profile())
	if s.InGroup() {
		t.Fatal("a new stream is in a group")
	}
	for i, partial := range []bool{true, true, false} {
		sd := base(uint64(i), 0)
		sd.Group.SubstepIndex, sd.Group.SubstepCount = uint32(i), 3
		if err := s.Check(sd); err != nil {
			t.Fatalf("substep %d: %v", i, err)
		}
		if s.InGroup() != partial {
			t.Fatalf("after substep %d of 3, InGroup is %v", i, s.InGroup())
		}
	}
}

// decode is the host's view of a decision: the engine's JSON decoded into
// protocol types, where Semantic.UnmarshalJSON keeps numbers as json.Number
// and nested objects as raw JSON (Task 5).
func decode(t *testing.T, sd protocol.SeatDecision) protocol.SeatDecision {
	t.Helper()
	b, err := json.Marshal(sd)
	if err != nil {
		t.Fatal(err)
	}
	var back protocol.SeatDecision
	if err := json.Unmarshal(b, &back); err != nil {
		t.Fatal(err)
	}
	return back
}

// game is one seat's stream: a priority decision with non-pass candidates, X
// for the spell it cast, a library search, and an order of two triggers.
func game() []protocol.SeatDecision {
	mountain, fireball := ref("o-mtn", "Mountain", "p0", "hand"), ref("o-fire", "Fireball", "p0", "hand")
	onStack := ref("o-stk", "Fireball", "p0", "stack")
	forest, swamp := ref("o-for", "Forest", "p0", "library"), ref("o-swa", "Swamp", "p0", "library")
	bear, elves := ref("o-bear", "Grizzly Bears", "p0", "battlefield"), ref("o-elf", "Llanowar Elves", "p0", "graveyard")
	step := func(i uint64) protocol.SeatDecision {
		sd := base(i, i)
		sd.Observation.Players[0].Hand = []protocol.ObjectRecord{card(mountain, "land")}
		sd.Observation.Players[0].HandCount = 1
		return sd
	}

	cast := step(0)
	cast.Observation.Players[0].Hand = append(cast.Observation.Players[0].Hand, card(fireball, "sorcery"))
	cast.Observation.Players[0].HandCount = 2
	cast.Candidates = []protocol.Candidate{{CandidateID: 0, Semantic: protocol.Pass()},
		{CandidateID: 1, Semantic: protocol.PlayLand(mountain, 0)},
		{CandidateID: 2, Semantic: protocol.CastSpell(fireball, "normal")}}

	x := step(1)
	x.Observation.Stack = []protocol.StackEntry{{ObjectRef: onStack, StackKind: "spell", Characteristics: chars("sorcery"),
		Targets: []*protocol.TargetRef{}}}
	x.Context = protocol.Context{Kind: "choice", Source: &onStack, Purpose: str("x_value")}
	x.Candidates = nil
	for v := int32(0); v <= 2; v++ {
		x.Candidates = append(x.Candidates, protocol.Candidate{CandidateID: uint32(v),
			Semantic: protocol.ChooseNumber(&onStack, "x_value", v, 0, 2)})
	}

	search := step(2)
	search.Observation.Known = []protocol.Known{
		{OwnerSeat: "p0", Zone: "library", CardName: "Forest", ObjectID: str("o-for"), How: "searching"},
		{OwnerSeat: "p0", Zone: "library", CardName: "Swamp", ObjectID: str("o-swa"), How: "searching"}}
	search.Context = protocol.Context{Kind: "choice", Purpose: str("search")}
	search.Candidates = []protocol.Candidate{
		{CandidateID: 0, Semantic: protocol.SelectObject(nil, "search", protocol.ObjectTarget(forest), 0, 0, 1)},
		{CandidateID: 1, Semantic: protocol.SelectObject(nil, "search", protocol.ObjectTarget(swamp), 0, 0, 1)},
		{CandidateID: 2, Semantic: protocol.FinishSelection(nil, "search", 0)}}

	order := step(3)
	order.Observation.Players[0].Battlefield = []protocol.ObjectRecord{permanent(bear, "creature")}
	order.Observation.Players[0].Graveyard = []protocol.ObjectRecord{card(elves, "creature")}
	order.Context = protocol.Context{Kind: "choice", Purpose: str("triggers")}
	order.Candidates = nil
	for i := uint32(0); i < 2; i++ {
		item := protocol.OrderItem{Trigger: &protocol.TriggerItem{Source: &bear, SourceName: str("Grizzly Bears"),
			AbilityIndex: u32(0), EventObjects: []protocol.ObjectRef{elves}, Instance: i}}
		order.Candidates = append(order.Candidates, protocol.Candidate{CandidateID: i,
			Semantic: protocol.OrderPick(nil, "triggers", item, 0, 2)})
	}
	return []protocol.SeatDecision{cast, x, search, order}
}

// G1-2: a host validates decisions it decoded from the engine's JSON (Task
// 25). Decoded decisions, with non-pass and choose_number candidates, get
// exactly the verdicts of the Go-built values, passing and failing alike.
func TestDecodedDecisionsGetTheGoBuiltVerdicts(t *testing.T) {
	p := every("pending_triggers", "keywords")
	built, wire := validate.NewStream(p), validate.NewStream(p)
	for i, sd := range game() {
		if err := built.Check(sd); err != nil {
			t.Fatalf("Go-built decision %d: %v", i, err)
		}
		if err := wire.Check(decode(t, sd)); err != nil {
			t.Fatalf("decoded decision %d: %v", i, err)
		}
	}
	x := decode(t, game()[1]).Candidates[2].Semantic.Fields
	if _, ok := x["value"].(json.Number); !ok {
		t.Fatalf("decoded choose_number value is %T, want json.Number", x["value"])
	}
	if _, ok := x["source"].(json.RawMessage); !ok {
		t.Fatalf("decoded choose_number source is %T, want json.RawMessage", x["source"])
	}

	for _, m := range []struct {
		what, want string
		at         int
		mutate     func(*protocol.SeatDecision)
	}{
		{"a repeated cast_spell", "V1", 0, func(sd *protocol.SeatDecision) {
			sd.Candidates = append(sd.Candidates, protocol.Candidate{CandidateID: 3, Semantic: sd.Candidates[2].Semantic})
		}},
		{"an X above its maximum", "V1", 1, func(sd *protocol.SeatDecision) {
			sd.Candidates[2].Semantic = protocol.ChooseNumber(sd.Context.Source, "x_value", 3, 0, 2)
		}},
		{"an X source unlike its stack entry", "V4", 1, func(sd *protocol.SeatDecision) {
			src := *sd.Context.Source
			src.CardName = str("Blaze")
			sd.Candidates[0].Semantic = protocol.ChooseNumber(&src, "x_value", 0, 0, 2)
		}},
		{"a search out of name order", "V5", 2, func(sd *protocol.SeatDecision) {
			sd.Candidates[0].Semantic, sd.Candidates[1].Semantic = sd.Candidates[1].Semantic, sd.Candidates[0].Semantic
		}},
		{"a trigger naming a card that is gone", "V4", 3, func(sd *protocol.SeatDecision) {
			sd.Observation.Players[0].Graveyard = []protocol.ObjectRecord{}
		}},
	} {
		steps := game()
		m.mutate(&steps[m.at])
		built, wire := validate.NewStream(p), validate.NewStream(p)
		for i, sd := range steps[:m.at+1] {
			want := ""
			if i == m.at {
				want = m.want
			}
			if b, w := verdict(built.Check(sd)), verdict(wire.Check(decode(t, sd))); b != want || w != want {
				t.Errorf("%s: decision %d reported %q built and %q decoded, want %q", m.what, i, b, w, want)
			}
		}
	}
}
