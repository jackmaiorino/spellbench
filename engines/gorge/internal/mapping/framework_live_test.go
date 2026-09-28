package mapping_test

// Live-engine tests for the Task 13 framework pieces later tasks consume:
// Accepts (oracle.go), SingleChoice (single.go), ResolveSource and MustSource
// (source.go), NewPick (pick.go). Each one is driven through a real game
// (envFor/untilPending), so its answers are checked against the engine itself.

import (
	"errors"
	"reflect"
	"testing"

	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/rules"
	"github.com/adams-shaun/gorge/state"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/gamecfg"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/mapping"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
)

// manaColourAsk drives a live Wildfire game to the colour ask of an
// activated Drossforge Bridge and returns the game, the KChoose "mana"
// decision and the bridge's object id.
func manaColourAsk(t *testing.T) (*gamecfg.Game, *decision.Decision, state.ObjID) {
	t.Helper()
	g := untilPending(t, "Wildfire", 1, func(d *decision.Decision, e *rules.Engine) bool {
		if d.Kind != decision.KPriority {
			return false
		}
		for _, o := range d.Options {
			if o.Kind == "activate" && e.G.Obj(o.Obj).Face().Name == "Drossforge Bridge" {
				return true
			}
		}
		return false
	})
	d := g.E.Pending()
	for _, o := range d.Options {
		if o.Kind == "activate" && g.E.G.Obj(o.Obj).Face().Name == "Drossforge Bridge" {
			if err := g.Submit(mapping.Intent(d, o.Index)); err != nil {
				t.Fatal(err)
			}
			ask := g.E.Pending()
			if ask == nil || ask.Kind != decision.KChoose || len(ask.Options) < 2 {
				t.Fatalf("the activation did not pose a colour ask: %+v", ask)
			}
			for _, co := range ask.Options {
				if co.Kind != "mana" || co.ManaSymbol == "" {
					t.Fatalf("colour ask option %+v", co)
				}
			}
			return g, ask, o.Obj
		}
	}
	t.Fatal("no activate option for the bridge")
	return nil, nil, 0
}

// Accepts judges an intent sequence on a clone: the empty sequence and a
// legal choice pass; out-of-range choices, too many choices, a stale seq and
// the other seat fail; the live game never moves.
func TestAcceptsJudgesIntentsOnAClone(t *testing.T) {
	g, ask, _ := manaColourAsk(t)
	env := envFor(t, g)
	if !mapping.Accepts(env) {
		t.Fatal("the empty sequence is not accepted")
	}
	if !mapping.Accepts(env, mapping.Intent(ask, 0)) {
		t.Fatal("a legal choice is not accepted")
	}
	bad := []decision.Intent{
		mapping.Intent(ask, len(ask.Options)),
		mapping.Intent(ask, 0, 0),
		{Seq: ask.Seq + 1, Player: ask.Player, Choices: []int{0}},
		{Seq: ask.Seq, Player: 1 - ask.Player, Choices: []int{0}},
	}
	for _, in := range bad {
		if mapping.Accepts(env, in) {
			t.Errorf("accepted %+v", in)
		}
	}
	if mapping.Accepts(env, mapping.Intent(ask, 0), mapping.Intent(ask, 0)) {
		t.Error("the second intent's seq is stale after the first resolves the ask")
	}
	if g.E.Pending() != ask {
		t.Fatal("Accepts moved the live game")
	}
}

// SingleChoice poses one candidate per native option its sem keeps (ok false
// drops the rest), and an answer commits the candidate's own native option,
// which the live game then accepts.
func TestSingleChoiceKeepsDropsAndCommits(t *testing.T) {
	g, ask, _ := manaColourAsk(t)
	env := envFor(t, g)
	dropped := ask.Options[0].Index
	tx, err := mapping.SingleChoice(env, ask, protocol.Context{Kind: "choice"}, func(o decision.Option) (protocol.Semantic, bool, error) {
		if o.Index == dropped {
			return protocol.Semantic{}, false, nil
		}
		return protocol.ChooseNumber(nil, "other", int32(o.Index), 0, int32(len(ask.Options))), true, nil
	})
	if err != nil {
		t.Fatal(err)
	}
	p, err := tx.Pose()
	if err != nil {
		t.Fatal(err)
	}
	if p.Seat != ask.Player || !p.GroupStart || p.SubstepIndex != 0 || p.SubstepCount != 1 || p.Native != ask {
		t.Fatalf("pose seat %d, group start %v, substep %d of %d", p.Seat, p.GroupStart, p.SubstepIndex, p.SubstepCount)
	}
	if len(p.Candidates) != len(ask.Options)-1 {
		t.Fatalf("%d candidates for %d options (one dropped)", len(p.Candidates), len(ask.Options))
	}
	for i, c := range p.Candidates {
		if c.Op.Op != "choose" || c.Op.Option == dropped || c.Sem.Fields["value"] != int32(c.Op.Option) {
			t.Fatalf("candidate %d %s %s", i, semJSON(c.Sem), semJSON(c.Op))
		}
	}
	want := ask.Options[1].ManaSymbol
	before := g.E.G.Players[ask.Player].Pool
	commit, done, err := tx.Answer(0)
	if err != nil || !done || !reflect.DeepEqual(commit, []decision.Intent{mapping.Intent(ask, 1)}) {
		t.Fatalf("commit %v, done %v, err %v; want option 1", commit, done, err)
	}
	if err := g.Submit(commit[0]); err != nil {
		t.Fatal(err)
	}
	after := g.E.G.Players[ask.Player].Pool
	if after == before {
		t.Fatalf("answering %s added no mana", want)
	}
}

// ResolveSource on a colour ask: a mana ability never uses the stack, so the
// source resolves to the permanent's current visible incarnation.
func TestResolveSourceFindsTheVisibleIncarnation(t *testing.T) {
	g, ask, bridge := manaColourAsk(t)
	env := envFor(t, g)
	want, err := env.Obs.Ref(ask.Player, bridge)
	if err != nil || want == nil {
		t.Fatal(want, err)
	}
	got, err := mapping.ResolveSource(env, ask)
	if err != nil || !reflect.DeepEqual(got, want) {
		t.Fatalf("ResolveSource %v, %v; want %v", got, err, want)
	}
	must, err := mapping.MustSource(env, ask)
	if err != nil || !reflect.DeepEqual(must, *want) {
		t.Fatalf("MustSource %v, %v; want %v", must, err, *want)
	}
}

// stackAbilityOf finds the topmost stack entry that is an ability of the
// object id (a triggered or activated ability on the stack, not a spell).
func stackAbilityOf(e *rules.Engine, id state.ObjID) (state.ObjID, bool) {
	for i := len(e.G.Stack) - 1; i >= 0; i-- {
		if so := e.G.Obj(e.G.Stack[i]); so != nil && so.Ability != nil && so.Source == id {
			return e.G.Stack[i], true
		}
	}
	return 0, false
}

func onStack(e *rules.Engine, id state.ObjID) bool {
	for _, s := range e.G.Stack {
		if s == id {
			return true
		}
	}
	return false
}

func onBattlefield(e *rules.Engine, id state.ObjID) bool {
	for _, z := range e.G.Zone(state.ZBattlefield, 0) {
		if z == id {
			return true
		}
	}
	for _, z := range e.G.Zone(state.ZBattlefield, 1) {
		if z == id {
			return true
		}
	}
	return false
}

// The ask of a trigger on the stack (Nihil Spellbomb's "you may pay {B}")
// names the card, now in the graveyard: ResolveSource returns the topmost
// stack entry of its ability, not the card.
func TestResolveSourcePrefersTheTopmostStackEntry(t *testing.T) {
	var entry state.ObjID
	g := untilPending(t, "Wildfire", 1, func(d *decision.Decision, e *rules.Engine) bool {
		if d.Kind != decision.KTriggerOptional || d.Source == 0 {
			return false
		}
		id, ok := stackAbilityOf(e, d.Source)
		if !ok {
			return false
		}
		entry = id
		return true
	})
	d := g.E.Pending()
	env := envFor(t, g)
	want, err := env.Obs.Ref(d.Player, entry)
	if err != nil || want == nil {
		t.Fatal(want, err)
	}
	card, err := env.Obs.Ref(d.Player, d.Source)
	if err != nil {
		t.Fatal(err)
	}
	got, err := mapping.ResolveSource(env, d)
	if err != nil || !reflect.DeepEqual(got, want) {
		t.Fatalf("ResolveSource %v, %v; want the stack entry %v", got, err, want)
	}
	if card != nil && reflect.DeepEqual(got, card) {
		t.Fatalf("ResolveSource returned the card %v, not its ability's stack entry", card)
	}
}

// While the seat is announcing a new action from a permanent, an earlier
// activation of it still on the stack is not this action's source: the skip
// keyed on Action.Since falls through to the permanent. Without the action
// context the same ask resolves to the stack entry.
func TestResolveSourceSkipsAnEarlierActivationWhileAnnouncing(t *testing.T) {
	var entry state.ObjID
	g := untilPending(t, "Wildfire", 1, func(d *decision.Decision, e *rules.Engine) bool {
		if d.Kind != decision.KChoose || d.Source == 0 || !onBattlefield(e, d.Source) {
			return false
		}
		id, ok := stackAbilityOf(e, d.Source)
		if !ok {
			return false
		}
		entry = id
		return true
	})
	d := g.E.Pending()
	env := envFor(t, g)
	stackRef, err := env.Obs.Ref(d.Player, entry)
	if err != nil || stackRef == nil {
		t.Fatal(stackRef, err)
	}
	permRef, err := env.Obs.Ref(d.Player, d.Source)
	if err != nil || permRef == nil {
		t.Fatal(permRef, err)
	}
	env.Action = &mapping.ActionContext{Seat: d.Player, Obj: d.Source, Since: entry + 1}
	got, err := mapping.ResolveSource(env, d)
	if err != nil || !reflect.DeepEqual(got, permRef) {
		t.Fatalf("announcing: ResolveSource %v, %v; want the permanent %v", got, err, permRef)
	}
	env.Action = nil
	got, err = mapping.ResolveSource(env, d)
	if err != nil || !reflect.DeepEqual(got, stackRef) {
		t.Fatalf("no action: ResolveSource %v, %v; want the stack entry %v", got, err, stackRef)
	}
	env.Action = &mapping.ActionContext{Seat: d.Player, Obj: d.Source + 4000, Since: entry + 1}
	got, err = mapping.ResolveSource(env, d)
	if err != nil || !reflect.DeepEqual(got, stackRef) {
		t.Fatalf("another action's object: ResolveSource %v, %v; want the stack entry %v", got, err, stackRef)
	}
}

// When Decision.Source is itself the ability's stack entry (Journey to
// Nowhere's enters-the-battlefield trigger), ResolveSource returns it.
func TestResolveSourceSeesTheStackEntryItself(t *testing.T) {
	g := untilPending(t, "CawGates", 1, func(d *decision.Decision, e *rules.Engine) bool {
		if d.Kind != decision.KTarget || d.Source == 0 || !onStack(e, d.Source) {
			return false
		}
		if so := e.G.Obj(d.Source); so != nil && so.Ability != nil {
			return true
		}
		return false
	})
	d := g.E.Pending()
	env := envFor(t, g)
	want, err := env.Obs.Ref(d.Player, d.Source)
	if err != nil || want == nil {
		t.Fatal(want, err)
	}
	got, err := mapping.ResolveSource(env, d)
	if err != nil || !reflect.DeepEqual(got, want) {
		t.Fatalf("ResolveSource %v, %v; want the stack entry %v", got, err, want)
	}
}

// With no Decision.Source the source is the acting seat's priority action
// object; with neither it is nil, and MustSource fails closed.
func TestResolveSourceFallsBackToTheActionThenNil(t *testing.T) {
	g, ask, _ := manaColourAsk(t)
	env := envFor(t, g)
	hand := g.E.G.Zone(state.ZHand, ask.Player)
	if len(hand) == 0 {
		t.Fatal("the acting seat holds no card")
	}
	d := &decision.Decision{Kind: decision.KChoose, Player: ask.Player}
	env.Action = &mapping.ActionContext{Seat: ask.Player, Obj: hand[0]}
	want, err := env.Obs.Ref(ask.Player, hand[0])
	if err != nil || want == nil {
		t.Fatal(want, err)
	}
	got, err := mapping.ResolveSource(env, d)
	if err != nil || !reflect.DeepEqual(got, want) {
		t.Fatalf("ResolveSource %v, %v; want the action object %v", got, err, want)
	}
	env.Action = nil
	got, err = mapping.ResolveSource(env, d)
	if got != nil || err != nil {
		t.Fatalf("ResolveSource %v, %v; want nil, nil", got, err)
	}
	if _, err := mapping.MustSource(env, d); !errors.Is(err, mapping.ErrUnresolvableSource) {
		t.Fatalf("MustSource %v, want %v", err, mapping.ErrUnresolvableSource)
	}
}

// chooseNumberSem is a pick sem: one distinct choose_number per option.
func chooseNumberSem(opt int, _ uint32) (mapping.Cand, error) {
	return mapping.Cand{Sem: protocol.ChooseNumber(nil, "other", int32(opt), 0, 64)}, nil
}

// A fixed pick (Min == Max) poses one pick per decision as one group, drops
// picks already made, and commits every pick in order; the commit is legal
// for the live game.
func TestPickFixedGroupCommitsEveryPickInOrder(t *testing.T) {
	g := untilPending(t, "Burn", 1, func(d *decision.Decision, e *rules.Engine) bool {
		return d.Kind == decision.KChoose && d.Min == 2 && d.Max == 2 && !d.Repeatable && len(d.Options) >= 3
	})
	d := g.E.Pending()
	env := envFor(t, g)
	tx := mapping.NewPick(env, mapping.PickSpec{
		D:       d,
		Options: []int{0, 1, 2},
		Sem:     chooseNumberSem,
		Context: protocol.Context{Kind: "choice"},
	})
	p, err := tx.Pose()
	if err != nil {
		t.Fatal(err)
	}
	if p.Seat != d.Player || !p.GroupStart || p.SubstepIndex != 0 || p.SubstepCount != 2 {
		t.Fatalf("first pick: seat %d, group start %v, substep %d of %d", p.Seat, p.GroupStart, p.SubstepIndex, p.SubstepCount)
	}
	if len(p.Candidates) != 3 {
		t.Fatalf("%d candidates, want 3", len(p.Candidates))
	}
	if commit, done, err := tx.Answer(2); err != nil || done || commit != nil {
		t.Fatalf("first pick: commit %v, done %v, err %v", commit, done, err)
	}
	p, err = tx.Pose()
	if err != nil {
		t.Fatal(err)
	}
	if p.GroupStart || p.SubstepIndex != 1 || p.SubstepCount != 2 {
		t.Fatalf("second pick: group start %v, substep %d of %d", p.GroupStart, p.SubstepIndex, p.SubstepCount)
	}
	if len(p.Candidates) != 2 {
		t.Fatalf("%d candidates, want 2 (the first pick is spent)", len(p.Candidates))
	}
	for _, c := range p.Candidates {
		if c.Op.Option == 2 {
			t.Fatalf("option 2 was picked already: %s", semJSON(c.Op))
		}
	}
	commit, done, err := tx.Answer(1)
	if err != nil || !done || !reflect.DeepEqual(commit, []decision.Intent{mapping.Intent(d, 2, 1)}) {
		t.Fatalf("commit %v, done %v, err %v; want picks 2 then 1", commit, done, err)
	}
	if err := g.Submit(commit[0]); err != nil {
		t.Fatalf("the live game refused the commit: %v", err)
	}
}

// digAsk drives a live Spy game to a dig ask (Lead the Stampede: Min 0,
// one option per creature among the top cards) and returns it.
func digAsk(t *testing.T) (*gamecfg.Game, *decision.Decision) {
	t.Helper()
	g := untilPending(t, "Spy", 1, func(d *decision.Decision, e *rules.Engine) bool {
		return d.Kind == decision.KChoose && d.Min == 0 && d.Max >= 2 && !d.Repeatable &&
			len(d.Options) >= 3 && d.Options[0].Kind == "dig"
	})
	return g, g.E.Pending()
}

// A variable pick (Min < Max) poses one group per decision and offers finish
// once Min is met, never before; finish commits the picks made. Options the
// engine cannot accept in any completion are not offered. The live dig ask
// (Min 0, Max >= 2) is the legality oracle: it accepts any 0..2 in-range
// choices, so a synthetic Min 1, Max 2 pick over it completes with one or
// two picks.
func TestPickVariableGroupOffersFinishOnceMinIsMet(t *testing.T) {
	g, live := digAsk(t)
	env := envFor(t, g)
	d := &decision.Decision{Kind: decision.KChoose, Seq: live.Seq, Player: live.Player, Min: 1, Max: 2,
		Options: append([]decision.Option{}, live.Options...)}
	tx := mapping.NewPick(env, mapping.PickSpec{
		D:       d,
		Options: []int{0, 1, 7}, // 7 is outside the live ask: never completable
		Sem:     chooseNumberSem,
		Context: protocol.Context{Kind: "choice"},
		Finish:  func(n uint32) protocol.Semantic { return protocol.FinishSelection(nil, "other", n) },
	})
	p, err := tx.Pose()
	if err != nil {
		t.Fatal(err)
	}
	if !p.GroupStart || p.SubstepCount != 1 {
		t.Fatalf("a variable pick is one group per decision: group start %v, substeps %d", p.GroupStart, p.SubstepCount)
	}
	if len(p.Candidates) != 2 { // option 7 is not offered, and finish waits for Min
		t.Fatalf("%d candidates, want 2: %s", len(p.Candidates), semJSON(p.Candidates))
	}
	for _, c := range p.Candidates {
		if c.Sem.Kind == "finish_selection" {
			t.Fatalf("finish is offered before Min is met: %s", semJSON(p.Candidates))
		}
	}
	if commit, done, err := tx.Answer(0); err != nil || done || commit != nil {
		t.Fatalf("first pick: commit %v, done %v, err %v", commit, done, err)
	}
	p, err = tx.Pose()
	if err != nil {
		t.Fatal(err)
	}
	if len(p.Candidates) != 2 || p.Candidates[0].Op.Option != 1 || p.Candidates[1].Sem.Kind != "finish_selection" {
		t.Fatalf("after one pick: %s", semJSON(p.Candidates))
	}
	commit, done, err := tx.Answer(1) // finish
	if err != nil || !done || !reflect.DeepEqual(commit, []decision.Intent{mapping.Intent(d, 0)}) {
		t.Fatalf("finish commits %v, done %v, err %v; want pick 0", commit, done, err)
	}
	if err := g.Submit(commit[0]); err != nil {
		t.Fatalf("the live game refused the commit: %v", err)
	}
}

// A real dig ask (Min 0) offers finish from the first decision, alongside
// every option; picking an option and finishing commits the pick, which the
// live game accepts.
func TestPickVariableGroupStartsWithFinish(t *testing.T) {
	g, d := digAsk(t)
	env := envFor(t, g)
	tx := mapping.NewPick(env, mapping.PickSpec{
		D:       d,
		Options: allOf(d),
		Sem:     chooseNumberSem,
		Context: protocol.Context{Kind: "choice"},
		Finish:  func(n uint32) protocol.Semantic { return protocol.FinishSelection(nil, "other", n) },
	})
	p, err := tx.Pose()
	if err != nil {
		t.Fatal(err)
	}
	fin := -1
	for i, c := range p.Candidates {
		if c.Sem.Kind == "finish_selection" {
			fin = i
			continue
		}
		if c.Op.Op != "choose" {
			t.Fatalf("candidate %d %s", i, semJSON(c.Op))
		}
	}
	if fin < 0 || len(p.Candidates) != len(d.Options)+1 {
		t.Fatalf("first pose %s", semJSON(p.Candidates))
	}
	pick := (fin + 1) % len(p.Candidates)
	opt := p.Candidates[pick].Op.Option
	if commit, done, err := tx.Answer(pick); err != nil || done || commit != nil {
		t.Fatalf("pick: commit %v, done %v, err %v", commit, done, err)
	}
	p, err = tx.Pose()
	if err != nil {
		t.Fatal(err)
	}
	fin = -1
	for i, c := range p.Candidates {
		if c.Sem.Kind == "finish_selection" {
			fin = i
		}
		if c.Op.Option == opt && c.Op.Op == "choose" {
			t.Fatalf("option %d was picked already: %s", opt, semJSON(c.Op))
		}
	}
	if fin < 0 || len(p.Candidates) != len(d.Options) {
		t.Fatalf("second pose %s", semJSON(p.Candidates))
	}
	commit, done, err := tx.Answer(fin)
	if err != nil || !done || !reflect.DeepEqual(commit, []decision.Intent{mapping.Intent(d, opt)}) {
		t.Fatalf("finish commits %v, done %v, err %v; want pick %d", commit, done, err, opt)
	}
	if err := g.Submit(commit[0]); err != nil {
		t.Fatalf("the live game refused the commit: %v", err)
	}
}

// allOf lists every option index of d.
func allOf(d *decision.Decision) []int {
	out := make([]int, len(d.Options))
	for i := range out {
		out[i] = i
	}
	return out
}
