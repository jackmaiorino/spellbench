package mapping

import (
	"fmt"

	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/state"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
)

var castMethods = map[string]string{"": "normal", "mayplay": "normal", "mayflash": "normal", "flashback": "flashback",
	"plot_cast": "plot", "bestowed": "alternative", "surged": "alternative", "blitzed": "alternative",
	"emerged": "alternative", "mutated": "alternative", "escape": "escape", "madness": "madness", "miracle": "miracle",
	"foretell_cast": "foretell", "adventure_alt": "adventure", "split_alt": "split_right", "fuse": "fuse",
	"suspend_cast": "suspend", "modal_spell": "mdfc_back"}

var optionalCostModes = map[string]string{"kicked": "kicker", "buyback": "buyback", "entwined": "entwine",
	"conspired": "conspire", "casualty": "casualty", "offspring": "offspring"}

// CastMethod classifies a "cast" option of a card whose AlternateMode is
// alternateMode: a method, or an optional cost over the normal method, or a
// special action. gorge's adventure_alt also casts an Omen face (Roost Seek),
// which v2's method vocabulary names only as "other". Every mode outside the
// tables fails closed (the engine notes list them).
func CastMethod(o decision.Option, alternateMode string) (method, optional, special string, ok bool) {
	if o.Mode == "plot" {
		return "", "", "plot", true
	}
	if c, ok := optionalCostModes[o.Mode]; ok {
		return "normal", c, "", true
	}
	if o.AltCostIndex > 0 {
		return "alternative", "", "", true
	}
	if o.Mode == "adventure_alt" && alternateMode != "Adventure" {
		return "other", "", "", true
	}
	m, ok := castMethods[o.Mode]
	return m, "", "", ok
}

func NonManaAbilityIndex(o *state.Object, abilityIdx int) uint32 {
	f := o.Face()
	n := uint32(0)
	for i, a := range f.Abilities {
		if i == abilityIdx {
			return n
		}
		if a.Kind == "AB" && a.API != "Mana" {
			n++
		}
	}
	return n
}

type castGroup struct {
	plain    int            // native index of the plain variant, -1 when absent
	optional map[string]int // cost -> native index
	cost     string
	method   string
	src      protocol.ObjectRef
}

type priorityTx struct {
	env      *Env
	d        *decision.Decision
	pose     *Pose
	groups   map[int]*castGroup // candidate index -> cast group needing a follow-up
	followup *castGroup
	follPose *Pose
}

func init() { Register("priority", newPriority) }

func newPriority(env *Env, d *decision.Decision) (Transaction, error) {
	return &priorityTx{env: env, d: d, groups: map[int]*castGroup{}}, nil
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
	casts := map[string]*castGroup{} // key: object and method
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
			idx := NonManaAbilityIndex(t.env.G.E.G.Obj(o.Obj), o.Ability)
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
			// One candidate per object, method and alternative cost: two
			// alternative costs of one card stay two variants (their equal
			// semantics then fail closed as duplicates), never one overwriting
			// the other.
			key := fmt.Sprint(o.Obj, "/", method, "/", o.AltCostIndex)
			cg := casts[key]
			if cg == nil {
				cg = &castGroup{plain: -1, optional: map[string]int{}, src: src, method: method}
				casts[key] = cg
				p.Candidates = append(p.Candidates, Cand{Sem: protocol.CastSpell(src, method), Op: NativeOp{Op: "cast", Option: -1}})
				t.groups[len(p.Candidates)-1] = cg
			}
			if optional == "" {
				cg.plain = o.Index
			} else {
				cg.optional[optional] = o.Index
				cg.cost = optional
			}
		default:
			return nil, fmt.Errorf("%w:priority/%s", ErrUnmapped, o.Kind)
		}
	}
	// A cast group without optional variants is a plain choice; one with an
	// optional-cost variant stands for every native variant it covers.
	for i, cg := range t.groups {
		switch {
		case len(cg.optional) == 0:
			p.Candidates[i].Op = NativeOp{Op: "choose", Option: cg.plain}
		case len(cg.optional) > 1:
			return nil, fmt.Errorf("%w:several optional costs on one cast", ErrUnmapped)
		default:
			for _, opt := range cg.optional {
				p.Candidates[i].Op.Covers = append(p.Candidates[i].Op.Covers, opt)
			}
			if cg.plain >= 0 {
				p.Candidates[i].Op.Covers = append(p.Candidates[i].Op.Covers, cg.plain)
			}
		}
	}
	if err := Finalize(p); err != nil {
		return nil, err
	}
	t.pose = p
	return p, nil
}

func (t *priorityTx) Answer(i int) ([]decision.Intent, bool, error) {
	if t.followup != nil {
		op := t.follPose.Candidates[i].Op
		return []decision.Intent{Intent(t.d, op.Option)}, true, nil
	}
	c := t.pose.Candidates[i]
	if c.Op.Op == "cast" {
		var cg *castGroup
		src, method := c.Sem.Fields["source"].(protocol.ObjectRef), c.Sem.Fields["method"].(string)
		for _, g := range t.groups {
			if g.src.ObjectID == src.ObjectID && g.method == method {
				cg = g
			}
		}
		t.followup = cg
		f := &Pose{Seat: t.d.Player, Context: protocol.Context{Kind: "choice", Source: &cg.src}, GroupStart: true, SubstepCount: 1, Native: t.d}
		for _, opt := range cg.optional {
			f.Candidates = append(f.Candidates, Cand{Sem: protocol.OptionalCost(cg.src, cg.cost, true), Op: NativeOp{Op: "choose", Option: opt}})
		}
		if cg.plain >= 0 {
			f.Candidates = append(f.Candidates, Cand{Sem: protocol.OptionalCost(cg.src, cg.cost, false), Op: NativeOp{Op: "choose", Option: cg.plain}})
		}
		if err := Finalize(f); err != nil {
			return nil, false, err
		}
		t.follPose = f
		return nil, false, nil
	}
	ins := []decision.Intent{Intent(t.d, c.Op.Option)}
	for _, f := range c.Op.Followup {
		ins = append(ins, decision.Intent{Choices: []int{f}}) // Seq and Player are filled by the session at commit
	}
	return ins, true, nil
}
