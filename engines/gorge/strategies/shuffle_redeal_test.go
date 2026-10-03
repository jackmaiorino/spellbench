package strategies

import (
	"context"
	"encoding/json"
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

// The actual pinned Lembas card is cast and sacrificed through legal intents.
// Its graveyard trigger returns it to the library and shuffles. One earlier
// legal declined land drop makes every native-policy replay incompatible.
func naturallyPlayedLembasShuffle(t *testing.T) (*rules.Engine, PublicGame, *Driver, History) {
	t.Helper()
	dir := os.Getenv("GORGE_CARDS")
	if dir == "" {
		t.Fatal("GORGE_CARDS must name the pinned corpus; this test cannot skip")
	}
	reg, err := testutil.OpenCorpusRegistry(dir)
	if err != nil {
		t.Fatal(err)
	}
	lembas, ok := reg.Lookup("Lembas")
	if !ok {
		t.Fatal("pinned corpus lacks Lembas")
	}
	_, setup := fixture(t, 17, true)
	opponent := make([]*cards.Card, 20)
	for i := range opponent {
		opponent[i] = setup.Decks[0][0]
	}
	opponent[12], opponent[13] = lembas, lembas
	setup.Decks[1] = opponent
	e, err := rules.NewHypotheticalPlanned(rules.Config{Seed: 17, Names: setup.Names, Decks: setup.Decks},
		[]rules.ChanceDraw{{Bound: 2, Value: 0}}, func(ctx rules.ShuffleContext) ([]state.ObjID, error) {
			if ctx.Ordinal != 0 {
				return nil, nil
			}
			order := []state.ObjID{ctx.Library[0].ID, ctx.Library[1].ID, ctx.Library[2].ID, ctx.Library[3].ID,
				ctx.Library[12].ID, ctx.Library[13].ID, ctx.Library[14].ID}
			seen := map[state.ObjID]bool{}
			for _, id := range order {
				seen[id] = true
			}
			for _, card := range ctx.Library {
				if !seen[card.ID] {
					order = append(order, card.ID)
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
	bots := [2]*seat.Bot{seat.NewBot(3), seat.NewBot(7)}
	declined, shuffled := false, false
	actions := map[string]int{}
	var h History
	for n := 0; n < 500 && !e.G.Over; n++ {
		d := e.Pending()
		driver.Observe(e)
		if shuffled && d.Player == 0 {
			h = PublicHistory(driver.seats[0].h)
			break
		}
		in, err := bots[d.Player].Decide(context.Background(), view.Project(e.G, e, d.Player, d), *d)
		if err != nil {
			t.Fatal(err)
		}
		if d.Player == 1 && d.Kind == decision.KPriority {
			land, pass := false, -1
			for i, option := range d.Options {
				land = land || option.Kind == "play_land"
				if option.Kind == "pass" {
					pass = i
				}
			}
			if !declined && land && pass >= 0 {
				in.Choices, declined = []int{pass}, true
			} else {
				food := false
				for _, id := range e.G.Zone(state.ZBattlefield, 1) {
					food = food || e.G.Obj(id).Card.Faces[0].Name == "Lembas"
				}
				cast, eat, mana := -1, -1, -1
				for i, option := range d.Options {
					if o := e.G.Obj(option.Obj); o != nil && o.Card != nil {
						name := o.Card.Faces[0].Name
						if option.Kind == "cast" && name == "Lembas" {
							cast = i
						}
						if option.Kind == "ability" && name == "Lembas" {
							eat = i
						}
						if food && option.Kind == "activate" && name == "Mountain" {
							mana = i
						}
					}
				}
				if eat >= 0 {
					in.Choices = []int{eat}
				} else if mana >= 0 {
					in.Choices = []int{mana}
				} else if cast >= 0 {
					in.Choices = []int{cast}
				}
			}
		}
		if err := driver.RecordAnswer(d, in); err != nil {
			t.Fatal(err)
		}
		if d.Player == 1 {
			for _, choice := range in.Choices {
				option := d.Options[choice]
				key := string(d.Kind) + "/" + option.Kind
				if o := e.G.Obj(option.Obj); o != nil && o.Card != nil {
					key += "/" + o.Card.Faces[0].Name
				}
				actions[key]++
			}
		}
		pos := len(e.L.Events)
		if err := e.SubmitHypothetical(in); err != nil {
			t.Fatal(err)
		}
		for _, ev := range e.L.Events[pos:] {
			shuffled = shuffled || ev.Kind == events.Shuffle && ev.Player == 1
		}
	}
	if !declined || !shuffled || len(h.Frames) == 0 {
		t.Fatalf("legal fixture did not reach the shuffle boundary: declined=%v shuffled=%v frames=%d turn=%d over=%v actions=%v", declined, shuffled, len(h.Frames), e.G.Turn, e.G.Over, actions)
	}
	return e, setup, driver, h
}

func TestPublicRedealAfterNaturallyPlayedLembasShuffle(t *testing.T) {
	e, setup, driver, h := naturallyPlayedLembasShuffle(t)
	for _, id := range e.G.Zone(state.ZLibrary, 1) {
		if e.G.Obj(id).Card.Faces[0].Name == "Lembas" && driver.seats[0].c.SpellbenchAlias(id) != 0 {
			t.Fatal("a stack ability restored a shuffled source's hidden copy link")
		}
	}
	known, err := searchprobe.ProjectKnownCards(h)
	if err != nil {
		t.Fatal(err)
	}
	member := false
	for _, minimum := range known.SpellbenchAnonymous {
		member = member || minimum.Player == 1 && minimum.Name == "Lembas" && minimum.Count > 0
	}
	if !member {
		t.Fatalf("natural shuffle lost known Lembas membership: %+v", known)
	}
	if err := known.Holds(searchprobe.World{Engine: e, Observer: driver.seats[0].c}); err != nil {
		t.Fatal(err)
	}
	opts := searchprobe.SampleOptions{Seed: 54321, Attempts: 64, Worlds: 8, MaxSubmits: 5000, KnownCards: true,
		Redeal: &searchprobe.RedealBase{SpellbenchPublic: true}}
	result, err := searchprobe.Sample(setup, h, opts)
	if err != nil || result.Accepted != 0 || result.Redealt != 8 || result.RedealRefused != "" {
		t.Fatalf("natural public-only shuffle reconstruction failed: %v %+v reconstruction=%+v", err, result, result.PublicReconstruction)
	}
	for _, world := range result.Worlds {
		if err := known.Holds(world); err != nil {
			t.Fatal(err)
		}
	}
	t.Logf("actor_frames=%d attempts=%d accepted=%d redealt=%d reconstruction=%+v", len(h.Frames), result.Attempts, result.Accepted, result.Redealt, result.PublicReconstruction)
}

// The legal fixture supplies an unresolved food ability and a blind shuffle.
// This injected draw isolates whether a later visible card restores the old
// ability's copy link; it does not claim a naturally played draw sequence.
func TestPublicStackSourceStaysUnlinkedAfterShuffleAndRedraw(t *testing.T) {
	e, _, driver, _ := naturallyPlayedLembasShuffle(t)
	var source, ability state.ObjID
	for _, id := range e.G.Stack {
		o := e.G.Obj(id)
		if src := e.G.Obj(o.Source); src != nil && src.Zone == state.ZLibrary && src.Card.Faces[0].Name == "Lembas" {
			source, ability = src.ID, id
			break
		}
	}
	if source == 0 {
		t.Fatal("fixture has no shuffled source for a remaining stack ability")
	}
	c := driver.seats[1].c
	if c.SpellbenchAlias(source) != 0 {
		t.Fatal("the blind shuffle retained the source's physical identity")
	}
	pos := len(e.L.Events)
	events.Emit(e.G, e.L, events.Event{Kind: events.Draw, Player: 1, Obj: source, From: state.ZLibrary, To: state.ZHand, Secret: true})
	f, err := c.SpellbenchCapture(e, e.L.Events[pos:])
	if err != nil {
		t.Fatal(err)
	}
	if c.SpellbenchAlias(source) == 0 {
		t.Fatal("the actor's drawn card was not introduced")
	}
	var board view.View
	if err := json.Unmarshal(f.Board, &board); err != nil {
		t.Fatal(err)
	}
	for _, stack := range board.Stack {
		if uint32(stack.ID) == c.SpellbenchAlias(ability) {
			if stack.Source != 0 {
				t.Fatal("a later visible draw restored the old stack ability's shuffled copy link")
			}
			return
		}
	}
	t.Fatal("public stack ability disappeared")
}
