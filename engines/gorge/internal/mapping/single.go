package mapping

import (
	"github.com/adams-shaun/gorge/decision"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
)

type singleTx struct {
	pose  *Pose
	d     *decision.Decision
	after func(opt int) // optional hook run on the chosen native option
}

func (s *singleTx) Pose() (*Pose, error) { return s.pose, nil }

func (s *singleTx) Answer(i int) ([]decision.Intent, bool, error) {
	op := s.pose.Candidates[i].Op
	if s.after != nil {
		s.after(op.Option)
	}
	return []decision.Intent{Intent(s.d, op.Option)}, true, nil
}

// SingleChoice maps each native option to at most one candidate (ok false drops it).
func SingleChoice(env *Env, d *decision.Decision, ctx protocol.Context, sem func(o decision.Option) (protocol.Semantic, bool, error)) (Transaction, error) {
	p := &Pose{Seat: d.Player, Context: ctx, GroupStart: true, SubstepCount: 1, Native: d}
	for _, o := range d.Options {
		s, ok, err := sem(o)
		if err != nil {
			return nil, err
		}
		if ok {
			p.Candidates = append(p.Candidates, Cand{Sem: s, Op: NativeOp{Op: "choose", Option: o.Index}})
		}
	}
	if err := Finalize(p); err != nil {
		return nil, err
	}
	return &singleTx{pose: p, d: d}, nil
}

func choice(src *protocol.ObjectRef, p string) protocol.Context {
	var pp *string
	if p != "" {
		pp = &p
	}
	return protocol.Context{Kind: "choice", Source: src, Purpose: pp}
}
