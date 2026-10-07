package strategies

import (
	"context"
	"strings"
	"testing"

	"github.com/adams-shaun/gorge/cards"
	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/events"
	"github.com/adams-shaun/gorge/internal/searchprobe"
	"github.com/adams-shaun/gorge/rules"
	"github.com/adams-shaun/gorge/seat"
	"github.com/adams-shaun/gorge/state"
	"github.com/adams-shaun/gorge/view"
)

// The opponent's public London bottoming moves its own hidden card. It must
// not disable guidance from the actor's independently observed future draws.
func TestOpponentLondonBottomPreservesActorsObservedDraws(t *testing.T) {
	_, setup := fixture(t, 17, false)
	deck := append([]*cards.Card(nil), setup.Decks[0]...)
	for i, name := range []string{"Rare One", "Rare Two", "Rare Three"} {
		deck[7+i] = fixtureCard(t, "Name:"+name+"\nManaCost:100 R\nTypes:Artifact\nOracle:Fixture.\n")
	}
	setup.Decks[0], setup.Mulligans = deck, 1
	e, err := rules.NewHypotheticalPlanned(rules.Config{Seed: 17, Names: setup.Names, Decks: setup.Decks, Mulligans: 1},
		[]rules.ChanceDraw{{Bound: 2, Value: 0}}, func(ctx rules.ShuffleContext) ([]state.ObjID, error) {
			if ctx.Player != 0 {
				return nil, nil
			}
			var order []state.ObjID
			for _, card := range ctx.Library {
				order = append(order, card.ID)
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
	bottomed, taken, draws := false, false, 0
	for n := 0; n < 200 && !e.G.Over; n++ {
		d := e.Pending()
		driver.Observe(e)
		if bottomed && draws == 3 && d.Player == 0 {
			h := canonicalJSONHistory(t, PublicHistory(driver.seats[0].h))
			opts := searchprobe.SampleOptions{Seed: 54321, Attempts: 64, Worlds: 8, MaxSubmits: 5000, Redeal: &searchprobe.RedealBase{SpellbenchPublic: true}}
			result, err := searchprobe.Sample(setup, h, opts)
			if err != nil || len(result.Worlds) != 8 || result.RedealRefused != "" {
				t.Fatalf("opponent bottoming lost actor draw constraints: %v accepted=%d worlds=%d refused=%s work=%+v", err, result.Accepted, len(result.Worlds), result.RedealRefused, result.PublicReconstruction)
			}
			t.Logf("observed rare draws=%d accepted=%d redealt=%d reconstruction=%+v", draws, result.Accepted, result.Redealt, result.PublicReconstruction)
			return
		}
		in, err := bots[d.Player].Decide(context.Background(), view.Project(e.G, e, d.Player, d), *d)
		if err != nil {
			t.Fatal(err)
		}
		if d.Kind == decision.KMulligan && d.Options[0].Kind == "keep" {
			in.Choices = []int{0}
			if d.Player == 1 && !taken && len(d.Options) > 1 {
				in.Choices, taken = []int{1}, true
			}
		}
		if err := driver.RecordAnswer(d, in); err != nil {
			t.Fatal(err)
		}
		pos := len(e.L.Events)
		if err := e.SubmitHypothetical(in); err != nil {
			t.Fatal(err)
		}
		for _, ev := range e.L.Events[pos:] {
			bottomed = bottomed || ev.Kind == events.MoveZone && ev.Player == 1 && ev.Text == "bottomed"
			if ev.Kind == events.Draw && ev.Player == 0 && strings.HasPrefix(e.G.Obj(ev.Obj).Face().Name, "Rare ") {
				draws++
			}
		}
	}
	t.Fatalf("fixture did not reach opponent bottoming and three known draws: bottomed=%v draws=%d", bottomed, draws)
}
