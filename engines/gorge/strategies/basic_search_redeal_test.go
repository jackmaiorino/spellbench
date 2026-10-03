package strategies

import (
	"context"
	"encoding/json"
	"os"
	"reflect"
	"testing"

	"github.com/adams-shaun/gorge/cards"
	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/internal/searchprobe"
	"github.com/adams-shaun/gorge/internal/testutil"
	"github.com/adams-shaun/gorge/rules"
	"github.com/adams-shaun/gorge/seat"
	"github.com/adams-shaun/gorge/state"
	"github.com/adams-shaun/gorge/view"
)

// A naturally cast pinned card offers dozens of named opponent basics in
// their library order. Random replay almost never reproduces that whole
// ordered window. Reconstruction must use the observed membership/order
// while preserving hidden hand sizes and all earlier public decisions.
func TestPublicReconstructionAtNaturallyPlayedOpponentBasicSearch(t *testing.T) {
	checkNaturallyPlayedOpponentBasicSearch(t, false)
}

func TestPublicReconstructionAfterNaturallyPlayedBasicSearchRemoval(t *testing.T) {
	checkNaturallyPlayedOpponentBasicSearch(t, true)
}

func checkNaturallyPlayedOpponentBasicSearch(t *testing.T, afterRemoval bool) {
	t.Helper()
	dir := os.Getenv("GORGE_CARDS")
	if dir == "" {
		t.Fatal("GORGE_CARDS must name the pinned corpus")
	}
	registry, err := testutil.OpenCorpusRegistry(dir)
	if err != nil {
		t.Fatal(err)
	}
	lookup := func(name string) *cards.Card {
		card, ok := registry.Lookup(name)
		if !ok {
			t.Fatalf("pinned corpus lacks %s", name)
		}
		return card
	}
	_, setup := fixture(t, 17, true)
	for i := 12; i < 15; i++ {
		setup.Decks[0][i] = lookup("Cleansing Wildfire")
	}
	setup.Decks[1] = make([]*cards.Card, 60)
	for i := range setup.Decks[1] {
		setup.Decks[1][i] = lookup([]string{"Forest", "Swamp", "Mountain"}[i%3])
	}
	if afterRemoval {
		for i := range setup.Decks[1] {
			setup.Decks[1][i] = lookup("Rugged Highlands")
		}
		for i, name := range map[int]string{6: "Swamp", 8: "Mountain", 9: "Forest", 10: "Mountain", 11: "Forest", 12: "Swamp", 13: "Swamp"} {
			setup.Decks[1][i] = lookup(name)
		}
	}
	e, err := rules.NewHypotheticalPlanned(rules.Config{Seed: 17, Names: setup.Names, Decks: setup.Decks, StartingLife: 20},
		[]rules.ChanceDraw{{Bound: 2, Value: 0}}, func(ctx rules.ShuffleContext) ([]state.ObjID, error) {
			if afterRemoval && ctx.Player == 1 && ctx.Ordinal == 0 {
				var order []state.ObjID
				for _, card := range ctx.Library {
					order = append(order, card.ID)
				}
				return order, nil
			}
			if ctx.Player != 0 || ctx.Ordinal != 0 {
				return nil, nil
			}
			indices := []int{0, 1, 2, 3, 12, 13, 14}
			seen := map[state.ObjID]bool{}
			var order []state.ObjID
			for _, i := range indices {
				order = append(order, ctx.Library[i].ID)
				seen[ctx.Library[i].ID] = true
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
	searched, basicsOffered := false, 0
	for n := 0; n < 300 && !e.G.Over; n++ {
		d := e.Pending()
		driver.Observe(e)
		atSearch := d.Player == 0 && d.Kind == decision.KChoose && d.ResumeKind == "search"
		if atSearch {
			searched, basicsOffered = true, len(d.Options)
		}
		ready := atSearch && !afterRemoval
		if afterRemoval && searched && d.Player == 0 {
			for _, id := range e.G.Zone(state.ZBattlefield, 1) {
				ready = ready || e.G.Obj(id).Card.Faces[0].Name == "Mountain"
			}
		}
		if ready {
			h := canonicalJSONHistory(t, PublicHistory(driver.seats[0].h))
			opts := searchprobe.SampleOptions{Seed: 54321, Attempts: 64, MaxSubmits: 5000, ComparePotentialActions: true}
			root, work, err := searchprobe.SpellbenchReconstructRedeal(setup, h, opts)
			if err != nil || root == nil || root.Engine == nil || root.Observer == nil {
				t.Fatalf("observed opponent search did not reconstruct: %v work=%+v", err, work)
			}
			if work.BudgetExhausted != 0 || work.Submits > opts.MaxSubmits {
				t.Fatalf("search reconstruction exceeded the native budget: %+v", work)
			}
			got, err := root.Observer.Clone().SpellbenchCapture(root.Engine, nil)
			if err != nil {
				t.Fatal(err)
			}
			last := h.Frames[len(h.Frames)-1]
			var gotBoard, wantBoard any
			if json.Unmarshal(got.Board, &gotBoard) != nil || json.Unmarshal(last.Board, &wantBoard) != nil ||
				!reflect.DeepEqual(gotBoard, wantBoard) || !reflect.DeepEqual(got.Decision, last.Decision) {
				t.Fatal("reconstructed root changed the public board or ordered search options")
			}
			t.Logf("after_removal=%v named_basics=%d frames=%d reconstruction=%+v", afterRemoval, basicsOffered, len(h.Frames), work)
			return
		}
		in, err := bots[d.Player].Decide(context.Background(), view.Project(e.G, e, d.Player, d), *d)
		if err != nil {
			t.Fatal(err)
		}
		if d.Player == 0 && d.Kind == decision.KTarget {
			for i, option := range d.Options {
				if object := e.G.Obj(option.Obj); object != nil && object.Owner == 1 && object.Zone == state.ZBattlefield {
					in.Choices = []int{i}
					break
				}
			}
		}
		if afterRemoval && atSearch {
			for i, option := range d.Options {
				if e.G.Obj(option.Obj).Card.Faces[0].Name == "Forest" {
					in.Choices = []int{i}
					break
				}
			}
		}
		if afterRemoval && d.Kind == decision.KChoose && d.ResumeKind == "search_mayshuffle" {
			for i, option := range d.Options {
				if option.Kind == "no" {
					in.Choices = []int{i}
					break
				}
			}
		}
		if afterRemoval && searched && d.Player == 0 && d.Kind == decision.KPriority {
			for i, option := range d.Options {
				if option.Kind == "pass" {
					in.Choices = []int{i}
					break
				}
			}
		}
		if afterRemoval && d.Player == 1 && d.Kind == decision.KPriority {
			for i, option := range d.Options {
				if option.Kind == "play_land" && e.G.Obj(option.Obj).Card.Faces[0].Name == "Mountain" {
					in.Choices = []int{i}
					break
				}
			}
		}
		if err := driver.RecordAnswer(d, in); err != nil {
			t.Fatal(err)
		}
		if err := e.SubmitHypothetical(in); err != nil {
			t.Fatal(err)
		}
	}
	t.Fatalf("fixture did not reach its public boundary: searched=%v named_basics=%d turn=%d", searched, basicsOffered, e.G.Turn)
}
