package mapping

import (
	"fmt"

	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/state"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/observe"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
)

var CostKinds = map[string]string{"sacrifice": "sacrifice", "discard": "discard", "tapcost": "tap",
	"returncost": "return_to_hand", "exile_cost": "exile", "exile": "exile"}

var costPurposes = map[string]string{"sacrifice": "sacrifice", "discard": "discard", "tap": "tap",
	"return_to_hand": "return_to_hand", "exile": "exile"}

func init() {
	Register("target", newTargets)
	Register("choose/cost", newCost)
}

func TargetOf(env *Env, d *decision.Decision, o decision.Option) (protocol.TargetRef, error) {
	if o.Kind == "player" {
		return protocol.PlayerTarget(observe.Seat(o.Player)), nil
	}
	r, err := env.Obs.Ref(d.Player, o.Obj)
	if err != nil || r == nil {
		return protocol.TargetRef{}, fmt.Errorf("%w: target %d not visible", ErrUnmapped, o.Obj)
	}
	return protocol.ObjectTarget(*r), nil
}

// slotTx wraps a target pick to count the slot when it completes.
type slotTx struct {
	Transaction
	env *Env
	key string
}

func (s *slotTx) Answer(i int) ([]decision.Intent, bool, error) {
	c, done, err := s.Transaction.Answer(i)
	if done {
		s.env.Slots[s.key]++
	}
	return c, done, err
}

func newTargets(env *Env, d *decision.Decision) (Transaction, error) {
	src, err := MustSource(env, d)
	if err != nil {
		return nil, err
	}
	slot := env.Slots[src.ObjectID]
	lo, hi := uint32(d.Min), uint32(d.Max)
	spec := PickSpec{D: d, Options: allOptions(d), Context: protocol.Context{Kind: "choice", Source: &src},
		Sem: func(opt int, sel uint32) (Cand, error) {
			tg, err := TargetOf(env, d, d.Options[opt])
			return Cand{Sem: protocol.ChooseTarget(src, slot, tg, sel, lo, hi)}, err
		},
		Finish: func(sel uint32) protocol.Semantic { return protocol.FinishTargetSelection(src, slot, sel) }}
	return &slotTx{Transaction: NewPick(env, spec), env: env, key: src.ObjectID}, nil
}

func newCost(env *Env, d *decision.Decision) (Transaction, error) {
	src, err := MustSource(env, d)
	if err != nil {
		return nil, err
	}
	kind, ok := CostKinds[d.Options[0].Kind]
	if !ok {
		return nil, fmt.Errorf("%w:cost/%s", ErrUnmapped, d.Options[0].Kind)
	}
	lo, hi := uint32(d.Min), uint32(d.Max)
	ref := func(opt int) (protocol.ObjectRef, error) {
		r, err := env.Obs.Ref(d.Player, d.Options[opt].Obj)
		if err != nil || r == nil {
			return protocol.ObjectRef{}, fmt.Errorf("%w: cost object not visible", ErrUnmapped)
		}
		return *r, nil
	}
	spec := PickSpec{D: d, Options: allOptions(d), Context: protocol.Context{Kind: "choice", Source: &src}}
	if d.Min == d.Max {
		spec.Sem = func(opt int, sel uint32) (Cand, error) {
			r, err := ref(opt)
			return Cand{Sem: protocol.ChooseCostTarget(src, kind, r, sel, lo, hi)}, err
		}
		return NewPick(env, spec), nil
	}
	purp := costPurposes[kind]
	if kind == "exile" && env.G.E.G.Obj(d.Options[0].Obj).Zone == state.ZGraveyard {
		purp = "delve"
	}
	spec.Context.Purpose = &purp
	spec.Sem = func(opt int, sel uint32) (Cand, error) {
		r, err := ref(opt)
		return Cand{Sem: protocol.SelectObject(&src, purp, protocol.ObjectTarget(r), sel, lo, hi)}, err
	}
	spec.Finish = func(sel uint32) protocol.Semantic { return protocol.FinishSelection(&src, purp, sel) }
	return NewPick(env, spec), nil
}
