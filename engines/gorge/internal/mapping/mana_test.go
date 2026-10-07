package mapping_test

import (
	"errors"
	"fmt"
	"slices"
	"strings"
	"testing"

	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/rules"
	"github.com/adams-shaun/gorge/state"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/mapping"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
)

func untappedBridge(d *decision.Decision, e *rules.Engine) bool {
	if d.Kind != decision.KPriority {
		return false
	}
	for _, o := range d.Options {
		if o.Kind == "activate" && e.G.Obj(o.Obj).Face().Name == "Drossforge Bridge" {
			return true
		}
	}
	return false
}

// payableGate is a priority decision offering Heap Gate's {1} ability: the
// pool can pay for it, so both of the gate's mana abilities are available.
func payableGate(d *decision.Decision, e *rules.Engine) bool {
	if d.Kind != decision.KPriority {
		return false
	}
	for _, o := range d.Options {
		if o.Kind == "activate" && o.Cost != "" && e.G.Obj(o.Obj).Face().Name == "Heap Gate" {
			return true // the {1} ability is payable from the pool
		}
	}
	return false
}

func TestDualLandExpandsIntoOneCandidatePerColour(t *testing.T) {
	g := untilPending(t, "Wildfire", 1, untappedBridge)
	env := envFor(t, g)
	tx, err := mapping.Begin(env, g.E.Pending())
	if err != nil {
		t.Fatal(err)
	}
	p, err := tx.Pose()
	if err != nil {
		t.Fatal(err)
	}
	colours := map[string]int{}
	for i, c := range p.Candidates {
		if c.Sem.Kind != "activate_mana_ability" {
			continue
		}
		src := c.Sem.Fields["source"].(protocol.ObjectRef)
		if *src.CardName == "Drossforge Bridge" {
			if mc, _ := c.Sem.Fields["mana_choice"].(*string); mc != nil {
				colours[*mc] = i
			}
		}
	}
	if len(colours) < 2 {
		t.Fatalf("bridge colours %v", colours)
	}
	commit, done, err := tx.Answer(colours["R"])
	if err != nil || !done || len(commit) != 2 {
		t.Fatalf("commit %v done %v err %v", commit, done, err)
	}
	c, err := g.Probe(commit[0])
	if err != nil {
		t.Fatal(err)
	}
	f := c.Pending()
	commit[1].Seq, commit[1].Player = f.Seq, f.Player
	if err := c.SubmitHypothetical(commit[1]); err != nil {
		t.Fatal(err)
	}
	if c.G.Players[g.E.Pending().Player].Pool[state.MR] < 1 {
		t.Fatal("choosing R did not add red mana")
	}
}

// Heap Gate has two mana abilities ({T}: Add {C}; {1}, {T}: add one mana of
// any color). With mana floating, both are available, so activating it asks
// gorge's stage-1 "choose a mana ability", and the second ability then asks
// its colour: both asks fold into one decision, and each candidate names its
// ability by index (G2-1, G2-11).
func TestHeapGateFoldsItsTwoAbilitiesAndTheColourAsk(t *testing.T) {
	g := untilPending(t, "CawGates", 1, payableGate)
	env := envFor(t, g)
	d := g.E.Pending()
	tx, err := mapping.Begin(env, d)
	if err != nil {
		t.Fatal(err)
	}
	p, err := tx.Pose()
	if err != nil {
		t.Fatal(err)
	}
	got := map[string]int{} // "<ability_index>/<mana_choice>" -> candidate
	gate := ""
	for i, c := range p.Candidates {
		if c.Sem.Kind != "activate_mana_ability" {
			continue
		}
		src := c.Sem.Fields["source"].(protocol.ObjectRef)
		if *src.CardName != "Heap Gate" || (gate != "" && src.ObjectID != gate) {
			continue
		}
		gate = src.ObjectID
		mc, _ := c.Sem.Fields["mana_choice"].(*string)
		if mc == nil {
			t.Fatalf("Heap Gate candidate without a mana choice: %+v", c.Sem)
		}
		got[fmt.Sprint(c.Sem.Fields["ability_index"], "/", *mc)] = i
	}
	for _, want := range []string{"0/C", "1/W", "1/U", "1/B", "1/R", "1/G"} {
		if _, ok := got[want]; !ok {
			t.Fatalf("Heap Gate candidates %v lack %s", got, want)
		}
	}
	if len(got) != 6 {
		t.Fatalf("Heap Gate candidates %v, want 6", got)
	}
	commit, done, err := tx.Answer(got["1/G"])
	if err != nil || !done || len(commit) != 3 {
		t.Fatalf("commit %v done %v err %v", commit, done, err)
	}
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
	before, after := g.E.G.Players[d.Player].Pool, c.G.Players[d.Player].Pool
	if after[state.MG] != before[state.MG]+1 {
		t.Fatalf("green mana %d, want %d", after[state.MG], before[state.MG]+1)
	}
}

// A single-ability source with a fixed production (a basic land) stays one
// candidate: ability_index 0, mana_choice and cost_target null, no folded
// follow-up, and its answer is the activation alone.
func TestPlainLandIsOneCandidateWithoutAManaChoice(t *testing.T) {
	g := untilPending(t, "Wildfire", 1, func(d *decision.Decision, e *rules.Engine) bool {
		if d.Kind != decision.KPriority {
			return false
		}
		for _, o := range d.Options {
			if o.Kind == "activate" && e.G.Obj(o.Obj).Face().Name == "Mountain" {
				return true
			}
		}
		return false
	})
	env := envFor(t, g)
	d := g.E.Pending()
	tx, err := mapping.Begin(env, d)
	if err != nil {
		t.Fatal(err)
	}
	p, err := tx.Pose()
	if err != nil {
		t.Fatal(err)
	}
	found := 0
	cand := -1
	for i, c := range p.Candidates {
		if c.Sem.Kind != "activate_mana_ability" {
			continue
		}
		src := c.Sem.Fields["source"].(protocol.ObjectRef)
		if *src.CardName != "Mountain" {
			continue
		}
		found++
		cand = i
		mc, _ := c.Sem.Fields["mana_choice"].(*string)
		ct, _ := c.Sem.Fields["cost_target"].(*protocol.TargetRef)
		if c.Sem.Fields["ability_index"] != uint32(0) || mc != nil || ct != nil {
			t.Fatalf("plain source candidate %+v", c.Sem)
		}
		if err := c.Sem.Check(); err != nil {
			t.Fatal(err)
		}
		if c.Op.Op != "choose" || len(c.Op.Followup) != 0 {
			t.Fatalf("plain source op %+v", c.Op)
		}
	}
	if found != 1 {
		t.Fatalf("%d Mountain candidates, want 1", found)
	}
	commit, done, err := tx.Answer(cand)
	if err != nil || !done || len(commit) != 1 {
		t.Fatalf("commit %v done %v err %v", commit, done, err)
	}
	c, err := g.Probe(commit[0])
	if err != nil {
		t.Fatal(err)
	}
	if c.G.Players[d.Player].Pool[state.MR] != g.E.G.Players[d.Player].Pool[state.MR]+1 {
		t.Fatal("tapping a Mountain added no red mana")
	}
}

// A folded pose is deterministic (Section 13 F3) and records each folded
// native follow-up in Followups, keyed "<option>" and, past a stage-1 ask,
// "<option>/<stage-1 option>".
func TestFoldedFollowupsAreRecordedAndDeterministic(t *testing.T) {
	g := untilPending(t, "CawGates", 1, payableGate)
	env := envFor(t, g)
	d := g.E.Pending()
	opt := -1
	for _, o := range d.Options {
		if o.Kind == "activate" && g.E.G.Obj(o.Obj).Face().Name == "Heap Gate" {
			opt = o.Index
			break
		}
	}
	if opt < 0 {
		t.Fatal("no Heap Gate activate option")
	}
	pose := func() *mapping.Pose {
		tx, err := mapping.Begin(env, d)
		if err != nil {
			t.Fatal(err)
		}
		p, err := tx.Pose()
		if err != nil {
			t.Fatal(err)
		}
		return p
	}
	p, again := pose(), pose()
	if semJSON(p.Candidates) != semJSON(again.Candidates) {
		t.Fatal("re-posing the folded decision differs")
	}
	key := fmt.Sprint(opt)
	stage1, ok := p.Followups[key]
	if !ok {
		t.Fatalf("follow-up keys %v, want %q among them", followupKeys(p), key)
	}
	// Other activate options in the pose fold their own colour asks; every
	// recorded follow-up is a KChoose of mana options.
	for k, f := range p.Followups {
		if f.Kind != decision.KChoose || len(f.Options) == 0 || f.Options[0].Kind != "mana" {
			t.Fatalf("follow-up %q is %+v", k, f)
		}
	}
	if stage1.Kind != decision.KChoose || len(stage1.Options) != 2 {
		t.Fatalf("stage-1 follow-up %+v", stage1)
	}
	stage2, ok := p.Followups[fmt.Sprint(key, "/", stage1.Options[1].Index)]
	if !ok {
		t.Fatalf("follow-up keys %v lack the stage-2 key", followupKeys(p))
	}
	if stage2.Kind != decision.KChoose || len(stage2.Options) != 5 || stage2.Options[0].Kind != "mana" {
		t.Fatalf("stage-2 follow-up %+v", stage2)
	}
}

func followupKeys(p *mapping.Pose) []string {
	var out []string
	for k := range p.Followups {
		out = append(out, k)
	}
	return out
}

// A raw colour ask reaching the session means a fold was missed: the
// registered choose/mana route fails closed rather than posing it.
func TestChooseManaRouteFailsClosed(t *testing.T) {
	g, ask, _ := manaColourAsk(t)
	env := envFor(t, g)
	if _, err := mapping.Begin(env, ask); err == nil || !strings.Contains(err.Error(), "unfolded_mana_colour") || !errors.Is(err, mapping.ErrUnmapped) {
		t.Fatalf("choose/mana: %v, want ErrUnmapped:unfolded_mana_colour", err)
	}
}

func TestManaSymbolFromOption(t *testing.T) {
	for _, c := range []struct {
		name string
		o    decision.Option
		want string
		ok   bool
	}{
		{"the field wins", decision.Option{ManaSymbol: "W", Label: "Pay 1: Add any color"}, "W", true},
		{"a bare pip label", decision.Option{Label: "Add C"}, "C", true},
		{"padded label", decision.Option{Label: "  Add R \n"}, "R", true},
		{"a paid any-color label", decision.Option{Label: "Pay 1: Add any color"}, "", false},
		{"a multi-pip label", decision.Option{Label: "Add B or R"}, "", false},
		{"a doubled pip", decision.Option{Label: "Sacrifice a creature: Add BB"}, "", false},
		{"no suffix", decision.Option{Label: "Add "}, "", false},
		{"empty", decision.Option{}, "", false},
		{"not a colour", decision.Option{Label: "Add X"}, "", false},
	} {
		got, ok := mapping.ManaSymbol(c.o)
		if got != c.want || ok != c.ok {
			t.Errorf("%s: %q, %v; want %q, %v", c.name, got, ok, c.want, c.ok)
		}
		if ok && !slices.Contains(protocol.Vocab["mana_symbol"], got) {
			t.Errorf("%s: %q is outside the mana_symbol vocabulary", c.name, got)
		}
	}
}
