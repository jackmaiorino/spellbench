package strategies

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"testing"

	"github.com/adams-shaun/gorge/cards"
	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/events"
	"github.com/adams-shaun/gorge/internal/searchprobe"
	"github.com/adams-shaun/gorge/internal/testutil"
	"github.com/adams-shaun/gorge/rules"
	"github.com/adams-shaun/gorge/seat"
	"github.com/adams-shaun/gorge/state"
	"github.com/adams-shaun/gorge/view"
)

func TestPublicLondonBottomReplayPreservesFutureDiscards(t *testing.T) {
	setup, h := londonDiscardHistory(t, false)
	_, other := londonDiscardHistory(t, true)
	a, _ := json.Marshal(h)
	b, _ := json.Marshal(other)
	if string(a) != string(b) {
		t.Fatal("unobserved opponent tail changed actor history")
	}
	bottomed, discards := false, 0
	for _, frame := range h.Frames {
		for _, ev := range frame.Events {
			if ev.Kind == events.MoveZone && ev.Obj == 0 && ev.From == state.ZHand && ev.To == state.ZLibrary && ev.Text == "bottomed" {
				bottomed = true
			}
			if bottomed && ev.Kind == events.MoveZone && ev.Player == 1 && ev.From == state.ZHand && ev.To == state.ZGraveyard && ev.Text == "discarded" {
				discards++
			}
		}
	}
	if !bottomed || discards < 10 {
		t.Fatalf("fixture needs a hidden London bottom and later public discards: %d", discards)
	}
	opts := searchprobe.SampleOptions{Seed: 54321, Attempts: 64, Worlds: 8, MaxSubmits: 5000}
	before, err := searchprobe.Sample(setup, h, opts)
	if err != nil {
		t.Fatal(err)
	}
	opts.Redeal = &searchprobe.RedealBase{SpellbenchPublic: true}
	after, err := searchprobe.Sample(setup, h, opts)
	if err != nil || len(after.Worlds) != opts.Worlds || after.RedealRefused != "" || after.PublicReconstruction == nil || after.PublicReconstruction.BudgetExhausted != 0 {
		t.Fatalf("London discard replay: %v worlds=%d result=%+v", err, len(after.Worlds), after)
	}
	if before.Attempts != after.Attempts || before.Accepted != after.Accepted || before.PrefixRejected != after.PrefixRejected || before.Submits != after.Submits || before.BudgetExhausted != after.BudgetExhausted {
		t.Fatal("public witness changed the native weighted sampler")
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
	t.Logf("frames=%d discards=%d reconstruction=%+v", len(h.Frames), discards, after.PublicReconstruction)
}

func londonDiscardHistory(t *testing.T, swapTail bool) (PublicGame, History) {
	t.Helper()
	quiet := fixtureCard(t, "Name:Quiet London Actor\nManaCost:99\nTypes:Artifact\nOracle:Fixture.\n")
	actor, opponent := make([]*cards.Card, 40), make([]*cards.Card, 40)
	var actorNames, opponentNames []string
	for i := range actor {
		actor[i] = quiet
		actorNames = append(actorNames, quiet.Faces[0].Name)
		name := fmt.Sprintf("Quiet London Card %02d", i)
		if i == 38 {
			name = "A Spare London Card"
		}
		if i == 39 {
			name = "B Spare London Card"
		}
		opponent[i] = fixtureCard(t, "Name:"+name+"\nManaCost:99\nTypes:Artifact\nOracle:Fixture.\n")
		opponentNames = append(opponentNames, name)
	}
	setup := PublicGame{Names: []string{"p0", "p1"}, Decks: [][]*cards.Card{actor, opponent}, StartingLife: 20, Mulligans: 1}
	e, err := rules.NewHypotheticalPlanned(rules.Config{Seed: 17, Names: setup.Names, Decks: setup.Decks, StartingLife: 20, Mulligans: 1},
		[]rules.ChanceDraw{{Bound: 2, Value: 0}}, func(ctx rules.ShuffleContext) ([]state.ObjID, error) {
			byName := map[string][]state.ObjID{}
			for _, card := range ctx.Library {
				byName[card.Name] = append(byName[card.Name], card.ID)
			}
			names := actorNames
			if ctx.Player == 1 {
				names = append([]string(nil), opponentNames...)
				if swapTail {
					names[38], names[39] = names[39], names[38]
				}
			}
			var order []state.ObjID
			for _, name := range names {
				queue := byName[name]
				if len(queue) == 0 {
					t.Fatal("fixture shuffle lacks ", name)
				}
				order = append(order, queue[0])
				byName[name] = queue[1:]
			}
			return order, nil
		})
	if err != nil {
		t.Fatal(err)
	}
	if err := e.AdvanceHypothetical(); err != nil {
		t.Fatal(err)
	}
	driver, bot := NewDriver(), seat.NewBot(3)
	mulligan := [2]bool{}
	for n := 0; n < 800 && !e.G.Over; n++ {
		d := e.Pending()
		driver.Observe(e)
		if d.Player == 0 && d.Kind == decision.KPriority && e.G.Turn >= 27 {
			if !mulligan[0] || !mulligan[1] {
				t.Fatal("fixture skipped London")
			}
			return setup, canonicalJSONHistory(t, PublicHistory(driver.seats[0].h))
		}
		in, err := bot.Decide(context.Background(), view.Project(e.G, e, d.Player, d), *d)
		if err != nil {
			t.Fatal(err)
		}
		if d.Kind == decision.KMulligan && d.Options[0].Kind == "keep" {
			in.Choices = []int{0}
			if !mulligan[d.Player] && len(d.Options) > 1 {
				in.Choices, mulligan[d.Player] = []int{1}, true
			}
		} else if d.Kind == decision.KMulligan && d.Options[0].Kind == "bottom" {
			in.Choices = []int{len(d.Options) - 1}
		}
		for i, option := range d.Options {
			if d.Kind == decision.KPriority && option.Kind == "pass" {
				in.Choices = []int{i}
			}
			if option.Kind == "discard" {
				in.Choices = []int{i}
				break
			}
		}
		if err := driver.RecordAnswer(d, in); err != nil {
			t.Fatal(err)
		}
		if err := e.SubmitHypothetical(in); err != nil {
			t.Fatal(err)
		}
	}
	t.Fatal("fixture did not reach the public discard sequence")
	return setup, History{}
}

func TestPublicActorLondonReplayPreservesLaterDraws(t *testing.T) {
	setup, h := actorLondonHistory(t, false)
	_, other := actorLondonHistory(t, true)
	a, _ := json.Marshal(h)
	b, _ := json.Marshal(other)
	if string(a) != string(b) {
		t.Fatal("unobserved opponent opening order changed actor history")
	}
	opts := searchprobe.SampleOptions{Seed: 54321, Attempts: 64, Worlds: 8, MaxSubmits: 5000}
	root, work, err := searchprobe.SpellbenchReconstructRedeal(setup, h, opts)
	if err != nil || root == nil || work.BudgetExhausted != 0 || work.Submits >= opts.MaxSubmits {
		t.Fatalf("actor London reconstruction: %v work=%+v", err, work)
	}
	before, err := searchprobe.Sample(setup, h, opts)
	if err != nil {
		t.Fatal(err)
	}
	opts.Redeal = &searchprobe.RedealBase{SpellbenchPublic: true}
	after, err := searchprobe.Sample(setup, h, opts)
	if err != nil || len(after.Worlds) != opts.Worlds || after.RedealRefused != "" {
		t.Fatalf("actor London sampled worlds: %v worlds=%d refused=%s", err, len(after.Worlds), after.RedealRefused)
	}
	if before.Attempts != after.Attempts || before.Accepted != after.Accepted || before.PrefixRejected != after.PrefixRejected || before.Submits != after.Submits || before.BudgetExhausted != after.BudgetExhausted {
		t.Fatal("public witness changed the native weighted sampler")
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
	t.Logf("frames=%d native_accepted=%d reconstruction=%+v", len(h.Frames), after.Accepted, work)
}

func TestPublicActorOpeningDrawsSurviveOpponentLibrarySearch(t *testing.T) {
	setup, h := actorOpeningHistory(t, false, true)
	_, other := actorOpeningHistory(t, true, true)
	a, _ := json.Marshal(h)
	b, _ := json.Marshal(other)
	if string(a) != string(b) {
		t.Fatal("unobserved opponent library order changed actor history")
	}
	searched, laterDraw := false, false
	for _, frame := range h.Frames {
		for _, event := range frame.Events {
			if event.Kind == events.MoveZone && event.Obj == 0 && event.From == state.ZLibrary && event.To == state.ZHand {
				searched = true
			}
			if searched && event.Kind == events.Draw && event.Player == h.Actor && event.Obj != 0 {
				laterDraw = true
			}
		}
	}
	if !searched || !laterDraw {
		t.Fatal("fixture needs an anonymous opponent library exit followed by a named actor draw")
	}
	opts := searchprobe.SampleOptions{Seed: 54321, Attempts: 64, Worlds: 8, MaxSubmits: 5000}
	before, err := searchprobe.Sample(setup, h, opts)
	if err != nil {
		t.Fatal(err)
	}
	opts.Redeal = &searchprobe.RedealBase{SpellbenchPublic: true}
	after, err := searchprobe.Sample(setup, h, opts)
	if err != nil || len(after.Worlds) != opts.Worlds || after.RedealRefused != "" || after.PublicReconstruction == nil || after.PublicReconstruction.BudgetExhausted != 0 {
		t.Fatalf("public search reconstruction: %v worlds=%d result=%+v", err, len(after.Worlds), after)
	}
	if before.Attempts != after.Attempts || before.Accepted != after.Accepted || before.PrefixRejected != after.PrefixRejected || before.Submits != after.Submits || before.BudgetExhausted != after.BudgetExhausted {
		t.Fatal("public witness changed the native weighted sampler")
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
	t.Logf("frames=%d native_accepted=%d reconstruction=%+v", len(h.Frames), after.Accepted, after.PublicReconstruction)
}

// Both seats legally mulligan and bottom. The actor then observes two distinct
// draws from its unchanged library. Only the opponent's unseen land order
// varies; it passes priority and discards the same named artifact if needed.
func actorLondonHistory(t *testing.T, swapOpponent bool) (PublicGame, History) {
	return actorOpeningHistory(t, swapOpponent, false)
}

func actorOpeningHistory(t *testing.T, swapOpponent, cycleOpponent bool) (PublicGame, History) {
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
	quiet := fixtureCard(t, "Name:Quiet London Artifact\nManaCost:99\nTypes:Artifact\nOracle:Fixture.\n")
	names := []string{"Twisted Landscape", "Mountain", "Forest", "Swamp", quiet.Faces[0].Name, quiet.Faces[0].Name, "Lembas",
		"Refurbished Familiar", "Nihil Spellbomb", quiet.Faces[0].Name, "Forest", "Swamp", "Mountain", "Island", quiet.Faces[0].Name, quiet.Faces[0].Name}
	actor := make([]*cards.Card, len(names))
	for i, name := range names {
		actor[i] = quiet
		if name != quiet.Faces[0].Name {
			actor[i] = lookup(name)
		}
	}
	opponent := make([]*cards.Card, len(names))
	for i := range opponent {
		opponent[i] = quiet
	}
	opponent[0], opponent[1] = lookup("Forest"), lookup("Mountain")
	if cycleOpponent {
		opponent[1], opponent[8] = lookup("Lórien Revealed"), lookup("Island")
		opponent[10], opponent[11] = lookup("Mountain"), lookup("Swamp")
	}
	setup := PublicGame{Names: []string{"p0", "p1"}, Decks: [][]*cards.Card{actor, opponent}, Tokens: reg.Tokens, StartingLife: 20, Mulligans: 1}
	e, err := rules.NewHypotheticalPlanned(rules.Config{Seed: 17, Names: setup.Names, Decks: setup.Decks, Tokens: setup.Tokens, StartingLife: 20, Mulligans: 1},
		[]rules.ChanceDraw{{Bound: 2, Value: 0}}, func(ctx rules.ShuffleContext) ([]state.ObjID, error) {
			byName := map[string][]state.ObjID{}
			for _, card := range ctx.Library {
				byName[card.Name] = append(byName[card.Name], card.ID)
			}
			orderNames := names
			if ctx.Player == 1 {
				orderNames = []string{"Forest", "Mountain"}
				for range len(names) - 2 {
					orderNames = append(orderNames, quiet.Faces[0].Name)
				}
				if swapOpponent {
					orderNames[0], orderNames[1] = orderNames[1], orderNames[0]
				}
				if cycleOpponent {
					orderNames = []string{"Forest", "Lórien Revealed"}
					for range len(names) - 2 {
						orderNames = append(orderNames, quiet.Faces[0].Name)
					}
					orderNames[8], orderNames[10], orderNames[11] = "Island", "Mountain", "Swamp"
					if swapOpponent {
						orderNames[10], orderNames[11] = orderNames[11], orderNames[10]
					}
					// A search has removed an Island and may have drawn other cards.
					// Preserve the visible names while varying only the unseen tail.
					var remaining []string
					for _, name := range orderNames {
						if len(byName[name]) > 0 {
							remaining = append(remaining, name)
							byName[name] = byName[name][1:]
						}
					}
					byName = map[string][]state.ObjID{}
					for _, card := range ctx.Library {
						byName[card.Name] = append(byName[card.Name], card.ID)
					}
					orderNames = remaining
				}
			}
			var order []state.ObjID
			for _, name := range orderNames {
				queue := byName[name]
				if len(queue) == 0 {
					t.Fatalf("fixture shuffle lacks %s", name)
				}
				order = append(order, queue[0])
				byName[name] = queue[1:]
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
	mulligan := [2]bool{}
	for n := 0; n < 200 && !e.G.Over; n++ {
		d := e.Pending()
		driver.Observe(e)
		if d.Player == 0 && d.Kind == decision.KPriority && e.G.Turn >= 5 {
			if !mulligan[0] || !mulligan[1] {
				t.Fatal("fixture skipped a London mulligan")
			}
			return setup, canonicalJSONHistory(t, PublicHistory(driver.seats[0].h))
		}
		in, err := bot.Decide(context.Background(), view.Project(e.G, e, d.Player, d), *d)
		if err != nil {
			t.Fatal(err)
		}
		if d.Kind == decision.KMulligan && d.Options[0].Kind == "keep" {
			in.Choices = []int{0}
			if !mulligan[d.Player] && len(d.Options) > 1 {
				in.Choices, mulligan[d.Player] = []int{1}, true
			}
		}
		for i, option := range d.Options {
			if d.Kind == decision.KPriority && option.Kind == "pass" && (!cycleOpponent || d.Player == 0) {
				in.Choices = []int{i}
			}
			if (option.Kind == "bottom" || option.Kind == "discard") && e.G.Obj(option.Obj).Card.Faces[0].Name == quiet.Faces[0].Name {
				in.Choices = []int{i}
				break
			}
		}
		if err := driver.RecordAnswer(d, in); err != nil {
			t.Fatal(err)
		}
		if err := e.SubmitHypothetical(in); err != nil {
			t.Fatal(err)
		}
	}
	t.Fatal("fixture did not reach the second actor draw")
	return setup, History{}
}
