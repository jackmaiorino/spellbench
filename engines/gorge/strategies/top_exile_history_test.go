package strategies

import (
	"encoding/json"
	"os"
	"reflect"
	"sort"
	"testing"

	"github.com/adams-shaun/gorge/cards"
	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/events"
	"github.com/adams-shaun/gorge/internal/searchprobe"
	"github.com/adams-shaun/gorge/internal/testutil"
	"github.com/adams-shaun/gorge/rules"
	"github.com/adams-shaun/gorge/state"
)

func TestPublicTopExilesPreserveLaterDrawsAndCasts(t *testing.T) {
	setup, history := publicDigHistory(t, "exile", false, false)
	_, other := publicDigHistory(t, "exile", false, true)
	checkPublicDigReplay(t, setup, history, other, true)
}

func TestPublicOwnedTopExilesAfterLondonBottom(t *testing.T) {
	setup, history := publicDigHistory(t, "owned-exile", false, false)
	_, other := publicDigHistory(t, "owned-exile", false, true)
	checkPublicDigReplay(t, setup, history, other, true)
}

func TestPublicOwnedTopLookPreservesWindow(t *testing.T) {
	for _, pending := range []bool{true, false} {
		t.Run(map[bool]string{true: "pending", false: "answered"}[pending], func(t *testing.T) {
			setup, history := publicDigHistory(t, "look", pending, false)
			_, other := publicDigHistory(t, "look", pending, true)
			checkPublicDigReplay(t, setup, history, other, !pending)
		})
	}
}

func checkPublicDigReplay(t *testing.T, setup PublicGame, h, other History, worlds bool) {
	t.Helper()
	a, _ := json.Marshal(h)
	b, _ := json.Marshal(other)
	if string(a) != string(b) {
		t.Fatal("unseen library tail changed public history")
	}
	opts := searchprobe.SampleOptions{Seed: 54321, Attempts: 64, Worlds: 8, MaxSubmits: 5000, KnownCards: true}
	root, work, err := searchprobe.SpellbenchReconstructRedeal(setup, h, opts)
	if err != nil || root == nil || work.BudgetExhausted != 0 || work.Submits > opts.MaxSubmits {
		t.Fatalf("public Dig witness: %v work=%+v", err, work)
	}
	known, err := searchprobe.ProjectKnownCards(h)
	if err != nil {
		t.Fatal(err)
	}
	if err := known.Holds(searchprobe.World{Engine: root.Engine, Observer: root.Observer}); err != nil {
		t.Fatal(err)
	}
	if !worlds {
		t.Logf("pending frames=%d witness=%+v", len(h.Frames), work)
		return
	}
	before, err := searchprobe.Sample(setup, h, opts)
	if err != nil {
		t.Fatal(err)
	}
	opts.Redeal = &searchprobe.RedealBase{SpellbenchPublic: true}
	after, err := searchprobe.Sample(setup, h, opts)
	if err != nil || len(after.Worlds) != opts.Worlds || after.RedealRefused != "" {
		t.Fatalf("public Dig worlds: %v worlds=%d refused=%s", err, len(after.Worlds), after.RedealRefused)
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
		t.Fatal("public Dig guidance changed native diagnostics")
	}
	for _, world := range after.Worlds {
		if err := known.Holds(world); err != nil {
			t.Fatal(err)
		}
	}
	t.Logf("frames=%d witness=%+v native_accepted=%d worlds=%d", len(h.Frames), work, after.Accepted, len(after.Worlds))
}

// Actual printed Synthesizer, Impulse and Stampede effects execute through
// legal native asks. Only cards beyond every observed window are permuted.
func publicDigHistory(t *testing.T, mode string, pending, swap bool) (PublicGame, History) {
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
	quiet := fixtureCard(t, "Name:Quiet Dig Artifact\nManaCost:99\nTypes:Artifact\nOracle:Fixture.\n")
	decks := [][]*cards.Card{make([]*cards.Card, 24), make([]*cards.Card, 24)}
	for p := range decks {
		for i := range decks[p] {
			decks[p][i] = quiet
		}
		decks[p][22] = lookup("Island")
	}
	if mode == "exile" || mode == "owned-exile" {
		decks[0][7], decks[0][8] = lookup("Forest"), lookup("Mountain")
		for i, name := range []string{"Mountain", "Mountain", "Experimental Synthesizer", "Reckless Impulse"} {
			decks[1][i] = lookup(name)
		}
		decks[1][8], decks[1][10], decks[1][11] = lookup("Goblin Bushwhacker"), lookup("Clockwork Percussionist"), lookup("Mountain")
		if mode == "owned-exile" {
			decks[0], decks[1] = decks[1], decks[0]
			decks[0][7], decks[0][8] = lookup("Mountain"), lookup("Goblin Tomb Raider")
		}
	} else {
		for i := 0; i < 3; i++ {
			decks[0][i] = lookup("Forest")
		}
		decks[0][3] = lookup("Lead the Stampede")
		decks[0][9], decks[0][10], decks[0][11], decks[0][12], decks[0][13] = lookup("Saruli Caretaker"), lookup("Forest"), quiet, lookup("Gatecreeper Vine"), lookup("Tinder Wall")
	}
	setup := PublicGame{Names: []string{"p0", "p1"}, Decks: decks, Tokens: reg.Tokens, StartingLife: 20, Mulligans: 1}
	e, err := rules.NewHypotheticalPlanned(rules.Config{Seed: 17, Names: setup.Names, Decks: setup.Decks, Tokens: setup.Tokens, StartingLife: 20, Mulligans: 1},
		[]rules.ChanceDraw{{Bound: 2, Value: 0}}, func(ctx rules.ShuffleContext) ([]state.ObjID, error) {
			var order []state.ObjID
			for _, card := range ctx.Library {
				order = append(order, card.ID)
			}
			if mode == "owned-exile" {
				sort.Slice(order, func(i, j int) bool { return order[i] < order[j] })
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
	casted := map[string]bool{}
	looked, exiled := false, 0
	mulligan, bottomed := false, false
	for step := 0; step < 700 && !e.G.Over; step++ {
		d := e.Pending()
		driver.Observe(e)
		exiled = 0
		for _, ev := range e.L.Events {
			if ev.Kind == events.MoveZone && ev.From == state.ZLibrary && ev.To == state.ZExile {
				exiled++
			}
			if ev.Kind == events.Note && ev.Player == 0 && ev.Text == "looks at the top of the library" {
				looked = true
			}
		}
		if (mode == "exile" || mode == "owned-exile") && exiled == 3 && e.G.Turn >= 5 && d.Player == 0 && d.Kind == decision.KPriority {
			if mode == "owned-exile" && (!mulligan || !bottomed || !casted["Goblin Tomb Raider"]) {
				t.Fatal("fixture skipped owned London bottoming or exiled-card cast")
			}
			return setup, canonicalJSONHistory(t, PublicHistory(driver.seats[0].h))
		}
		if mode == "look" && looked && d.Player == 0 && ((pending && d.Kind == decision.KChoose) || (!pending && d.Kind == decision.KPriority)) {
			return setup, canonicalJSONHistory(t, PublicHistory(driver.seats[0].h))
		}
		in := decision.Intent{Seq: d.Seq, Player: d.Player}
		if d.Kind == decision.KArrange {
			for i := range d.Options {
				in.Choices = append(in.Choices, i)
			}
		} else if d.Kind == decision.KChoose && mode == "look" {
			for i, option := range d.Options {
				if option.Kind == "dig" {
					in.Choices = append(in.Choices, i)
				}
			}
		} else {
			for i, option := range d.Options {
				if option.Kind == "keep" || option.Kind == "pass" {
					in.Choices = []int{i}
				}
			}
		}
		if mode == "owned-exile" && d.Player == 0 && d.Kind == decision.KMulligan {
			for i, option := range d.Options {
				if option.Kind == "mulligan" && !mulligan {
					in.Choices = []int{i}
					mulligan = true
					break
				}
				if option.Kind == "bottom" && e.G.Obj(option.Obj).Card.Faces[0].Name == quiet.Faces[0].Name {
					in.Choices = []int{i}
					bottomed = true
					break
				}
			}
		}
		if d.Kind == decision.KPriority && e.G.Step == state.StepMain1 && e.G.Active == d.Player {
			playing := (mode == "exile" && d.Player == 1) || ((mode == "look" || mode == "owned-exile") && d.Player == 0)
			wanted := "Lead the Stampede"
			if mode == "exile" || mode == "owned-exile" {
				wanted = "Experimental Synthesizer"
				if casted[wanted] {
					wanted = "Reckless Impulse"
					if mode == "owned-exile" && !casted["Goblin Tomb Raider"] {
						wanted = "Goblin Tomb Raider"
					}
				}
			}
			if playing && !casted[wanted] {
				choice := -1
				for i, option := range d.Options {
					object := e.G.Obj(option.Obj)
					if object == nil || object.Card == nil {
						continue
					}
					name := object.Card.Faces[0].Name
					if option.Kind == "play_land" || (option.Kind == "activate" && (name == "Mountain" || name == "Forest")) {
						choice = i
					}
				}
				for i, option := range d.Options {
					object := e.G.Obj(option.Obj)
					if option.Kind == "cast" && object != nil && object.Card.Faces[0].Name == wanted && !(mode == "owned-exile" && wanted == "Experimental Synthesizer" && e.G.Turn < 3) {
						choice = i
						casted[wanted] = true
						break
					}
				}
				if choice >= 0 {
					in.Choices = []int{choice}
				}
			}
		}
		if len(in.Choices) == 0 && d.Min > 0 {
			for i := 0; i < d.Min; i++ {
				in.Choices = append(in.Choices, i)
			}
		}
		if err := d.Validate(in); err != nil {
			t.Fatalf("legal Dig fixture: %v decision=%+v intent=%+v", err, d, in)
		}
		if err := driver.RecordAnswer(d, in); err != nil {
			t.Fatal(err)
		}
		if err := e.SubmitHypothetical(in); err != nil {
			t.Fatal(err)
		}
	}
	t.Fatalf("Dig fixture did not reach %s boundary: casts=%v looked=%v exiled=%d turn=%d", mode, casted, looked, exiled, e.G.Turn)
	return setup, History{}
}
