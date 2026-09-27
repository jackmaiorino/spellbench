// Package testgame drives real gorge games for tests.
package testgame

import (
	"context"
	"testing"

	"github.com/adams-shaun/gorge/cards"
	"github.com/adams-shaun/gorge/rules"
	"github.com/adams-shaun/gorge/seat"
	"github.com/adams-shaun/gorge/state"
	"github.com/adams-shaun/gorge/view"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/catalog"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/gamecfg"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/secrets"
)

func New(t testing.TB, reg *cards.Registry, deck0, deck1 string, secretByte byte, mulligan string) *gamecfg.Game {
	t.Helper()
	var decks [2][]*cards.Card
	for i, id := range []string{deck0, deck1} {
		d, ok := catalog.ByID(id)
		if !ok {
			t.Fatalf("no catalog deck %s", id)
		}
		cs, err := catalog.Resolve(reg, d)
		if err != nil {
			t.Fatal(err)
		}
		decks[i] = cs
	}
	s := make([]byte, 32)
	s[0] = secretByte
	g, err := gamecfg.New(reg, secrets.NewGame(s), decks, gamecfg.Rules{Mulligan: mulligan, StartingSeat: state.PlayerID(0)})
	if err != nil {
		t.Fatal(err)
	}
	return g
}

func Bots(seed uint64) [2]seat.Seat { return [2]seat.Seat{seat.NewBot(seed), seat.NewBot(seed + 1)} }

// RunUntil answers decisions with bots until pred holds (true) or the game ends (false).
func RunUntil(t testing.TB, g *gamecfg.Game, bots [2]seat.Seat, pred func(*rules.Engine) bool, maxIntents int) bool {
	t.Helper()
	for n := 0; n < maxIntents; n++ {
		if pred(g.E) {
			return true
		}
		d := g.E.Pending()
		if g.E.G.Over || d == nil {
			return false
		}
		in, _ := bots[d.Player].Decide(context.Background(), view.Project(g.E.G, g.E, d.Player, d), *d)
		if err := g.Submit(in); err != nil {
			t.Fatal(err)
		}
	}
	return false
}
