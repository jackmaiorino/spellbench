package strategies

import (
	"bytes"
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

// The real corpus card assigns the search to the targeted land's controller.
// Different unseen library order must preserve identical caster observations.
func TestOpponentLibrarySearchUsesLandControllerAndHidesOffers(t *testing.T) {
	var histories, offers [][]byte
	for _, reverseTail := range []bool{false, true} {
		e, _, driver := naturallyPlayedOpponentLibrarySearch(t, reverseTail)
		d := e.Pending()
		if d.Player != 1 || len(d.Options) != 52 {
			t.Fatalf("search owner/options = %d/%d, want land controller and 52 basic offers", d.Player, len(d.Options))
		}
		var names []string
		for _, option := range d.Options {
			if option.Player != 1 || driver.Alias(0, option.Obj) != 0 || driver.Alias(1, option.Obj) == 0 {
				t.Fatal("private search copy was offered or bound to the caster")
			}
			names = append(names, e.G.Obj(option.Obj).Card.Faces[0].Name)
		}
		h := canonicalJSONHistory(t, PublicHistory(driver.seats[0].h))
		encoded, err := json.Marshal(h)
		if err != nil {
			t.Fatal(err)
		}
		histories = append(histories, encoded)
		encoded, err = json.Marshal(names)
		if err != nil {
			t.Fatal(err)
		}
		offers = append(offers, encoded)
	}
	if bytes.Equal(offers[0], offers[1]) || !bytes.Equal(histories[0], histories[1]) {
		t.Fatal("different private offers did not preserve identical caster history")
	}
}

func TestPublicReconstructionAfterOpponentLibrarySearch(t *testing.T) {
	e, setup, driver := naturallyPlayedOpponentLibrarySearch(t, false)
	selected := -1
	for i, option := range e.Pending().Options {
		if e.G.Obj(option.Obj).Card.Faces[0].Name == "Forest" {
			selected = i
			break
		}
	}
	if selected < 0 {
		t.Fatal("natural search lacks its declared basic")
	}
	submit := func(choices []int) {
		d := e.Pending()
		in := decision.Intent{Seq: d.Seq, Player: d.Player, Choices: choices}
		if err := driver.RecordAnswer(d, in); err != nil {
			t.Fatal(err)
		}
		if err := e.SubmitHypothetical(in); err != nil {
			t.Fatal(err)
		}
		driver.Observe(e)
	}
	submit([]int{selected})
	d := e.Pending()
	if d.Player != 1 || d.ResumeKind != "search_mayshuffle" {
		t.Fatalf("shuffle confirm belongs to %d/%s, want searching player", d.Player, d.ResumeKind)
	}
	for i, option := range d.Options {
		if option.Kind == "no" {
			submit([]int{i})
			break
		}
	}
	if e.Pending().Player != 0 {
		t.Fatal("fixture did not return to the caster after the private search")
	}
	h := canonicalJSONHistory(t, PublicHistory(driver.seats[0].h))
	root, work, err := searchprobe.SpellbenchReconstructRedeal(setup, h,
		searchprobe.SampleOptions{Seed: 54321, Attempts: 64, MaxSubmits: 5000, ComparePotentialActions: true})
	if err != nil || root == nil {
		t.Fatalf("public outcome did not reconstruct: %v work=%+v", err, work)
	}
	got, err := root.Observer.Clone().SpellbenchCapture(root.Engine, nil)
	if err != nil {
		t.Fatal(err)
	}
	var gotBoard, wantBoard any
	last := h.Frames[len(h.Frames)-1]
	if json.Unmarshal(got.Board, &gotBoard) != nil || json.Unmarshal(last.Board, &wantBoard) != nil ||
		!reflect.DeepEqual(gotBoard, wantBoard) || !reflect.DeepEqual(got.Decision, last.Decision) {
		t.Fatal("reconstructed root changed the legitimate public outcome")
	}
	t.Logf("actor_frames=%d work=%+v", len(h.Frames), work)
}

func naturallyPlayedOpponentLibrarySearch(t *testing.T, reverseTail bool) (*rules.Engine, PublicGame, *Driver) {
	t.Helper()
	registry, err := testutil.OpenCorpusRegistry(os.Getenv("GORGE_CARDS"))
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
	e, err := rules.NewHypotheticalPlanned(rules.Config{Seed: 17, Names: setup.Names, Decks: setup.Decks, StartingLife: 20},
		[]rules.ChanceDraw{{Bound: 2, Value: 0}}, func(ctx rules.ShuffleContext) ([]state.ObjID, error) {
			if ctx.Ordinal != 0 {
				return nil, nil
			}
			var order []state.ObjID
			if ctx.Player == 1 {
				for _, card := range ctx.Library {
					order = append(order, card.ID)
				}
				if reverseTail {
					for i, j := 12, len(order)-1; i < j; i, j = i+1, j-1 {
						order[i], order[j] = order[j], order[i]
					}
				}
				return order, nil
			}
			seen := map[state.ObjID]bool{}
			for _, i := range []int{0, 1, 2, 3, 12, 13, 14} {
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
	for n := 0; n < 300 && !e.G.Over; n++ {
		d := e.Pending()
		driver.Observe(e)
		if d.ResumeKind == "search_confirm" && d.Player != 1 {
			t.Fatalf("opponent library confirmation is assigned to caster %d", d.Player)
		}
		if d.ResumeKind == "search" {
			return e, setup, driver
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
		if err := driver.RecordAnswer(d, in); err != nil {
			t.Fatal(err)
		}
		if err := e.SubmitHypothetical(in); err != nil {
			t.Fatal(err)
		}
	}
	t.Fatal("fixture did not reach the real opponent library search")
	return nil, setup, nil
}
