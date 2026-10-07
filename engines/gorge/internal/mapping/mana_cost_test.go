package mapping_test

// Live-engine tests for expandActivate's cost fold (mana.go's costKinds
// branch). No catalog deck reaches it: the one catalog card with a costed
// mana ability, Saruli Caretaker, has a tapXType cost the engine refuses at
// offer time. These games are built straight from the pinned registry around
// Phyrexian Altar ("Sacrifice a creature: Add one mana of any color") and
// Ashnod's Altar ("Sacrifice a creature: Add {C}{C}"): a sacrifice pick of
// Min == Max == 1 is posed whenever a second creature is on the battlefield.

import (
	"errors"
	"fmt"
	"slices"
	"strings"
	"testing"

	"github.com/adams-shaun/gorge/cards"
	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/rules"
	"github.com/adams-shaun/gorge/state"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/gamecfg"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/mapping"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/observe"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/secrets"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/testcorpus"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/testgame"
)

// altarDeck is Mountains, both altars and 0-drop creatures, so random bots
// flood the board and some seed reaches a seat holding an altar with two
// creatures to feed it.
func altarDeck(t *testing.T) []*cards.Card {
	t.Helper()
	reg := testcorpus.Registry(t)
	var deck []*cards.Card
	for _, row := range []struct {
		name  string
		count int
	}{
		{"Mountain", 20}, {"Phyrexian Altar", 4}, {"Ashnod's Altar", 4}, {"Memnite", 32},
	} {
		c, ok := reg.Lookup(row.name)
		if !ok {
			t.Fatalf("%s is not in the corpus", row.name)
		}
		for i := 0; i < row.count; i++ {
			deck = append(deck, c)
		}
	}
	return deck
}

// altarPosition drives a two-altar game (both seats play it) to a priority
// decision offering name's activation while that seat controls at least
// minCreatures creatures, so the sacrifice cost is a real pick (a single
// candidate is forced and never asked).
func altarPosition(t *testing.T, name string, minCreatures int) *gamecfg.Game {
	t.Helper()
	reg := testcorpus.Registry(t)
	deck := altarDeck(t)
	for s := byte(1); s < 21; s++ {
		var seed [32]byte
		seed[0] = s
		other := append([]*cards.Card(nil), deck...)
		g, err := gamecfg.New(reg, secrets.NewGame(seed[:]), [2][]*cards.Card{deck, other}, gamecfg.Rules{Mulligan: "none", StartingSeat: 0})
		if err != nil {
			t.Fatal(err)
		}
		if testgame.RunUntil(t, g, testgame.Bots(uint64(s)), func(e *rules.Engine) bool {
			d := e.Pending()
			if d == nil || d.Kind != decision.KPriority {
				return false
			}
			creatures := 0
			for _, id := range e.G.Zone(state.ZBattlefield, d.Player) {
				if e.IsCreature(id) {
					creatures++
				}
			}
			if creatures < minCreatures {
				return false
			}
			for _, o := range d.Options {
				if o.Kind == "activate" && e.G.Obj(o.Obj).Face().Name == name {
					return true
				}
			}
			return false
		}, 30000) {
			return g
		}
	}
	t.Fatalf("no altar game reached %s with %d creatures", name, minCreatures)
	return nil
}

// activateOption finds the pending priority decision's activate option on the
// named permanent.
func activateOption(t *testing.T, g *gamecfg.Game, name string) (decision.Option, state.ObjID) {
	t.Helper()
	d := g.E.Pending()
	for _, o := range d.Options {
		if o.Kind == "activate" && g.E.G.Obj(o.Obj).Face().Name == name {
			return o, o.Obj
		}
	}
	t.Fatalf("no activate option for %s in %+v", name, d)
	return decision.Option{}, 0
}

// sacrificeAsk probes the activation and returns the engine's follow-up: a
// Min == Max == 1 pick of a creature to sacrifice.
func sacrificeAsk(t *testing.T, g *gamecfg.Game, d *decision.Decision, opt int) *decision.Decision {
	t.Helper()
	c, err := g.Probe(mapping.Intent(d, opt))
	if err != nil {
		t.Fatal(err)
	}
	ask := c.Pending()
	if ask == nil || ask.Kind != decision.KChoose || ask.Min != 1 || ask.Max != 1 ||
		len(ask.Options) < 2 || ask.Options[0].Kind != "sacrifice" {
		t.Fatalf("the activation's follow-up is %+v, want a Min/Max 1 sacrifice pick", ask)
	}
	return ask
}

// replayCommit replays a folded commit into a fresh probe clone, the way the
// session would submit it, and returns the clone at the end.
func replayCommit(t *testing.T, g *gamecfg.Game, commit []decision.Intent) *rules.Engine {
	t.Helper()
	c, err := g.Probe(commit[0])
	if err != nil {
		t.Fatal(err)
	}
	for _, in := range commit[1:] {
		f := c.Pending()
		in.Seq, in.Player = f.Seq, f.Player
		if err := c.SubmitHypothetical(in); err != nil {
			t.Fatal(err)
		}
	}
	return c
}

// Phyrexian Altar's sacrifice cost poses a pick and, past it, a colour ask:
// the fold carries one candidate per (creature, colour), each naming its
// cost_target, and its three-intent commit replayed on a clone sacrifices the
// creature and adds the mana (Task 15 fix round: the cost fold's first live
// coverage).
func TestCostFoldExpandsPerCreatureAndColour(t *testing.T) {
	g := altarPosition(t, "Phyrexian Altar", 2)
	env := envFor(t, g)
	d := g.E.Pending()
	o, altar := activateOption(t, g, "Phyrexian Altar")
	ask := sacrificeAsk(t, g, d, o.Index)
	tx, err := mapping.Begin(env, d)
	if err != nil {
		t.Fatal(err)
	}
	p, err := tx.Pose()
	if err != nil {
		t.Fatal(err)
	}
	src, err := env.Obs.Ref(d.Player, altar)
	if err != nil || src == nil {
		t.Fatal(src, err)
	}
	got := map[string]int{} // "<cost_target>/<mana_choice>" -> candidate
	for i, c := range p.Candidates {
		if c.Sem.Kind != "activate_mana_ability" {
			continue
		}
		s := c.Sem.Fields["source"].(protocol.ObjectRef)
		if s.ObjectID != src.ObjectID {
			continue
		}
		mc, _ := c.Sem.Fields["mana_choice"].(*string)
		ct, _ := c.Sem.Fields["cost_target"].(*protocol.TargetRef)
		if mc == nil || ct == nil || ct.Object == nil {
			t.Fatalf("cost candidate without a mana choice or cost target: %+v", c.Sem)
		}
		if !slices.Contains(protocol.Vocab["mana_symbol"], *mc) {
			t.Fatalf("mana choice %q is outside the mana_symbol vocabulary", *mc)
		}
		if c.Sem.Fields["ability_index"] != uint32(0) {
			t.Fatalf("ability_index %v, want 0", c.Sem.Fields["ability_index"])
		}
		if c.Op.Op != "choose" || c.Op.Option != o.Index || len(c.Op.Followup) != 2 {
			t.Fatalf("cost candidate op %+v", c.Op)
		}
		got[ct.Object.ObjectID+"/"+*mc] = i
	}
	if len(got) != len(ask.Options)*5 {
		t.Fatalf("%d altar candidates for %d sacrifice options, want one per creature and colour", len(got), len(ask.Options))
	}
	// The follow-ups are recorded: the sacrifice pick under "<option>", and
	// past each pick its colour ask under "<option>/<pick>".
	key := fmt.Sprint(o.Index)
	fold, ok := p.Followups[key]
	if !ok || fold.Kind != decision.KChoose || fold.Options[0].Kind != "sacrifice" {
		t.Fatalf("follow-up %q is %+v", key, fold)
	}
	for _, co := range ask.Options {
		f2, ok := p.Followups[fmt.Sprint(key, "/", co.Index)]
		if !ok || f2.Kind != decision.KChoose || len(f2.Options) != 5 || f2.Options[0].Kind != "mana" {
			t.Fatalf("follow-up %q/%d is %+v", key, co.Index, f2)
		}
	}
	// Answer "sacrifice the first candidate creature, add green" and replay.
	pickRef, err := env.Obs.Ref(d.Player, ask.Options[0].Obj)
	if err != nil || pickRef == nil {
		t.Fatal(pickRef, err)
	}
	cand, ok := got[pickRef.ObjectID+"/G"]
	if !ok {
		t.Fatalf("candidates %v lack %s/G", got, pickRef.ObjectID)
	}
	commit, done, err := tx.Answer(cand)
	if err != nil || !done || len(commit) != 3 {
		t.Fatalf("commit %v done %v err %v", commit, done, err)
	}
	c := replayCommit(t, g, commit)
	before, after := g.E.G.Players[d.Player].Pool, c.G.Players[d.Player].Pool
	if after[state.MG] != before[state.MG]+1 {
		t.Fatalf("green mana %d, want %d", after[state.MG], before[state.MG]+1)
	}
	if z := c.G.Obj(ask.Options[0].Obj).Zone; z != state.ZGraveyard {
		t.Fatalf("the sacrificed creature is in %s, want graveyard", z)
	}
}

// Ashnod's Altar's ability asks its sacrifice but no colour (its production
// is fixed): one plain cost candidate per creature, mana_choice null, a
// two-intent commit.
func TestCostFoldWithoutColourAskIsOneCandidatePerCreature(t *testing.T) {
	g := altarPosition(t, "Ashnod's Altar", 2)
	env := envFor(t, g)
	d := g.E.Pending()
	o, altar := activateOption(t, g, "Ashnod's Altar")
	ask := sacrificeAsk(t, g, d, o.Index)
	tx, err := mapping.Begin(env, d)
	if err != nil {
		t.Fatal(err)
	}
	p, err := tx.Pose()
	if err != nil {
		t.Fatal(err)
	}
	src, err := env.Obs.Ref(d.Player, altar)
	if err != nil || src == nil {
		t.Fatal(src, err)
	}
	var got []int
	for i, c := range p.Candidates {
		if c.Sem.Kind != "activate_mana_ability" {
			continue
		}
		s := c.Sem.Fields["source"].(protocol.ObjectRef)
		if s.ObjectID != src.ObjectID {
			continue
		}
		mc, _ := c.Sem.Fields["mana_choice"].(*string)
		ct, _ := c.Sem.Fields["cost_target"].(*protocol.TargetRef)
		if mc != nil || ct == nil || ct.Object == nil {
			t.Fatalf("plain cost candidate %+v", c.Sem)
		}
		if c.Sem.Fields["ability_index"] != uint32(0) {
			t.Fatalf("ability_index %v, want 0", c.Sem.Fields["ability_index"])
		}
		if c.Op.Op != "choose" || c.Op.Option != o.Index || len(c.Op.Followup) != 1 {
			t.Fatalf("plain cost candidate op %+v", c.Op)
		}
		got = append(got, i)
	}
	if len(got) != len(ask.Options) {
		t.Fatalf("%d altar candidates for %d sacrifice options", len(got), len(ask.Options))
	}
	// No colour ask is folded past the picks.
	key := fmt.Sprint(o.Index)
	if _, ok := p.Followups[fmt.Sprint(key, "/", ask.Options[0].Index)]; ok {
		t.Fatalf("a fixed-production cost folded a colour ask: %v", followupKeys(p))
	}
	commit, done, err := tx.Answer(got[0])
	if err != nil || !done || len(commit) != 2 {
		t.Fatalf("commit %v done %v err %v", commit, done, err)
	}
	c := replayCommit(t, g, commit)
	before, after := g.E.G.Players[d.Player].Pool, c.G.Players[d.Player].Pool
	if after[state.MC] != before[state.MC]+2 {
		t.Fatalf("colourless mana %d, want %d", after[state.MC], before[state.MC]+2)
	}
	if z := c.G.Obj(ask.Options[0].Obj).Zone; z != state.ZGraveyard {
		t.Fatalf("the sacrificed creature is in %s, want graveyard", z)
	}
}

// The cost fold fails closed when the observation cannot reference a cost
// option's object (mana.go's cost_target_hidden guard). No live state reaches
// it — the engine only ever offers the activator's own battlefield permanents,
// always visible to them — so the test projects the position through a game
// where those objects do not exist: every Ref comes back nil and the pose
// halts instead of posing a candidate with an unreferenceable target.
func TestCostFoldFailsClosedOnAHiddenCostTarget(t *testing.T) {
	g := altarPosition(t, "Phyrexian Altar", 2)
	env := envFor(t, g)
	d := g.E.Pending()
	o, altar := activateOption(t, g, "Phyrexian Altar")
	ask := sacrificeAsk(t, g, d, o.Index)
	src, err := env.Obs.Ref(d.Player, altar)
	if err != nil || src == nil {
		t.Fatal(src, err)
	}
	// A game whose objects are fourteen Mountains: every sacrifice candidate's
	// object id is past them.
	reg := testcorpus.Registry(t)
	mountain, ok := reg.Lookup("Mountain")
	if !ok {
		t.Fatal("Mountain is not in the corpus")
	}
	small := []*cards.Card{mountain, mountain, mountain, mountain, mountain, mountain, mountain}
	var seed [32]byte
	seed[0] = 1
	g2, err := gamecfg.New(reg, secrets.NewGame(seed[:]), [2][]*cards.Card{small, small}, gamecfg.Rules{Mulligan: "none", StartingSeat: 0})
	if err != nil {
		t.Fatal(err)
	}
	for _, co := range ask.Options {
		if g2.E.G.Obj(co.Obj) != nil {
			t.Fatalf("construction assumption broken: %d exists in the small game", co.Obj)
		}
	}
	env.Obs = &observe.Projector{E: g2.E, IDs: env.IDs}
	if _, _, err := mapping.ExpandActivate(env, d, o, *src); !errors.Is(err, mapping.ErrUnmapped) ||
		!strings.Contains(err.Error(), "cost_target_hidden") {
		t.Fatalf("hidden cost target: %v, want ErrUnmapped:cost_target_hidden", err)
	}
}

// An activation the engine refuses on the probe clone is not offered: the
// fold drops it silently rather than halting a pose over an option the pose
// no longer contains (mana.go's refused-probe guard).
func TestRefusedActivationIsNotOffered(t *testing.T) {
	g := altarPosition(t, "Phyrexian Altar", 2)
	env := envFor(t, g)
	d := g.E.Pending()
	bad := decision.Option{Kind: "activate", Index: len(d.Options) + 1}
	cs, folds, err := mapping.ExpandActivate(env, d, bad, protocol.ObjectRef{})
	if cs != nil || folds != nil || err != nil {
		t.Fatalf("refused activation: %v, %v, %v; want nil, nil, nil", cs, folds, err)
	}
}
