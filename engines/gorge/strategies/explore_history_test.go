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

// Both histories are produced through legal engine decisions. Only the
// actor's unseen library tail changes. A London bottom and a Map creation
// precede the explore, whose pending, land and nonland outcomes stay visible.
func TestPublicActorExploreAfterLondonAndToken(t *testing.T) {
	for _, outcome := range []string{"land", "top", "graveyard", "pending"} {
		t.Run(outcome, func(t *testing.T) {
			setup, history := actorExploreHistory(t, outcome, false)
			_, other := actorExploreHistory(t, outcome, true)
			first, _ := json.Marshal(history)
			second, _ := json.Marshal(other)
			if string(first) != string(second) {
				t.Fatal("unobserved library tail changed actor history")
			}
			opts := searchprobe.SampleOptions{Seed: 54321, Attempts: 64, Worlds: 8, MaxSubmits: 5000, KnownCards: true}
			root, work, err := searchprobe.SpellbenchReconstructRedeal(setup, history, opts)
			if err != nil || root == nil || work.BudgetExhausted != 0 || work.Submits >= opts.MaxSubmits {
				t.Fatalf("explore reconstruction: %v work=%+v", err, work)
			}
			before, err := searchprobe.Sample(setup, history, opts)
			if err != nil {
				t.Fatal(err)
			}
			opts.Redeal = &searchprobe.RedealBase{SpellbenchPublic: true}
			after, err := searchprobe.Sample(setup, history, opts)
			if err != nil || len(after.Worlds) != opts.Worlds || after.RedealRefused != "" {
				t.Fatalf("explore replay: %v worlds=%d native_accepted=%d refused=%s", err, len(after.Worlds), after.Accepted, after.RedealRefused)
			}
			// The reconstruction supplements the native sampler. Every native
			// diagnostic must remain identical for the same visible input.
			a, _ := json.Marshal(before)
			b, _ := json.Marshal(after)
			var left, right map[string]any
			json.Unmarshal(a, &left)
			json.Unmarshal(b, &right)
			delete(left, "RedealRefused")
			delete(right, "RedealRefused")
			delete(left, "PublicReconstruction")
			delete(right, "PublicReconstruction")
			delete(left, "Redealt")
			delete(right, "Redealt")
			if !reflect.DeepEqual(left, right) {
				t.Fatal("public witness changed native sampler diagnostics")
			}
			known, err := searchprobe.ProjectKnownCards(history)
			if err != nil {
				t.Fatal(err)
			}
			if err := known.Holds(searchprobe.World{Engine: root.Engine, Observer: root.Observer}); err != nil {
				t.Fatal(err)
			}
			for _, world := range after.Worlds {
				if err := known.Holds(world); err != nil {
					t.Fatal(err)
				}
			}
			t.Logf("frames=%d reconstruction=%+v native_accepted=%d", len(history.Frames), work, after.Accepted)
		})
	}
}

func actorExploreHistory(t *testing.T, outcome string, swapTail bool) (PublicGame, History) {
	t.Helper()
	registry, err := testutil.OpenCorpusRegistry(os.Getenv("GORGE_CARDS"))
	if err != nil {
		t.Fatal(err)
	}
	scout := fixtureCard(t, "Name:Public Explore Scout\nManaCost:0\nTypes:Creature Scout\nPT:1/1\nA:AB$ Token | Cost$ 0 | TokenScript$ c_a_map_sac_explore\nA:AB$ Explore | Cost$ 0 | Defined$ Self\nOracle:Fixture.\n")
	quiet := fixtureCard(t, "Name:Quiet Explore Artifact\nManaCost:99\nTypes:Artifact\nOracle:Fixture.\n")
	forest, ok := registry.Lookup("Forest")
	if !ok {
		t.Fatal("Forest")
	}
	actor, opponent := make([]*cards.Card, 24), make([]*cards.Card, 24)
	for i := range actor {
		actor[i], opponent[i] = quiet, quiet
	}
	actor[0], actor[22] = scout, forest
	if outcome == "land" {
		actor[7] = forest
	}
	setup := PublicGame{Names: []string{"p0", "p1"}, Decks: [][]*cards.Card{actor, opponent}, Tokens: registry.Tokens, StartingLife: 20, Mulligans: 1}
	engine, err := rules.NewHypotheticalPlanned(rules.Config{Seed: 17, Names: setup.Names, Decks: setup.Decks, Tokens: setup.Tokens, StartingLife: 20, Mulligans: 1},
		[]rules.ChanceDraw{{Bound: 2, Value: 0}}, func(ctx rules.ShuffleContext) ([]state.ObjID, error) {
			byName := map[string][]state.ObjID{}
			for _, card := range ctx.Library {
				byName[card.Name] = append(byName[card.Name], card.ID)
			}
			var order []state.ObjID
			for _, card := range setup.Decks[ctx.Player] {
				name := card.Faces[0].Name
				if len(byName[name]) == 0 {
					t.Fatal("fixture shuffle lacks ", name)
				}
				order = append(order, byName[name][0])
				byName[name] = byName[name][1:]
			}
			if swapTail && ctx.Player == 0 {
				order[22], order[23] = order[23], order[22]
			}
			return order, nil
		})
	if err != nil {
		t.Fatal(err)
	}
	if err := engine.AdvanceHypothetical(); err != nil {
		t.Fatal(err)
	}
	driver := NewDriver()
	mulligan, tokenRequested, token, activated := false, false, false, false
	for step := 0; step < 350 && !engine.G.Over; step++ {
		d := engine.Pending()
		driver.Observe(engine)
		for _, event := range engine.L.Events {
			token = token || event.Kind == events.TokenCreate
		}
		if activated && d.Player == 0 {
			if outcome == "pending" && d.Kind == decision.KChoose && len(d.Options) == 2 && d.Options[0].Kind == "graveyard" && d.Options[1].Kind == "top" {
				return setup, canonicalJSONHistory(t, PublicHistory(driver.seats[0].h))
			}
			if d.Kind == decision.KPriority && engine.G.Turn >= 3 {
				if !mulligan || !token {
					t.Fatal("fixture skipped London or token")
				}
				found := false
				for _, event := range engine.L.Events {
					found = found || event.Kind == events.Explore
				}
				if !found {
					t.Fatal("fixture did not finish explore")
				}
				return setup, canonicalJSONHistory(t, PublicHistory(driver.seats[0].h))
			}
		}
		choice := -1
		for i, option := range d.Options {
			if d.Kind == decision.KMulligan && option.Kind == "keep" {
				choice = i
			}
			if d.Kind == decision.KMulligan && option.Kind == "mulligan" && d.Player == 0 && !mulligan {
				choice, mulligan = i, true
			}
			if option.Kind == "bottom" && engine.G.Obj(option.Obj).Card.Faces[0].Name == quiet.Faces[0].Name {
				choice = i
			}
			if option.Kind == "pass" {
				choice = i
			}
		}
		if d.Player == 0 && d.Kind == decision.KPriority {
			for i, option := range d.Options {
				if option.Kind == "cast" && engine.G.Obj(option.Obj).Card.Faces[0].Name == scout.Faces[0].Name {
					choice = i
				}
				if option.Kind == "ability" && engine.G.Obj(option.Obj).Card.Faces[0].Name == scout.Faces[0].Name {
					api := scout.Faces[0].Abilities[option.Ability].API
					if !tokenRequested && api == "Token" {
						choice, tokenRequested = i, true
						break
					}
					if token && !activated && api == "Explore" {
						choice, activated = i, true
						break
					}
				}
			}
		}
		if d.Kind == decision.KChoose {
			for i, option := range d.Options {
				if option.Kind == outcome {
					choice = i
				}
			}
		}
		if choice < 0 {
			choice = 0
		}
		intent := decision.Intent{Seq: d.Seq, Player: d.Player, Choices: []int{choice}}
		if err := d.Validate(intent); err != nil {
			t.Fatalf("fixture intent: %v decision=%+v", err, d)
		}
		if err := driver.RecordAnswer(d, intent); err != nil {
			t.Fatal(err)
		}
		if err := engine.SubmitHypothetical(intent); err != nil {
			t.Fatal(err)
		}
	}
	t.Fatalf("fixture did not reach explore: mulligan=%v tokenRequested=%v token=%v activated=%v turn=%d over=%v", mulligan, tokenRequested, token, activated, engine.G.Turn, engine.G.Over)
	return setup, History{}
}
