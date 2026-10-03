package mapping

import (
	"encoding/json"
	"slices"

	"github.com/adams-shaun/gorge/decision"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
)

// PickSpec describes a Min..Max pick over native options, posed one pick per
// decision: a fixed group when Min == Max, else one group per decision with a
// finish candidate once Min is met (Section 7.5).
type PickSpec struct {
	D       *decision.Decision
	Options []int // native option indices, presentation order
	Sem     func(opt int, selected uint32) (Cand, error)
	Finish  func(selected uint32) protocol.Semantic // required when Min < Max
	Context protocol.Context
	Known   []protocol.Known
	Look    bool
}

type pickTx struct {
	env    *Env
	s      PickSpec
	chosen []int
	pose   *Pose
	memo   map[string]bool
}

func NewPick(env *Env, s PickSpec) Transaction {
	return &pickTx{env: env, s: s, memo: map[string]bool{}}
}

// allOptions lists every native option index in offered order.
func allOptions(d *decision.Decision) []int {
	out := make([]int, len(d.Options))
	for i := range out {
		out[i] = i
	}
	return out
}

func (t *pickTx) fixed() bool { return t.s.D.Min == t.s.D.Max }

func key(xs []int) string { b, _ := json.Marshal(xs); return string(b) }

func (t *pickTx) accepts(choices []int) bool {
	k := key(choices)
	if v, ok := t.memo[k]; ok {
		return v
	}
	v := Accepts(t.env, Intent(t.s.D, choices...))
	t.memo[k] = v
	return v
}

// completable: some answer extending prefix is accepted (depth-first, bounded).
func (t *pickTx) completable(prefix []int, budget *int) bool {
	d := t.s.D
	if len(prefix) >= d.Min && t.accepts(prefix) {
		return true
	}
	if len(prefix) >= d.Max || *budget <= 0 {
		return false
	}
	for _, o := range t.s.Options {
		if !d.Repeatable && slices.Contains(prefix, o) {
			continue
		}
		*budget--
		if t.completable(append(slices.Clone(prefix), o), budget) {
			return true
		}
	}
	return false
}

func (t *pickTx) Pose() (*Pose, error) {
	d := t.s.D
	p := &Pose{Seat: d.Player, Context: t.s.Context, Known: t.s.Known, Look: t.s.Look, Native: d}
	if t.fixed() {
		p.GroupStart, p.SubstepIndex, p.SubstepCount = len(t.chosen) == 0, uint32(len(t.chosen)), uint32(d.Max)
	} else {
		p.GroupStart, p.SubstepCount = true, 1
	}
	for _, o := range t.s.Options {
		if !d.Repeatable && slices.Contains(t.chosen, o) {
			continue
		}
		budget := 64
		if !t.completable(append(slices.Clone(t.chosen), o), &budget) {
			continue
		}
		c, err := t.s.Sem(o, uint32(len(t.chosen)))
		if err != nil {
			return nil, err
		}
		c.Op = NativeOp{Op: "choose", Option: o}
		p.Candidates = append(p.Candidates, c)
	}
	if !t.fixed() && len(t.chosen) >= d.Min && t.accepts(t.chosen) {
		p.Candidates = append(p.Candidates, Cand{Sem: t.s.Finish(uint32(len(t.chosen))), Op: NativeOp{Op: "finish", Option: -1}})
	}
	if err := Finalize(p); err != nil {
		return nil, err
	}
	t.pose = p
	return p, nil
}

func (t *pickTx) Answer(i int) ([]decision.Intent, bool, error) {
	op := t.pose.Candidates[i].Op
	if op.Op == "finish" {
		return []decision.Intent{Intent(t.s.D, t.chosen...)}, true, nil
	}
	t.chosen = append(t.chosen, op.Option)
	if len(t.chosen) == t.s.D.Max {
		return []decision.Intent{Intent(t.s.D, t.chosen...)}, true, nil
	}
	return nil, false, nil
}
