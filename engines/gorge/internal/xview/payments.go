package xview

import (
	"fmt"

	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/state"
)

func paymentKey(p *decision.PaymentSelection) string { return p.ActionID + "/" + p.Plan.ID }

// Reissue every witness from seat-local object incarnations and a seat-local
// decision index. Native plan digests and MoveZone event counters never cross
// the wire. A fresh incarnation has a fresh object alias, so zone_seq can be 0.
func (r rekeyer) payments(d *decision.Decision, perm []int) (map[string]decision.PaymentSelection, error) {
	out := map[string]decision.PaymentSelection{}
	for i := range d.PaymentActions {
		a := &d.PaymentActions[i]
		nativeID := a.ID
		a.Cast.Object = r(a.Cast.Object)
		if a.Cast.Object == 0 {
			return nil, fmt.Errorf("payment cast is not visible")
		}
		if a.BaseOptionIndex != nil {
			n := at(perm, *a.BaseOptionIndex)
			a.BaseOptionIndex = &n
		}
		id, err := decision.PaymentActionID(decision.PaymentPlanV1, d.Seq, d.Player, a.Cast)
		if err != nil {
			return nil, err
		}
		a.ID = id
		for j := range a.Plans {
			p := &a.Plans[j]
			nativePlan := p.ID
			for k := range p.Activations {
				activation := &p.Activations[k]
				activation.Source = r(activation.Source)
				if activation.Source == 0 {
					return nil, fmt.Errorf("payment source is not visible")
				}
				activation.SourceZoneSeq = 0
			}
			p.ID, err = decision.PaymentPlanID(d.Seq, d.Player, a.Cast, *p)
			if err != nil {
				return nil, err
			}
			out[nativeID+"/"+nativePlan] = decision.PaymentSelection{ActionID: a.ID, Plan: decision.ClonePaymentPlan(*p)}
		}
	}
	return out, nil
}

// PublicPayment is used only by the realized-intent audit. Agents select a
// candidate; the engine retains and commits the original native witness.
func (x *Extender) PublicPayment(seat state.PlayerID, p *decision.PaymentSelection) *decision.PaymentSelection {
	if p == nil {
		return nil
	}
	public, ok := x.lastPayments[seat][paymentKey(p)]
	if !ok {
		panic("committed payment was not exposed")
	}
	return decision.ClonePaymentSelection(&public)
}
