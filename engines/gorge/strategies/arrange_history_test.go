package strategies

import (
	"encoding/json"
	"fmt"
	"os"
	"reflect"
	"strings"
	"testing"

	"github.com/adams-shaun/gorge/cards"
	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/events"
	"github.com/adams-shaun/gorge/internal/searchprobe"
	"github.com/adams-shaun/gorge/internal/testutil"
	"github.com/adams-shaun/gorge/rules"
	"github.com/adams-shaun/gorge/state"
)

// Legal actor decisions bottom an observed London card, scry one or two
// distinct cards, and draw through the resulting order. Permuting the unseen
// library tail must leave the entire history and native diagnostics identical.
func TestPublicActorArrangeAfterLondon(t *testing.T) {
	for _, outcome := range []string{"pending", "keep", "bottom", "reverse", "shuffle-pending", "shuffle-keep", "shuffle-bottom", "shuffle-reverse"} {
		t.Run(outcome, func(t *testing.T) {
			setup, history := actorArrangeHistory(t, outcome, false)
			_, other := actorArrangeHistory(t, outcome, true)
			left, _ := json.Marshal(history)
			right, _ := json.Marshal(other)
			if string(left) != string(right) {
				t.Fatal("unseen actor library tail changed the scry history")
			}
			opts := searchprobe.SampleOptions{Seed: 54321, Attempts: 64, Worlds: 8, MaxSubmits: 5000, KnownCards: true}
			root, work, err := searchprobe.SpellbenchReconstructRedeal(setup, history, opts)
			if err != nil || root == nil || work.BudgetExhausted != 0 || work.Submits >= opts.MaxSubmits {
				t.Fatalf("London scry reconstruction: %v work=%+v", err, work)
			}
			before, err := searchprobe.Sample(setup, history, opts)
			if err != nil {
				t.Fatal(err)
			}
			opts.Redeal = &searchprobe.RedealBase{SpellbenchPublic: true}
			after, err := searchprobe.Sample(setup, history, opts)
			if err != nil || len(after.Worlds) != opts.Worlds || after.RedealRefused != "" {
				t.Fatalf("London scry worlds: %v worlds=%d refused=%s", err, len(after.Worlds), after.RedealRefused)
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
				t.Fatal("public arrangement witness changed native sampler diagnostics")
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

func actorArrangeHistory(t *testing.T, outcome string, swapTail bool) (PublicGame, History) {
	t.Helper()
	midShuffle := strings.HasPrefix(outcome, "shuffle-")
	outcome = strings.TrimPrefix(outcome, "shuffle-")
	registry, err := testutil.OpenCorpusRegistry(os.Getenv("GORGE_CARDS"))
	if err != nil {
		t.Fatal(err)
	}
	window := 1
	if outcome == "reverse" {
		window = 2
	}
	scout := fixtureCard(t, fmt.Sprintf("Name:Public Scry Scout\nManaCost:0\nTypes:Creature Scout\nPT:1/1\nA:AB$ Scry | Cost$ 0 | ScryNum$ %d | Defined$ You\nA:AB$ Draw | Cost$ 0 | NumCards$ 2\nA:AB$ Shuffle | Cost$ 0 | Defined$ You\nOracle:Fixture.\n", window))
	quiet := fixtureCard(t, "Name:Quiet Scry Artifact\nManaCost:99\nTypes:Artifact\nOracle:Fixture.\n")
	bottom := fixtureCard(t, "Name:London Scry Bottom\nManaCost:99\nTypes:Artifact\nOracle:Fixture.\n")
	peek := fixtureCard(t, "Name:First Scry Card\nManaCost:99\nTypes:Artifact\nOracle:Fixture.\n")
	next := fixtureCard(t, "Name:Second Scry Card\nManaCost:99\nTypes:Artifact\nOracle:Fixture.\n")
	actor, opponent := make([]*cards.Card, 24), make([]*cards.Card, 24)
	for i := range actor {
		actor[i], opponent[i] = quiet, quiet
	}
	actor[0], actor[1], actor[7], actor[8] = scout, bottom, peek, next
	for index, name := range map[int]string{22: "Forest", 23: "Swamp"} {
		card, ok := registry.Lookup(name)
		if !ok {
			t.Fatal(name)
		}
		actor[index] = card
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
					if ctx.Ordinal < 2 {
						t.Fatal("fixture opening shuffle lacks ", name)
					}
					continue
				}
				order = append(order, byName[name][0])
				byName[name] = byName[name][1:]
			}
			if swapTail && ctx.Player == 0 {
				last := len(order) - 1
				order[last-1], order[last] = order[last], order[last-1]
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
	mulligan, shuffleRequested, scry, arranged, draw := false, false, false, false, false
	for step := 0; step < 200 && !engine.G.Over; step++ {
		d := engine.Pending()
		driver.Observe(engine)
		orderSeen, drawn, shuffles := false, 0, 0
		for _, event := range engine.L.Events {
			if event.Kind == events.Shuffle && event.Player == 0 {
				shuffles++
			}
			orderSeen = orderSeen || event.Kind == events.LibraryOrder && event.Player == 0
			if orderSeen && event.Kind == events.Draw && event.Player == 0 {
				drawn++
			}
		}
		if d.Player == 0 && d.Kind == decision.KArrange && outcome == "pending" {
			if !mulligan || !scry || len(d.Options) != window || midShuffle && shuffles != 3 {
				t.Fatal("fixture skipped London bottoming or scry window")
			}
			return setup, canonicalJSONHistory(t, PublicHistory(driver.seats[0].h))
		}
		if d.Player == 0 && d.Kind == decision.KPriority && drawn >= 2 {
			if !mulligan || !arranged || !draw || midShuffle && shuffles != 3 {
				t.Fatal("fixture skipped London, arrangement or draw")
			}
			return setup, canonicalJSONHistory(t, PublicHistory(driver.seats[0].h))
		}
		choice := -1
		for i, option := range d.Options {
			if option.Kind == "keep" || option.Kind == "pass" {
				choice = i
			}
			if option.Kind == "mulligan" && d.Player == 0 && !mulligan {
				choice, mulligan = i, true
			}
			if option.Kind == "bottom" && engine.G.Obj(option.Obj).Card.Faces[0].Name == bottom.Faces[0].Name {
				choice = i
			}
		}
		if d.Player == 0 && d.Kind == decision.KPriority {
			for i, option := range d.Options {
				object := engine.G.Obj(option.Obj)
				if object == nil || object.Card == nil || object.Card.Faces[0].Name != scout.Faces[0].Name {
					continue
				}
				if option.Kind == "cast" {
					choice = i
				}
				if option.Kind == "ability" {
					api := scout.Faces[0].Abilities[option.Ability].API
					if api == "Shuffle" && midShuffle && !shuffleRequested {
						choice, shuffleRequested = i, true
						break
					}
					if api == "Scry" && !scry && (!midShuffle || shuffles == 3) {
						choice, scry = i, true
						break
					}
					if api == "Draw" && arranged && orderSeen && !draw {
						choice, draw = i, true
						break
					}
				}
			}
		}
		if choice < 0 {
			choice = 0
		}
		intent := decision.Intent{Seq: d.Seq, Player: d.Player, Choices: []int{choice}}
		if d.Player == 0 && d.Kind == decision.KArrange {
			switch outcome {
			case "keep":
				intent.Choices = []int{0}
			case "bottom":
				intent.Choices = []int{}
			case "reverse":
				intent.Choices = []int{1, 0}
			default:
				t.Fatal("unexpected scry outcome ", outcome)
			}
			arranged = true
		}
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
	t.Fatalf("fixture did not finish scry: mulligan=%v scry=%v arranged=%v draw=%v", mulligan, scry, arranged, draw)
	return setup, History{}
}
