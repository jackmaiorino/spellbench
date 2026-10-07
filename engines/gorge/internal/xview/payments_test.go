package xview

import (
	"testing"

	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/state"
)

func paymentFixture(t *testing.T) decision.Decision {
	t.Helper()
	cast := decision.PlannedCast{Object: 7, Origin: "hand"}
	plan := decision.PaymentPlan{Version: 1, Cost: decision.PaymentCost{Mana: decision.ManaAmount{0, 0, 0, 1}},
		Activations: []decision.PaymentActivation{{Source: 9, SourceZoneSeq: 987654, Ability: decision.PaymentAbility{Kind: "printed"}, Produces: decision.ManaAmount{0, 0, 0, 1}}}}
	id, err := decision.PaymentActionID(1, 99, 0, cast)
	if err != nil {
		t.Fatal(err)
	}
	plan.ID, err = decision.PaymentPlanID(99, 0, cast, plan)
	if err != nil {
		t.Fatal(err)
	}
	base := 2
	return decision.Decision{Kind: decision.KPriority, Seq: 3, Player: 0, Min: 1, Max: 1,
		PaymentActions: []decision.PaymentAction{{ID: id, Cast: cast, BaseOptionIndex: &base, Plans: []decision.PaymentPlan{plan}}}}
}

func TestPaymentWitnessUsesPublicIncarnations(t *testing.T) {
	d := paymentFixture(t)
	native := decision.ClonePaymentAction(d.PaymentActions[0])
	r := rekeyer(func(id state.ObjID) state.ObjID { return id + 100 })
	translations, err := r.payments(&d, []int{1, 2, 0})
	if err != nil {
		t.Fatal(err)
	}
	a := d.PaymentActions[0]
	p := a.Plans[0]
	if a.Cast.Object != 107 || *a.BaseOptionIndex != 0 || p.Activations[0].Source != 109 || p.Activations[0].SourceZoneSeq != 0 {
		t.Fatalf("native identity or counter survived: %+v", a)
	}
	if a.ID == native.ID || p.ID == native.Plans[0].ID {
		t.Fatal("native witness digest survived")
	}
	in := decision.Intent{Seq: d.Seq, Player: d.Player, Payment: &decision.PaymentSelection{ActionID: a.ID, Plan: p}}
	if err := d.Validate(in); err != nil {
		t.Fatalf("reissued witness invalid: %v", err)
	}
	if translations[native.ID+"/"+native.Plans[0].ID].ActionID != a.ID {
		t.Fatal("original witness is not bound to its public witness")
	}
}

func TestHiddenPaymentSourceIsRejected(t *testing.T) {
	d := paymentFixture(t)
	r := rekeyer(func(id state.ObjID) state.ObjID {
		if id == 9 {
			return 0
		}
		return id + 100
	})
	if _, err := r.payments(&d, []int{0, 1, 2}); err == nil {
		t.Fatal("hidden source became a usable payment")
	}
}
