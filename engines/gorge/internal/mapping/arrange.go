package mapping

import (
	"fmt"
	"slices"
	"strconv"
	"strings"

	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/rules"
	"github.com/adams-shaun/gorge/state"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/observe"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
)

var destOrder = []string{"top", "bottom", "graveyard", "exile", "hand", "battlefield", "pile_0", "pile_1"}

func init() {
	for _, k := range []string{"bottom", "graveyard", "exile", "hand"} {
		Register("arrange/"+k, newScryLike)
	}
	Register("arrange/dig_bottom", newDigBottom)
	Register("choose/dig", newDig)
	Register("choose/explore", newExplore)
}

// arrangeTx is Section 7.5's arrangement: n arrange_card decisions (top card
// first), then n-1 order_pick decisions placing destination by destination.
//
// Native ops, which the Go agent reads through x_gorge_view_v1:
//   - a partition candidate is "dest": Option is the card's native option
//     index (-1 when it has none), List the destination, Position the card
//     index. "top" and "hand" are the destinations inside the native
//     Choices; every other destination is outside them.
//   - an ordering candidate is "list": List names the native answer list
//     ("choices", "rest" or "followup:<key>"), Option is the card's option
//     index in that decision, Position its place within the destination.
//     A lone dig remainder is the exception: gorge moves it without asking
//     dig_bottom, so its ordering pick carries a presentational "dest" op.
type arrangeTx struct {
	env      *Env
	d        *decision.Decision
	purpose  string
	src      *protocol.ObjectRef
	cards    []state.ObjID
	refs     []protocol.ObjectRef
	byID     map[string]int // look id -> card index
	native   []int          // the card's native option index, -1 for none
	dests    [][]string
	legal    func(i int, dst string, chosen []string) bool
	restOnly map[string]bool                  // destinations whose native order is fixed by the engine
	destOp   func(i int, dst string) NativeOp // optional override of the partition op
	listFor  func(i int, dst string) (list string, option int)
	orderOp  func(i int, dst string) (NativeOp, bool) // optional override of the ordering op
	prepare  func() error                             // optional, runs once before the first ordering pick
	prepared bool
	follow   map[string]*decision.Decision
	chosen   []string
	placed   []int
	known    []protocol.Known
	commit   func() ([]decision.Intent, error)
	pose     *Pose
}

func (t *arrangeTx) n() int { return len(t.cards) }

func cardName(r protocol.ObjectRef) string {
	if r.CardName == nil {
		return ""
	}
	return *r.CardName
}

// look opens the seat's look and mints the look ids and known entries, with
// each card's live distance from the top of the library.
func (t *arrangeTx) look(how string) error {
	t.env.OpenLook(t.d.Player)
	lib := t.env.G.E.G.Zone(state.ZLibrary, t.d.Player)
	t.byID = map[string]int{}
	for i, id := range t.cards {
		r, err := t.env.Obs.LookRef(t.d.Player, id)
		if err != nil {
			return err
		}
		at := slices.Index(lib, id)
		if at < 0 {
			return fmt.Errorf("%w: looked-at card %d is not in the library", ErrUnmapped, id)
		}
		t.refs = append(t.refs, r)
		t.byID[r.ObjectID] = i
		p := uint32(at)
		t.known = append(t.known, observe.KnownEntry(r, how, &p))
	}
	observe.SortKnown(t.known)
	return nil
}

func (t *arrangeTx) nativeOf(cards []int) []int {
	out := make([]int, 0, len(cards))
	for _, i := range cards {
		out = append(out, t.native[i])
	}
	return out
}

func (t *arrangeTx) currentDest() (string, []int) {
	for _, dst := range destOrder {
		var unplaced []int
		for i, c := range t.chosen {
			if c == dst && !slices.Contains(t.placed, i) {
				unplaced = append(unplaced, i)
			}
		}
		if len(unplaced) > 0 {
			return dst, unplaced
		}
	}
	return "", nil
}

// orderedFor lists the card indices sent to dst, in placement order.
func (t *arrangeTx) orderedFor(dst string) []int {
	var out []int
	for _, i := range t.placed {
		if t.chosen[i] == dst {
			out = append(out, i)
		}
	}
	return out
}

func (t *arrangeTx) Pose() (*Pose, error) {
	if t.n() == 0 {
		return nil, ErrDeadEnd
	}
	step := len(t.chosen) + len(t.placed)
	p := &Pose{Seat: t.d.Player, Context: protocol.Context{Kind: "choice", Source: t.src, Purpose: &t.purpose},
		GroupStart: step == 0, SubstepIndex: uint32(step), SubstepCount: uint32(2*t.n() - 1), Known: t.known, Look: true, Native: t.d}
	if len(t.chosen) < t.n() {
		i := len(t.chosen)
		for _, dst := range t.dests[i] {
			if !t.legal(i, dst, t.chosen) {
				continue
			}
			op := NativeOp{Op: "dest", Option: t.native[i], List: dst, Position: i}
			if t.destOp != nil {
				op = t.destOp(i, dst)
			}
			p.Candidates = append(p.Candidates, Cand{Sem: protocol.ArrangeCard(t.src, t.purpose, t.refs[i], uint32(i), uint32(t.n()), dst), Op: op})
		}
	} else {
		if t.prepare != nil && !t.prepared {
			if err := t.prepare(); err != nil {
				return nil, err
			}
			t.prepared = true
		}
		dst, unplaced := t.currentDest()
		if t.restOnly[dst] {
			unplaced = unplaced[:1] // the engine fixes this order: offered order, one candidate per pick
		}
		pos := len(t.orderedFor(dst))
		for _, i := range unplaced {
			list, idx := t.listFor(i, dst)
			op := NativeOp{Op: "list", Option: idx, List: list, Position: pos}
			if t.orderOp != nil {
				if o, ok := t.orderOp(i, dst); ok {
					op = o
				}
			}
			// The items are library cards: Finalize orders them by (card_name, object_id).
			p.Candidates = append(p.Candidates, Cand{
				Sem:    protocol.OrderPick(t.src, "arrangement", protocol.ObjectItem(t.refs[i]), uint32(len(t.placed)), uint32(t.n())),
				Op:     op,
				Hidden: true, SortName: cardName(t.refs[i]), SortID: t.refs[i].ObjectID})
		}
		p.Followups = t.follow
	}
	if err := Finalize(p); err != nil {
		return nil, err
	}
	t.pose = p
	return p, nil
}

func (t *arrangeTx) Answer(k int) ([]decision.Intent, bool, error) {
	c := t.pose.Candidates[k]
	if len(t.chosen) < t.n() {
		t.chosen = append(t.chosen, c.Sem.Fields["destination"].(string))
		if t.n() == 1 {
			t.placed = []int{0}
		}
	} else {
		t.placed = append(t.placed, t.byID[c.Sem.Fields["item"].(protocol.OrderItem).Object.ObjectID])
		if len(t.placed) == t.n()-1 { // only the final pick of the arrangement is implied
			_, last := t.currentDest()
			t.placed = append(t.placed, last...)
		}
	}
	if len(t.placed) < t.n() {
		return nil, false, nil
	}
	ins, err := t.commit()
	return ins, true, err
}

// newScryLike: gorge KArrange (Scry and Surveil). Options are the top N in
// library order; pile A (Choices) stays on top in answer order, pile B goes to
// the options' Kind destination, in Rest order when Restable.
func newScryLike(env *Env, d *decision.Decision) (Transaction, error) {
	src, err := ResolveSource(env, d)
	if err != nil {
		return nil, err
	}
	other := d.Options[0].Kind
	purp := map[string]string{"bottom": "scry", "graveyard": "surveil"}[other]
	switch {
	case d.Min == len(d.Options) && d.Max == len(d.Options):
		purp = "look_at_top" // a full rearrange (Ponder): pile B is always empty
	case purp == "":
		purp = "other"
	}
	t := &arrangeTx{env: env, d: d, purpose: purp, src: src, restOnly: map[string]bool{}}
	for _, o := range d.Options {
		t.cards = append(t.cards, o.Obj)
		t.native = append(t.native, o.Index)
		t.dests = append(t.dests, []string{"top", other})
	}
	if !d.Restable {
		t.restOnly[other] = true
	}
	if err := t.look("looked_at"); err != nil {
		return nil, err
	}
	t.legal = func(i int, dst string, chosen []string) bool {
		top := 0
		for _, c := range chosen {
			if c == "top" {
				top++
			}
		}
		rest := t.n() - i - 1
		if dst == "top" {
			return top+1 <= d.Max && top+1+rest >= d.Min
		}
		return top <= d.Max && top+rest >= d.Min
	}
	t.listFor = func(i int, dst string) (string, int) {
		if dst == "top" {
			return "choices", t.native[i]
		}
		return "rest", t.native[i]
	}
	t.commit = func() ([]decision.Intent, error) {
		in := Intent(d, t.nativeOf(t.orderedFor("top"))...)
		if d.Restable {
			in.Rest = t.nativeOf(t.orderedFor(other))
		}
		return []decision.Intent{in}, nil
	}
	return t, nil
}

// digBottom returns the dig_bottom ask pending on c for seat, if any.
func digBottom(c *rules.Engine, seat state.PlayerID) *decision.Decision {
	n := c.Pending()
	if n == nil || c.G.Over || n.Player != seat || n.Kind != decision.KArrange || len(n.Options) == 0 || n.Options[0].Kind != "dig_bottom" {
		return nil
	}
	return n
}

// newDig: gorge asks "dig" (which eligible cards go to the hand) and then,
// when two or more cards remain, "dig_bottom" (their order on the bottom).
// v2 sees one arrangement over the whole DigNum window. The dig_bottom ask is
// found by lookahead once the partition is known and carried as the
// follow-up "dig_bottom".
func newDig(env *Env, d *decision.Decision) (Transaction, error) {
	sa := d.ResumeSA
	if sa == nil {
		return nil, fmt.Errorf("%w:dig_shape", ErrUnmapped)
	}
	param := func(k string) string { return strings.TrimSpace(sa.Params[k]) }
	dest, dest2, pos2 := param("DestinationZone"), param("DestinationZone2"), param("LibraryPosition2")
	if dest == "" {
		dest = "Hand" // gorge's defaults (effects/cardflow.go)
	}
	if dest2 == "" {
		dest2, pos2 = "Library", "-1"
	}
	if !strings.EqualFold(dest, "Hand") || !strings.EqualFold(dest2, "Library") || pos2 != "-1" || d.MaxSum > 0 ||
		strings.EqualFold(param("SkipReorder"), "True") || strings.EqualFold(param("FromBottom"), "True") {
		return nil, fmt.Errorf("%w:dig_shape", ErrUnmapped)
	}
	n, err := strconv.Atoi(param("DigNum"))
	if err != nil || n <= 0 {
		return nil, fmt.Errorf("%w:dig_num", ErrUnmapped)
	}
	src, err := ResolveSource(env, d)
	if err != nil {
		return nil, err
	}
	lib := env.G.E.G.Zone(state.ZLibrary, d.Player)
	window := slices.Clone(lib[:min(n, len(lib))])
	eligible := map[state.ObjID]int{}
	for _, o := range d.Options {
		if o.Player != d.Player || !slices.Contains(window, o.Obj) {
			return nil, fmt.Errorf("%w:dig_option_outside_window", ErrUnmapped)
		}
		eligible[o.Obj] = o.Index
	}
	how := "looked_at"
	if strings.EqualFold(param("Reveal"), "True") {
		how = "revealed"
	}
	t := &arrangeTx{env: env, d: d, purpose: "dig", src: src, cards: window, restOnly: map[string]bool{}}
	for _, id := range window {
		if idx, ok := eligible[id]; ok {
			t.native = append(t.native, idx)
			t.dests = append(t.dests, []string{"hand", "bottom"})
		} else {
			t.native = append(t.native, -1)
			t.dests = append(t.dests, []string{"bottom"})
		}
	}
	if err := t.look(how); err != nil {
		return nil, err
	}
	eligibleAfter := func(i int) int {
		k := 0
		for _, idx := range t.native[i+1:] {
			if idx >= 0 {
				k++
			}
		}
		return k
	}
	t.legal = func(i int, dst string, chosen []string) bool {
		hand := 0
		for _, c := range chosen {
			if c == "hand" {
				hand++
			}
		}
		if dst == "hand" {
			return hand+1 <= d.Max
		}
		return hand+eligibleAfter(i) >= d.Min
	}
	sentTo := func(dst string) (cards []int) {
		for i, c := range t.chosen {
			if c == dst {
				cards = append(cards, i)
			}
		}
		return cards
	}
	followIdx := map[state.ObjID]int{}
	t.prepare = func() error {
		if len(sentTo("bottom")) < 2 {
			return nil // gorge moves a lone remainder without asking
		}
		c, err := env.G.Probe(Intent(d, t.nativeOf(sentTo("hand"))...))
		if err != nil {
			return err
		}
		nb := digBottom(c, d.Player)
		if nb == nil {
			return fmt.Errorf("%w:dig_bottom_missing", ErrUnmapped)
		}
		t.follow = map[string]*decision.Decision{"dig_bottom": nb}
		for _, o := range nb.Options {
			followIdx[o.Obj] = o.Index
		}
		return nil
	}
	t.listFor = func(i int, dst string) (string, int) {
		if dst == "hand" {
			return "choices", t.native[i]
		}
		return "followup:dig_bottom", followIdx[t.cards[i]]
	}
	t.orderOp = func(_ int, dst string) (NativeOp, bool) {
		if dst == "bottom" && len(sentTo("bottom")) == 1 {
			// gorge moves a lone remainder without asking dig_bottom: the
			// ordering pick carries the presentational dest op instead.
			return NativeOp{Op: "dest", Option: -1, List: "bottom"}, true
		}
		return NativeOp{}, false
	}
	t.commit = func() ([]decision.Intent, error) {
		dig := Intent(d, t.nativeOf(t.orderedFor("hand"))...)
		bottom := t.orderedFor("bottom")
		if len(bottom) < 2 {
			return []decision.Intent{dig}, nil
		}
		c, err := env.G.Probe(dig)
		if err != nil {
			return nil, err
		}
		nb := digBottom(c, d.Player)
		if nb == nil {
			return nil, fmt.Errorf("%w:dig_bottom_missing", ErrUnmapped)
		}
		at := map[state.ObjID]int{}
		for _, o := range nb.Options {
			at[o.Obj] = o.Index
		}
		order := make([]int, 0, len(bottom))
		for _, i := range bottom {
			idx, ok := at[t.cards[i]]
			if !ok {
				return nil, fmt.Errorf("%w:dig_bottom_card_missing", ErrUnmapped)
			}
			order = append(order, idx)
		}
		return []decision.Intent{dig, {Seq: nb.Seq, Player: nb.Player, Choices: order}}, nil
	}
	return t, nil
}

// newDigBottom: a dig_bottom ask with no take ask before it (gorge took the
// eligible cards silently, or none were eligible). Every offered card goes to
// the bottom, so each partition pick is forced and only the order is chosen.
func newDigBottom(env *Env, d *decision.Decision) (Transaction, error) {
	src, err := ResolveSource(env, d)
	if err != nil {
		return nil, err
	}
	t := &arrangeTx{env: env, d: d, purpose: "dig", src: src, restOnly: map[string]bool{}}
	for _, o := range d.Options {
		t.cards = append(t.cards, o.Obj)
		t.native = append(t.native, o.Index)
		t.dests = append(t.dests, []string{"bottom"})
	}
	if err := t.look("looked_at"); err != nil {
		return nil, err
	}
	t.legal = func(int, string, []string) bool { return true }
	t.destOp = func(i int, dst string) NativeOp { return NativeOp{Op: "dest", Option: -1, List: dst, Position: i} }
	t.listFor = func(i int, _ string) (string, int) { return "choices", t.native[i] }
	t.commit = func() ([]decision.Intent, error) {
		return []decision.Intent{Intent(d, t.nativeOf(t.orderedFor("bottom"))...)}, nil
	}
	return t, nil
}

// newExplore: "Put the revealed card back on top or into your graveyard?"
func newExplore(env *Env, d *decision.Decision) (Transaction, error) {
	src, err := ResolveSource(env, d)
	if err != nil {
		return nil, err
	}
	lib := env.G.E.G.Zone(state.ZLibrary, d.Player)
	if len(lib) == 0 {
		return nil, fmt.Errorf("%w:explore_empty_library", ErrUnmapped)
	}
	kindIdx := map[string]int{}
	var dests []string
	for _, o := range d.Options {
		kindIdx[o.Kind] = o.Index
	}
	for _, dst := range []string{"top", "graveyard"} {
		if _, ok := kindIdx[dst]; ok {
			dests = append(dests, dst)
		}
	}
	t := &arrangeTx{env: env, d: d, purpose: "other", src: src, cards: slices.Clone(lib[:1]), native: []int{-1},
		dests: [][]string{dests}, restOnly: map[string]bool{}}
	if err := t.look("revealed"); err != nil {
		return nil, err
	}
	t.legal = func(int, string, []string) bool { return true }
	t.destOp = func(_ int, dst string) NativeOp { return NativeOp{Op: "choose", Option: kindIdx[dst]} }
	t.commit = func() ([]decision.Intent, error) {
		return []decision.Intent{Intent(d, kindIdx[t.chosen[0]])}, nil
	}
	return t, nil
}
