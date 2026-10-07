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

// A London-bottomed opponent makes a token, then casts a visible draw spell.
// Its spell on the stack and a later land constrain only public draw history.
// Swapping two unseen opponent cards must leave the complete actor history
// and every native sampler diagnostic unchanged.
func TestPublicLondonOpponentTokenAndStack(t *testing.T) {
	for _, ending := range []string{"stack", "land"} {
		t.Run(ending, func(t *testing.T) {
			setup, history := londonTokenHistory(t, ending, false)
			_, other := londonTokenHistory(t, ending, true)
			left, _ := json.Marshal(history)
			right, _ := json.Marshal(other)
			if string(left) != string(right) {
				t.Fatal("unseen opponent library tail changed actor history")
			}
			opts := searchprobe.SampleOptions{Seed: 54321, Attempts: 64, Worlds: 8, MaxSubmits: 5000, KnownCards: true}
			root, work, err := searchprobe.SpellbenchReconstructRedeal(setup, history, opts)
			if err != nil || root == nil || work.BudgetExhausted != 0 || work.Submits >= opts.MaxSubmits {
				t.Fatalf("London token/stack reconstruction: %v work=%+v", err, work)
			}
			before, err := searchprobe.Sample(setup, history, opts)
			if err != nil {
				t.Fatal(err)
			}
			opts.Redeal = &searchprobe.RedealBase{SpellbenchPublic: true}
			after, err := searchprobe.Sample(setup, history, opts)
			if err != nil || len(after.Worlds) != opts.Worlds || after.RedealRefused != "" {
				t.Fatalf("London token/stack sampling: %v worlds=%d refused=%s", err, len(after.Worlds), after.RedealRefused)
			}
			first, _ := json.Marshal(before)
			second, _ := json.Marshal(after)
			var nativeBefore, nativeAfter map[string]any
			json.Unmarshal(first, &nativeBefore)
			json.Unmarshal(second, &nativeAfter)
			for _, key := range []string{"PublicReconstruction", "Redealt", "RedealRefused"} {
				delete(nativeBefore, key)
				delete(nativeAfter, key)
			}
			if !reflect.DeepEqual(nativeBefore, nativeAfter) {
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

func londonTokenHistory(t *testing.T, ending string, swapTail bool) (PublicGame, History) {
	t.Helper()
	registry, err := testutil.OpenCorpusRegistry(os.Getenv("GORGE_CARDS"))
	if err != nil {
		t.Fatal(err)
	}
	lookup := func(name string) *cards.Card {
		card, ok := registry.Lookup(name)
		if !ok {
			t.Fatal(name)
		}
		return card
	}
	maker := fixtureCard(t, "Name:Public Map Maker\nManaCost:0\nTypes:Sorcery\nA:SP$ Token | Cost$ 0 | TokenScript$ c_a_map_sac_explore\nOracle:Fixture.\n")
	draw := fixtureCard(t, "Name:Public London Draw\nManaCost:0\nTypes:Instant\nA:SP$ Draw | Cost$ 0 | NumCards$ 2\nOracle:Fixture.\n")
	quiet := fixtureCard(t, "Name:Quiet London Token Artifact\nManaCost:99\nTypes:Artifact\nOracle:Fixture.\n")
	actor, opponent := make([]*cards.Card, 24), make([]*cards.Card, 24)
	for i := range actor {
		actor[i], opponent[i] = quiet, quiet
	}
	opponent[0], opponent[1], opponent[10] = maker, draw, lookup("Mountain")
	opponent[22], opponent[23] = lookup("Forest"), lookup("Swamp")
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
			if swapTail && ctx.Player == 1 {
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
	mulligan, made, cast, played := false, false, false, false
	for step := 0; step < 350 && !engine.G.Over; step++ {
		d := engine.Pending()
		driver.Observe(engine)
		token := false
		for _, event := range engine.L.Events {
			token = token || event.Kind == events.TokenCreate
		}
		if d.Player == 0 && d.Kind == decision.KPriority && cast {
			for _, item := range engine.G.Stack {
				object := engine.G.Obj(item)
				if ending == "stack" && object != nil && object.Card != nil && object.Card.Faces[0].Name == draw.Faces[0].Name {
					if !mulligan || !token {
						t.Fatal("fixture skipped London bottoming or token creation")
					}
					return setup, canonicalJSONHistory(t, PublicHistory(driver.seats[0].h))
				}
			}
			if ending == "land" && played {
				if !mulligan || !token {
					t.Fatal("fixture skipped London bottoming or token creation")
				}
				return setup, canonicalJSONHistory(t, PublicHistory(driver.seats[0].h))
			}
		}
		choice := -1
		for i, option := range d.Options {
			if option.Kind == "keep" || option.Kind == "pass" {
				choice = i
			}
			if option.Kind == "mulligan" && d.Player == 1 && !mulligan {
				choice, mulligan = i, true
			}
			if option.Kind == "bottom" && engine.G.Obj(option.Obj).Card.Faces[0].Name == quiet.Faces[0].Name {
				choice = i
			}
		}
		if d.Player == 1 && d.Kind == decision.KPriority {
			for i, option := range d.Options {
				object := engine.G.Obj(option.Obj)
				if object == nil || object.Card == nil {
					continue
				}
				name := object.Card.Faces[0].Name
				if option.Kind == "cast" && name == maker.Faces[0].Name && !made {
					choice, made = i, true
					break
				}
				if option.Kind == "cast" && name == draw.Faces[0].Name && token && !cast && engine.G.Turn >= 4 {
					choice, cast = i, true
					break
				}
				if option.Kind == "play_land" && name == "Mountain" && cast {
					choice, played = i, true
					break
				}
			}
		}
		if choice < 0 {
			choice = 0
		}
		intent := decision.Intent{Seq: d.Seq, Player: d.Player, Choices: []int{choice}}
		if err := d.Validate(intent); err != nil {
			t.Fatal(err)
		}
		if err := driver.RecordAnswer(d, intent); err != nil {
			t.Fatal(err)
		}
		if err := engine.SubmitHypothetical(intent); err != nil {
			t.Fatal(err)
		}
	}
	t.Fatalf("fixture did not reach %s: mulligan=%v made=%v cast=%v played=%v turn=%d", ending, mulligan, made, cast, played, engine.G.Turn)
	return setup, History{}
}
