package mapping

import (
	"fmt"
	"strings"

	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/rules"
	"github.com/adams-shaun/gorge/state"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
)

func init() {
	ExpandActivate = expandActivate
	Register("choose/mana", func(*Env, *decision.Decision) (Transaction, error) {
		return nil, fmt.Errorf("%w:unfolded_mana_colour", ErrUnmapped)
	})
}

func ManaSymbol(o decision.Option) (string, bool) {
	if o.ManaSymbol != "" {
		return o.ManaSymbol, true
	}
	l := strings.TrimSpace(o.Label)
	if i := strings.LastIndex(l, "Add "); i >= 0 && len(l) == i+5 && strings.ContainsAny(l[i+4:], "WUBRGC") {
		return l[i+4:], true
	}
	return "", false
}

var costKinds = map[string]bool{"tapcost": true, "sacrifice": true, "discard": true, "exile_cost": true, "returncost": true}

func sameSeatChoose(c *rules.Engine, seat state.PlayerID) *decision.Decision {
	n := c.Pending()
	if n == nil || c.G.Over || n.Player != seat || n.Kind != decision.KChoose || len(n.Options) == 0 {
		return nil
	}
	return n
}

func expandActivate(env *Env, d *decision.Decision, o decision.Option, src protocol.ObjectRef) ([]Cand, map[string]*decision.Decision, error) {
	c, err := env.G.Probe(Intent(d, o.Index))
	if err != nil {
		return nil, nil, nil // the engine refuses this activation now: not offered
	}
	folds := map[string]*decision.Decision{}
	plain := []Cand{{Sem: protocol.ActivateManaAbility(src, 0, nil, nil), Op: NativeOp{Op: "choose", Option: o.Index}}}
	next := sameSeatChoose(c, d.Player)
	if next == nil {
		return plain, nil, nil
	}
	key := fmt.Sprint(o.Index)
	switch k := next.Options[0].Kind; {
	case k == "mana":
		// A colour ask, or gorge's stage-1 "choose a mana ability" ask for a
		// source with several available mana abilities (Heap Gate). Each
		// option carries its ability in Option.Ability (0 for a colour ask
		// of a single-ability source), and either a single pip or, for an
		// ability whose colour is asked next, none: that stage-2 colour ask
		// is folded as the follow-up "<option>/<stage-1 option>".
		folds[key] = next
		var out []Cand
		for _, co := range next.Options {
			idx := uint32(co.Ability)
			if sym, ok := ManaSymbol(co); ok {
				out = append(out, Cand{Sem: protocol.ActivateManaAbility(src, idx, &sym, nil),
					Op: NativeOp{Op: "choose", Option: o.Index, Followup: []int{co.Index}}})
				continue
			}
			c2, err := env.G.Probe(Intent(d, o.Index), Intent(next, co.Index))
			if err != nil {
				continue // the engine refuses this ability now: not offered
			}
			n2 := sameSeatChoose(c2, d.Player)
			if n2 == nil || n2.Options[0].Kind != "mana" {
				return nil, nil, fmt.Errorf("%w:mana_ability/%q", ErrUnmapped, co.Label)
			}
			folds[fmt.Sprint(key, "/", co.Index)] = n2
			for _, col := range n2.Options {
				sym, ok := ManaSymbol(col)
				if !ok {
					return nil, nil, fmt.Errorf("%w:mana_option/%q", ErrUnmapped, col.Label)
				}
				out = append(out, Cand{Sem: protocol.ActivateManaAbility(src, idx, &sym, nil),
					Op: NativeOp{Op: "choose", Option: o.Index, Followup: []int{co.Index, col.Index}}})
			}
		}
		return out, folds, nil
	case costKinds[k] && next.Min == 1 && next.Max == 1:
		folds[key] = next
		var out []Cand
		for _, co := range next.Options {
			target, err := env.Obs.Ref(d.Player, co.Obj)
			if err != nil || target == nil {
				return nil, nil, fmt.Errorf("%w:cost_target_hidden", ErrUnmapped)
			}
			ct := protocol.ObjectTarget(*target)
			c2, err := env.G.Probe(Intent(d, o.Index), Intent(next, co.Index))
			if err != nil {
				continue
			}
			if n2 := sameSeatChoose(c2, d.Player); n2 != nil && n2.Options[0].Kind == "mana" {
				folds[fmt.Sprint(key, "/", co.Index)] = n2
				for _, col := range n2.Options {
					sym, ok := ManaSymbol(col)
					if !ok {
						return nil, nil, fmt.Errorf("%w:mana_option/%q", ErrUnmapped, col.Label)
					}
					out = append(out, Cand{Sem: protocol.ActivateManaAbility(src, 0, &sym, &ct),
						Op: NativeOp{Op: "choose", Option: o.Index, Followup: []int{co.Index, col.Index}}})
				}
				continue
			}
			out = append(out, Cand{Sem: protocol.ActivateManaAbility(src, 0, nil, &ct),
				Op: NativeOp{Op: "choose", Option: o.Index, Followup: []int{co.Index}}})
		}
		return out, folds, nil
	}
	return plain, nil, nil // any other follow-up (a trigger order, say) is posed on its own
}
