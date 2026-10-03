package xview

import (
	"github.com/adams-shaun/gorge/state"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/mapping"
)

// SearchAliases joins the current public incarnation IDs to previously
// observed history IDs. Map ordering carries no native option ordering.
func (x *Extender) SearchAliases(env *mapping.Env, p *mapping.Pose, alias func(state.ObjID) uint32) (map[uint32]uint32, error) {
	r, errp := x.rekey(env, p.Seat, shownBy(p))
	out := map[uint32]uint32{}
	add := func(id state.ObjID) {
		if _, player := id.PlayerRef(); player {
			return
		}
		if public, observed := r(id), alias(id); public != 0 && observed != 0 {
			out[uint32(public)] = observed
		}
	}
	add(p.Native.Source)
	for _, o := range p.Native.Options {
		add(o.Obj)
		add(o.Attacker)
	}
	for _, action := range p.Native.PaymentActions {
		add(action.Cast.Object)
		for _, plan := range action.Plans {
			for _, activation := range plan.Activations {
				add(activation.Source)
			}
		}
	}
	return out, *errp
}
