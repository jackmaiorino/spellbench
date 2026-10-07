package agent

import (
	"context"
	"encoding/json"
	"fmt"

	"github.com/adams-shaun/gorge/cards"
	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/spellbench-strategies"
	"github.com/adams-shaun/gorge/state"
	"github.com/adams-shaun/gorge/view"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/catalog"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/wire"
)

type searchDeck struct {
	Name     string         `json:"name"`
	Decklist []wire.DeckRow `json:"decklist"`
}

// SetRegistry supplies static corpus definitions; it never supplies a game.
// The command loads the pinned corpus, and in-process qualification reuses
// that same immutable registry rather than opening it once per test agent.
func (s *Server) SetRegistry(reg *cards.Registry) { s.registry = reg }

func (s *Server) startSearch(q request) error {
	if s.registry == nil || q.OwnDeck == nil || q.OpponentDeck == nil {
		return fmt.Errorf("search requires the pinned corpus and both public decklists")
	}
	actor := state.PlayerID(0)
	if q.Seat == "p1" {
		actor = 1
	} else if q.Seat != "p0" {
		return fmt.Errorf("invalid search actor")
	}
	decks := make([][]*cards.Card, 2)
	for i, d := range []*searchDeck{q.OwnDeck, q.OpponentDeck} {
		if len(d.Decklist) == 0 {
			return fmt.Errorf("search requires nonempty public decklists")
		}
		for _, row := range d.Decklist {
			if row.Count <= 0 || row.Count > 1000 {
				return fmt.Errorf("invalid public deck row")
			}
		}
		cards, err := catalog.Resolve(s.registry, catalog.Deck{Name: d.Name, Rows: d.Decklist})
		if err != nil {
			return err
		}
		seat := actor
		if i == 1 {
			seat = 1 - actor
		}
		decks[seat] = cards
	}
	s.searchSetup = strategies.PublicGame{Names: []string{"p0", "p1"}, Decks: decks, Tokens: s.registry.Tokens, StartingLife: 20}
	switch q.Rules.Mulligan {
	case "london":
		s.searchSetup.Mulligans = 7
	case "none":
	default:
		return fmt.Errorf("search requires the declared mulligan rule")
	}
	s.searchHistory = strategies.History{Actor: actor, Answers: map[int][]strategies.Action{}}
	return nil
}

func (s *Server) decideSearch(q request, v view.View, d decision.Decision, bot *strategies.Search) (decision.Intent, *strategies.Trace) {
	raw, ok := q.Decision.Extensions[strategies.Extension]
	if !ok {
		panic("required search history extension is absent")
	}
	var delta strategies.Delta
	if err := json.Unmarshal(raw, &delta); err != nil {
		panic(err)
	}
	if err := strategies.AppendDelta(&s.searchHistory, delta); err != nil {
		panic(err)
	}
	in, trace, err := bot.DecideObserved(context.Background(), v, d, s.searchSetup, s.searchHistory, delta)
	if err != nil {
		panic(err)
	}
	return in, &trace
}
