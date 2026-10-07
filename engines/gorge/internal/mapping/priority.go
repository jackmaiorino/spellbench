package mapping

import (
	"fmt"
	"strings"

	"github.com/adams-shaun/gorge/cards"
	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/rules"
	"github.com/adams-shaun/gorge/state"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
)

// castMethods maps a "cast" option's Mode to its Section 7.4 method. The
// madness, miracle and suspend_cast rows cannot fire at the pinned gorge:
// gorge enters those modes itself (rules/altcast.go, rules/miracle.go,
// rules/turn.go), never as priority options.
var castMethods = map[string]string{"": "normal", "mayplay": "normal", "mayflash": "normal", "flashback": "flashback",
	"plot_cast": "plot", "bestowed": "alternative", "surged": "alternative", "blitzed": "alternative",
	"emerged": "alternative", "mutated": "alternative", "escape": "escape", "madness": "madness", "miracle": "miracle",
	"foretell_cast": "foretell", "adventure_alt": "adventure", "split_alt": "split_right", "fuse": "fuse",
	"suspend_cast": "suspend", "modal_spell": "mdfc_back"}

// optionalCostModes maps a Mode that adds an optional cost to the normal cast
// to its Section 7.4 optional_cost.cost word. gorge's optionalcost is a card's
// own OptionalCost static: an optional additional cost, whose decline path is
// the plain cast (rules/legal.go). An additional cost leaves the method
// normal (CR 601.2b), and Section 7.4 names the cost "additional".
var optionalCostModes = map[string]string{"kicked": "kicker", "buyback": "buyback", "entwined": "entwine",
	"conspired": "conspire", "casualty": "casualty", "offspring": "offspring", "optionalcost": "additional"}

// CastMethod classifies a "cast" option of a card whose AlternateMode is
// alternateMode: a Section 7.4 method, or an optional cost over the normal
// method, or a special action. Every mode outside the tables fails closed
// (Task 29's engine notes list them).
func CastMethod(o decision.Option, alternateMode string) (method, optional, special string, ok bool) {
	if o.Mode == "plot" {
		return "", "", "plot", true
	}
	// Before the AltCostIndex rule: an optionalcost option's AltCostIndex
	// numbers the card's optional-cost statics, not an alternative cost.
	if c, ok := optionalCostModes[o.Mode]; ok {
		return "normal", c, "", true
	}
	if o.AltCostIndex > 0 {
		return "alternative", "", "", true
	}
	// An Omen face (Roost Seek) has no v2 method but "other". This cannot
	// fire at the pinned gorge: it offers adventure_alt only for AlternateMode
	// Adventure (rules/adventure.go) and has no Omen cast path, so Roost Seek
	// is never offered.
	if o.Mode == "adventure_alt" && alternateMode != "Adventure" {
		return "other", "", "", true
	}
	m, ok := castMethods[o.Mode]
	return m, "", "", ok
}

// NonManaAbilityIndex is the Section 7.2 ability_index of the printed
// ability an "ability" option anchors: its place among the object's non-mana
// activated abilities, in the face's order (Oracle order on every catalog
// card). It fails closed on every other anchor, since Section 7.2 orders
// granted abilities after the printed ones by timestamp, which an option
// does not carry: keyword-granted (Ability -1, Keyword), SVar-granted (SVar,
// GrantSource) and gained (GainedSource) abilities, and any ability of a
// mutated pile, whose Ability indexes the abilities of all its cards.
func NonManaAbilityIndex(o *state.Object, opt decision.Option) (uint32, error) {
	var f *cards.Face
	if o != nil {
		f = o.Face()
	}
	switch {
	case f == nil:
		return 0, fmt.Errorf("%w:ability/no_face", ErrUnmapped)
	case opt.Ability < 0 || opt.Keyword != "":
		return 0, fmt.Errorf("%w:ability/keyword_granted", ErrUnmapped)
	case opt.SVar != "" || opt.GrantSource != 0:
		return 0, fmt.Errorf("%w:ability/svar_granted", ErrUnmapped)
	case opt.GainedSource != 0:
		return 0, fmt.Errorf("%w:ability/gained", ErrUnmapped)
	case len(o.MergedCards) > 0:
		return 0, fmt.Errorf("%w:ability/mutated_pile", ErrUnmapped)
	case opt.Ability >= len(f.Abilities) || f.Abilities[opt.Ability].Kind != "AB" || manaAbility(f.Abilities[opt.Ability]):
		return 0, fmt.Errorf("%w:ability/not_a_non_mana_ability %d", ErrUnmapped, opt.Ability)
	}
	n := uint32(0)
	for _, a := range f.Abilities[:opt.Ability] {
		if a.Kind == "AB" && !manaAbility(a) {
			n++
		}
	}
	return n, nil
}

// manaAbility is gorge's own split of activated abilities: its priority walk
// (rules/legal.go) offers an AB as an "ability" option unless
// isManaAbilityAPI(ab.API) && !isLoyaltyAbility(ab), since a loyalty ability
// is never a mana ability (CR 605.1b). Both are unexported, so this mirrors
// them (rules/mana_activation.go, and isLoyaltyAbilityCost in rules/legal.go).
func manaAbility(a *cards.SA) bool {
	if a.API != "Mana" && a.API != "ManaReflected" {
		return false
	}
	if v, ok := a.Params["Planeswalker"]; ok && strings.EqualFold(strings.TrimSpace(v), "True") {
		return false
	}
	c := rules.ParseCost(a.Params["Cost"])
	for _, parts := range [][]rules.CostPart{c.AddCounter, c.SubCounter} {
		for _, part := range parts {
			if strings.EqualFold(part.Spec, "LOYALTY") {
				return false
			}
		}
	}
	return true
}

// castKey names one cast_spell candidate: an object, a method and, for an
// alternative cost, which one. Two alternative costs of one card stay two
// candidates, whose equal semantics then fail closed as duplicates.
type castKey struct {
	obj    state.ObjID
	method string
	alt    int
}

// castGroup is the native variants behind one cast_spell candidate: a plain
// cast and at most one optional-cost variant of it.
type castGroup struct {
	payment  *decision.PaymentSelection
	cand     int            // candidate index before Finalize
	plain    int            // native index of the plain variant, -1 when absent
	optional map[string]int // optional cost word -> native index of its variant
	cost     string         // the optional cost word, when there is one
	src      protocol.ObjectRef
}

// add records native option i as the group's plain variant, or as its
// variant for the optional cost. A second variant for either slot fails
// closed, never silently dropping a legal action.
func (cg *castGroup) add(i int, cost string) error {
	if cost == "" {
		if cg.plain >= 0 {
			return fmt.Errorf("%w: native casts %d and %d are one candidate", ErrDuplicate, cg.plain, i)
		}
		cg.plain = i
		return nil
	}
	if j, ok := cg.optional[cost]; ok {
		return fmt.Errorf("%w: native %s casts %d and %d are one candidate", ErrDuplicate, cost, j, i)
	}
	cg.optional[cost], cg.cost = i, cost
	return nil
}

type priorityTx struct {
	env      *Env
	d        *decision.Decision
	pose     *Pose
	groups   map[int]*castGroup // final candidate index of a "cast" candidate -> its variants
	followup *castGroup
	follPose *Pose
}

func init() { Register("priority", newPriority) }

func newPriority(env *Env, d *decision.Decision) (Transaction, error) {
	return &priorityTx{env: env, d: d}, nil
}

func (t *priorityTx) ref(id state.ObjID) (protocol.ObjectRef, error) {
	r, err := t.env.Obs.Ref(t.d.Player, id)
	if err != nil {
		return protocol.ObjectRef{}, err
	}
	if r == nil {
		return protocol.ObjectRef{}, fmt.Errorf("%w: priority option on hidden object %d", ErrUnmapped, id)
	}
	return *r, nil
}

func (t *priorityTx) Pose() (*Pose, error) {
	if t.followup != nil {
		return t.follPose, nil
	}
	d := t.d
	p := &Pose{Seat: d.Player, Context: protocol.Context{Kind: "priority"}, GroupStart: true, SubstepCount: 1, Native: d}
	casts := map[castKey]*castGroup{}
	var groups []*castGroup          // in candidate order
	byNative := map[int]*castGroup{} // native cast option -> its group
	for _, o := range d.Options {
		switch o.Kind {
		case "concede":
		case "pass":
			p.Candidates = append(p.Candidates, Cand{Sem: protocol.Pass(), Op: NativeOp{Op: "choose", Option: o.Index}})
		case "play_land":
			src, err := t.ref(o.Obj)
			if err != nil {
				return nil, err
			}
			face := uint32(0)
			if o.Mode == "modal_land" {
				face = 1
			}
			p.Candidates = append(p.Candidates, Cand{Sem: protocol.PlayLand(src, face), Op: NativeOp{Op: "choose", Option: o.Index}})
		case "ability":
			src, err := t.ref(o.Obj)
			if err != nil {
				return nil, err
			}
			idx, err := NonManaAbilityIndex(t.env.G.E.G.Obj(o.Obj), o)
			if err != nil {
				return nil, err
			}
			p.Candidates = append(p.Candidates, Cand{Sem: protocol.ActivateAbility(src, idx), Op: NativeOp{Op: "choose", Option: o.Index}})
		case "turn_face_up", "unlock":
			src, err := t.ref(o.Obj)
			if err != nil {
				return nil, err
			}
			action := map[string]string{"turn_face_up": "turn_face_up", "unlock": "unlock_door"}[o.Kind]
			p.Candidates = append(p.Candidates, Cand{Sem: protocol.SpecialAction(src, action), Op: NativeOp{Op: "choose", Option: o.Index}})
		case "activate":
			src, err := t.ref(o.Obj)
			if err != nil {
				return nil, err
			}
			cs, folds, err := ExpandActivate(t.env, d, o, src)
			if err != nil {
				return nil, err
			}
			p.Candidates = append(p.Candidates, cs...)
			for k, v := range folds {
				if p.Followups == nil {
					p.Followups = map[string]*decision.Decision{}
				}
				p.Followups[k] = v
			}
		case "cast":
			src, err := t.ref(o.Obj)
			if err != nil {
				return nil, err
			}
			obj := t.env.G.E.G.Obj(o.Obj)
			method, optional, special, ok := CastMethod(o, obj.Card.AlternateMode)
			if !ok {
				return nil, fmt.Errorf("%w:cast_mode/%s", ErrUnmapped, o.Mode)
			}
			if special != "" {
				p.Candidates = append(p.Candidates, Cand{Sem: protocol.SpecialAction(src, special), Op: NativeOp{Op: "choose", Option: o.Index}})
				continue
			}
			// An optional-cost variant joins its plain cast; an alternative
			// cost keys on which one it is (AltCostIndex, which an optional
			// cost's static index must not split).
			key := castKey{obj: o.Obj, method: method}
			if optional == "" {
				key.alt = o.AltCostIndex
			}
			cg := casts[key]
			if cg == nil {
				cg = &castGroup{cand: len(p.Candidates), plain: -1, optional: map[string]int{}, src: src}
				casts[key] = cg
				groups = append(groups, cg)
				p.Candidates = append(p.Candidates, Cand{Sem: protocol.CastSpell(src, method), Op: NativeOp{Op: "cast", Option: -1}})
			}
			if err := cg.add(o.Index, optional); err != nil {
				return nil, err
			}
			byNative[o.Index] = cg
		default:
			return nil, fmt.Errorf("%w:priority/%s", ErrUnmapped, o.Kind)
		}
	}
	// A cast group without an optional variant is a plain choice. One with an
	// optional-cost variant stands for it and its plain cast, and its answer
	// poses the optional_cost follow-up.
	if t.env.AutoPay {
		var err error
		groups, err = t.addPayments(p, casts, groups)
		if err != nil {
			return nil, err
		}
	}
	for _, cg := range groups {
		c := &p.Candidates[cg.cand]
		switch {
		case len(cg.optional) == 0:
			c.Op = cg.plainOp()
		case len(cg.optional) > 1:
			return nil, fmt.Errorf("%w:several optional costs on one cast", ErrUnmapped)
		default:
			c.Op.Payment = decision.ClonePaymentSelection(cg.payment)
			c.Op.Covers = []int{cg.optional[cg.cost]}
			if cg.plain >= 0 {
				c.Op.Covers = append(c.Op.Covers, cg.plain)
			}
		}
	}
	if err := Finalize(p); err != nil {
		return nil, err
	}
	// Finalize moves pass to candidate 0, so each "cast" candidate finds its
	// group by final index, through the native options it covers.
	t.groups = map[int]*castGroup{}
	for i, c := range p.Candidates {
		if c.Op.Op == "cast" {
			t.groups[i] = byNative[c.Op.Covers[0]]
		}
	}
	t.pose = p
	return p, nil
}

func (t *priorityTx) Answer(i int) ([]decision.Intent, bool, error) {
	if t.followup != nil {
		op := t.follPose.Candidates[i].Op
		if op.Op == "payment" {
			return []decision.Intent{paymentIntent(t.d, op.Payment)}, true, nil
		}
		return []decision.Intent{Intent(t.d, op.Option)}, true, nil
	}
	c := t.pose.Candidates[i]
	if c.Op.Op == "payment" {
		return []decision.Intent{paymentIntent(t.d, c.Op.Payment)}, true, nil
	}
	if c.Op.Op == "cast" {
		cg := t.groups[i]
		if cg == nil {
			return nil, false, fmt.Errorf("%w: cast candidate %d has no variants", ErrUnmapped, i)
		}
		// The follow-up's source is the card itself: gorge has not started
		// casting, so no stack entry exists (Section 7.3).
		f := &Pose{Seat: t.d.Player, Context: protocol.Context{Kind: "choice", Source: &cg.src}, GroupStart: true, SubstepCount: 1, Native: t.d}
		f.Candidates = append(f.Candidates, Cand{Sem: protocol.OptionalCost(cg.src, cg.cost, true), Op: NativeOp{Op: "choose", Option: cg.optional[cg.cost]}})
		if cg.plain >= 0 || cg.payment != nil {
			f.Candidates = append(f.Candidates, Cand{Sem: protocol.OptionalCost(cg.src, cg.cost, false), Op: cg.plainOp()})
		}
		if err := Finalize(f); err != nil {
			return nil, false, err
		}
		t.followup, t.follPose = cg, f
		return nil, false, nil
	}
	ins := []decision.Intent{Intent(t.d, c.Op.Option)}
	for _, f := range c.Op.Followup {
		ins = append(ins, decision.Intent{Choices: []int{f}}) // Seq and Player are filled by the session at commit
	}
	return ins, true, nil
}
