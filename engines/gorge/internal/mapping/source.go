package mapping

import (
	"github.com/adams-shaun/gorge/decision"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
)

// ResolveSource finds a choice decision's v2 source (Section 7.3), in order:
//  1. the stack entry of the ability whose source is Decision.Source (topmost),
//     or Decision.Source itself when it is on the stack. While the acting seat
//     is still announcing its own action from Decision.Source, abilities put
//     on the stack before that action began are skipped: they are an earlier
//     activation of the same permanent, not this one;
//     rules-owned ward/unless mana windows omit Source, but Ask suspends
//     their resolution on the current top stack entry;
//  2. the current visible incarnation of Decision.Source;
//  3. the object of the acting seat's last priority action (gorge chooses an
//     activated ability's targets and costs before pushing it: sourceprobe);
//  4. nil.
func ResolveSource(env *Env, d *decision.Decision) (*protocol.ObjectRef, error) {
	g := env.G.E.G
	if d.Source != 0 {
		a := env.Action
		announcing := a != nil && a.Seat == d.Player && a.Obj == d.Source
		for i := len(g.Stack) - 1; i >= 0; i-- {
			id := g.Stack[i]
			if announcing && id < a.Since {
				continue
			}
			if so := g.Obj(id); so != nil && so.Ability != nil && so.Source == d.Source {
				return env.Obs.Ref(d.Player, id)
			}
		}
		if r, err := env.Obs.Ref(d.Player, d.Source); r != nil || err != nil {
			return r, err
		}
	}
	if d.Source == 0 && d.Kind == decision.KChoose &&
		(d.ResumeKind == "unless_mana" || d.ResumeKind == "ward_mana") {
		// rules.askWardMana does not populate Decision.Source. Its Ask call
		// captures the current top stack object as the suspended resolution.
		// Refer only to that publicly visible entry, without changing the
		// native decision or borrowing an unrelated priority action's source.
		if n := len(g.Stack); n > 0 {
			return env.Obs.Ref(d.Player, g.Stack[n-1])
		}
	}
	if a := env.Action; a != nil && a.Seat == d.Player {
		return env.Obs.Ref(d.Player, a.Obj)
	}
	return nil, nil
}

// MustSource is ResolveSource for kinds whose source is typed R (never null).
func MustSource(env *Env, d *decision.Decision) (protocol.ObjectRef, error) {
	r, err := ResolveSource(env, d)
	if err != nil {
		return protocol.ObjectRef{}, err
	}
	if r == nil {
		return protocol.ObjectRef{}, ErrUnresolvableSource
	}
	return *r, nil
}
