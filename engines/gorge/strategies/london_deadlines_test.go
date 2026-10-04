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

// Legal London bottoming, a declined land drop and three later public land
// names must reconstruct without guessing their hidden physical copies.
// The actor's printed search reveals only its matching basic lands. Islands
// and expensive artifacts in the unseen tail can vary without changing it.
func TestPublicLondonReplayPreservesDrawsAndFilteredOwnSearch(t *testing.T) {
	setup, h := londonLandscapeHistory(t, false)
	_, other := londonLandscapeHistory(t, true)
	a, _ := json.Marshal(h)
	b, _ := json.Marshal(other)
	if string(a) != string(b) {
		for i := range h.Frames {
			if !reflect.DeepEqual(h.Frames[i], other.Frames[i]) {
				t.Logf("first difference frame=%d identities=%+v versus%+v events=%+v versus%+v", i, h.Frames[i].Identities, other.Frames[i].Identities, h.Frames[i].Events, other.Frames[i].Events)
				break
			}
		}
		t.Fatal("unseen nonmatching library order changed public history")
	}
	identities := map[uint32]string{}
	searches := 0
	for _, frame := range h.Frames {
		for _, identity := range frame.Identities {
			identities[identity.ID] = identity.Name
		}
		if frame.Decision != nil && frame.Decision.Kind == decision.KChoose && len(frame.Decision.Options) > 0 && frame.Decision.Options[0].Action.Kind == "search" {
			searches++
			for _, option := range frame.Decision.Options {
				name := identities[option.Action.Obj]
				if name != "Forest" && name != "Swamp" && name != "Mountain" {
					t.Fatalf("filtered landscape offer contains %s", name)
				}
			}
		}
	}
	if searches != 1 {
		t.Fatal("fixture did not expose exactly one filtered search")
	}
	result, err := searchprobe.Sample(setup, h, searchprobe.SampleOptions{Seed: 54321, Attempts: 64, Worlds: 8, MaxSubmits: 5000,
		Redeal: &searchprobe.RedealBase{SpellbenchPublic: true}})
	if err != nil || len(result.Worlds) != 8 || result.RedealRefused != "" || result.PublicReconstruction == nil ||
		result.PublicReconstruction.BudgetExhausted != 0 || result.PublicReconstruction.Submits > 5000 {
		t.Fatalf("London/search replay: %v accepted=%d worlds=%d refused=%s work=%+v", err, result.Accepted, len(result.Worlds), result.RedealRefused, result.PublicReconstruction)
	}
	known, err := searchprobe.ProjectKnownCards(h)
	if err != nil {
		t.Fatal(err)
	}
	for _, world := range result.Worlds {
		if err := known.Holds(world); err != nil {
			t.Fatal(err)
		}
	}
	t.Logf("actor_frames=%d accepted=%d redealt=%d work=%+v", len(h.Frames), result.Accepted, result.Redealt, result.PublicReconstruction)
}

func londonLandscapeHistory(t *testing.T, swapTail bool) (PublicGame, History) {
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
	quiet := fixtureCard(t, "Name:Quiet Artifact\nManaCost:99\nTypes:Artifact\nOracle:Fixture.\n")
	actor := []*cards.Card{lookup("Twisted Landscape"), lookup("Mountain"), lookup("Forest"), lookup("Swamp"), quiet, quiet, lookup("Mountain"),
		quiet, quiet, quiet, quiet, lookup("Forest"), lookup("Swamp"), lookup("Mountain"), lookup("Island"), quiet,
		lookup("Forest"), lookup("Swamp"), lookup("Mountain"), lookup("Island")}
	opponent := make([]*cards.Card, 20)
	for i := range opponent {
		opponent[i] = quiet
	}
	opponent[0], opponent[1], opponent[2] = lookup("Forest"), lookup("Swamp"), lookup("Mountain")
	setup := PublicGame{Names: []string{"p0", "p1"}, Decks: [][]*cards.Card{actor, opponent}, Tokens: reg.Tokens, StartingLife: 20, Mulligans: 1}
	e, err := rules.NewHypotheticalPlanned(rules.Config{Seed: 17, Names: setup.Names, Decks: setup.Decks, Tokens: setup.Tokens, StartingLife: 20, Mulligans: 1},
		[]rules.ChanceDraw{{Bound: 2, Value: 0}}, func(ctx rules.ShuffleContext) ([]state.ObjID, error) {
			var order []state.ObjID
			if ctx.Player == 1 {
				for _, name := range []string{"Forest", "Swamp", "Mountain"} {
					for _, card := range ctx.Library {
						if card.Name == name {
							order = append(order, card.ID)
						}
					}
				}
			}
			for _, card := range ctx.Library {
				if ctx.Player == 0 || card.Name == "Quiet Artifact" {
					order = append(order, card.ID)
				}
			}
			if swapTail && ctx.Player == 0 && ctx.Ordinal == 0 {
				order[14], order[15] = order[15], order[14]
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
	taken, landscape, played := false, false, 0
	searched := false
	for n := 0; n < 350 && !e.G.Over; n++ {
		d := e.Pending()
		driver.Observe(e)
		if searched && d.Player == 0 && d.Kind == decision.KPriority {
			return setup, canonicalJSONHistory(t, PublicHistory(driver.seats[0].h))
		}
		if d.Player == 0 && d.Kind == decision.KChoose && len(d.Options) > 0 && d.Options[0].Kind == "search" {
			if !taken || played != 3 {
				t.Fatal("fixture skipped London bottoming or public lands")
			}
			searched = true
		}
		in, err := bot.Decide(context.Background(), view.Project(e.G, e, d.Player, d), *d)
		if err != nil {
			t.Fatal(err)
		}
		if d.Player == 0 && d.Kind == decision.KChoose && len(d.Options) > 0 && d.Options[0].Kind == "search" {
			in.Choices = []int{0}
		}
		if d.Kind == decision.KMulligan && d.Options[0].Kind == "keep" {
			in.Choices = []int{0}
			if d.Player == 1 && !taken && len(d.Options) > 1 {
				in.Choices, taken = []int{1}, true
			}
		}
		if d.Player == 1 && d.Kind == decision.KMulligan && d.Options[0].Kind == "bottom" {
			for i, option := range d.Options {
				if e.G.Obj(option.Obj).Card.Faces[0].Name == "Quiet Artifact" {
					in.Choices = []int{i}
					break
				}
			}
		}
		if d.Kind == decision.KPriority {
			for i, option := range d.Options {
				if option.Kind == "pass" {
					in.Choices = []int{i}
					break
				}
			}
			for i, option := range d.Options {
				object := e.G.Obj(option.Obj)
				if object == nil || object.Card == nil {
					continue
				}
				name := object.Card.Faces[0].Name
				if d.Player == 0 && !landscape && option.Kind == "play_land" && name == "Twisted Landscape" {
					in.Choices, landscape = []int{i}, true
					break
				}
				if d.Player == 0 && landscape && played == 3 && option.Kind == "ability" && option.Ability == 1 && name == "Twisted Landscape" {
					in.Choices = []int{i}
					break
				}
				if d.Player == 1 && e.G.Turn >= 4 && played < 3 && option.Kind == "play_land" && name == []string{"Forest", "Swamp", "Mountain"}[played] {
					in.Choices = []int{i}
					played++
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
	t.Fatalf("fixture did not reach the filtered own search: took_mulligan=%v landscape=%v public_lands=%d", taken, landscape, played)
	return setup, History{}
}
