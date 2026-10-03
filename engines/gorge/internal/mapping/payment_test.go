package mapping_test

import (
	"testing"

	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/rules"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/mapping"
)

func TestSpellbombWindowIsOneManaPaymentDecision(t *testing.T) {
	g := untilPending(t, "Wildfire", 1, func(d *decision.Decision, e *rules.Engine) bool {
		k := map[string]bool{}
		for _, o := range d.Options {
			k[o.Kind] = true
		}
		return d.Kind == decision.KChoose && k["activate"] && k["done"]
	})
	env := envFor(t, g)
	tx, err := mapping.Begin(env, g.E.Pending())
	if err != nil {
		t.Fatal(err)
	}
	p, err := tx.Pose()
	if err != nil {
		t.Fatal(err)
	}
	if p.Context.Purpose == nil || *p.Context.Purpose != "mana_payment" {
		t.Fatalf("purpose %v", p.Context.Purpose)
	}
	kinds := map[string]int{}
	decline := -1
	for i, c := range p.Candidates {
		kinds[c.Sem.Kind]++
		if c.Sem.Kind == "optional_cost" && c.Sem.Fields["pay"] == false {
			decline = i
		}
	}
	if kinds["activate_mana_ability"] == 0 || decline < 0 {
		t.Fatalf("kinds %v decline %d", kinds, decline)
	}
	commit, done, err := tx.Answer(decline)
	if err != nil || !done || len(commit) != 2 {
		t.Fatalf("decline commits done then decline: %v %v %v", commit, done, err)
	}
}

func TestUnlessPayIsOfferedOnlyWhenThePoolCovers(t *testing.T) {
	g := untilPending(t, "CawGates", 1, func(d *decision.Decision, e *rules.Engine) bool {
		return d.Kind == decision.KModes && d.ResumeKind == "unless_pay"
	})
	env := envFor(t, g)
	d := g.E.Pending()
	tx, _ := mapping.Begin(env, d)
	p, _ := tx.Pose()
	for _, c := range p.Candidates {
		if c.Sem.Kind != "optional_cost" {
			t.Fatalf("kind %s", c.Sem.Kind)
		}
		if c.Sem.Fields["pay"] == true {
			commit := []decision.Intent{mapping.Intent(d, c.Op.Option)}
			cl, err := g.Probe(commit...)
			if err != nil {
				t.Fatal(err)
			}
			if n := cl.Pending(); n != nil && n.ResumeKind == "unless_mana" && n.Player == d.Player {
				t.Fatal("pay:true offered but paying opens a mana window")
			}
		}
	}
}

func TestHybridPipIsAnsweredInternally(t *testing.T) {
	d := &decision.Decision{Kind: decision.KChoose, Min: 1, Max: 1, Options: []decision.Option{{Index: 0, Kind: "pay_R"}, {Index: 1, Kind: "pay_G"}}}
	in, ok, err := mapping.Internal(nil, d)
	if !ok || err != nil || len(in.Choices) != 1 || in.Choices[0] != 0 {
		t.Fatalf("internal answer %v %v %v", in, ok, err)
	}
	if _, ok, _ := mapping.Internal(nil, &decision.Decision{Kind: decision.KPriority}); ok {
		t.Fatal("priority answered internally")
	}
}
