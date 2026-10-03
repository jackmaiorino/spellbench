package strategies

import (
	"context"
	"encoding/json"
	"reflect"
	"strings"
	"testing"

	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/internal/searchprobe"
	"github.com/adams-shaun/gorge/seat"
	"github.com/adams-shaun/gorge/view"
)

// A real planned cast answers priority with Payment rather than Choices.
// The actor's replay must preserve that cast and its public payment sources.
func TestPublicSamplerReplaysActorsAtomicCast(t *testing.T) {
	e, setup := fixture(t, 17, true)
	driver := NewDriver()
	bots := [2]*seat.Bot{seat.NewBot(3), seat.NewBot(7)}
	bots[0].EnableAutoPayMana()
	paid := false
	var original *decision.PaymentSelection
	for n := 0; n < 160 && !e.G.Over; n++ {
		d := e.Pending()
		driver.Observe(e)
		if paid && d.Player == 0 {
			h := canonicalJSONHistory(t, PublicHistory(driver.seats[0].h))
			paymentFrame := -1
			var payment Action
			for index, actions := range h.Answers {
				for _, action := range actions {
					if action.SpellbenchPayment != "" {
						paymentFrame, payment = index, action
					}
				}
			}
			if paymentFrame < 0 || original == nil {
				t.Fatal("atomic cast did not retain a semantic payment answer")
			}
			if strings.Contains(payment.SpellbenchPayment, original.ActionID) || strings.Contains(payment.SpellbenchPayment, original.Plan.ID) {
				t.Fatal("native payment digest entered public history")
			}
			var publicPlan decision.PaymentPlan
			if err := json.Unmarshal([]byte(payment.SpellbenchPayment), &publicPlan); err != nil {
				t.Fatal(err)
			}
			if publicPlan.ID != "" || len(publicPlan.Activations) != len(original.Plan.Activations) {
				t.Fatal("payment witness was not preserved and redacted")
			}
			for i, activation := range publicPlan.Activations {
				if activation.SourceZoneSeq != 0 || uint32(activation.Source) != driver.Alias(0, original.Plan.Activations[i].Source) {
					t.Fatal("payment source is not an observer-local incarnation")
				}
			}
			result, err := searchprobe.Sample(setup, h, searchprobe.SampleOptions{Seed: 54321, Attempts: 64, Worlds: 8, MaxSubmits: 5000})
			if err != nil || result.Accepted == 0 || len(result.Worlds) != 8 {
				t.Fatalf("actor's atomic cast was lost in public replay: %v accepted=%d worlds=%d first_rejection=%s", err, result.Accepted, len(result.Worlds), result.FirstRejection)
			}
			// A different mana residue is not the observed cast. Matching must
			// reject it rather than substitute a freshly planned payment.
			publicPlan.PoolAfter[0]++
			changed, _ := json.Marshal(publicPlan)
			payment.SpellbenchPayment = string(changed)
			h.Answers[paymentFrame] = []Action{payment}
			bad, err := searchprobe.Sample(setup, h, searchprobe.SampleOptions{Seed: 54321, Attempts: 16, Worlds: 1, MaxSubmits: 5000})
			if err != nil || bad.Accepted != 0 || len(bad.Worlds) != 0 {
				t.Fatal("changed payment witness accepted as the observed answer")
			}
			t.Logf("atomic actor cast accepted=%d worlds=%d; changed witness accepted=%d", result.Accepted, len(result.Worlds), bad.Accepted)
			return
		}
		in, err := bots[d.Player].Decide(context.Background(), view.Project(e.G, e, d.Player, d), *d)
		if err != nil {
			t.Fatal(err)
		}
		before := decision.ClonePaymentSelection(in.Payment)
		if err := driver.RecordAnswer(d, in); err != nil {
			t.Fatal(err)
		}
		if !reflect.DeepEqual(before, in.Payment) {
			t.Fatal("recording history changed the native payment selection")
		}
		if d.Player == 0 && in.Payment != nil && len(in.Payment.Plan.Activations) > 0 {
			original = before
		}
		if err := e.SubmitHypothetical(in); err != nil {
			t.Fatal(err)
		}
		paid = paid || d.Player == 0 && in.Payment != nil && len(in.Payment.Plan.Activations) > 0
	}
	t.Fatal("fixture did not perform a planned cast using battlefield mana")
}

func TestPublicRedealReplaysOpponentsAtomicCast(t *testing.T) {
	e, setup := fixture(t, 17, true)
	driver := NewDriver()
	bots := [2]*seat.Bot{seat.NewBot(3), seat.NewBot(7)}
	bots[1].EnableAutoPayMana()
	paid := false
	for n := 0; n < 160 && !e.G.Over; n++ {
		d := e.Pending()
		driver.Observe(e)
		if paid && d.Player == 0 {
			h := canonicalJSONHistory(t, PublicHistory(driver.seats[0].h))
			opts := searchprobe.SampleOptions{Seed: 54321, Attempts: 64, Worlds: 8, MaxSubmits: 5000}
			plain, err := searchprobe.Sample(setup, h, opts)
			if err != nil || plain.Accepted != 0 || len(plain.Worlds) != 0 {
				t.Fatal("fixture did not distinguish atomic opponent casts from native manual policy")
			}
			opts.Redeal = &searchprobe.RedealBase{SpellbenchPublic: true}
			result, err := searchprobe.Sample(setup, h, opts)
			if err != nil || result.Redealt != 8 || len(result.Worlds) != 8 || result.RedealRefused != "" || result.PublicReconstruction == nil || result.PublicReconstruction.BudgetExhausted != 0 {
				t.Fatalf("opponent's legal atomic cast was omitted from reconstruction: %v worlds=%d refused=%s work=%+v", err, len(result.Worlds), result.RedealRefused, result.PublicReconstruction)
			}
			for _, actions := range h.Answers {
				for _, action := range actions {
					if action.SpellbenchPayment != "" {
						t.Fatal("opponent's private payment answer entered actor history")
					}
				}
			}
			t.Logf("atomic opponent cast native accepted=%d redealt=%d reconstruction=%+v", result.Accepted, result.Redealt, result.PublicReconstruction)
			return
		}
		in, err := bots[d.Player].Decide(context.Background(), view.Project(e.G, e, d.Player, d), *d)
		if err != nil {
			t.Fatal(err)
		}
		if err := driver.RecordAnswer(d, in); err != nil {
			t.Fatal(err)
		}
		if err := e.SubmitHypothetical(in); err != nil {
			t.Fatal(err)
		}
		paid = paid || d.Player == 1 && in.Payment != nil && len(in.Payment.Plan.Activations) > 0
	}
	t.Fatal("fixture did not perform an opponent planned cast")
}
