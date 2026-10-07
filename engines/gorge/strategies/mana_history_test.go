package strategies

import (
	"context"
	"testing"

	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/internal/searchprobe"
	"github.com/adams-shaun/gorge/rules"
	"github.com/adams-shaun/gorge/seat"
	"github.com/adams-shaun/gorge/view"
)

func TestPublicSamplerReplaysActorMultiColorMana(t *testing.T) {
	for _, symbol := range []string{"B", "R"} {
		t.Run(symbol, func(t *testing.T) {
			_, setup := fixture(t, 17, true)
			bridge := fixtureCard(t, "Name:Fixture Bridge\nTypes:Artifact Land\nA:AB$ Mana | Cost$ T | Produced$ Combo B R\nOracle:Fixture.\n")
			for i := 0; i < 12; i++ {
				setup.Decks[0][i] = bridge
			}
			e, err := rules.NewHypothetical(rules.Config{Seed: 17, Names: setup.Names, Decks: setup.Decks, StartingLife: 20}, []rules.ChanceDraw{{Bound: 2, Value: 0}})
			if err != nil {
				t.Fatal(err)
			}
			if err := e.AdvanceHypothetical(); err != nil {
				t.Fatal(err)
			}
			driver := NewDriver()
			bots := [2]*seat.Bot{seat.NewBot(3), seat.NewBot(7)}
			selected := false
			for n := 0; n < 160 && !e.G.Over; n++ {
				d := e.Pending()
				driver.Observe(e)
				if selected && d.Player == 0 {
					h := canonicalJSONHistory(t, PublicHistory(driver.seats[0].h))
					result, err := searchprobe.Sample(setup, h, searchprobe.SampleOptions{Seed: 54321, Attempts: 64, Worlds: 8, MaxSubmits: 5000})
					if err != nil || result.Accepted < 8 || len(result.Worlds) != 8 {
						t.Fatalf("actor's selected %s mana did not replay: %v accepted=%d worlds=%d rejection=%s", symbol, err, result.Accepted, len(result.Worlds), result.FirstRejection)
					}
					t.Logf("symbol=%s accepted=%d worlds=%d attempts=%d", symbol, result.Accepted, len(result.Worlds), result.Attempts)
					return
				}
				in, err := bots[d.Player].Decide(context.Background(), view.Project(e.G, e, d.Player, d), *d)
				if err != nil {
					t.Fatal(err)
				}
				if d.Player == 0 && d.Kind == decision.KChoose {
					for i, option := range d.Options {
						if option.Kind == "mana" && option.ManaSymbol == symbol {
							in.Choices = []int{i}
							selected = true
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
			t.Fatal("fixture never replayed a multi-color mana answer")
		})
	}
}
