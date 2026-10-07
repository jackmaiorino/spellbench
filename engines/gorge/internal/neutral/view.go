package neutral

import (
	"fmt"
	"slices"
	"sort"
	"strconv"
	"strings"

	"github.com/adams-shaun/gorge/cards"
	"github.com/adams-shaun/gorge/state"
	"github.com/adams-shaun/gorge/view"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/observe"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
)

// steps is Section 6.2's phase_step order, which is gorge's state.Step order.
var steps = []string{"untap", "upkeep", "draw", "precombat_main", "beginning_of_combat", "declare_attackers",
	"declare_blockers", "combat_damage", "end_of_combat", "postcombat_main", "end_step", "cleanup"}

// IDs numbers a seat's v2 object ids densely, in first-appearance order, for
// one game. v2 ids are fresh per incarnation (Section 5.3), so one gorge id
// is one object in one zone, which is all gorge's Board needs.
type IDs struct {
	m    map[string]state.ObjID
	back []string
}

func NewIDs() *IDs { return &IDs{m: map[string]state.ObjID{}, back: []string{""}} }

// Of returns id's gorge id, minting one for a new id. The empty id is 0.
func (t *IDs) Of(id string) state.ObjID {
	if id == "" {
		return 0
	}
	n, ok := t.m[id]
	if !ok {
		n = state.ObjID(len(t.back))
		t.m[id] = n
		t.back = append(t.back, id)
	}
	return n
}

// V2 returns the v2 id a gorge id stands for.
func (t *IDs) V2(n state.ObjID) string {
	if int(n) < len(t.back) {
		return t.back[n]
	}
	return ""
}

// Seat parses "p0" or "p1".
func Seat(s string) (state.PlayerID, error) {
	switch s {
	case "p0":
		return 0, nil
	case "p1":
		return 1, nil
	}
	return 0, fmt.Errorf("%q is not a seat", s)
}

// Builder turns observations into gorge views for one seat and game.
type Builder struct {
	Reg *cards.Registry
	IDs *IDs
	// refs caches Resolve by observed name; a miss (a token, a name the
	// registry lacks) caches the zero Ref.
	refs map[string]Ref
	// tokens lists the registry's token scripts by face name, stems sorted.
	tokens map[string][]string
}

func NewBuilder(reg *cards.Registry) *Builder {
	b := &Builder{Reg: reg, IDs: NewIDs(), refs: map[string]Ref{}, tokens: map[string][]string{}}
	for stem, c := range reg.Tokens {
		if len(c.Faces) > 0 {
			b.tokens[c.Faces[0].Name] = append(b.tokens[c.Faces[0].Name], stem)
		}
	}
	for _, stems := range b.tokens {
		sort.Strings(stems)
	}
	return b
}

func (b *Builder) ref(name *string) Ref {
	if name == nil {
		return Ref{}
	}
	r, ok := b.refs[*name]
	if !ok {
		r, _ = Resolve(b.Reg, *name)
		b.refs[*name] = r
	}
	return r
}

// face is the printed face an observed object shows: a card's face by name
// (a copy, token or not, shows the card it copies), or for any other token
// the token script of that name whose colors and printed keywords agree
// with what is observed. It is nil when neither is known.
func (b *Builder) face(name *string, token bool, c *protocol.Characteristics) *cards.Face {
	if name == nil {
		return nil
	}
	if !token {
		r := b.ref(name)
		if r.Card == nil {
			return nil
		}
		return r.Card.Faces[r.Face]
	}
	var best *cards.Face
	for _, stem := range b.tokens[*name] {
		f := b.Reg.Tokens[stem].Faces[0]
		if c != nil && f.Colors != strings.Join(c.Colors, ",") {
			continue
		}
		if c != nil && !slices.ContainsFunc(f.Keywords, func(l string) bool {
			k := observe.Keywords([]string{l})
			return len(k) == 1 && !slices.Contains(c.Keywords, k[0])
		}) {
			return f
		}
		if best == nil {
			best = f
		}
	}
	return best
}

// View builds the seat's gorge view from its observation. Every fact comes
// from the observation, except the printed facts gorge's Board reads off a
// card (mana cost, type line, spell API, mana production), which come from
// the registry by the card's name.
func (b *Builder) View(o *protocol.Observation) (view.View, error) {
	viewer, err := Seat(o.Viewer)
	if err != nil {
		return view.View{}, err
	}
	v := view.View{Viewer: viewer, Visibility: "seat", Turn: int32(o.Turn), Players: []view.PlayerView{},
		Stack: []view.StackView{}, Pending: []view.PendingView{}}
	// pregame is gorge's untap step of turn 0.
	i := 0
	if o.PhaseStep != "pregame" {
		if i = slices.Index(steps, o.PhaseStep); i < 0 {
			return view.View{}, fmt.Errorf("phase_step %q", o.PhaseStep)
		}
	}
	v.Step, v.Phase = state.Step(i).String(), view.PhaseOf(state.Step(i))
	if o.ActiveSeat != nil {
		if v.Active, err = Seat(*o.ActiveSeat); err != nil {
			return view.View{}, err
		}
	}
	if o.PrioritySeat != nil {
		if v.Priority, err = Seat(*o.PrioritySeat); err != nil {
			return view.View{}, err
		}
	}
	blockers := map[string][]state.ObjID{} // attacker v2 id -> its blockers
	for _, p := range o.Players {
		for _, r := range p.Battlefield {
			if r.Permanent != nil {
				for _, a := range r.Permanent.BlockedAttackers {
					blockers[a.ObjectID] = append(blockers[a.ObjectID], b.IDs.Of(r.ObjectID))
				}
			}
		}
	}
	for _, p := range o.Players {
		seat, err := Seat(p.Seat)
		if err != nil {
			return view.View{}, err
		}
		pool := p.ManaPool
		pv := view.PlayerView{ID: seat, Name: p.Seat, Life: p.Life, LibrarySize: int(p.LibraryCount),
			HandSize: int(p.HandCount), GraveyardSize: len(p.Graveyard),
			Pool: map[string]int32{"W": int32(pool.W), "U": int32(pool.U), "B": int32(pool.B),
				"R": int32(pool.R), "G": int32(pool.G), "C": int32(pool.C)},
			Command: []view.CardView{}, Commanders: []view.CardView{}, CommanderCasts: []int32{}}
		zone := func(rs []protocol.ObjectRecord) ([]view.CardView, error) {
			out := make([]view.CardView, 0, len(rs))
			for _, r := range rs {
				cv, err := b.card(r, blockers)
				if err != nil {
					return nil, err
				}
				out = append(out, cv)
			}
			return out, nil
		}
		if seat == viewer {
			if pv.Hand, err = zone(p.Hand); err != nil {
				return view.View{}, err
			}
		}
		for _, z := range []struct {
			dst *[]view.CardView
			src []protocol.ObjectRecord
		}{{&pv.Battlefield, p.Battlefield}, {&pv.Graveyard, p.Graveyard}, {&pv.Exile, p.Exile}, {&pv.Command, p.Command}} {
			if *z.dst, err = zone(z.src); err != nil {
				return view.View{}, err
			}
		}
		v.Players = append(v.Players, pv)
	}
	for _, e := range o.Stack {
		sv, err := b.stack(e)
		if err != nil {
			return view.View{}, err
		}
		v.Stack = append(v.Stack, sv)
	}
	return v, nil
}

func (b *Builder) card(r protocol.ObjectRecord, blockers map[string][]state.ObjID) (view.CardView, error) {
	controller, err := Seat(r.ControllerSeat)
	if err != nil {
		return view.CardView{}, err
	}
	owner, err := Seat(r.OwnerSeat)
	if err != nil {
		return view.CardView{}, err
	}
	id := b.IDs.Of(r.ObjectID)
	cv := view.CardView{ID: id, Controller: controller, Owner: owner, FaceDown: r.FaceDown,
		Token: "#" + strconv.FormatUint(uint64(id), 10)}
	if r.CardName == nil {
		// A face-down card the viewer may not look at: gorge projects it
		// with every printed field blank.
		return cv, nil
	}
	f := b.face(r.CardName, r.Token && !r.Copy, r.Characteristics)
	b.printed(&cv, f, *r.CardName, r.Characteristics)
	if c := r.Characteristics; c != nil {
		if c.Power != nil {
			cv.Power = *c.Power
		}
		if c.Toughness != nil {
			cv.Toughness = *c.Toughness
		}
		cv.Keywords = keywordLines(f, c.Keywords)
	}
	if p := r.Permanent; p != nil {
		cv.Tapped, cv.Damage, cv.SummonSick, cv.Attacking = p.Tapped, int32(p.Damage), p.SummoningSick, p.Attacking
		if p.AttachedTo != nil && p.AttachedTo.Object != nil {
			cv.AttachedTo = b.IDs.Of(p.AttachedTo.Object.ObjectID)
		}
		if p.Attacking && p.AttackTarget != nil && p.AttackTarget.Player != nil {
			who, err := Seat(*p.AttackTarget.Player)
			if err != nil {
				return view.CardView{}, err
			}
			cv.AttackingPlayer = &who
		}
		if bs := blockers[r.ObjectID]; len(bs) > 0 {
			cv.BlockedBy = slices.Clone(bs)
		}
		if len(p.Counters) > 0 {
			cv.Counters = map[string]int32{}
			for k, n := range p.Counters {
				cv.Counters[strings.ToUpper(k)] = int32(n)
			}
		}
	}
	return cv, nil
}

// printed fills a card's printed facts: from its registry face, or from its
// observed characteristics for a card the registry does not know.
func (b *Builder) printed(cv *view.CardView, f *cards.Face, name string, c *protocol.Characteristics) {
	cv.Name = name
	cv.Printing = view.Printing{Name: name}
	if f == nil {
		if c != nil {
			var words []string
			for _, list := range [][]string{c.Supertypes, c.Types, c.Subtypes} {
				for _, w := range list {
					words = append(words, title(w))
				}
			}
			cv.Types = strings.Join(words, " ")
		}
		return
	}
	cv.Name, cv.Printing.Name = f.Name, f.Name
	cv.Types = strings.Join(f.Types, " ")
	cv.ManaCost = f.ManaCost
	if sa := f.SpellAbility(); sa != nil {
		cv.SpellAPI = sa.API
	}
	if p := f.ManaProduction(); !p.IsZero() {
		cv.Produces = &p
	}
}

func (b *Builder) stack(e protocol.StackEntry) (view.StackView, error) {
	controller, err := Seat(e.ControllerSeat)
	if err != nil {
		return view.StackView{}, err
	}
	sv := view.StackView{ID: b.IDs.Of(e.ObjectID), Controller: controller, Targets: []view.TargetView{}}
	if e.CardName != nil {
		sv.Name = *e.CardName
	}
	for _, t := range e.Targets {
		switch {
		case t == nil:
		case t.Player != nil:
			who, err := Seat(*t.Player)
			if err != nil {
				return view.StackView{}, err
			}
			sv.Targets = append(sv.Targets, view.TargetView{Player: who, IsPlayer: true})
		case t.Object != nil:
			sv.Targets = append(sv.Targets, view.TargetView{Obj: b.IDs.Of(t.Object.ObjectID)})
		}
	}
	switch e.StackKind {
	case "spell":
		sv.Kind = "spell"
		owner, err := Seat(e.OwnerSeat)
		if err != nil {
			return view.StackView{}, err
		}
		if e.CardName != nil {
			cv := view.CardView{ID: sv.ID, Controller: controller, Owner: owner, Token: "#" + strconv.FormatUint(uint64(sv.ID), 10)}
			f := b.face(e.CardName, false, e.Characteristics)
			b.printed(&cv, f, *e.CardName, e.Characteristics)
			if c := e.Characteristics; c != nil {
				if c.Power != nil {
					cv.Power = *c.Power
				}
				if c.Toughness != nil {
					cv.Toughness = *c.Toughness
				}
				cv.Keywords = keywordLines(f, c.Keywords)
			}
			sv.Name = cv.Name
			sv.Card = &cv
		}
	case "triggered_ability":
		sv.Kind = "trigger"
	default:
		sv.Kind = "ability"
	}
	if e.Source != nil {
		sv.Source = b.IDs.Of(e.Source.ObjectID)
	}
	return sv, nil
}

// keywordLines turns Section 6.10 keyword names back into gorge's keyword
// lines: the printed face's own line when it has one for that keyword (so a
// parameter such as a flashback cost survives), else the name in gorge's
// title case ("first_strike" -> "First Strike"). The face's lines that name
// no CR 702 keyword (gorge's internal ones, such as etbCounter) are kept
// first, as gorge's derived list carries them.
func keywordLines(f *cards.Face, names []string) []string {
	var out []string
	if f != nil {
		for _, l := range f.Keywords {
			if len(observe.Keywords([]string{l})) == 0 {
				out = append(out, l)
			}
		}
	}
	for _, k := range names {
		line := ""
		if f != nil {
			for _, l := range f.Keywords {
				if got := observe.Keywords([]string{l}); len(got) == 1 && got[0] == k {
					line = l
					break
				}
			}
		}
		if line == "" {
			words := strings.Split(k, "_")
			for i, w := range words {
				words[i] = title(w)
			}
			line = strings.Join(words, " ")
		}
		out = append(out, line)
	}
	return out
}

func title(w string) string {
	if w == "" {
		return w
	}
	return strings.ToUpper(w[:1]) + w[1:]
}
