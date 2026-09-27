// Package gamecfg builds a gorge engine whose every random draw comes from
// Section 11.6 streams: rules.NewHypotheticalPlanned asks a planner for each
// library shuffle (per player and ordinal), and the chance prefix forces the
// toss to the host-assigned starting seat. The hypothetical constructor is
// used deliberately as the live engine; see the plan's Global Constraints.
package gamecfg

import (
	"encoding/binary"
	"errors"
	"fmt"

	"github.com/adams-shaun/gorge/cards"
	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/rules"
	"github.com/adams-shaun/gorge/state"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/secrets"
)

var ErrUnplannedRandomness = errors.New("engine_contract_failure:unplanned_randomness")

type Rules struct {
	Mulligan     string // "london" or "none"
	StartingSeat state.PlayerID
}

type Game struct {
	E       *rules.Engine
	Secret  *secrets.Game
	planned uint64 // draws the planner forced, plus the toss
}

// New returns the game at its first decision, even alongside a CheckRandomness error.
func New(reg *cards.Registry, sec *secrets.Game, decks [2][]*cards.Card, r Rules) (*Game, error) {
	g := &Game{Secret: sec, planned: 1}
	seed := sec.StreamSeed("shared", "gorge_seed", 0)
	cfg := rules.Config{
		Seed:         binary.BigEndian.Uint64(seed[:8]),
		Names:        []string{"p0", "p1"},
		Decks:        [][]*cards.Card{decks[0], decks[1]},
		Tokens:       reg.Tokens,
		NameUniverse: reg.Cards,
	}
	if r.Mulligan == "london" {
		cfg.Mulligans = 7
	}
	e, err := rules.NewHypotheticalPlanned(cfg, []rules.ChanceDraw{{Bound: 2, Value: int(r.StartingSeat)}}, g.plan)
	if err != nil {
		return nil, err
	}
	g.E = e
	if err := e.AdvanceHypothetical(); err != nil {
		return nil, err
	}
	return g, g.CheckRandomness()
}

// plan draws the shuffle of ctx.Player's library from that seat's own stream.
func (g *Game) plan(ctx rules.ShuffleContext) ([]state.ObjID, error) {
	r := g.Secret.Stream(fmt.Sprintf("p%d", ctx.Player), "library_shuffle", uint64(ctx.Ordinal))
	out := make([]state.ObjID, len(ctx.Library))
	for i, c := range ctx.Library {
		out[i] = c.ID
	}
	for i := len(out) - 1; i > 0; i-- {
		j := r.IntN(i + 1)
		out[i], out[j] = out[j], out[i]
	}
	if len(out) > 1 {
		g.planned += uint64(len(out) - 1)
	}
	return out, nil
}

// CheckRandomness fails when the engine drew a value no planner supplied.
func (g *Game) CheckRandomness() error {
	if got := g.E.RNGDraws(); got != g.planned {
		return fmt.Errorf("%w: %d draws, %d planned", ErrUnplannedRandomness, got, g.planned)
	}
	return nil
}

func (g *Game) Submit(in decision.Intent) error {
	if err := g.E.SubmitHypothetical(in); err != nil {
		return err
	}
	return g.CheckRandomness()
}

// Probe submits ins to a clone. Clones have no planner, so a probe's own
// shuffles draw from the clone's generator; probes judge legality only.
// A clone still holds the real hidden zones and the secret-seeded generator,
// so no probe outcome may set a decision's shape through hidden-zone
// contents (Section 13 F3); Task 28's resample check is the net.
func (g *Game) Probe(ins ...decision.Intent) (*rules.Engine, error) {
	c := g.E.Clone()
	for _, in := range ins {
		if err := c.SubmitHypothetical(in); err != nil {
			return nil, err
		}
	}
	return c, nil
}
