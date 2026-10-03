package mapping

import (
	"encoding/json"
	"fmt"
	"slices"

	"github.com/adams-shaun/gorge/decision"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
)

func init() {
	Register("trigger_order", newTriggerOrder)
	Register("mulligan/bottom", newMulliganBottom)
	Register("hand_move/library", newHandToLibrary)
}

// orderTx places `count` native options one position per decision.
type orderTx struct {
	env     *Env
	d       *decision.Decision
	purpose string
	items   map[int]protocol.OrderItem
	pool    []int // candidate native options
	count   int
	implied bool // the last position is implied (items offered == items placed)
	placed  []int
	pose    *Pose
	prefix  []decision.Intent // intents committed before the ordered one (hand_move select)
	build   func(order []int) decision.Intent
	size    uint32
}

func (t *orderTx) Pose() (*Pose, error) {
	pos := len(t.placed)
	p := &Pose{Seat: t.d.Player, Context: protocol.Context{Kind: "choice", Purpose: &t.purpose}, Native: t.d,
		GroupStart: pos == 0, SubstepIndex: uint32(pos), SubstepCount: t.size}
	for _, o := range t.pool {
		if slices.Contains(t.placed, o) {
			continue
		}
		p.Candidates = append(p.Candidates, Cand{Sem: protocol.OrderPick(nil, t.purpose, t.items[o], uint32(pos), uint32(t.count)),
			Op: NativeOp{Op: "list", Option: o, List: "choices", Position: pos}})
	}
	if err := Finalize(p); err != nil {
		return nil, err
	}
	t.pose = p
	return p, nil
}

func (t *orderTx) Answer(i int) ([]decision.Intent, bool, error) {
	t.placed = append(t.placed, t.pose.Candidates[i].Op.Option)
	if t.implied && len(t.placed) == t.count-1 {
		for _, o := range t.pool {
			if !slices.Contains(t.placed, o) {
				t.placed = append(t.placed, o)
			}
		}
	}
	if len(t.placed) < t.count {
		return nil, false, nil
	}
	return append(t.prefix, t.build(t.placed)), true, nil
}

func newTriggerOrder(env *Env, d *decision.Decision) (Transaction, error) {
	t := &orderTx{env: env, d: d, purpose: "triggers", items: map[int]protocol.OrderItem{}, count: len(d.Options), implied: true,
		size: uint32(len(d.Options) - 1)}
	instances := map[string]uint32{}
	for _, o := range d.Options {
		src, err := env.Obs.Ref(d.Player, o.Obj)
		if err != nil {
			return nil, err
		}
		var name *string
		if src != nil {
			name = src.CardName
		}
		// instance numbers the triggers whose visible fields are equal (two
		// triggers of hidden sources both read source and name null), so
		// the key is those fields, never the native object.
		item := protocol.TriggerItem{Source: src, SourceName: name, EventObjects: []protocol.ObjectRef{}}
		b, _ := json.Marshal(item)
		item.Instance = instances[string(b)]
		instances[string(b)]++
		t.items[o.Index] = protocol.OrderItem{Trigger: &item}
		t.pool = append(t.pool, o.Index)
	}
	t.build = func(order []int) decision.Intent { return Intent(d, order...) }
	return t, nil
}

func newMulliganBottom(env *Env, d *decision.Decision) (Transaction, error) {
	t := &orderTx{env: env, d: d, purpose: "mulligan_bottom", items: map[int]protocol.OrderItem{}, count: d.Max, size: uint32(d.Max)}
	for _, o := range d.Options {
		r, err := env.Obs.Ref(d.Player, o.Obj)
		if err != nil || r == nil {
			return nil, fmt.Errorf("%w: mulligan card not visible", ErrUnmapped)
		}
		t.items[o.Index] = protocol.ObjectItem(*r)
		t.pool = append(t.pool, o.Index)
	}
	t.build = func(order []int) decision.Intent { return Intent(d, order...) }
	return t, nil
}

// handToLibrary: Brainstorm. A fixed select_object group picks the cards, then
// an order_pick library_top group places them (last position implied).
type handToLibrary struct {
	sel   Transaction
	order *orderTx
	d     *decision.Decision
	env   *Env
}

func newHandToLibrary(env *Env, d *decision.Decision) (Transaction, error) {
	h := &handToLibrary{d: d, env: env}
	src, err := ResolveSource(env, d)
	if err != nil {
		return nil, err
	}
	purp := "other"
	lo, hi := uint32(d.Min), uint32(d.Max)
	// Selecting runs on a private decision copy so the pick does not commit.
	h.sel = NewPick(env, PickSpec{D: d, Options: allOptions(d), Context: protocol.Context{Kind: "choice", Source: src, Purpose: &purp},
		Sem: func(opt int, sel uint32) (Cand, error) {
			r, err := env.Obs.Ref(d.Player, d.Options[opt].Obj)
			if err != nil || r == nil {
				return Cand{}, fmt.Errorf("%w: hand card not visible", ErrUnmapped)
			}
			return Cand{Sem: protocol.SelectObject(src, purp, protocol.ObjectTarget(*r), sel, lo, hi)}, nil
		},
		Finish: func(sel uint32) protocol.Semantic { return protocol.FinishSelection(src, purp, sel) }})
	return h, nil
}

func (h *handToLibrary) Pose() (*Pose, error) {
	if h.order != nil {
		return h.order.Pose()
	}
	return h.sel.Pose()
}

func (h *handToLibrary) Answer(i int) ([]decision.Intent, bool, error) {
	if h.order != nil {
		return h.order.Answer(i)
	}
	commit, done, err := h.sel.Answer(i)
	if err != nil || !done {
		return nil, false, err
	}
	chosen := commit[0].Choices
	if len(chosen) < 2 {
		return commit, true, nil
	}
	o := &orderTx{env: h.env, d: h.d, purpose: "library_top", items: map[int]protocol.OrderItem{}, count: len(chosen),
		implied: true, size: uint32(len(chosen) - 1), pool: chosen}
	for _, c := range chosen {
		r, _ := h.env.Obs.Ref(h.d.Player, h.d.Options[c].Obj)
		o.items[c] = protocol.ObjectItem(*r)
	}
	o.build = func(order []int) decision.Intent { return Intent(h.d, order...) }
	h.order = o
	return nil, false, nil
}
