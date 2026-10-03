package mapping

import (
	"fmt"
	"strings"

	"github.com/adams-shaun/gorge/decision"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
)

func init() {
	Register("modes/unless", newUnless)
	Register("choose/mana_window", newManaWindow)
	Register("choose/trigger_cost", newTriggerCost)
	RegisterInternal("choose/pay_pip", payPip)
}

// payPip allocates floating mana to a hybrid pip with gorge's first offered
// option: v2.0 has no kind for it (pay_mana is reserved), so this is the
// engine's payment procedure, recorded in the engine notes (controller
// decision 3).
func payPip(_ *Env, d *decision.Decision) (decision.Intent, error) {
	return Intent(d, d.Options[0].Index), nil
}

func unlessCost(d *decision.Decision) string {
	if d.ResumeSA == nil {
		return "other"
	}
	switch api := d.ResumeSA.API; {
	case api == "Counter":
		return "unless_payment"
	case strings.Contains(api, "Copy"):
		return "copy"
	}
	return "other"
}

func newUnless(env *Env, d *decision.Decision) (Transaction, error) {
	src, err := MustSource(env, d)
	if err != nil {
		return nil, err
	}
	cost := unlessCost(d)
	return SingleChoice(env, d, choice(&src, ""), func(o decision.Option) (protocol.Semantic, bool, error) {
		pay := o.Mode == decision.ModeUnlessPay
		return protocol.OptionalCost(src, cost, pay), true, nil
	})
}

func newTriggerCost(env *Env, d *decision.Decision) (Transaction, error) {
	src, err := MustSource(env, d)
	if err != nil {
		return nil, err
	}
	return SingleChoice(env, d, choice(&src, ""), func(o decision.Option) (protocol.Semantic, bool, error) {
		return protocol.OptionalCost(src, "other", o.Kind == "trigger_cost_pay"), true, nil
	})
}

type windowTx struct {
	d    *decision.Decision
	pose *Pose
}

func (w *windowTx) Pose() (*Pose, error) { return w.pose, nil }

func (w *windowTx) Answer(i int) ([]decision.Intent, bool, error) {
	op := w.pose.Candidates[i].Op
	ins := []decision.Intent{Intent(w.d, op.Option)}
	for _, f := range op.Followup {
		ins = append(ins, decision.Intent{Choices: []int{f}})
	}
	return ins, true, nil
}

func newManaWindow(env *Env, d *decision.Decision) (Transaction, error) {
	src, err := MustSource(env, d)
	if err != nil {
		return nil, err
	}
	done := -1
	for _, o := range d.Options {
		if o.Kind == "done" {
			done = o.Index
		}
	}
	c, err := env.G.Probe(Intent(d, done))
	if err != nil {
		return nil, err
	}
	ask := c.Pending()
	purp := "mana_payment"
	// The done ask is keyed by done's option index, like every folded
	// follow-up, so the agent finds it from the op alone.
	p := &Pose{Seat: d.Player, Context: protocol.Context{Kind: "choice", Source: &src, Purpose: &purp},
		GroupStart: true, SubstepCount: 1, Native: d, Followups: map[string]*decision.Decision{}}
	if ask != nil && ask.Player == d.Player && Route(ask) == "choose/trigger_cost" {
		p.Followups[fmt.Sprint(done)] = ask
		for _, ao := range ask.Options {
			pay := ao.Kind == "trigger_cost_pay"
			p.Candidates = append(p.Candidates, Cand{Sem: protocol.OptionalCost(src, "other", pay),
				Op: NativeOp{Op: "choose", Option: done, Followup: []int{ao.Index}}})
		}
	} else {
		// Cast, activation and elected unless/ward windows settle on Done.
		// Their next pending decision belongs to the resumed game, so do not
		// fold it into this payment. The successful probe preserves native
		// legality, including a payer who has already elected to pay.
		if ask == nil && !c.G.Over {
			return nil, fmt.Errorf("%w:mana_window_no_continuation", ErrUnmapped)
		}
		p.Candidates = append(p.Candidates, Cand{Sem: protocol.OptionalCost(src, unlessCost(d), true),
			Op: NativeOp{Op: "choose", Option: done}})
	}
	for _, o := range d.Options {
		if o.Kind != "activate" {
			continue
		}
		s, err := env.Obs.Ref(d.Player, o.Obj)
		if err != nil || s == nil {
			return nil, fmt.Errorf("%w: mana source not visible", ErrUnmapped)
		}
		cs, folds, err := ExpandActivate(env, d, o, *s)
		if err != nil {
			return nil, err
		}
		p.Candidates = append(p.Candidates, cs...)
		for k, v := range folds {
			p.Followups[k] = v
		}
	}
	if err := Finalize(p); err != nil {
		return nil, err
	}
	return &windowTx{d: d, pose: p}, nil
}
