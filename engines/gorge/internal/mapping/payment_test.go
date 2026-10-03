package mapping_test

import (
	"testing"

	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/rules"
	"github.com/adams-shaun/gorge/state"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/mapping"
)

func TestSpellbombWindowIsOneManaPaymentDecision(t *testing.T) {
	for _, mode := range []struct {
		name    string
		autoPay bool
	}{{"manual", false}, {"cast_witnesses", true}} {
		t.Run(mode.name, func(t *testing.T) {
			g := untilPending(t, "Wildfire", 1, func(d *decision.Decision, e *rules.Engine) bool {
				k := map[string]bool{}
				for _, o := range d.Options {
					k[o.Kind] = true
				}
				return d.Kind == decision.KChoose && k["activate"] && k["done"]
			})
			env := envFor(t, g)
			env.AutoPay = mode.autoPay
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
		})
	}
}

func TestUnlessPayPreservesNativeManaWindowChoices(t *testing.T) {
	g := untilPending(t, "CawGates", 1, func(d *decision.Decision, e *rules.Engine) bool {
		if d.Kind != decision.KModes || d.ResumeKind != "unless_pay" {
			return false
		}
		for _, option := range d.Options {
			if option.Mode == decision.ModeUnlessPay {
				return true
			}
		}
		return false
	})
	d := g.E.Pending()
	// Put the already-offered native payment's resources on its real lands
	// instead of in the floating pool, so this fixture exercises the window.
	g.E.G.Players[d.Player].Pool = state.Mana{}
	g.E.G.Players[d.Player].Snow = state.Mana{}
	for _, id := range g.E.G.Zone(state.ZBattlefield, d.Player) {
		g.E.G.Obj(id).Tapped = false
	}
	env := envFor(t, g)
	tx, _ := mapping.Begin(env, d)
	p, _ := tx.Pose()
	if len(p.Candidates) != len(d.Options) {
		t.Fatalf("native unless choices were omitted: %d offered, %d native", len(p.Candidates), len(d.Options))
	}
	windowsChecked := 0
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
				windowsChecked++
				if mapping.Route(n) != "choose/mana_window" {
					t.Fatalf("elected payment cannot enter its native mana window: %+v", n)
				}
				g.E = cl
				seenCompletion := false
				for step := 0; step < 16; step++ {
					n = g.E.Pending()
					if n == nil || mapping.Route(n) != "choose/mana_window" {
						break
					}
					env = envFor(t, g)
					env.Action = &mapping.ActionContext{Seat: d.Player, Obj: d.Source}
					window, err := mapping.Begin(env, n)
					if err != nil {
						t.Fatal(err)
					}
					pose, err := window.Pose()
					if err != nil {
						t.Fatal(err)
					}
					pick := -1
					decline := false
					for i, candidate := range pose.Candidates {
						if candidate.Sem.Kind == "optional_cost" && candidate.Sem.Fields["pay"] == false {
							decline = true
						}
						if pick < 0 && candidate.Sem.Kind == "activate_mana_ability" {
							pick = i
						}
					}
					if len(n.Options) == 1 {
						if len(pose.Candidates) != 1 || pose.Candidates[0].Sem.Kind != "finish_selection" ||
							pose.Context.Purpose == nil || *pose.Context.Purpose != "other" {
							t.Fatalf("Done-only window invents an election: %+v", pose)
						}
						pick = 0
						seenCompletion = true
					} else if !decline {
						t.Fatal("unfunded window omits its native Done/decline choice")
					}
					if pick < 0 {
						t.Fatal("window exposes neither a source nor completion")
					}
					commits, done, err := window.Answer(pick)
					if err != nil || !done || len(commits) == 0 || commits[0].Choices[0] != pose.Candidates[pick].Op.Option {
						t.Fatalf("native payment operation changed: %v %v %v", commits, done, err)
					}
					cl = g.E.Clone()
					for _, in := range commits {
						if in.Seq == 0 {
							in.Seq, in.Player = cl.Pending().Seq, cl.Pending().Player
						}
						if err := cl.SubmitHypothetical(in); err != nil {
							t.Fatal(err)
						}
					}
					g.E = cl
				}
				if !seenCompletion {
					t.Fatal("funding the native payment never reached its Done-only completion")
				}
			}
		}
	}
	if windowsChecked == 0 {
		t.Fatal("native fixture did not exercise the elected payment window")
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
