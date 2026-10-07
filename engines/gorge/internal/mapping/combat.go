package mapping

import (
	"fmt"
	"slices"
	"strings"

	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/state"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/observe"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
)

func init() {
	Register("attackers", func(env *Env, d *decision.Decision) (Transaction, error) { return newDeclare(env, d, true) })
	Register("blockers", func(env *Env, d *decision.Decision) (Transaction, error) { return newDeclare(env, d, false) })
	RegisterInternal("choose/division", engineOrderDivision)
}

type declareTx struct {
	env    *Env
	d      *decision.Decision
	attack bool
	units  []state.ObjID // one entry per decision (a blocker repeats per extra block)
	chosen []int
	i      int
	pose   *Pose
	memo   map[string]bool
}

func newDeclare(env *Env, d *decision.Decision, attack bool) (Transaction, error) {
	t := &declareTx{env: env, d: d, attack: attack, memo: map[string]bool{}}
	seen := map[state.ObjID]bool{}
	for _, o := range d.Options {
		if seen[o.Obj] {
			continue
		}
		seen[o.Obj] = true
		n := 1
		if !attack && o.Group != "" {
			n = d.GroupCapFor(o.Group)
		}
		for k := 0; k < n; k++ {
			t.units = append(t.units, o.Obj)
		}
	}
	return t, nil
}

func (t *declareTx) accepts(ch []int) bool {
	if v, ok := t.memo[key(ch)]; ok {
		return v
	}
	v := Accepts(t.env, Intent(t.d, ch...))
	t.memo[key(ch)] = v
	return v
}

// completable: a full declaration extending prefix, deciding only units from `from` on.
func (t *declareTx) completable(prefix []int, from int, budget *int) bool {
	if t.accepts(prefix) {
		return true
	}
	if fr := t.d.FitRequired(prefix); t.laterUnitsOnly(prefix, fr, from) && t.accepts(fr) {
		return true
	}
	for u := from; u < len(t.units) && *budget > 0; u++ {
		for _, o := range t.d.Options {
			if o.Obj != t.units[u] || slices.Contains(prefix, o.Index) {
				continue
			}
			*budget--
			if t.completable(append(slices.Clone(prefix), o.Index), u+1, budget) {
				return true
			}
		}
	}
	return false
}

// laterUnitsOnly reports whether the repair fr keeps prefix and adds options
// only for units at index from or later. FitRequired may add an option for a
// unit already decided (the current unit, when its null candidate is being
// tested): that completion would re-decide it, so it proves nothing.
func (t *declareTx) laterUnitsOnly(prefix, fr []int, from int) bool {
	if len(fr) < len(prefix) || !slices.Equal(fr[:len(prefix)], prefix) {
		return false
	}
	for _, o := range fr[len(prefix):] {
		if !slices.Contains(t.units[from:], t.d.Options[o].Obj) {
			return false
		}
	}
	return true
}

func (t *declareTx) ref(id state.ObjID) (protocol.ObjectRef, error) {
	r, err := t.env.Obs.Ref(t.d.Player, id)
	if err != nil || r == nil {
		return protocol.ObjectRef{}, fmt.Errorf("%w: combat object %d not visible", ErrUnmapped, id)
	}
	return *r, nil
}

func (t *declareTx) Pose() (*Pose, error) {
	unit := t.units[t.i]
	u, err := t.ref(unit)
	if err != nil {
		return nil, err
	}
	p := &Pose{Seat: t.d.Player, Context: protocol.Context{Kind: "choice"}, GroupStart: t.i == 0,
		SubstepIndex: uint32(t.i), SubstepCount: uint32(len(t.units)), Native: t.d}
	for _, o := range t.d.Options {
		if o.Obj != unit || slices.Contains(t.chosen, o.Index) {
			continue
		}
		budget := 32
		if !t.completable(append(slices.Clone(t.chosen), o.Index), t.i+1, &budget) {
			continue
		}
		var sem protocol.Semantic
		if t.attack {
			def := protocol.PlayerTarget(observe.Seat(o.Player))
			if o.Battle != 0 {
				b, err := t.ref(o.Battle)
				if err != nil {
					return nil, err
				}
				def = protocol.ObjectTarget(b)
			}
			sem = protocol.DeclareAttack(u, &def)
		} else {
			a, err := t.ref(o.Attacker)
			if err != nil {
				return nil, err
			}
			sem = protocol.DeclareBlock(u, &a)
		}
		p.Candidates = append(p.Candidates, Cand{Sem: sem, Op: NativeOp{Op: "choose", Option: o.Index, Unit: unit}})
	}
	budget := 32
	if t.completable(slices.Clone(t.chosen), t.i+1, &budget) {
		none := protocol.DeclareBlock(u, nil)
		if t.attack {
			none = protocol.DeclareAttack(u, nil)
		}
		p.Candidates = append(p.Candidates, Cand{Sem: none, Op: NativeOp{Op: "none", Option: -1, Unit: unit}})
	}
	if err := Finalize(p); err != nil {
		return nil, err
	}
	t.pose = p
	return p, nil
}

func (t *declareTx) Answer(i int) ([]decision.Intent, bool, error) {
	if op := t.pose.Candidates[i].Op; op.Op == "choose" {
		t.chosen = append(t.chosen, op.Option)
	}
	t.i++
	if t.i == len(t.units) {
		return []decision.Intent{Intent(t.d, t.chosen...)}, true, nil
	}
	return nil, false, nil
}

// Compositions reproduces gorge rules.divisionOptions: every nonnegative split
// of power over n recipients, first recipient's amount ascending outermost.
func Compositions(power int32, n int) [][]int32 {
	var out [][]int32
	cur := make([]int32, 0, n)
	var rec func(rem int32, idx int)
	rec = func(rem int32, idx int) {
		if idx == n-1 {
			out = append(out, append(append([]int32(nil), cur...), rem))
			return
		}
		for v := int32(0); v <= rem; v++ {
			cur = append(cur, v)
			rec(rem-v, idx+1)
			cur = cur[:len(cur)-1]
		}
	}
	rec(power, 0)
	return out
}

// EngineOrderSplit is Section 7.6's engine_order combat damage assignment
// over blockers in gorge's order: lethal damage to each blocker, the rest to
// the last one. lethal[i] is blocker i's lethal amount.
func EngineOrderSplit(power int32, lethal []int32) []int32 {
	out := make([]int32, len(lethal))
	remaining := power
	for i, need := range lethal {
		give := remaining
		if i < len(lethal)-1 && give > need {
			give = max(0, need)
		}
		out[i] = give
		remaining -= give
	}
	return out
}

// engineOrderDivision answers gorge's combat damage division ask itself,
// under hello_ok's combat_damage_assignment "engine_order": gorge's blocker
// order, and gorge's measure of lethal (the blocker's toughness, 1 when the
// attacker has deathtouch). gorge assigns trample damage and divisions too
// large to ask with the same rule (rules/combat.go), so every combat follows
// one declared rule and no distribute decision is ever posed.
func engineOrderDivision(env *Env, d *decision.Decision) (decision.Intent, error) {
	e := env.G.E
	a := e.G.Obj(d.Source)
	if a == nil || len(d.Options) == 0 {
		return decision.Intent{}, fmt.Errorf("%w:division_without_attacker", ErrUnmapped)
	}
	power := int32(d.Options[len(d.Options)-1].Amount)
	var live []state.ObjID
	for _, b := range a.BlockedBy {
		if o := e.G.Obj(b); o != nil && o.Zone == state.ZBattlefield {
			live = append(live, b)
		}
	}
	// The engine poses a division only for two or more live blockers
	// (rules.divisionNeeding); check before Compositions, whose recursion is
	// defined for n >= 1, so an out-of-contract ask halts instead of crashing.
	if len(live) < 2 {
		return decision.Intent{}, fmt.Errorf("%w:division_layout", ErrUnmapped)
	}
	splits := Compositions(power, len(live))
	if len(splits) != len(d.Options) {
		return decision.Intent{}, fmt.Errorf("%w:division_layout", ErrUnmapped)
	}
	for i, o := range d.Options {
		if int32(o.Amount) != splits[i][0] || len(strings.Split(o.Label, ",")) != len(live) {
			return decision.Intent{}, fmt.Errorf("%w:division_layout", ErrUnmapped)
		}
	}
	lethal := make([]int32, len(live))
	for i, b := range live {
		lethal[i] = e.Toughness(b)
		if e.HasKeyword(a.ID, "Deathtouch") {
			lethal[i] = 1
		}
	}
	want := EngineOrderSplit(power, lethal)
	for k, split := range splits {
		if slices.Equal(split, want) {
			return Intent(d, k), nil
		}
	}
	return decision.Intent{}, fmt.Errorf("%w:division_split", ErrUnmapped)
}
