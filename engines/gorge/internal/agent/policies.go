package agent

import (
	"context"
	"fmt"
	"math/rand/v2"
	"slices"

	"github.com/adams-shaun/gorge/botpolicy"
	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/seat"
	"github.com/adams-shaun/gorge/spellbench-strategies"
	"github.com/adams-shaun/gorge/view"
)

const Version = "gorge-26257e0eda17/adapter-0.2.0"

// Policy identifies one shipped policy, independently of its benchmark label.
// The default cast profile is an alias, because the pinned upstream profile
// equals DefaultCastWeights. An external profile must get its own identity.
type Policy struct {
	Key, Name string
	New       func(uint64) seat.Seat
}

var policies = []Policy{
	{"bot", "gorge-bot", func(seed uint64) seat.Seat { return seat.NewBot(seed) }},
	{"bot-auto-pay", "gorge-bot-auto-pay", func(seed uint64) seat.Seat { b := seat.NewBot(seed); b.EnableAutoPayMana(); return b }},
	{"lethal-pressure", "gorge-lethal-pressure", func(seed uint64) seat.Seat { return seat.NewLethalPressureBot(seed) }},
	{"lethal-pressure-auto-pay", "gorge-lethal-pressure-auto-pay", func(seed uint64) seat.Seat { b := seat.NewLethalPressureBot(seed); b.EnableAutoPayMana(); return b }},
	{"ar8", "gorge-ar8", func(seed uint64) seat.Seat { return seat.NewCombinedLethalBot(seed) }},
	{"blocks", "gorge-blocks", func(seed uint64) seat.Seat { return seat.NewBlocksBot(seed) }},
	{"explore", "gorge-explore", func(seed uint64) seat.Seat { return seat.NewExploreBot(seed) }},
	{"legacy", "gorge-legacy", func(seed uint64) seat.Seat {
		return &legacySeat{rand.New(rand.NewPCG(seed, seed^0x9e3779b97f4a7c15))}
	}},
	{"search", "gorge-search", func(seed uint64) seat.Seat { return strategies.NewSearch(seed, false) }},
	{"search-mana", "gorge-search-mana", func(seed uint64) seat.Seat { return strategies.NewSearch(seed, true) }},
}

// Policies returns the distinct policies currently supported by this adapter.
func Policies() []Policy { return slices.Clone(policies) }

func lookupPolicy(key string) (Policy, error) {
	if key == "cast-profile" {
		key = "bot"
	}
	for _, p := range policies {
		if p.Key == key {
			return p, nil
		}
	}
	return Policy{}, fmt.Errorf("unknown or not yet integrated policy %q", key)
}

// This is cmd/botbench's legacySeat, using the same public board projection
// and PCG seed derivation. It calls the upstream policy, rather than copying
// or approximating its decision rules.
type legacySeat struct{ r *rand.Rand }

func (s *legacySeat) Decide(_ context.Context, v view.View, d decision.Decision) (decision.Intent, error) {
	return botpolicy.LegacyDecide(seat.BoardFromView(v), &d, s.r), nil
}
