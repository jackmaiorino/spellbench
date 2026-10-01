package mapping_test

import (
	"testing"

	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/rules"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/mapping"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
)

func TestSimpleChoiceKinds(t *testing.T) {
	cases := []struct {
		deck, want string
		pred       func(*decision.Decision, *rules.Engine) bool
	}{
		{"Burn", "optional_cast", func(d *decision.Decision, e *rules.Engine) bool {
			return d.Kind == decision.KTriggerOptional && d.ResumeKind == "madness"
		}},
		{"Wildfire", "choose_boolean", func(d *decision.Decision, e *rules.Engine) bool {
			return d.Kind == decision.KTriggerOptional && d.ResumeKind == "optional"
		}},
		{"CawGates", "choose_color", func(d *decision.Decision, e *rules.Engine) bool {
			return d.Kind == decision.KChoose && len(d.Options) > 0 && d.Options[0].Kind == "color"
		}},
		{"Spy", "choose_name", func(d *decision.Decision, e *rules.Engine) bool {
			return d.Kind == decision.KChoose && len(d.Options) > 0 && d.Options[0].Kind == "type"
		}},
	}
	for _, c := range cases {
		g := untilPending(t, c.deck, 1, c.pred)
		env := envFor(t, g)
		tx, err := mapping.Begin(env, g.E.Pending())
		if err != nil {
			t.Fatalf("%s: %v", c.want, err)
		}
		p, err := tx.Pose()
		if err != nil || p.Candidates[0].Sem.Kind != c.want {
			t.Fatalf("%s: got %+v %v", c.want, p, err)
		}
		if err := p.Candidates[0].Sem.Check(); err != nil {
			t.Fatalf("%s: %v", c.want, err)
		}
		if c.want == "optional_cast" { // the card in exile, not the madness trigger on the stack
			if card := p.Candidates[0].Sem.Fields["card"].(protocol.ObjectRef); card.Zone != "exile" {
				t.Fatalf("madness card is in %s", card.Zone)
			}
		}
	}
}

func TestMulliganKeepCountsMulligans(t *testing.T) {
	g := untilPendingRules(t, "Burn", 1, "london", func(d *decision.Decision, e *rules.Engine) bool {
		return d.Kind == decision.KMulligan && d.Options[0].Kind != "bottom"
	})
	env := envFor(t, g)
	d := g.E.Pending()
	tx, _ := mapping.Begin(env, d)
	p, _ := tx.Pose()
	for i, c := range p.Candidates {
		if c.Sem.Fields["keep"] == false {
			tx.Answer(i)
		}
	}
	if env.Obs.Mulls[d.Player] != 1 {
		t.Fatalf("mulligans taken %d", env.Obs.Mulls[d.Player])
	}
}
