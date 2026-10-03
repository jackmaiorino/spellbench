package server

import (
	"encoding/json"
	"fmt"
	"strings"
	"testing"

	"github.com/adams-shaun/gorge/cards"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/catalog"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/gamecfg"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/secrets"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/session"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/testcorpus"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/wire"
)

func resetLine(t *testing.T, id, gameID string) []byte {
	t.Helper()
	d, ok := catalog.ByID("Burn")
	if !ok {
		t.Fatal("Burn is not in the catalog")
	}
	names, _ := json.Marshal(catalog.PoolNames())
	line := fmt.Sprintf(`{"request_type":"reset","protocol":"spellbench/v2","request_id":%q,"game_id":%q,"format":"pauper-bo1","seats":[{"seat":"p0","deck":{"deck_id":%q,"catalog_id":"Burn"}},{"seat":"p1","deck":{"deck_id":%q,"catalog_id":"Burn"}}],"rules":{"opponent_decklist":"visible","mulligan":"london","starting_player":"host_assigned","starting_seat":"p0","card_name_domain":{"domain_id":%q,"names":%s},"extensions":[],"probe":false},"game_secret":"%s","max_decisions":10000,"max_steps":100000}`,
		id, gameID, d.DeckID(), d.DeckID(), wire.DomainID(catalog.PoolNames()), names, strings.Repeat("ab", 32))
	return []byte(line)
}

// Task 22 review flag: session.Start returns gamecfg's CheckRandomness error
// as a plain error. Section 9.2 licenses it as unsupported_deck ("cards the
// engine cannot play, or whose decisions it cannot offer"), and the failed
// start must consume nothing: no game, no game id.
func TestStartFailureIsUnsupportedDeckAndConsumesNothing(t *testing.T) {
	old := startSession
	defer func() { startSession = old }()
	startSession = func(session.Config, string, *protocol.ResetReq, *secrets.Game, [2][]*cards.Card) (*session.Game, error) {
		return nil, fmt.Errorf("%w: 5 draws, 4 planned", gamecfg.ErrUnplannedRandomness)
	}
	s := New(testcorpus.Registry(t), nil)
	bad := s.Handle(resetLine(t, "r-1", "g-1"))
	var m map[string]any
	if err := json.Unmarshal(bad, &m); err != nil {
		t.Fatalf("%s: %v", bad, err)
	}
	e, _ := m["error"].(map[string]any)
	if m["response_type"] != "error" || e["code"] != "unsupported_deck" {
		t.Fatalf("start failure answered %s", bad)
	}
	if msg, _ := e["message"].(string); !strings.Contains(msg, "unplanned_randomness") {
		t.Fatalf("the cause did not reach the wire: %s", bad)
	}
	if s.game != nil || s.gameIDs["g-1"] {
		t.Fatal("a failed start started a game or consumed the game id")
	}
	startSession = old
	ok := s.Handle(resetLine(t, "r-2", "g-1"))
	if !strings.Contains(string(ok), `"response_type":"decision"`) {
		t.Fatalf("the game id was not reusable after a failed start: %s", ok)
	}
}
