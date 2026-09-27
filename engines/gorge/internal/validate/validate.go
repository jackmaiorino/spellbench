// Package validate is a Go subset of the Section 11.3 live validator, used by
// this adapter's tests and qualification until sub-project P's validator runs.
//
// Not covered: V1 for the observation (field types, vocabularies, NFC names)
// and for the decision's own fields (acting_seat as a seat, context purpose
// and text), the card_name domain of choose_name, and V10 provenance. Rewinds
// are not supported: this engine declares rewind false, so a decision with
// context.rewind true, or any early end of a group, fails V3. Group
// exclusivity spans both seats, so a host checks it with InGroup.
package validate

import (
	"cmp"
	"encoding/json"
	"fmt"
	"maps"
	"regexp"
	"slices"

	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/wire"
)

type Violation struct{ Rule, Msg string }

func (v *Violation) Error() string { return v.Rule + ": " + v.Msg }

func vio(rule, format string, a ...any) error {
	return &Violation{Rule: rule, Msg: fmt.Sprintf(format, a...)}
}

// Profile is what the engine declared and the game enabled: Kinds from
// hello_ok.decision_kinds, Flags from hello_ok.observation (Section 6.9), and
// Extensions from rules.extensions.
type Profile struct {
	Kinds      map[string]bool
	Flags      map[string]bool
	Extensions map[string]bool
}

type Stream struct {
	p            Profile
	nextSeatStep uint64
	group        *protocol.Group // open group, nil when none
	nextGroup    uint64
	zoneOf       map[string]string // object id -> the one zone it appeared in
	live         map[string]bool   // ids in the previous decision
	departed     map[string]bool   // ids that left the stream
}

func NewStream(p Profile) *Stream {
	return &Stream{p: p, zoneOf: map[string]string{}, live: map[string]bool{}, departed: map[string]bool{}}
}

// InGroup reports whether this seat's last decision left a group partial.
// Exclusivity (Section 8) spans both seats, which one stream cannot see: a
// host holding both seats' streams treats a decision for the other seat while
// this one is InGroup as a V3 violation, and a terminal other than halted too.
func (s *Stream) InGroup() bool { return s.group != nil }

var extKey = regexp.MustCompile(`^x_[a-z0-9_]+$`)

// EqualRef compares references by value (CardName is a pointer).
func EqualRef(a, b protocol.ObjectRef) bool {
	return a.ObjectID == b.ObjectID && a.OwnerSeat == b.OwnerSeat && a.ControllerSeat == b.ControllerSeat &&
		a.Zone == b.Zone && (a.CardName == nil) == (b.CardName == nil) && (a.CardName == nil || *a.CardName == *b.CardName)
}

func zones(p protocol.PlayerObs) [][]protocol.ObjectRecord {
	return [][]protocol.ObjectRecord{p.Hand, p.Battlefield, p.Graveyard, p.Exile, p.Command}
}

// records collects every object record of the observation by id: zone
// arrays, stack entries, and known entries that carry an id. Ids are unique
// within the observation (V4).
func records(o protocol.Observation) (map[string]protocol.ObjectRef, error) {
	out := map[string]protocol.ObjectRef{}
	add := func(r protocol.ObjectRef) error {
		if _, ok := out[r.ObjectID]; ok {
			return vio("V4", "id %s appears twice in the observation", r.ObjectID)
		}
		out[r.ObjectID] = r
		return nil
	}
	for _, p := range o.Players {
		for _, zone := range zones(p) {
			for _, rec := range zone {
				if rec.Zone == "library" {
					return nil, vio("V5", "zone array holds library object %s", rec.ObjectID)
				}
				if err := add(rec.ObjectRef); err != nil {
					return nil, err
				}
			}
		}
	}
	for _, s := range o.Stack {
		if err := add(s.ObjectRef); err != nil {
			return nil, err
		}
	}
	for _, k := range o.Known {
		if k.ObjectID != nil {
			name := k.CardName
			if err := add(protocol.ObjectRef{ObjectID: *k.ObjectID, CardName: &name, OwnerSeat: k.OwnerSeat, ControllerSeat: k.OwnerSeat, Zone: k.Zone}); err != nil {
				return nil, err
			}
		}
	}
	return out, nil
}

// walkRefs visits every object reference in a JSON value decoded into any,
// map keys in sorted order. Semantic.Check has already typed each reference's
// five fields; one missing or mistyped would read as "" and fail V4.
func walkRefs(x any, visit func(protocol.ObjectRef) error) error {
	switch t := x.(type) {
	case map[string]any:
		if id, ok := t["object_id"].(string); ok {
			r := protocol.ObjectRef{ObjectID: id}
			r.OwnerSeat, _ = t["owner_seat"].(string)
			r.ControllerSeat, _ = t["controller_seat"].(string)
			r.Zone, _ = t["zone"].(string)
			if name, ok := t["card_name"].(string); ok {
				r.CardName = &name
			}
			return visit(r)
		}
		for _, k := range slices.Sorted(maps.Keys(t)) {
			if err := walkRefs(t[k], visit); err != nil {
				return err
			}
		}
	case []any:
		for _, e := range t {
			if err := walkRefs(e, visit); err != nil {
				return err
			}
		}
	}
	return nil
}

// candidateRefs lists the object references in a candidate's JSON.
func candidateRefs(b []byte) ([]protocol.ObjectRef, error) {
	var generic any
	if err := json.Unmarshal(b, &generic); err != nil {
		return nil, err
	}
	var out []protocol.ObjectRef
	err := walkRefs(generic, func(r protocol.ObjectRef) error {
		out = append(out, r)
		return nil
	})
	return out, err
}

// observationRefs visits the object references the observation holds besides
// its records (V4): exiled_by, attachments, attack targets, blocked attackers,
// stack sources and targets, and pending-trigger sources. visit gets each one's
// place as a format and arguments, formatted only for a message. A target
// reference is exactly one of a seat and an object (Section 5.2), else V1.
func observationRefs(o protocol.Observation, visit func(r protocol.ObjectRef, where string, a ...any) error) error {
	ref := func(r *protocol.ObjectRef, where string, a ...any) error {
		if r == nil {
			return nil
		}
		return visit(*r, where, a...)
	}
	target := func(t *protocol.TargetRef, where string, a ...any) error {
		switch {
		case t == nil:
			return nil
		case (t.Player == nil) == (t.Object == nil):
			return vio("V1", "%s is not exactly one of a player and an object", fmt.Sprintf(where, a...))
		case t.Player != nil && *t.Player != "p0" && *t.Player != "p1":
			return vio("V1", "%s names player %q, not a seat", fmt.Sprintf(where, a...), *t.Player)
		}
		return ref(t.Object, where, a...)
	}
	for _, p := range o.Players {
		for _, zone := range zones(p) {
			for _, rec := range zone {
				if err := ref(rec.ExiledBy, "exiled_by of %s", rec.ObjectID); err != nil {
					return err
				}
				pm := rec.Permanent
				if pm == nil {
					continue
				}
				if err := target(pm.AttachedTo, "attached_to of %s", rec.ObjectID); err != nil {
					return err
				}
				if err := target(pm.AttackTarget, "attack_target of %s", rec.ObjectID); err != nil {
					return err
				}
				for i := range pm.BlockedAttackers {
					if err := ref(&pm.BlockedAttackers[i], "blocked_attackers[%d] of %s", i, rec.ObjectID); err != nil {
						return err
					}
				}
			}
		}
	}
	for _, st := range o.Stack {
		if err := ref(st.Source, "source of %s", st.ObjectID); err != nil {
			return err
		}
		for i, t := range st.Targets {
			if err := target(t, "target %d of %s", i, st.ObjectID); err != nil {
				return err
			}
		}
	}
	for i, pt := range o.PendingTriggers {
		if err := ref(pt.Source, "source of pending trigger %d", i); err != nil {
			return err
		}
	}
	return nil
}

// nameKey is Section 7.1's (card_name, object_id) order; a null name sorts first.
type nameKey struct{ name, id string }

func (k nameKey) less(o nameKey) bool { return k.name < o.name || (k.name == o.name && k.id < o.id) }

// hiddenOrder is V5's rule that candidates referencing cards in hidden zones
// (a library, or the other seat's hand) come, among themselves, in
// (card_name, object_id) order (Section 7.1). A candidate referencing several
// such cards is placed by the least of them.
func hiddenOrder(viewer string, refs [][]protocol.ObjectRef) error {
	var prev *nameKey
	for i, rs := range refs {
		var least *nameKey
		for _, r := range rs {
			if r.Zone != "library" && (r.Zone != "hand" || r.OwnerSeat == viewer) {
				continue
			}
			k := nameKey{id: r.ObjectID}
			if r.CardName != nil {
				k.name = *r.CardName
			}
			if least == nil || k.less(*least) {
				least = &k
			}
		}
		if least == nil {
			continue
		}
		if prev != nil && least.less(*prev) {
			return vio("V5", "candidate %d names hidden-zone card %s out of (card_name, object_id) order", i, least.id)
		}
		prev = least
	}
	return nil
}

var knownHow = []string{"revealed", "looked_at", "from_public_zone", "own_placement", "searching", "tracked"}

// nullsFirst compares optional values, null before any value.
func nullsFirst[T cmp.Ordered](a, b *T) int {
	switch {
	case a == nil && b == nil:
		return 0
	case a == nil:
		return -1
	case b == nil:
		return 1
	}
	return cmp.Compare(*a, *b)
}

// knownOrder is Section 6.7's order: owner_seat, zone, card_name,
// position_from_top, position_from_bottom, how, object_id, nulls first.
func knownOrder(a, b protocol.Known) int {
	return cmp.Or(cmp.Compare(a.OwnerSeat, b.OwnerSeat), cmp.Compare(a.Zone, b.Zone), cmp.Compare(a.CardName, b.CardName),
		nullsFirst(a.PositionFromTop, b.PositionFromTop), nullsFirst(a.PositionFromBottom, b.PositionFromBottom),
		cmp.Compare(a.How, b.How), nullsFirst(a.ObjectID, b.ObjectID))
}

// checkKnown is V5's rules for known (Section 6.7): each entry's shape, the
// number of hand entries per seat, and the order.
func checkKnown(o protocol.Observation) error {
	hand := map[string]uint32{}
	for i, k := range o.Known {
		top, bottom := k.PositionFromTop != nil, k.PositionFromBottom != nil
		switch {
		case k.OwnerSeat != "p0" && k.OwnerSeat != "p1":
			return vio("V5", "known %d has owner %q", i, k.OwnerSeat)
		case k.Zone != "hand" && k.Zone != "library":
			return vio("V5", "known %d is in zone %q, not hand or library", i, k.Zone)
		case !slices.Contains(knownHow, k.How):
			return vio("V5", "known %d has how %q", i, k.How)
		case k.CardName == "":
			return vio("V5", "known %d has no card name", i)
		case k.ObjectID != nil && !currentLook[k.How]:
			return vio("V5", "known %d has an id, but only cards looked at, revealed or searched in this decision have one", i)
		case k.Zone == "hand" && k.OwnerSeat == o.Viewer:
			return vio("V5", "known %d lists the viewer's own hand", i)
		case k.Zone == "hand" && (top || bottom):
			return vio("V5", "known hand entry %d has a position", i)
		case k.Zone == "library" && top && bottom:
			return vio("V5", "known library entry %d has two positions", i)
		case k.Zone == "library" && !top && !bottom && k.How != "searching":
			return vio("V5", "known library entry %d has no position", i)
		}
		if k.Zone == "hand" {
			hand[k.OwnerSeat]++
		}
		if i > 0 && knownOrder(o.Known[i-1], k) > 0 {
			return vio("V5", "known entries %d and %d are out of order", i-1, i)
		}
	}
	for i, seat := range []string{"p0", "p1"} {
		if hand[seat] > o.Players[i].HandCount {
			return vio("V5", "%d known hand entries for %s, hand_count %d", hand[seat], seat, o.Players[i].HandCount)
		}
	}
	return nil
}

// currentLook is how a card looked at, revealed or searched in this decision
// is known. Only such an entry carries an object id (Section 6.7, V5).
var currentLook = map[string]bool{"looked_at": true, "revealed": true, "searching": true}

// checkFlags is V8's rule for the optional fields of Section 6.9. With its flag
// false a field is null; with the flag true it is non-null, except that
// full_name, exiled_by, stack text and class_level may still be null. known is
// always an array, and with known_cards false it lists only cards looked at,
// revealed or searched in this decision (Section 6.7): every entry carries an
// id, and V5 has already held entries with ids to those three hows.
func (s *Stream) checkFlags(o protocol.Observation) error {
	var err error
	field := func(flag string, null, nullable bool, what string) {
		switch on := s.p.Flags[flag]; {
		case err != nil:
		case !on && !null:
			err = vio("V8", "%s is set with %s false", what, flag)
		case on && null && !nullable:
			err = vio("V8", "%s is null with %s true", what, flag)
		}
	}
	field("day_night", o.DayNight == nil, false, "day_night")
	field("passed_seats", o.PassedSeats == nil, false, "passed_seats")
	field("pending_triggers", o.PendingTriggers == nil, false, "pending_triggers")
	for _, p := range o.Players {
		field("poison", p.Poison == nil, false, "poison of "+p.Seat)
		field("player_counters", p.Counters == nil, false, "counters of "+p.Seat)
		field("designations", p.Designations == nil, false, "designations of "+p.Seat)
		field("player_progress", p.Progress == nil, false, "progress of "+p.Seat)
		for _, zone := range zones(p) {
			for _, rec := range zone {
				if c := rec.Characteristics; c != nil {
					field("keywords", c.Keywords == nil, false, "keywords of "+rec.ObjectID)
				}
				field("full_name", rec.FullName == nil, true, "full_name of "+rec.ObjectID)
				field("exiled_by", rec.ExiledBy == nil, true, "exiled_by of "+rec.ObjectID)
				if pm := rec.Permanent; pm != nil {
					field("permanent_details", pm.Statuses == nil, false, "statuses of "+rec.ObjectID)
					field("permanent_details", pm.ClassLevel == nil, true, "class_level of "+rec.ObjectID)
					field("permanent_details", pm.Chosen == nil, false, "chosen of "+rec.ObjectID)
				}
			}
		}
	}
	for _, st := range o.Stack {
		if c := st.Characteristics; c != nil {
			field("keywords", c.Keywords == nil, false, "keywords of "+st.ObjectID)
		}
		field("stack_text", st.Text == nil, true, "text of "+st.ObjectID)
	}
	if err != nil {
		return err
	}
	if o.Known == nil {
		return vio("V8", "known is null, not an array")
	}
	if !s.p.Flags["known_cards"] {
		for i, k := range o.Known {
			if k.ObjectID == nil {
				return vio("V8", "known %d (%s) has no id, so it is not a card looked at, revealed or searched in this decision, with known_cards false", i, k.How)
			}
		}
	}
	return nil
}

// Check validates this seat's next decision and advances the stream when it
// passes.
func (s *Stream) Check(sd protocol.SeatDecision) error {
	o := sd.Observation
	// V2
	if o.Viewer != sd.ActingSeat {
		return vio("V2", "viewer %s, acting seat %s", o.Viewer, sd.ActingSeat)
	}
	// V3
	if sd.Context.Rewind {
		return vio("V3", "context.rewind is true, but rewinds are not supported (this engine declares rewind false)")
	}
	if sd.SeatStep != s.nextSeatStep {
		return vio("V3", "seat_step %d, want %d", sd.SeatStep, s.nextSeatStep)
	}
	g := sd.Group
	if s.group != nil {
		if g.GroupID != s.group.GroupID || g.SubstepIndex != s.group.SubstepIndex+1 || g.SubstepCount != s.group.SubstepCount {
			return vio("V3", "partial group %d not continued", s.group.GroupID)
		}
	} else if g.GroupID != s.nextGroup || g.SubstepIndex != 0 || g.SubstepCount == 0 {
		return vio("V3", "group %d/%d, want new group %d", g.GroupID, g.SubstepIndex, s.nextGroup)
	}
	// V1: extensions is an object. A nil map is how a JSON null or a missing
	// key decodes, so it fails although ExtensionMap marshals nil as {}.
	if sd.Extensions == nil {
		return vio("V1", "extensions is null, not an object")
	}
	// V1 candidates
	if len(sd.Candidates) == 0 || len(sd.Candidates) > 4096 {
		return vio("V1", "%d candidates", len(sd.Candidates))
	}
	seen := map[string]bool{}
	priority, declines := 0, 0
	refs := make([][]protocol.ObjectRef, len(sd.Candidates))
	for i, c := range sd.Candidates {
		if c.CandidateID != uint32(i) {
			return vio("V1", "candidate %d has id %d", i, c.CandidateID)
		}
		if err := c.Semantic.Check(); err != nil {
			return vio("V1", "candidate %d: %v", i, err)
		}
		// The host's canonical JSON (Section 4.3) is the candidate as values:
		// equal semantics match however they were built or decoded, and one
		// that does not encode fails here instead of skipping V4 and V5.
		b, err := wire.Canonical(c.Semantic)
		if err != nil {
			return vio("V1", "candidate %d does not encode as JSON: %v", i, err)
		}
		if seen[string(b)] {
			return vio("V1", "candidate %d repeats a semantic", i)
		}
		seen[string(b)] = true
		if refs[i], err = candidateRefs(b); err != nil {
			return vio("V1", "candidate %d: %v", i, err)
		}
		if c.Semantic.Kind == "pass" && i != 0 {
			return vio("V1", "pass at %d", i)
		}
		if !s.p.Kinds[c.Semantic.Kind] {
			return vio("V8", "kind %s not declared", c.Semantic.Kind)
		}
		if protocol.PriorityKinds[c.Semantic.Kind] {
			priority++
		}
		if pay, ok := c.Semantic.Fields["pay"].(bool); c.Semantic.Kind == "optional_cost" && ok && !pay {
			declines++
		}
	}
	// V9: the families do not mix, except activate_mana_ability beside
	// optional_cost candidates under purpose mana_payment, and such a decision
	// always offers pay:false (Section 7.1), so it holds an optional_cost.
	manaPayment := sd.Context.Purpose != nil && *sd.Context.Purpose == "mana_payment"
	switch {
	case sd.Context.Kind == "priority" && priority != len(sd.Candidates):
		return vio("V9", "priority context with choice candidates")
	case sd.Context.Kind == "choice" && priority > 0:
		for _, c := range sd.Candidates {
			switch k := c.Semantic.Kind; {
			case k == "activate_mana_ability" || k == "optional_cost":
			case protocol.PriorityKinds[k]:
				return vio("V9", "choice context with %s", k)
			default:
				return vio("V9", "activate_mana_ability beside %s, not only optional_cost", k)
			}
		}
		if !manaPayment {
			return vio("V9", "activate_mana_ability in a choice decision without purpose mana_payment")
		}
	case sd.Context.Kind != "priority" && sd.Context.Kind != "choice":
		return vio("V9", "context kind %q", sd.Context.Kind)
	}
	if sd.Context.Kind == "choice" && manaPayment && declines == 0 {
		return vio("V9", "a mana_payment decision without optional_cost pay:false, which is always offered")
	}
	// V5
	other := 1
	if sd.ActingSeat == "p1" {
		other = 0
	}
	if o.Players[other].Hand != nil {
		return vio("V5", "the other seat's hand is not null")
	}
	me := o.Players[1-other]
	if me.Hand == nil || uint32(len(me.Hand)) != me.HandCount {
		return vio("V5", "viewer hand has %d records, hand_count %d", len(me.Hand), me.HandCount)
	}
	if err := checkKnown(o); err != nil {
		return err
	}
	if err := hiddenOrder(sd.ActingSeat, refs); err != nil {
		return err
	}
	// V8 optional fields and extensions
	if err := s.checkFlags(o); err != nil {
		return err
	}
	for k := range sd.Extensions {
		if !extKey.MatchString(k) || !s.p.Extensions[k] {
			return vio("V8", "extension %s not enabled", k)
		}
	}
	// V6
	for _, st := range o.Stack {
		if st.FaceDown && st.ControllerSeat != sd.ActingSeat && st.CardName != nil {
			return vio("V6", "face-down stack object %s shows a name", st.ObjectID)
		}
	}
	for _, p := range o.Players {
		for _, rec := range p.Battlefield {
			if rec.FaceDown && rec.ControllerSeat != sd.ActingSeat && (rec.CardName != nil || rec.FullName != nil) {
				return vio("V6", "face-down permanent %s shows a name", rec.ObjectID)
			}
		}
	}
	// V4 and V7
	recs, err := records(o)
	if err != nil {
		return err
	}
	for id, r := range recs {
		if z, ok := s.zoneOf[id]; ok && z != r.Zone {
			return vio("V7", "id %s appears in %s and %s", id, z, r.Zone)
		}
		if s.departed[id] {
			return vio("V7", "id %s returned after leaving", id)
		}
	}
	match := func(r protocol.ObjectRef, where string, a ...any) error {
		rec, ok := recs[r.ObjectID]
		switch {
		case !ok:
			return vio("V4", "%s references %s, which is not in the observation", fmt.Sprintf(where, a...), r.ObjectID)
		case !EqualRef(rec, r):
			return vio("V4", "%s references %s unlike its observation record", fmt.Sprintf(where, a...), r.ObjectID)
		}
		return nil
	}
	if src := sd.Context.Source; src != nil {
		if err := match(*src, "context.source"); err != nil {
			return err
		}
	}
	if err := observationRefs(o, match); err != nil {
		return err
	}
	for i, rs := range refs {
		for _, r := range rs {
			if err := match(r, "candidate %d", i); err != nil {
				return err
			}
		}
	}
	for id := range s.live {
		if _, still := recs[id]; !still {
			s.departed[id] = true
		}
	}
	s.live = map[string]bool{}
	for id, r := range recs {
		s.live[id] = true
		s.zoneOf[id] = r.Zone
	}
	// advance counters
	s.nextSeatStep++
	if g.SubstepIndex+1 == g.SubstepCount {
		s.group, s.nextGroup = nil, g.GroupID+1
	} else {
		cp := g
		s.group = &cp
	}
	return nil
}
