package strategies

import (
	"context"
	"encoding/json"
	"reflect"
	"testing"

	"github.com/adams-shaun/gorge/cards"
	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/internal/searchprobe"
	"github.com/adams-shaun/gorge/internal/searchseat"
	"github.com/adams-shaun/gorge/rules"
	"github.com/adams-shaun/gorge/seat"
	"github.com/adams-shaun/gorge/state"
	"github.com/adams-shaun/gorge/view"
)

// The opponent legally passes every priority, despite holding only lands.
// Its public behavior cannot be replayed by the native land-playing policy.
// Both source seeds have the same own draws and different hidden land deals.
func redealFixture(t *testing.T, seed uint64) (*rules.Engine, PublicGame, *Driver, History) {
	t.Helper()
	_, setup := fixture(t, seed, true)
	mountain := setup.Decks[0][0]
	forest := fixtureCard(t, "Name:Forest\nTypes:Basic Land Forest\nOracle:Fixture.\n")
	opponent := make([]*cards.Card, 20)
	for i := range opponent {
		opponent[i] = mountain
		if i%2 == 0 {
			opponent[i] = forest
		}
	}
	setup.Decks[1] = opponent
	e, err := rules.NewHypotheticalPlanned(rules.Config{Seed: seed, Names: setup.Names, Decks: setup.Decks, StartingLife: 20}, []rules.ChanceDraw{{Bound: 2, Value: 0}}, func(ctx rules.ShuffleContext) ([]state.ObjID, error) {
		if ctx.Player != 0 {
			return nil, nil
		}
		// Four lands and three creatures in the actor's opening hand.
		order := []state.ObjID{ctx.Library[0].ID, ctx.Library[1].ID, ctx.Library[2].ID, ctx.Library[3].ID, ctx.Library[12].ID, ctx.Library[13].ID, ctx.Library[14].ID}
		for _, c := range ctx.Library {
			seen := false
			for _, id := range order {
				seen = seen || id == c.ID
			}
			if !seen {
				order = append(order, c.ID)
			}
		}
		return order, nil
	})
	if err != nil {
		t.Fatal(err)
	}
	if err := e.AdvanceHypothetical(); err != nil {
		t.Fatal(err)
	}
	driver := NewDriver()
	bot := seat.NewBot(3)
	for n := 0; n < 160 && !e.G.Over; n++ {
		d := e.Pending()
		driver.Observe(e)
		if d.Player == 0 && d.Kind == decision.KAttackers && len(d.Options) > 0 {
			return e, setup, driver, PublicHistory(driver.seats[0].h)
		}
		in, err := bot.Decide(context.Background(), view.Project(e.G, e, d.Player, d), *d)
		if err != nil {
			t.Fatal(err)
		}
		if d.Player == 1 && d.Kind == decision.KPriority {
			for i, o := range d.Options {
				if o.Kind == "pass" {
					in.Choices = []int{i}
					break
				}
			}
		}
		if d.Player == 1 && d.Kind == decision.KChoose && len(d.Options) > 0 && d.Options[0].Kind == "discard" {
			// Discards are public. Keep those actions fixed while varying
			// the opponent cards that remain hidden.
			in.Choices = nil
			for i, o := range d.Options {
				if e.G.Obj(o.Obj).Card.Faces[0].Name == "Mountain" && len(in.Choices) < d.Min {
					in.Choices = append(in.Choices, i)
				}
			}
			if len(in.Choices) != d.Min {
				t.Fatal("fixture cannot match its public discard")
			}
		}
		if err := driver.RecordAnswer(d, in); err != nil {
			t.Fatal(err)
		}
		if err := e.SubmitHypothetical(in); err != nil {
			t.Fatal(err)
		}
	}
	t.Fatal("fixture never reached an attacking actor")
	return nil, setup, driver, History{}
}

func TestPublicRedealReconstructsZeroAcceptedNativeProposals(t *testing.T) {
	e, setup, driver, h := redealFixture(t, 17)
	h = canonicalJSONHistory(t, h)
	opts := searchprobe.SampleOptions{Seed: 54321, Attempts: 64, Worlds: 8, MaxSubmits: 5000}
	plain, err := searchprobe.Sample(setup, h, opts)
	if err != nil || plain.Accepted != 0 || len(plain.Worlds) != 0 {
		t.Fatalf("fixture must starve native-policy replay: %v %+v", err, plain)
	}
	opts.Redeal = &searchprobe.RedealBase{SpellbenchPublic: true}
	public, err := searchprobe.Sample(setup, h, opts)
	if err != nil || public.Accepted != 0 || public.Redealt != 8 || len(public.Worlds) != 8 || public.PublicReconstruction == nil || public.PublicReconstruction.Submits == 0 {
		t.Fatalf("public reconstruction did not supply redealt worlds: %v %+v", err, public)
	}
	if public.RedealRefused != "" || public.PublicReconstruction.BudgetExhausted != 0 || public.PublicReconstruction.Submits > opts.MaxSubmits {
		t.Fatalf("invalid public reconstruction result: %+v", public)
	}
	// Compare the teacher's actual decision and values against native redeal
	// from the source engine, using identical candidates and rollout settings.
	d := e.Pending()
	v := view.Project(e.G, e, d.Player, d)
	v.Round = view.RoundOf(e.G, e.L.Events)
	base, err := seat.NewBot(19).Decide(context.Background(), v, *d)
	if err != nil {
		t.Fatal(err)
	}
	native := searchseat.Defaults()
	native.Redeal = true
	want, _, nativeTrace := searchseat.Choose(setup, h, driver.seats[0].c, e, d, base, h.Frames[len(h.Frames)-1], native)
	aliases := map[uint32]uint32{}
	for _, o := range d.Options {
		for _, id := range []state.ObjID{o.Obj, o.Attacker} {
			if ref := driver.seats[0].c.SpellbenchAlias(id); ref != 0 {
				aliases[uint32(id)] = ref
			}
		}
	}
	search := NewRedealSearch(19, false)
	got, trace, err := search.DecideObserved(context.Background(), v, *d, setup, h, Delta{Live: true, Aliases: aliases})
	if err != nil || !reflect.DeepEqual(got, want) || !reflect.DeepEqual(trace.Values, nativeTrace.Values) || trace.Index != nativeTrace.Index || trace.Rollouts != nativeTrace.Rollouts {
		t.Fatalf("public/native redeal answer mismatch: %v\n%+v %+v\n%+v %+v", err, got, want, trace, nativeTrace)
	}
	if !trace.Covered || trace.Accepted != 0 || trace.Redealt != 8 || trace.Terminal == 0 || trace.PublicReconstruction == nil {
		t.Fatalf("fixture did not exercise public redeal search: %+v", trace)
	}
	t.Logf("native accepted=%d redealt=%d public attempts=%d submits=%d rollouts=%d terminal=%d capped=%d", trace.Accepted, trace.Redealt, trace.PublicReconstruction.Attempts, trace.PublicReconstruction.Submits, trace.Rollouts, trace.Terminal, trace.Capped)
}

func TestPublicRedealIgnoresDifferentHiddenDealsAndFutureSeeds(t *testing.T) {
	a, setup, _, ha := redealFixture(t, 17)
	b, _, _, hb := redealFixture(t, 83)
	if !reflect.DeepEqual(ha, hb) {
		for i := range ha.Frames {
			if i >= len(hb.Frames) {
				t.Fatal("source frame count changed")
			}
			if !reflect.DeepEqual(ha.Frames[i], hb.Frames[i]) {
				aa, _ := json.Marshal(ha.Frames[i])
				bb, _ := json.Marshal(hb.Frames[i])
				t.Fatalf("source public frame %d changed: %s\n%s", i, aa, bb)
			}
		}
		t.Fatal("source actor answers changed")
	}
	if a.L.Head() == b.L.Head() {
		t.Fatal("source fixture lacks distinct hidden histories")
	}
	handNames := func(e *rules.Engine) []string {
		var out []string
		for _, id := range e.G.Zone(state.ZHand, 1) {
			out = append(out, e.G.Obj(id).Card.Faces[0].Name)
		}
		return out
	}
	if reflect.DeepEqual(handNames(a), handNames(b)) {
		t.Fatal("source fixture lacks distinct hidden card names")
	}
	opts := searchprobe.SampleOptions{Seed: 54321, Attempts: 64, Worlds: 8, MaxSubmits: 5000, Redeal: &searchprobe.RedealBase{SpellbenchPublic: true}}
	wa, err := searchprobe.Sample(setup, ha, opts)
	if err != nil {
		t.Fatal(err)
	}
	wb, err := searchprobe.Sample(setup, hb, opts)
	if err != nil {
		t.Fatal(err)
	}
	if wa.Redealt != 8 || wb.Redealt != 8 || !reflect.DeepEqual(wa.PublicReconstruction, wb.PublicReconstruction) {
		t.Fatal("public redeal did not reproduce")
	}
	for i := range wa.Worlds {
		if wa.Worlds[i].Engine.L.Head() != wb.Worlds[i].Engine.L.Head() || !reflect.DeepEqual(handNames(wa.Worlds[i].Engine), handNames(wb.Worlds[i].Engine)) {
			t.Fatal("hidden source state affected reconstructed worlds")
		}
	}
}

func TestPublicRedealReconstructionBudgetFailsClosed(t *testing.T) {
	_, setup, _, h := redealFixture(t, 17)
	opts := searchprobe.SampleOptions{Seed: 54321, Attempts: 64, Worlds: 8, MaxSubmits: 1}
	root, work, err := searchprobe.SpellbenchReconstructRedeal(setup, h, opts)
	if err == nil || root != nil || work.Submits != 1 || work.BudgetExhausted != 1 {
		t.Fatalf("budget exhaustion returned a root: %v %+v %+v", err, work, root)
	}
}
