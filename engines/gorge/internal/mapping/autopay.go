package mapping

import (
	"fmt"

	"github.com/adams-shaun/gorge/decision"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
)

func paymentIntent(d *decision.Decision, p *decision.PaymentSelection) decision.Intent {
	return decision.Intent{Seq: d.Seq, Player: d.Player, Payment: decision.ClonePaymentSelection(p)}
}

// A pool-only plan and its existing normal cast have identical execution.
// Keep the ordinary cast intent, preserving manual-policy behavior. The
// payment tag allows an auto-pay policy to select that same wire candidate.
func (cg *castGroup) plainOp() NativeOp {
	op := NativeOp{Op: "choose", Option: cg.plain, Payment: decision.ClonePaymentSelection(cg.payment)}
	if cg.plain < 0 && cg.payment != nil {
		op.Op = "payment"
	}
	return op
}

// Expose the upstream planner's first plan as an engine-paid normal cast.
// This is the same plan Bot.paymentIntent selects. Existing manual options,
// including mana activations and optional costs, retain their native indices.
func (t *priorityTx) addPayments(p *Pose, casts map[castKey]*castGroup, groups []*castGroup) ([]*castGroup, error) {
	for _, a := range t.d.PaymentActions {
		if len(a.Plans) == 0 {
			continue
		}
		if a.Cast.Face != 0 || a.Cast.Origin != "hand" {
			return nil, fmt.Errorf("%w: unsupported planned cast", ErrUnmapped)
		}
		key := castKey{obj: a.Cast.Object, method: "normal"}
		cg := casts[key]
		if cg == nil {
			src, err := t.ref(a.Cast.Object)
			if err != nil {
				return nil, err
			}
			cg = &castGroup{cand: len(p.Candidates), plain: -1, optional: map[string]int{}, src: src}
			casts[key] = cg
			groups = append(groups, cg)
			p.Candidates = append(p.Candidates, Cand{Sem: protocol.CastSpell(src, "normal")})
		}
		if cg.payment != nil {
			return nil, fmt.Errorf("%w: repeated planned cast", ErrDuplicate)
		}
		if cg.plain >= 0 && (a.BaseOptionIndex == nil || *a.BaseOptionIndex != cg.plain || len(a.Plans[0].Activations) != 0) {
			return nil, fmt.Errorf("%w: payment differs from existing cast", ErrUnmapped)
		}
		cg.payment = &decision.PaymentSelection{ActionID: a.ID, Plan: decision.ClonePaymentPlan(a.Plans[0])}
	}
	return groups, nil
}
