package strategies

import (
	"encoding/json"
	"os"
	"reflect"
	"testing"

	"github.com/adams-shaun/gorge/cards"
	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/events"
	"github.com/adams-shaun/gorge/internal/searchprobe"
	"github.com/adams-shaun/gorge/internal/testutil"
	"github.com/adams-shaun/gorge/rules"
	"github.com/adams-shaun/gorge/state"
)

func TestPublicRedealDistinguishesSameSourceManaAndStackAbility(t *testing.T) {
	checkPublicLandscapeReplay(t, false)
}

func TestPublicRedealRetainsOpponentsHandAcrossShuffle(t *testing.T) {
	checkPublicLandscapeReplay(t, true)
}

func checkPublicLandscapeReplay(t *testing.T, held bool) {
	t.Helper()
	setup, h := publicLandscapeHistory(t, false, held)
	_, other := publicLandscapeHistory(t, true, held)
	a, _ := json.Marshal(h)
	b, _ := json.Marshal(other)
	if string(a) != string(b) {
		t.Fatal("unseen library tail changed public history")
	}
	opts := searchprobe.SampleOptions{Seed: 54321, Attempts: 64, Worlds: 8, MaxSubmits: 5000, KnownCards: true}
	before, err := searchprobe.Sample(setup, h, opts)
	if err != nil {
		t.Fatal(err)
	}
	opts.Redeal = &searchprobe.RedealBase{SpellbenchPublic: true}
	after, err := searchprobe.Sample(setup, h, opts)
	if err != nil || len(after.Worlds) != 8 || after.RedealRefused != "" || after.PublicReconstruction == nil || after.PublicReconstruction.BudgetExhausted != 0 || after.PublicReconstruction.Submits > opts.MaxSubmits {
		t.Fatalf("land's distinct activations did not replay: %v worlds=%d refused=%s work=%+v", err, len(after.Worlds), after.RedealRefused, after.PublicReconstruction)
	}
	a, _ = json.Marshal(before)
	b, _ = json.Marshal(after)
	var left, right map[string]any
	json.Unmarshal(a, &left)
	json.Unmarshal(b, &right)
	for _, key := range []string{"PublicReconstruction", "RedealRefused", "Redealt"} {
		delete(left, key)
		delete(right, key)
	}
	if !reflect.DeepEqual(left, right) {
		for key, value := range left {
			if !reflect.DeepEqual(value, right[key]) {
				t.Logf("changed field %s: before=%v after=%v", key, value, right[key])
			}
		}
		t.Fatal("ability witness changed native sampler diagnostics")
	}
	known, err := searchprobe.ProjectKnownCards(h)
	if err != nil {
		t.Fatal(err)
	}
	for _, world := range after.Worlds {
		if err := known.Holds(world); err != nil {
			t.Fatal(err)
		}
	}
	t.Logf("frames=%d worlds=%d work=%+v", len(h.Frames), len(after.Worlds), after.PublicReconstruction)
}

// The real land first taps for mana, then sacrifices to its other ability on
// the actor's draw step. Every answer is legal; the opponent's asks stay private.
func publicLandscapeHistory(t *testing.T, swap, held bool) (PublicGame, History) {
	t.Helper()
	reg, err := testutil.OpenCorpusRegistry(os.Getenv("GORGE_CARDS"))
	if err != nil {
		t.Fatal(err)
	}
	lookup := func(name string) *cards.Card {
		card, ok := reg.Lookup(name)
		if !ok {
			t.Fatal(name)
		}
		return card
	}
	quiet := fixtureCard(t, "Name:Quiet Ability Artifact\nManaCost:99\nTypes:Artifact\nOracle:Fixture.\n")
	decks := [][]*cards.Card{make([]*cards.Card, 24), make([]*cards.Card, 24)}
	for p := range decks {
		for i := range decks[p] {
			decks[p][i] = quiet
		}
		decks[p][22] = lookup("Island")
	}
	decks[1][0], decks[1][1], decks[1][2] = lookup("Twisted Landscape"), lookup("Forest"), lookup("Mountain")
	if held {
		decks[1][3] = fixtureCard(t, "Name:Held Flash Artifact\nManaCost:0\nTypes:Artifact\nK:Flash\nOracle:Fixture.\n")
	}
	setup := PublicGame{Names: []string{"p0", "p1"}, Decks: decks, Tokens: reg.Tokens, StartingLife: 20, Mulligans: 1}
	e, err := rules.NewHypotheticalPlanned(rules.Config{Seed: 17, Names: setup.Names, Decks: setup.Decks, Tokens: setup.Tokens, StartingLife: 20, Mulligans: 1},
		[]rules.ChanceDraw{{Bound: 2, Value: 0}}, func(ctx rules.ShuffleContext) ([]state.ObjID, error) {
			if ctx.Ordinal != 0 {
				return nil, nil
			}
			var order []state.ObjID
			for _, card := range ctx.Library {
				order = append(order, card.ID)
			}
			if swap {
				order[22], order[23] = order[23], order[22]
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
	played, floated, activated, shuffled := false, false, false, false
	heldCast := false
	for step := 0; step < 350 && !e.G.Over; step++ {
		d := e.Pending()
		driver.Observe(e)
		if shuffled && (!held || heldCast) && d.Player == 0 {
			if !played || !floated || !activated {
				t.Fatal("fixture omitted one of the land's legal activations")
			}
			return setup, canonicalJSONHistory(t, PublicHistory(driver.seats[0].h))
		}
		in := decision.Intent{Seq: d.Seq, Player: d.Player}
		if d.Kind == decision.KArrange {
			for i := range d.Options {
				in.Choices = append(in.Choices, i)
			}
		} else {
			for i, option := range d.Options {
				if option.Kind == "keep" || option.Kind == "pass" {
					in.Choices = []int{i}
				}
			}
		}
		if d.Player == 1 && d.Kind == decision.KPriority {
			for i, option := range d.Options {
				o := e.G.Obj(option.Obj)
				if held && shuffled && !heldCast && option.Kind == "cast" && o != nil && o.Card != nil && o.Card.Faces[0].Name == "Held Flash Artifact" {
					in.Choices, heldCast = []int{i}, true
					break
				}
				if o == nil || o.Card == nil || o.Card.Faces[0].Name != "Twisted Landscape" {
					continue
				}
				if !played && option.Kind == "play_land" {
					in.Choices, played = []int{i}, true
					break
				}
				if played && !floated && option.Kind == "activate" {
					in.Choices, floated = []int{i}, true
					break
				}
				if floated && !activated && e.G.Turn >= 3 && e.G.Active == 0 && e.G.Step == state.StepDraw && option.Kind == "ability" && option.Ability == 1 {
					in.Choices, activated = []int{i}, true
					break
				}
			}
		}
		if len(in.Choices) == 0 && d.Min > 0 {
			for i := 0; i < d.Min; i++ {
				in.Choices = append(in.Choices, i)
			}
		}
		if err := d.Validate(in); err != nil {
			t.Fatalf("legal land fixture: %v decision=%+v intent=%+v", err, d, in)
		}
		if err := driver.RecordAnswer(d, in); err != nil {
			t.Fatal(err)
		}
		pos := len(e.L.Events)
		if err := e.SubmitHypothetical(in); err != nil {
			t.Fatal(err)
		}
		for _, ev := range e.L.Events[pos:] {
			shuffled = shuffled || ev.Kind == events.Shuffle && ev.Player == 1
		}
	}
	t.Fatalf("land fixture did not reach shuffle: played=%v floated=%v activated=%v turn=%d", played, floated, activated, e.G.Turn)
	return setup, History{}
}
