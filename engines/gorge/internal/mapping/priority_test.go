package mapping_test

import (
	"encoding/json"
	"errors"
	"fmt"
	"reflect"
	"slices"
	"testing"

	"github.com/adams-shaun/gorge/cards"
	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/rules"
	"github.com/adams-shaun/gorge/state"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/identity"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/mapping"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/observe"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/testcorpus"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/testgame"
)

func hasOption(d *decision.Decision, kind, mode string) bool {
	for _, o := range d.Options {
		if o.Kind == kind && o.Mode == mode {
			return true
		}
	}
	return false
}

// mustPose begins d's transaction and poses its first decision.
func mustPose(t *testing.T, env *mapping.Env, d *decision.Decision) (mapping.Transaction, *mapping.Pose) {
	t.Helper()
	tx, err := mapping.Begin(env, d)
	if err != nil {
		t.Fatal(err)
	}
	p, err := tx.Pose()
	if err != nil {
		t.Fatal(err)
	}
	return tx, p
}

func source(c mapping.Cand) protocol.ObjectRef {
	r, _ := c.Sem.Fields["source"].(protocol.ObjectRef)
	return r
}

func semJSON(v any) string {
	b, err := json.Marshal(v)
	if err != nil {
		return err.Error()
	}
	return string(b)
}

// checkPriorityShape pins Sections 7.1 and 8 for a priority decision: the
// acting seat, a group start of exactly one substep, a priority context with
// no source or purpose, and pass first.
func checkPriorityShape(t *testing.T, p *mapping.Pose, d *decision.Decision) {
	t.Helper()
	if p.Seat != d.Player || !p.GroupStart || p.SubstepIndex != 0 || p.SubstepCount != 1 {
		t.Fatalf("priority pose: seat %d, group start %v, substep %d of %d", p.Seat, p.GroupStart, p.SubstepIndex, p.SubstepCount)
	}
	if p.Context.Kind != "priority" || p.Context.Source != nil || p.Context.Purpose != nil {
		t.Fatalf("priority context %s", semJSON(p.Context))
	}
	if len(p.Candidates) == 0 || p.Candidates[0].Sem.Kind != "pass" {
		t.Fatalf("candidate 0 is not pass: %s", semJSON(p.Candidates))
	}
}

// checkFollowup pins an optional-cost follow-up (Sections 7.3, 7.5 and 8):
// its own group of exactly one substep, a choice context whose source is the
// card being cast (still where it was, since no stack entry exists yet), and
// one optional_cost candidate per native variant, pay true for the optional
// one and pay false for the plain one.
func checkFollowup(t *testing.T, f *mapping.Pose, d *decision.Decision, src protocol.ObjectRef, cost string, pays ...bool) {
	t.Helper()
	if f.Seat != d.Player || !f.GroupStart || f.SubstepIndex != 0 || f.SubstepCount != 1 {
		t.Fatalf("follow-up: seat %d, group start %v, substep %d of %d", f.Seat, f.GroupStart, f.SubstepIndex, f.SubstepCount)
	}
	if f.Context.Kind != "choice" || f.Context.Source == nil || !reflect.DeepEqual(*f.Context.Source, src) || f.Context.Purpose != nil {
		t.Fatalf("follow-up context %s, want a choice sourced at %s", semJSON(f.Context), semJSON(src))
	}
	var got []bool
	for _, c := range f.Candidates {
		if err := c.Sem.Check(); err != nil {
			t.Fatal(err)
		}
		if c.Sem.Kind != "optional_cost" || c.Sem.Fields["cost"] != cost || !reflect.DeepEqual(source(c), src) || c.Op.Op != "choose" {
			t.Fatalf("follow-up candidate %s %s", semJSON(c.Sem), semJSON(c.Op))
		}
		got = append(got, c.Sem.Fields["pay"].(bool))
	}
	if len(got) == 2 && !got[0] {
		got[0], got[1] = got[1], got[0]
	}
	if !slices.Equal(got, pays) {
		t.Fatalf("follow-up pays %v, want %v", got, pays)
	}
}

// answerFollowup answers candidate cast of d's priority pose, then the
// follow-up candidate whose pay is pay, on a fresh transaction, and returns
// the commit.
func answerFollowup(t *testing.T, env *mapping.Env, d *decision.Decision, cast int, pay bool) []decision.Intent {
	t.Helper()
	tx, _ := mustPose(t, env, d)
	commit, done, err := tx.Answer(cast)
	if err != nil || done || commit != nil {
		t.Fatalf("cast answer: commit %v, done %v, err %v", commit, done, err)
	}
	f, err := tx.Pose()
	if err != nil {
		t.Fatal(err)
	}
	for i, c := range f.Candidates {
		if c.Sem.Fields["pay"] == pay {
			commit, done, err = tx.Answer(i)
			if err != nil || !done {
				t.Fatalf("follow-up answer: done %v, err %v", done, err)
			}
			return commit
		}
	}
	t.Fatalf("follow-up has no pay %v candidate", pay)
	return nil
}

// nativeCasts returns the native "cast" options of the object ref names, by mode.
func nativeCasts(t *testing.T, env *mapping.Env, d *decision.Decision, ref protocol.ObjectRef) map[string]int {
	t.Helper()
	out := map[string]int{}
	for _, o := range d.Options {
		r, err := env.Obs.Ref(d.Player, o.Obj)
		if err != nil {
			t.Fatal(err)
		}
		if o.Kind == "cast" && r != nil && r.ObjectID == ref.ObjectID {
			out[o.Mode] = o.Index
		}
	}
	return out
}

func TestPriorityPassFirstAndNoConcede(t *testing.T) {
	g := untilPending(t, "Burn", 1, func(d *decision.Decision, e *rules.Engine) bool {
		return d.Kind == decision.KPriority && hasOption(d, "cast", "")
	})
	env := envFor(t, g)
	d := g.E.Pending()
	_, p := mustPose(t, env, d)
	checkPriorityShape(t, p, d)
	if !hasOption(d, "concede", "") {
		t.Fatal("no native concede option: the test proves nothing")
	}
	for _, c := range p.Candidates {
		covers := append([]int{c.Op.Option}, c.Op.Covers...)
		for _, k := range covers {
			if k >= 0 && d.Options[k].Kind == "concede" {
				t.Fatalf("candidate %s covers concede", semJSON(c.Sem))
			}
		}
		if c.Sem.Kind == "cast_spell" && c.Sem.Fields["method"] != "normal" && c.Sem.Fields["method"] != "flashback" {
			t.Errorf("unexpected method %v", c.Sem.Fields["method"])
		}
	}
	if len(p.Candidates) != len(d.Options)-1 {
		t.Fatalf("%d candidates for %d native options (concede excluded)", len(p.Candidates), len(d.Options))
	}
}

func TestKickerBecomesAFollowUpOptionalCost(t *testing.T) {
	g := untilPending(t, "Rally", 1, func(d *decision.Decision, e *rules.Engine) bool {
		return d.Kind == decision.KPriority && hasOption(d, "cast", "kicked")
	})
	env := envFor(t, g)
	d := g.E.Pending()
	_, p := mustPose(t, env, d)
	checkPriorityShape(t, p, d)
	cast := -1
	for i, c := range p.Candidates {
		if c.Sem.Kind == "cast_spell" && *source(c).CardName == "Goblin Bushwhacker" && c.Op.Op == "cast" {
			cast = i
		}
	}
	if cast < 0 {
		t.Fatal("no cast_spell for Goblin Bushwhacker")
	}
	c := p.Candidates[cast]
	modes := nativeCasts(t, env, d, source(c))
	kicked, kok := modes["kicked"]
	plain, pok := modes[""]
	if !kok || !pok || c.Sem.Fields["method"] != "normal" || !reflect.DeepEqual(c.Op.Covers, []int{kicked, plain}) {
		t.Fatalf("kicker candidate %s %s, native casts %v", semJSON(c.Sem), semJSON(c.Op), modes)
	}
	for _, pay := range []bool{true, false} {
		tx, _ := mustPose(t, env, d)
		if commit, done, err := tx.Answer(cast); err != nil || done || commit != nil {
			t.Fatalf("after cast: commit %v, done %v, err %v", commit, done, err)
		}
		f, err := tx.Pose()
		if err != nil {
			t.Fatal(err)
		}
		checkFollowup(t, f, d, source(c), "kicker", true, false)
		want := plain
		if pay {
			want = kicked
		}
		if commit := answerFollowup(t, env, d, cast, pay); !reflect.DeepEqual(commit, []decision.Intent{mapping.Intent(d, want)}) {
			t.Fatalf("pay %v commits %v, want native option %d (%s)", pay, commit, want, d.Options[want].Mode)
		}
	}
}

func TestCastMethodTable(t *testing.T) {
	for _, c := range []struct {
		opt                      decision.Option
		altMode                  string
		method, optional, action string
	}{
		{decision.Option{Kind: "cast"}, "", "normal", "", ""},
		{decision.Option{Kind: "cast", Mode: "mayplay"}, "", "normal", "", ""},
		{decision.Option{Kind: "cast", Mode: "mayflash"}, "", "normal", "", ""},
		{decision.Option{Kind: "cast", Mode: "flashback"}, "", "flashback", "", ""},
		{decision.Option{Kind: "cast", Mode: "plot_cast"}, "", "plot", "", ""},
		{decision.Option{Kind: "cast", Mode: "bestowed"}, "", "alternative", "", ""},
		{decision.Option{Kind: "cast", Mode: "surged"}, "", "alternative", "", ""},
		{decision.Option{Kind: "cast", Mode: "blitzed"}, "", "alternative", "", ""},
		{decision.Option{Kind: "cast", Mode: "emerged"}, "", "alternative", "", ""},
		{decision.Option{Kind: "cast", Mode: "mutated"}, "", "alternative", "", ""},
		{decision.Option{Kind: "cast", Mode: "escape"}, "", "escape", "", ""},
		{decision.Option{Kind: "cast", Mode: "foretell_cast"}, "", "foretell", "", ""},
		{decision.Option{Kind: "cast", Mode: "adventure_alt"}, "Adventure", "adventure", "", ""},
		{decision.Option{Kind: "cast", Mode: "split_alt"}, "", "split_right", "", ""},
		{decision.Option{Kind: "cast", Mode: "fuse"}, "", "fuse", "", ""},
		{decision.Option{Kind: "cast", Mode: "modal_spell"}, "", "mdfc_back", "", ""},
		// These rows cannot fire at the pinned gorge (see priority.go); they
		// pin the kept branches for a later pin.
		{decision.Option{Kind: "cast", Mode: "adventure_alt"}, "Omen", "other", "", ""}, // Roost Seek
		{decision.Option{Kind: "cast", Mode: "madness"}, "", "madness", "", ""},
		{decision.Option{Kind: "cast", Mode: "miracle"}, "", "miracle", "", ""},
		{decision.Option{Kind: "cast", Mode: "suspend_cast"}, "", "suspend", "", ""},
		// Any alternative cost (Fireblast's), whichever it is.
		{decision.Option{Kind: "cast", AltCostIndex: 1}, "", "alternative", "", ""},
		{decision.Option{Kind: "cast", AltCostIndex: 2}, "", "alternative", "", ""},
		// Optional costs over the normal method.
		{decision.Option{Kind: "cast", Mode: "kicked"}, "", "normal", "kicker", ""},
		{decision.Option{Kind: "cast", Mode: "buyback"}, "", "normal", "buyback", ""},
		{decision.Option{Kind: "cast", Mode: "entwined"}, "", "normal", "entwine", ""},
		{decision.Option{Kind: "cast", Mode: "conspired"}, "", "normal", "conspire", ""},
		{decision.Option{Kind: "cast", Mode: "casualty"}, "", "normal", "casualty", ""},
		{decision.Option{Kind: "cast", Mode: "offspring"}, "", "normal", "offspring", ""},
		// gorge's OptionalCost static is an optional additional cost; its
		// AltCostIndex numbers the static, not an alternative cost.
		{decision.Option{Kind: "cast", Mode: "optionalcost", AltCostIndex: 1}, "", "normal", "additional", ""},
		{decision.Option{Kind: "cast", Mode: "plot"}, "", "", "", "plot"},
	} {
		m, o, a, ok := mapping.CastMethod(c.opt, c.altMode)
		if !ok || m != c.method || o != c.optional || a != c.action {
			t.Errorf("%+v %s: %q %q %q %v", c.opt, c.altMode, m, o, a, ok)
		}
		if (m != "" && !slices.Contains(protocol.Vocab["method"], m)) ||
			(o != "" && !slices.Contains(protocol.Vocab["optional_cost.cost"], o)) ||
			(a != "" && !slices.Contains(protocol.Vocab["special_action.action"], a)) {
			t.Errorf("%+v: %q %q %q is outside the Section 7.4 vocabularies", c.opt, m, o, a)
		}
	}
	// Every other mode gorge can offer at the pin fails closed (the engine
	// notes list them, Task 29).
	for _, mode := range []string{"multikicked", "kicked1", "kicked2", "kickedboth", "replicated", "squadded",
		"evoked", "dashed", "overloaded", "warped", "morphed", "megamorphed", "disguised", "harmonize",
		"aftermath", "retrace", "jumpstart", "mayhem", "adventure_recast", "warp_recast", "room_alt",
		"foretell", "suspend"} {
		if _, _, _, ok := mapping.CastMethod(decision.Option{Kind: "cast", Mode: mode}, ""); ok {
			t.Errorf("%s is mapped; it must fail closed", mode)
		}
	}
}

func sa(kind, api, cost string, params ...string) *cards.SA {
	p := map[string]string{"Cost": cost}
	for i := 0; i+1 < len(params); i += 2 {
		p[params[i]] = params[i+1]
	}
	return &cards.SA{Kind: kind, API: api, Params: p}
}

// abilityObj is an object whose one face has abs, with merged cards stacked
// beneath it (a mutated pile when merged > 0).
func abilityObj(merged int, abs ...*cards.SA) *state.Object {
	o := &state.Object{Card: &cards.Card{Faces: []*cards.Face{{Name: "Probe", Abilities: abs}}}}
	for i := 0; i < merged; i++ {
		o.MergedCards = append(o.MergedCards, state.MergedCard{Card: &cards.Card{Faces: []*cards.Face{{Name: "Under", Abilities: abs}}}})
	}
	return o
}

// Section 7.2's ability_index counts non-mana activated abilities in Oracle
// order, with gorge's own mana split: Mana and ManaReflected abilities are
// mana abilities unless they are loyalty abilities (CR 605.1b), marked by
// Planeswalker$ or by a LOYALTY counter cost (rules/legal.go).
func TestNonManaAbilityIndex(t *testing.T) {
	mana, pump := sa("AB", "Mana", "T"), sa("AB", "Pump", "2")
	twisted := []*cards.SA{mana, sa("AB", "ChangeZone", "T Sac<1/CARDNAME>"), sa("AB", "Draw", "B R G Discard<1/CARDNAME>")}
	for _, c := range []struct {
		name string
		abs  []*cards.SA
		at   int
		want uint32
	}{
		{"Twisted Landscape's search, after a mana ability", twisted, 1, 0},
		{"Twisted Landscape's cycling", twisted, 2, 1},
		{"Heap Gate's token ability, after two mana abilities", []*cards.SA{mana, sa("AB", "Mana", "1 T"), sa("AB", "Token", "1 T tapXType<1/Gate>")}, 2, 0},
		{"Lórien Revealed's islandcycling, after its spell ability", []*cards.SA{sa("SP", "Draw", ""), sa("AB", "ChangeZone", "1 Discard<1/CARDNAME>")}, 1, 0},
		{"after a ManaReflected ability", []*cards.SA{sa("AB", "ManaReflected", "T"), pump}, 1, 0},
		{"a loyalty mana ability (Planeswalker$)", []*cards.SA{sa("AB", "Mana", "AddCounter<1/LOYALTY>", "Planeswalker", "True"), pump}, 0, 0},
		{"after a loyalty mana ability (Planeswalker$)", []*cards.SA{sa("AB", "Mana", "AddCounter<1/LOYALTY>", "Planeswalker", "True"), pump}, 1, 1},
		{"after a loyalty mana ability (Planeswalker$ spelled true)", []*cards.SA{sa("AB", "Mana", "T", "Planeswalker", " true "), pump}, 1, 1},
		{"after a loyalty mana ability (AddCounter LOYALTY cost)", []*cards.SA{sa("AB", "Mana", "AddCounter<2/LOYALTY>"), pump}, 1, 1},
		{"after a loyalty mana ability (SubCounter LOYALTY cost)", []*cards.SA{sa("AB", "Mana", "SubCounter<1/LOYALTY>"), pump}, 1, 1},
		{"after Wall of Roots' mana ability (M0M1 counter cost)", []*cards.SA{sa("AB", "Mana", "AddCounter<1/M0M1>"), pump}, 1, 0},
	} {
		got, err := mapping.NonManaAbilityIndex(abilityObj(0, c.abs...), decision.Option{Kind: "ability", Ability: c.at})
		if err != nil || got != c.want {
			t.Errorf("%s: %d, %v; want %d", c.name, got, err, c.want)
		}
	}
}

// Anchors that are not a printed ability of one card fail closed: Section
// 7.2 orders granted abilities after the printed ones by timestamp, which a
// gorge option does not carry, and a mutated pile's index spans its cards.
func TestNonManaAbilityIndexFailsClosed(t *testing.T) {
	abs := []*cards.SA{sa("SP", "Draw", ""), sa("AB", "Mana", "T"), sa("AB", "Pump", "2")}
	for _, c := range []struct {
		name string
		obj  *state.Object
		opt  decision.Option
	}{
		{"keyword-granted (Ability -1)", abilityObj(0, abs...), decision.Option{Ability: -1, Keyword: "Cycling:1 U"}},
		{"a negative anchor", abilityObj(0, abs...), decision.Option{Ability: -1}},
		{"keyword-granted", abilityObj(0, abs...), decision.Option{Ability: 2, Keyword: "Cycling:1 U"}},
		{"SVar-granted by itself", abilityObj(0, abs...), decision.Option{Ability: 2, SVar: "GrantedAbility"}},
		{"SVar-granted by another object", abilityObj(0, abs...), decision.Option{Ability: 2, SVar: "GrantedAbility", GrantSource: 9}},
		{"granted by another object", abilityObj(0, abs...), decision.Option{Ability: 2, GrantSource: 9}},
		{"gained", abilityObj(0, abs...), decision.Option{Ability: 2, GainedSource: 9, GainedIdx: 1}},
		// gorge's GainedIdx is face-local and can be 0 (legal.go), so only
		// GainedSource tells a gained ability apart.
		{"gained at index 0", abilityObj(0, abs...), decision.Option{Ability: 2, GainedSource: 9, GainedIdx: 0}},
		{"a mutated pile", abilityObj(1, abs...), decision.Option{Ability: 2}},
		{"a mana ability", abilityObj(0, abs...), decision.Option{Ability: 1}},
		{"a spell ability", abilityObj(0, abs...), decision.Option{Ability: 0}},
		{"past the face's abilities", abilityObj(0, abs...), decision.Option{Ability: 3}},
		{"no face", &state.Object{}, decision.Option{Ability: 0}},
		{"no object", nil, decision.Option{Ability: 0}},
	} {
		c.opt.Kind = "ability"
		if got, err := mapping.NonManaAbilityIndex(c.obj, c.opt); !errors.Is(err, mapping.ErrUnmapped) {
			t.Errorf("%s: %d, %v; want %v", c.name, got, err, mapping.ErrUnmapped)
		}
	}
	// The priority route halts on such an anchor rather than posing it.
	env, d0, hand, _ := synthPosition(t)
	d := synthetic(d0, decision.Option{Kind: "ability", Obj: hand[0], Ability: -1, Keyword: "Cycling:1 U"})
	if err := poseErr(env, d); !errors.Is(err, mapping.ErrUnmapped) {
		t.Errorf("keyword-granted ability option: %v, want %v", err, mapping.ErrUnmapped)
	}
}

// synthPosition is a live priority position whose seat holds at least three
// cards. Synthetic priority decisions over it reference real objects, so the
// route resolves them exactly as it resolves gorge's own options; they pose
// option shapes gorge can offer (cited per test) that the catalog never
// reaches. It also returns a card of the seat's library, hidden from it.
func synthPosition(t *testing.T) (*mapping.Env, *decision.Decision, []state.ObjID, state.ObjID) {
	t.Helper()
	g := untilPending(t, "Burn", 1, func(d *decision.Decision, e *rules.Engine) bool {
		return d.Kind == decision.KPriority && len(e.G.Zone(state.ZHand, d.Player)) >= 3
	})
	d := g.E.Pending()
	return envFor(t, g), d, g.E.G.Zone(state.ZHand, d.Player), g.E.G.Zone(state.ZLibrary, d.Player)[0]
}

// synthetic is a priority decision of d's seat offering opts, then pass and
// concede, the order gorge ends every priority decision with.
func synthetic(d *decision.Decision, opts ...decision.Option) *decision.Decision {
	s := &decision.Decision{Kind: decision.KPriority, Seq: d.Seq, Player: d.Player}
	for _, o := range append(opts, decision.Option{Kind: "pass"}, decision.Option{Kind: "concede"}) {
		o.Index = len(s.Options)
		s.Options = append(s.Options, o)
	}
	return s
}

func poseErr(env *mapping.Env, d *decision.Decision) error {
	tx, err := mapping.Begin(env, d)
	if err != nil {
		return err
	}
	_, err = tx.Pose()
	return err
}

// candidateFor finds the candidate of kind whose source is obj and whose
// field key is val.
func candidateFor(t *testing.T, env *mapping.Env, p *mapping.Pose, kind string, obj state.ObjID, key string, val any) int {
	t.Helper()
	r, err := env.Obs.Ref(p.Seat, obj)
	if err != nil || r == nil {
		t.Fatalf("object %d: ref %v, err %v", obj, r, err)
	}
	for i, c := range p.Candidates {
		if c.Sem.Kind == kind && reflect.DeepEqual(source(c), *r) && c.Sem.Fields[key] == val {
			return i
		}
	}
	t.Fatalf("no %s %s=%v on object %d in %s", kind, key, val, obj, semJSON(p.Candidates))
	return -1
}

// Fireblast castable both ways (its own cost and its alternative cost, the
// shape rules/legal.go's alternative-cost walk offers) is two candidates,
// each committing its own native option.
func TestPriorityAlternativeCostIsItsOwnCandidate(t *testing.T) {
	env, d0, hand, _ := synthPosition(t)
	a := hand[0]
	d := synthetic(d0, decision.Option{Kind: "cast", Obj: a}, decision.Option{Kind: "cast", Obj: a, AltCostIndex: 1})
	_, p := mustPose(t, env, d)
	checkPriorityShape(t, p, d)
	if len(p.Candidates) != 3 {
		t.Fatalf("candidates %s", semJSON(p.Candidates))
	}
	for method, native := range map[string]int{"normal": 0, "alternative": 1} {
		i := candidateFor(t, env, p, "cast_spell", a, "method", method)
		tx, _ := mustPose(t, env, d)
		commit, done, err := tx.Answer(i)
		if err != nil || !done || !reflect.DeepEqual(commit, []decision.Intent{mapping.Intent(d, native)}) {
			t.Fatalf("%s commits %v, done %v, err %v; want native option %d", method, commit, done, err, native)
		}
	}
}

// Two objects, each with a plain flashback cast and a kicker pair, the
// flashback first for one and last for the other: each cast candidate keeps
// its own variants, and the follow-up belongs to the chosen candidate's
// object and method. Repeated, so an answer that depends on map order cannot
// pass by luck.
func TestPriorityCastGroupsStayApart(t *testing.T) {
	env, d0, hand, _ := synthPosition(t)
	a, b := hand[0], hand[1]
	d := synthetic(d0,
		decision.Option{Kind: "cast", Obj: a, Mode: "flashback"}, // 0
		decision.Option{Kind: "cast", Obj: a},                    // 1
		decision.Option{Kind: "cast", Obj: a, Mode: "kicked"},    // 2
		decision.Option{Kind: "cast", Obj: b},                    // 3
		decision.Option{Kind: "cast", Obj: b, Mode: "kicked"},    // 4
		decision.Option{Kind: "cast", Obj: b, Mode: "flashback"}, // 5
	)
	_, p := mustPose(t, env, d)
	checkPriorityShape(t, p, d)
	if len(p.Candidates) != 5 {
		t.Fatalf("candidates %s", semJSON(p.Candidates))
	}
	fa := candidateFor(t, env, p, "cast_spell", a, "method", "flashback")
	fb := candidateFor(t, env, p, "cast_spell", b, "method", "flashback")
	na := candidateFor(t, env, p, "cast_spell", a, "method", "normal")
	nb := candidateFor(t, env, p, "cast_spell", b, "method", "normal")
	if p.Candidates[fa].Op.Op != "choose" || p.Candidates[fb].Op.Op != "choose" ||
		!reflect.DeepEqual(p.Candidates[na].Op.Covers, []int{2, 1}) || !reflect.DeepEqual(p.Candidates[nb].Op.Covers, []int{4, 3}) {
		t.Fatalf("candidates %s", semJSON(p.Candidates))
	}
	for n := 0; n < 16; n++ {
		for cand, native := range map[int]int{fa: 0, fb: 5} {
			tx, _ := mustPose(t, env, d)
			if commit, done, err := tx.Answer(cand); err != nil || !done || !reflect.DeepEqual(commit, []decision.Intent{mapping.Intent(d, native)}) {
				t.Fatalf("flashback commits %v, done %v, err %v; want %d", commit, done, err, native)
			}
		}
		for _, c := range []struct {
			cand          int
			obj           state.ObjID
			kicked, plain int
		}{{na, a, 2, 1}, {nb, b, 4, 3}} {
			tx, _ := mustPose(t, env, d)
			if _, done, err := tx.Answer(c.cand); err != nil || done {
				t.Fatalf("cast answer: done %v, err %v", done, err)
			}
			f, err := tx.Pose()
			if err != nil {
				t.Fatal(err)
			}
			checkFollowup(t, f, d, source(p.Candidates[c.cand]), "kicker", true, false)
			if got := answerFollowup(t, env, d, c.cand, true); !reflect.DeepEqual(got, []decision.Intent{mapping.Intent(d, c.kicked)}) {
				t.Fatalf("object %d pay true commits %v, want %d", c.obj, got, c.kicked)
			}
			if got := answerFollowup(t, env, d, c.cand, false); !reflect.DeepEqual(got, []decision.Intent{mapping.Intent(d, c.plain)}) {
				t.Fatalf("object %d pay false commits %v, want %d", c.obj, got, c.plain)
			}
		}
	}
}

// gorge's optionalcost (a card's own OptionalCost static, an optional
// additional cost whose decline path is the plain cast: rules/legal.go's
// hand walk) is the normal cast plus an optional_cost "additional"
// follow-up, even though the option carries AltCostIndex for its static.
// A group with only the optional variant offers only paying it.
func TestPriorityOptionalAdditionalCost(t *testing.T) {
	env, d0, hand, _ := synthPosition(t)
	a, b := hand[0], hand[1]
	d := synthetic(d0,
		decision.Option{Kind: "cast", Obj: a},
		decision.Option{Kind: "cast", Obj: a, Mode: "optionalcost", AltCostIndex: 1},
		decision.Option{Kind: "cast", Obj: b, Mode: "optionalcost", AltCostIndex: 1},
	)
	_, p := mustPose(t, env, d)
	checkPriorityShape(t, p, d)
	if len(p.Candidates) != 3 {
		t.Fatalf("candidates %s", semJSON(p.Candidates))
	}
	na := candidateFor(t, env, p, "cast_spell", a, "method", "normal")
	nb := candidateFor(t, env, p, "cast_spell", b, "method", "normal")
	// Covers names every native variant, the optional-cost one first, even
	// when the plain variant is native option 0.
	if !reflect.DeepEqual(p.Candidates[na].Op.Covers, []int{1, 0}) || !reflect.DeepEqual(p.Candidates[nb].Op.Covers, []int{2}) {
		t.Fatalf("covers %s and %s", semJSON(p.Candidates[na].Op), semJSON(p.Candidates[nb].Op))
	}
	for _, c := range []struct {
		cand, paid, plain int
	}{{na, 1, 0}, {nb, 2, -1}} {
		tx, _ := mustPose(t, env, d)
		if _, done, err := tx.Answer(c.cand); err != nil || done {
			t.Fatalf("cast answer: done %v, err %v", done, err)
		}
		f, err := tx.Pose()
		if err != nil {
			t.Fatal(err)
		}
		pays := []bool{true, false}
		if c.plain < 0 {
			pays = pays[:1]
		}
		checkFollowup(t, f, d, source(p.Candidates[c.cand]), "additional", pays...)
		if got := answerFollowup(t, env, d, c.cand, true); !reflect.DeepEqual(got, []decision.Intent{mapping.Intent(d, c.paid)}) {
			t.Fatalf("pay true commits %v, want %d", got, c.paid)
		}
		if c.plain >= 0 {
			if got := answerFollowup(t, env, d, c.cand, false); !reflect.DeepEqual(got, []decision.Intent{mapping.Intent(d, c.plain)}) {
				t.Fatalf("pay false commits %v, want %d", got, c.plain)
			}
		}
	}
}

// Option shapes that must halt rather than silently drop or merge a legal
// action.
func TestPriorityFailsClosed(t *testing.T) {
	env, d0, hand, hidden := synthPosition(t)
	a := hand[0]
	for _, c := range []struct {
		name string
		want error
		opts []decision.Option
	}{
		// Two variants that would share one candidate (Minor 1): a plain cast
		// and a may-play cast, or two optional-cost statics of one card.
		{"plain collision", mapping.ErrDuplicate, []decision.Option{{Kind: "cast", Obj: a}, {Kind: "cast", Obj: a, Mode: "mayplay"}}},
		{"optional collision", mapping.ErrDuplicate, []decision.Option{{Kind: "cast", Obj: a}, {Kind: "cast", Obj: a, Mode: "optionalcost", AltCostIndex: 1}, {Kind: "cast", Obj: a, Mode: "optionalcost", AltCostIndex: 2}}},
		// Two alternative costs: v2 has one word for both.
		{"two alternative costs", mapping.ErrDuplicate, []decision.Option{{Kind: "cast", Obj: a, AltCostIndex: 1}, {Kind: "cast", Obj: a, AltCostIndex: 2}}},
		{"two optional costs on one cast", mapping.ErrUnmapped, []decision.Option{{Kind: "cast", Obj: a}, {Kind: "cast", Obj: a, Mode: "kicked"}, {Kind: "cast", Obj: a, Mode: "buyback"}}},
		{"unmapped cast mode", mapping.ErrUnmapped, []decision.Option{{Kind: "cast", Obj: a, Mode: "kicked1"}}},
		{"granted", mapping.ErrUnmapped, []decision.Option{{Kind: "granted", Obj: a}}},
		{"specialize", mapping.ErrUnmapped, []decision.Option{{Kind: "specialize", Obj: a}}},
		{"station", mapping.ErrUnmapped, []decision.Option{{Kind: "station", Obj: a}}},
		{"hidden object", mapping.ErrUnmapped, []decision.Option{{Kind: "cast", Obj: hidden}}},
	} {
		if err := poseErr(env, synthetic(d0, c.opts...)); !errors.Is(err, c.want) {
			t.Errorf("%s: %v, want %v", c.name, err, c.want)
		}
	}
}

// play_land names the face (a modal double-faced card's back is face 1), and
// the special actions name theirs; each commits its own native option.
func TestPriorityLandFacesAndSpecialActions(t *testing.T) {
	env, d0, hand, _ := synthPosition(t)
	a, b, c := hand[0], hand[1], hand[2]
	d := synthetic(d0,
		decision.Option{Kind: "play_land", Obj: a},
		decision.Option{Kind: "play_land", Obj: a, Mode: "modal_land"},
		decision.Option{Kind: "cast", Obj: b, Mode: "plot"},
		decision.Option{Kind: "turn_face_up", Obj: c},
		decision.Option{Kind: "unlock", Obj: a},
	)
	_, p := mustPose(t, env, d)
	checkPriorityShape(t, p, d)
	if len(p.Candidates) != 6 {
		t.Fatalf("candidates %s", semJSON(p.Candidates))
	}
	for _, w := range []struct {
		kind, key string
		val       any
		obj       state.ObjID
		native    int
	}{
		{"play_land", "face", uint32(0), a, 0},
		{"play_land", "face", uint32(1), a, 1},
		{"special_action", "action", "plot", b, 2},
		{"special_action", "action", "turn_face_up", c, 3},
		{"special_action", "action", "unlock_door", a, 4},
	} {
		i := candidateFor(t, env, p, w.kind, w.obj, w.key, w.val)
		tx, _ := mustPose(t, env, d)
		commit, done, err := tx.Answer(i)
		if err != nil || !done || !reflect.DeepEqual(commit, []decision.Intent{mapping.Intent(d, w.native)}) {
			t.Fatalf("%s %v commits %v, done %v, err %v; want %d", w.kind, w.val, commit, done, err, w.native)
		}
	}
}

// The activate path passes ExpandActivate's candidates and folded
// follow-ups through untouched, and an answer commits the option then each
// folded follow-up. A stand-in replaces ExpandActivate, so this holds for
// Task 15's lookahead as for the stub.
func TestPriorityActivateUsesExpandActivate(t *testing.T) {
	env, d0, hand, _ := synthPosition(t)
	a := hand[0]
	d := synthetic(d0, decision.Option{Kind: "activate", Obj: a})
	ref, err := env.Obs.Ref(d.Player, a)
	if err != nil || ref == nil {
		t.Fatal(ref, err)
	}
	red, green := "R", "G"
	folded := &decision.Decision{Kind: decision.KChoose}
	stub := mapping.ExpandActivate
	t.Cleanup(func() { mapping.ExpandActivate = stub })
	calls := 0
	mapping.ExpandActivate = func(e *mapping.Env, dd *decision.Decision, o decision.Option, src protocol.ObjectRef) ([]mapping.Cand, map[string]*decision.Decision, error) {
		calls++
		if e != env || dd != d || !reflect.DeepEqual(o, d.Options[0]) || !reflect.DeepEqual(src, *ref) {
			t.Errorf("ExpandActivate called with option %+v, source %s", o, semJSON(src))
		}
		return []mapping.Cand{
			{Sem: protocol.ActivateManaAbility(src, 0, &red, nil), Op: mapping.NativeOp{Op: "choose", Option: o.Index, Followup: []int{1}}},
			{Sem: protocol.ActivateManaAbility(src, 0, &green, nil), Op: mapping.NativeOp{Op: "choose", Option: o.Index, Followup: []int{3, 0}}},
		}, map[string]*decision.Decision{"0": folded}, nil
	}
	_, p := mustPose(t, env, d)
	checkPriorityShape(t, p, d)
	if calls != 1 || len(p.Candidates) != 3 || p.Followups["0"] != folded || len(p.Followups) != 1 {
		t.Fatalf("calls %d, candidates %s, follow-ups %v", calls, semJSON(p.Candidates), p.Followups)
	}
	for i, want := range [][]int{{1}, {3, 0}} {
		c := p.Candidates[i+1]
		if c.Sem.Kind != "activate_mana_ability" || !reflect.DeepEqual(c.Op.Followup, want) {
			t.Fatalf("candidate %d: %s %s", i+1, semJSON(c.Sem), semJSON(c.Op))
		}
		tx, _ := mustPose(t, env, d)
		commit, done, err := tx.Answer(i + 1)
		intents := []decision.Intent{mapping.Intent(d, 0)}
		for _, f := range want {
			intents = append(intents, decision.Intent{Choices: []int{f}})
		}
		if err != nil || !done || !reflect.DeepEqual(commit, intents) {
			t.Fatalf("candidate %d commits %v, done %v, err %v; want %v", i+1, commit, done, err, intents)
		}
	}
}

// oracleAbility is each catalog ability's Section 7.2 ability_index read
// from its Oracle text (its place among the card's non-mana activated
// abilities), keyed by card name and the ability's index in gorge's face.
var oracleAbility = map[string]map[int]uint32{
	"Basilisk Gate": {1: 0}, "Blood Fountain": {0: 0}, "Experimental Synthesizer": {0: 0},
	"Generous Ent": {0: 0}, "Heap Gate": {2: 0}, "Krark-Clan Shaman": {0: 0}, "Lembas": {0: 0},
	"Lórien Revealed": {1: 0}, "Makeshift Munitions": {0: 0}, "Masked Meower": {0: 0},
	"Nihil Spellbomb": {0: 0}, "Quirion Ranger": {0: 0}, "Sacred Cat": {0: 0}, "Tinder Wall": {1: 0},
	"Troll of Khazad-dûm": {0: 0}, "Twisted Landscape": {1: 0, 2: 1},
	// Tokens the catalog makes.
	"Blood Token": {0: 0}, "Clue Token": {0: 0}, "Food Token": {0: 0}, "Map Token": {0: 0},
}

// sweepMethod is the Section 7.4 method expected for each cast mode the
// catalog offers; a mode outside it fails the sweep.
func sweepMethod(o decision.Option) (string, bool) {
	switch {
	case o.Mode == "" && o.AltCostIndex > 0:
		return "alternative", true
	case o.Mode == "" || o.Mode == "mayplay" || o.Mode == "kicked":
		return "normal", true
	case o.Mode == "flashback":
		return "flashback", true
	case o.Mode == "plot_cast":
		return "plot", true
	case o.Mode == "bestowed":
		return "alternative", true
	}
	return "", false
}

var optionalModes = map[string]string{"kicked": "kicker"}

// prioritySweep checks every priority decision of real games against its
// native decision, and records what it met so the test can insist the games
// still reach every shape it pins.
type prioritySweep struct {
	t    *testing.T
	n    int
	seen map[string]bool
}

func (s *prioritySweep) check(env *mapping.Env, d *decision.Decision) {
	t := s.t
	t.Helper()
	s.n++
	_, p := mustPose(t, env, d)
	checkPriorityShape(t, p, d)
	if _, again := mustPose(t, env, d); semJSON(again.Candidates) != semJSON(p.Candidates) {
		t.Fatalf("re-pose differs:\n%s\n%s", semJSON(p.Candidates), semJSON(again.Candidates))
	}
	covered := map[int]int{}
	for i, c := range p.Candidates {
		if err := c.Sem.Check(); err != nil || !protocol.PriorityKinds[c.Sem.Kind] || c.Hidden {
			t.Fatalf("candidate %d %s: %v", i, semJSON(c.Sem), err)
		}
		switch c.Op.Op {
		case "choose":
			if c.Op.Option < 0 || c.Op.Option >= len(d.Options) || len(c.Op.Covers) != 0 {
				t.Fatalf("candidate %d op %s", i, semJSON(c.Op))
			}
			covered[c.Op.Option]++
			s.consistent(env, d, c, d.Options[c.Op.Option])
		case "cast":
			s.castGroup(env, d, c)
			for _, k := range c.Op.Covers {
				covered[k]++
			}
		default:
			t.Fatalf("candidate %d op %s", i, semJSON(c.Op))
		}
		if i == s.n%len(p.Candidates) || c.Sem.Kind == "activate_ability" || c.Op.Op == "cast" {
			s.answer(env, d, i, c)
		}
	}
	for _, o := range d.Options {
		n := covered[o.Index]
		switch {
		case o.Kind == "concede":
			if n != 0 {
				t.Fatalf("concede is a candidate: %s", semJSON(p.Candidates))
			}
			s.seen["concede"] = true
		case o.Kind == "activate":
			if n == 0 {
				t.Fatalf("activate option %d has no candidate", o.Index)
			}
		case n != 1:
			t.Fatalf("native %s/%s option %d is covered %d times: %s", o.Kind, o.Mode, o.Index, n, semJSON(p.Candidates))
		}
	}
}

// consistent checks a "choose" candidate against the native option it commits.
func (s *prioritySweep) consistent(env *mapping.Env, d *decision.Decision, c mapping.Cand, o decision.Option) {
	t := s.t
	t.Helper()
	ref, err := env.Obs.Ref(d.Player, o.Obj)
	same := err == nil && ref != nil && reflect.DeepEqual(source(c), *ref)
	ok := false
	switch c.Sem.Kind {
	case "pass":
		ok = o.Kind == "pass"
	case "play_land":
		face := uint32(0)
		if o.Mode == "modal_land" {
			face = 1
		}
		ok = o.Kind == "play_land" && same && c.Sem.Fields["face"] == face
		s.seen["play_land"] = true
	case "cast_spell":
		want, known := sweepMethod(o)
		ok = o.Kind == "cast" && same && known && c.Sem.Fields["method"] == want
		s.seen["method:"+want] = true
		s.seen["mode:"+o.Mode] = true
	case "activate_ability":
		f := env.G.E.G.Obj(o.Obj).Face()
		want, known := oracleAbility[f.Name][o.Ability]
		ok = o.Kind == "ability" && same && known && c.Sem.Fields["ability_index"] == want
		s.seen[fmt.Sprintf("ability:%s#%d", f.Name, o.Ability)] = true
	case "special_action":
		a := c.Sem.Fields["action"]
		ok = same && ((o.Kind == "cast" && o.Mode == "plot" && a == "plot") ||
			(o.Kind == "turn_face_up" && a == "turn_face_up") || (o.Kind == "unlock" && a == "unlock_door"))
		s.seen["action:"+fmt.Sprint(a)] = true
	case "activate_mana_ability":
		ok = o.Kind == "activate" && same
		s.seen["activate"] = true
	}
	if !ok {
		t.Fatalf("candidate %s %s does not match native %+v", semJSON(c.Sem), semJSON(c.Op), o)
	}
}

// castGroup checks a "cast" candidate: one optional-cost variant and at most
// one plain variant of its own object, all of its method.
func (s *prioritySweep) castGroup(env *mapping.Env, d *decision.Decision, c mapping.Cand) {
	t := s.t
	t.Helper()
	optional := 0
	for _, k := range c.Op.Covers {
		o := d.Options[k]
		ref, err := env.Obs.Ref(d.Player, o.Obj)
		want, known := sweepMethod(o)
		if err != nil || ref == nil || !reflect.DeepEqual(source(c), *ref) || o.Kind != "cast" || !known || c.Sem.Fields["method"] != want {
			t.Fatalf("cast candidate %s covers native %+v", semJSON(c.Sem), o)
		}
		if _, ok := optionalModes[o.Mode]; ok {
			optional++
		}
	}
	if c.Sem.Kind != "cast_spell" || c.Op.Option != -1 || optional != 1 || len(c.Op.Covers) > 2 {
		t.Fatalf("cast candidate %s %s", semJSON(c.Sem), semJSON(c.Op))
	}
	s.seen["follow-up"] = true
}

// answer answers candidate i on a fresh transaction: a choose commits its
// native option and folded follow-ups; a cast poses the optional-cost
// follow-up, whose answers commit the paid and the plain variant.
func (s *prioritySweep) answer(env *mapping.Env, d *decision.Decision, i int, c mapping.Cand) {
	t := s.t
	t.Helper()
	if c.Op.Op == "cast" {
		var paid, plain = -1, -1
		cost := ""
		for _, k := range c.Op.Covers {
			if w, ok := optionalModes[d.Options[k].Mode]; ok {
				paid, cost = k, w
			} else {
				plain = k
			}
		}
		pays := []bool{true, false}
		if plain < 0 {
			pays = pays[:1]
		}
		tx, _ := mustPose(t, env, d)
		if commit, done, err := tx.Answer(i); err != nil || done || commit != nil {
			t.Fatalf("cast answer: commit %v, done %v, err %v", commit, done, err)
		}
		f, err := tx.Pose()
		if err != nil {
			t.Fatal(err)
		}
		checkFollowup(t, f, d, source(c), cost, pays...)
		if got := answerFollowup(t, env, d, i, true); !reflect.DeepEqual(got, []decision.Intent{mapping.Intent(d, paid)}) {
			t.Fatalf("pay true commits %v, want %d", got, paid)
		}
		if plain >= 0 {
			if got := answerFollowup(t, env, d, i, false); !reflect.DeepEqual(got, []decision.Intent{mapping.Intent(d, plain)}) {
				t.Fatalf("pay false commits %v, want %d", got, plain)
			}
		}
		return
	}
	tx, _ := mustPose(t, env, d)
	commit, done, err := tx.Answer(i)
	want := []decision.Intent{mapping.Intent(d, c.Op.Option)}
	for _, f := range c.Op.Followup {
		want = append(want, decision.Intent{Choices: []int{f}})
	}
	if err != nil || !done || !reflect.DeepEqual(commit, want) {
		t.Fatalf("candidate %s commits %v, done %v, err %v; want %v", semJSON(c.Sem), commit, done, err, want)
	}
}

// TestPriorityRealGames checks every priority decision of two real games
// that between them reach Twisted Landscape's search and cycling
// (ability_index 0 and 1), Heap Gate's token ability after two mana
// abilities, Lórien Revealed's islandcycling after its spell ability,
// play_land, activate, flashback, Fireblast's alternative cost, may-play,
// plot, and a kicker follow-up. Bots rarely reach plot_cast and bestow;
// TestCastMethodTable pins those.
func TestPriorityRealGames(t *testing.T) {
	reg := testcorpus.Registry(t)
	s := &prioritySweep{t: t, seen: map[string]bool{}}
	for _, game := range []struct {
		d0, d1 string
		seed   byte
	}{{"Wildfire", "CawGates", 3}, {"Burn", "Rally", 4}} {
		g := testgame.New(t, reg, game.d0, game.d1, game.seed, "none")
		tr := identity.New(g.E, g.Secret)
		testgame.RunUntil(t, g, testgame.Bots(uint64(game.seed)), func(e *rules.Engine) bool {
			if err := tr.Sync(e); err != nil {
				t.Fatal(err)
			}
			if d := e.Pending(); d != nil && d.Kind == decision.KPriority {
				s.check(&mapping.Env{G: g, IDs: tr, Obs: &observe.Projector{E: g.E, IDs: tr}, Slots: map[string]uint32{}}, d)
			}
			return false
		}, 200000)
		if !g.E.G.Over {
			t.Fatalf("%s vs %s seed %d did not end", game.d0, game.d1, game.seed)
		}
	}
	for _, want := range []string{"concede", "play_land", "activate", "ability:Twisted Landscape#1",
		"ability:Twisted Landscape#2", "ability:Heap Gate#2", "ability:Lórien Revealed#1", "method:normal",
		"method:flashback", "method:alternative", "mode:mayplay", "action:plot", "follow-up"} {
		if !s.seen[want] {
			t.Errorf("the games no longer reach %s", want)
		}
	}
	t.Logf("%d priority decisions", s.n)
}
