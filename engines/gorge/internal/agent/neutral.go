package agent

import (
	"encoding/json"
	"fmt"
	"strings"

	"github.com/jackmaiorino/spellbench/engines/gorge/internal/neutral"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/wire"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/xview"
)

// NeutralVersion versions the translation from v2 observations and
// candidates; it joins Version in a neutral agent's identity.
const NeutralVersion = "neutral-0.1.0"

// neutralGame is a seat playing another engine's game: each decision is
// translated from the observation and candidates alone (internal/neutral).
type neutralGame struct {
	session *neutral.Session
	line    []byte
	// Gaps lists the cards of either public decklist gorge cannot play fully.
	Gaps []neutral.Gap
}

// EnableNeutral makes the server read the v2 observation and candidates
// instead of x_gorge_view_v1, so it can play a game hosted by any engine.
// It needs the registry for printed card facts. Search policies replay games
// in gorge and cannot play another engine's game.
func (s *Server) EnableNeutral() error {
	if strings.HasPrefix(s.policy, "search") {
		return fmt.Errorf("policy %s replays games in gorge and cannot play another engine's game", s.policy)
	}
	if s.registry == nil {
		return fmt.Errorf("the neutral world needs the pinned registry")
	}
	s.neutral = &neutralGame{}
	return nil
}

func (s *Server) startNeutral(q request) error {
	g := &neutralGame{session: neutral.NewSession(s.registry)}
	for _, d := range []*searchDeck{q.OwnDeck, q.OpponentDeck} {
		if d == nil {
			continue
		}
		rows := make([]wire.DeckRow, len(d.Decklist))
		copy(rows, d.Decklist)
		deck, err := neutral.ResolveDeck(s.registry, rows)
		if err != nil {
			return fmt.Errorf("deck %s: %w", d.Name, err)
		}
		g.Gaps = append(g.Gaps, neutral.Coverage(s.registry, deck)...)
	}
	s.neutral = g
	return nil
}

func (s *Server) translate(q request) (xview.Payload, error) {
	var full struct {
		Decision protocol.SeatDecision `json:"decision"`
	}
	if err := json.Unmarshal(s.neutral.line, &full); err != nil {
		return xview.Payload{}, err
	}
	if s.neutral.session == nil {
		return xview.Payload{}, fmt.Errorf("choose before game_start")
	}
	p, err := s.neutral.session.Payload(&full.Decision)
	if err == nil && len(p.Ops) != len(q.Decision.Candidates) {
		err = fmt.Errorf("%d ops for %d candidates", len(p.Ops), len(q.Decision.Candidates))
	}
	return p, err
}

// NeutralCounts reports the seat's untranslated decisions by candidate kind.
func (s *Server) NeutralCounts() map[string]int {
	if s.neutral == nil || s.neutral.session == nil {
		return nil
	}
	return s.neutral.session.Counts
}
