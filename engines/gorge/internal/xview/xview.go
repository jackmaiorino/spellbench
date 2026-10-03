// Package xview builds x_gorge_view_v1: gorge's own seat view and native
// decision for gorge-native bots, re-keyed to per-seat non-native ids.
package xview

import (
	"encoding/json"
	"fmt"
	"maps"
	"slices"
	"sort"
	"strconv"
	"strings"

	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/state"
	"github.com/adams-shaun/gorge/view"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/mapping"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/observe"
)

type OptionFacts struct {
	Attach     bool            `json:"attach"`
	Grant      *decision.Grant `json:"grant"`
	Controller uint8           `json:"controller"`
	SetProps   []string        `json:"set_props"`
	BlockMust  bool            `json:"block_must"`
	AttackMust bool            `json:"attack_must"`
}

// ProducesFacts restores a card view's server-side mana production flags
// (cards.ManaProduction's Indeterminate and Reflected are json "-"), which
// gorge's bot reads when it taps mana.
type ProducesFacts struct {
	Card          state.ObjID `json:"card"`
	Indeterminate bool        `json:"indeterminate"`
	Reflected     bool        `json:"reflected"`
}

type Facts struct {
	Options                   []OptionFacts   `json:"options"`
	Produces                  []ProducesFacts `json:"produces"`
	EffectOptional            bool            `json:"effect_optional"`
	CopyOfCopy                bool            `json:"copy_of_copy"`
	AffordableTargets         int             `json:"affordable_targets"`
	TargetsWithSameController bool            `json:"targets_with_same_controller"`
	SetPropMode               string          `json:"set_prop_mode"`
	ResumeKind                string          `json:"resume_kind"`
	ResumeAPI                 string          `json:"resume_api"`
	ResumeUnlessCost          string          `json:"resume_unless_cost"`
}

type Payload struct {
	Version     int                          `json:"version"`
	NativeIndex uint64                       `json:"native_index"`
	View        view.View                    `json:"view"`
	Decision    decision.Decision            `json:"decision"`
	Facts       Facts                        `json:"policy_facts"`
	Followups   map[string]decision.Decision `json:"followups"`
	Ops         []mapping.NativeOp           `json:"ops"`
}

type table struct {
	ints map[string]uint32
	next uint32
}

// Follow is one folded follow-up of a seat's last payload: its payload key
// and its native -> payload option renumbering.
type Follow struct {
	Key  string
	Perm []int
}

type Extender struct {
	lastPayments [2]map[string]decision.PaymentSelection
	tables       [2]*table
	last         [2][]int             // the seat's last native -> payload renumbering (audit only, Task 28a)
	lastFollow   [2]map[string]Follow // the same for its follow-ups, by native key (audit only, Task 28a)
}

func New() *Extender {
	return &Extender{tables: [2]*table{{ints: map[string]uint32{}}, {ints: map[string]uint32{}}}}
}

// rekey maps gorge object ids to the seat's small integers. Only objects the
// seat sees, or the hidden cards this pose's own look shows (its native and
// follow-up options), get one. Every other reference (a card in a hidden zone,
// an absent object, 0) becomes 0, the payload's analogue of v2's null
// (Sections 5.1 and 5.3).
func (x *Extender) rekey(env *mapping.Env, seat state.PlayerID, shown map[state.ObjID]bool) (rekeyer, *error) {
	var firstErr error
	t := x.tables[seat]
	return func(id state.ObjID) state.ObjID {
		o := env.G.E.G.Obj(id)
		var v2 string
		var err error
		switch {
		case o == nil:
			return 0
		case observe.Visible(seat, o) || o.Zone == state.ZCeased:
			v2, err = env.IDs.VisibleID(seat, id)
		case shown[id]:
			v2, err = env.IDs.LookID(seat, id)
		default:
			return 0
		}
		if err != nil {
			if firstErr == nil {
				firstErr = err
			}
			return 0
		}
		n, ok := t.ints[v2]
		if !ok {
			t.next++
			n, t.ints[v2] = t.next, t.next
		}
		return state.ObjID(n)
	}, &firstErr
}

// shownBy lists the objects the pose's native decision and folded follow-ups
// offer: the only hidden-zone cards the payload may name.
func shownBy(p *mapping.Pose) map[state.ObjID]bool {
	shown := map[state.ObjID]bool{}
	for _, d := range append([]*decision.Decision{p.Native}, slices.Collect(maps.Values(p.Followups))...) {
		for _, o := range d.Options {
			shown[o.Obj] = true
		}
	}
	return shown
}

// relabelGroups replaces each option's Group with an opaque label in
// first-appearance order (g0, g1, ...), keeping equal groups equal, and
// renames GroupLimits keys the same way. gorge writes native object ids into
// group names ("blocker:65", "payment:12").
func relabelGroups(d *decision.Decision) {
	labels := map[string]string{}
	label := func(g string) string {
		if g == "" {
			return ""
		}
		l, ok := labels[g]
		if !ok {
			l = "g" + strconv.Itoa(len(labels))
			labels[g] = l
		}
		return l
	}
	for i := range d.Options {
		d.Options[i].Group = label(d.Options[i].Group)
	}
	if d.GroupLimits != nil {
		m := make(map[string]int, len(d.GroupLimits))
		for _, g := range slices.Sorted(maps.Keys(d.GroupLimits)) {
			m[label(g)] = d.GroupLimits[g]
		}
		d.GroupLimits = m
	}
}

// dropSourceless drops the pending triggers whose source rekeyed to 0: a
// hidden, absent or zero source, as the observation omits them (Section 6.6).
func dropSourceless(v *view.View) {
	kept := v.Pending[:0]
	for _, pv := range v.Pending {
		if pv.Source != 0 {
			kept = append(kept, pv)
		}
	}
	v.Pending = kept
}

// produces collects the mana production flags of every card in the view.
func produces(v *view.View) []ProducesFacts {
	var out []ProducesFacts
	add := func(cvs []view.CardView) {
		for _, cv := range cvs {
			if pr := cv.Produces; pr != nil && (pr.Indeterminate || pr.Reflected) {
				out = append(out, ProducesFacts{Card: cv.ID, Indeterminate: pr.Indeterminate, Reflected: pr.Reflected})
			}
		}
	}
	for _, p := range v.Players {
		for _, z := range [][]view.CardView{p.Hand, p.Battlefield, p.Graveyard, p.Exile, p.Command, p.Commanders} {
			add(z)
		}
	}
	return out
}

func facts(d *decision.Decision) Facts {
	f := Facts{EffectOptional: d.EffectOptional, CopyOfCopy: d.CopyOfCopy, AffordableTargets: d.AffordableTargets,
		TargetsWithSameController: d.TargetsWithSameController, SetPropMode: string(d.SetPropMode), ResumeKind: d.ResumeKind}
	if d.ResumeSA != nil {
		f.ResumeAPI, f.ResumeUnlessCost = d.ResumeSA.API, d.ResumeSA.Params["UnlessCost"]
	}
	for _, o := range d.Options {
		f.Options = append(f.Options, OptionFacts{Attach: o.Attach, Grant: o.Grant, Controller: uint8(o.Controller),
			SetProps: o.SetProps, BlockMust: o.BlockMust, AttackMust: o.AttackMust})
	}
	return f
}

// sortHidden reorders the options of d that reference hidden-zone cards by
// (card name, look id), renumbers every option, and returns old -> new
// (perm) and new -> old (order).
func sortHidden(env *mapping.Env, seat state.PlayerID, d *decision.Decision) (perm, order []int) {
	g := env.G.E.G
	perm, order = make([]int, len(d.Options)), make([]int, len(d.Options))
	var hid []int
	for i, o := range d.Options {
		order[i], perm[i] = i, i
		if obj := g.Obj(o.Obj); obj != nil && !observe.Visible(seat, obj) {
			hid = append(hid, i)
		}
	}
	key := func(i int) string {
		id, _ := env.IDs.LookID(seat, d.Options[i].Obj)
		return g.Obj(d.Options[i].Obj).Face().Name + "\x00" + id
	}
	sorted := append([]int(nil), hid...)
	sort.SliceStable(sorted, func(a, b int) bool { return key(sorted[a]) < key(sorted[b]) })
	for k, slot := range hid {
		order[slot] = sorted[k]
	}
	opts := make([]decision.Option, len(d.Options))
	for newIdx, old := range order {
		opts[newIdx] = d.Options[old]
		opts[newIdx].Index = newIdx
		perm[old] = newIdx
	}
	d.Options = opts
	return perm, order
}

func at(perm []int, i int) int {
	if i >= 0 && i < len(perm) {
		return perm[i]
	}
	return i
}

// followKey translates a follow-up key. "<option>" and "<option>/<follow-up
// option>" name native indices, which sortHidden renumbers; named keys
// ("dig_bottom") stay.
func followKey(k string, perm []int, fperm map[string][]int) string {
	a, b, two := strings.Cut(k, "/")
	i, err := strconv.Atoi(a)
	if err != nil {
		return k
	}
	out := strconv.Itoa(at(perm, i))
	if two {
		j, err := strconv.Atoi(b)
		if err != nil {
			return k
		}
		out += "/" + strconv.Itoa(at(fperm[a], j))
	}
	return out
}

func (x *Extender) Extend(env *mapping.Env, p *mapping.Pose, nativeIndex uint64) (map[string]json.RawMessage, error) {
	e := env.G.E
	seat := p.Seat
	r, errp := x.rekey(env, seat, shownBy(p))
	v := view.Project(e.G, e, seat, nil)
	v.Round = view.RoundOf(e.G, e.L.Events)
	r.view(&v)
	dropSourceless(&v)
	d := p.Native.CloneValue()
	pl := Payload{Version: 1, NativeIndex: nativeIndex, Facts: facts(&d), Followups: map[string]decision.Decision{}}
	pl.Facts.Produces = produces(&v)
	perm, order := sortHidden(env, seat, &d)
	x.last[seat] = perm
	if f := pl.Facts.Options; len(f) == len(order) {
		nf := make([]OptionFacts, len(f))
		for newIdx, old := range order {
			nf[newIdx] = f[old]
		}
		pl.Facts.Options = nf
	}
	paymentActions := d.PaymentActions
	r.decision(&d, nativeIndex)
	if env.AutoPay {
		d.PaymentActions = paymentActions
	}
	payments, err := r.payments(&d, perm)
	if err != nil {
		return nil, err
	}
	x.lastPayments[seat] = payments
	relabelGroups(&d)
	pl.Decision = d
	// Follow-ups are sorted the same way; their keys and every op that points
	// into them are translated with their own permutations. Keys are visited
	// in sorted order, so ids are numbered the same way on every rerun.
	fperm := map[string][]int{}
	follows := map[string]Follow{}
	for _, k := range slices.Sorted(maps.Keys(p.Followups)) {
		c := p.Followups[k].CloneValue()
		fperm[k], _ = sortHidden(env, seat, &c)
		r.decision(&c, nativeIndex)
		relabelGroups(&c)
		key := followKey(k, perm, fperm)
		pl.Followups[key] = c
		follows[k] = Follow{Key: key, Perm: fperm[k]}
	}
	x.lastFollow[seat] = follows
	for _, c := range p.Candidates {
		op := c.Op
		if op.Payment != nil {
			public, ok := payments[paymentKey(op.Payment)]
			if !ok {
				return nil, fmt.Errorf("candidate payment is not exposed")
			}
			op.Payment = decision.ClonePaymentSelection(&public)
		}
		// The pose may be posed again (a retransmission): never rewrite its slices.
		op.Covers = append([]int(nil), op.Covers...)
		op.Followup = append([]int(nil), op.Followup...)
		if key, ok := strings.CutPrefix(op.List, "followup:"); ok {
			op.Option = at(fperm[key], op.Option)
		} else {
			op.Option = at(perm, op.Option)
		}
		if len(op.Followup) > 0 {
			k0 := strconv.Itoa(c.Op.Option)
			op.Followup[0] = at(fperm[k0], c.Op.Followup[0])
			if len(op.Followup) > 1 {
				op.Followup[1] = at(fperm[k0+"/"+strconv.Itoa(c.Op.Followup[0])], c.Op.Followup[1])
			}
		}
		for i, cv := range op.Covers {
			op.Covers[i] = at(perm, cv)
		}
		if op.Unit != 0 {
			op.Unit = r(op.Unit)
		}
		pl.Ops = append(pl.Ops, op)
	}
	pl.View = v
	if *errp != nil {
		return nil, *errp
	}
	raw, err := json.Marshal(pl)
	if err != nil {
		return nil, err
	}
	return map[string]json.RawMessage{"x_gorge_view_v1": raw}, nil
}
