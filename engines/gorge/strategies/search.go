// Package strategies bridges the pinned gorge internal search API using only
// declared public decks, actor observations and observer-local identities.
package strategies

import (
	"context"
	"fmt"

	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/internal/searchprobe"
	"github.com/adams-shaun/gorge/internal/searchseat"
	"github.com/adams-shaun/gorge/rules"
	"github.com/adams-shaun/gorge/seat"
	"github.com/adams-shaun/gorge/state"
	"github.com/adams-shaun/gorge/view"
)

type PublicGame = searchprobe.PublicGame
type History = searchprobe.History
type Frame = searchprobe.Frame
type Action = searchprobe.Action
type Trace = searchseat.Trace

// PublicHistory removes opponent observation boundaries from a native feed.
func PublicHistory(h History) History { return searchprobe.SpellbenchPublicHistory(h) }

// Search keeps the original SearchBot's default policy and RNG stream.
type Search struct {
	native *searchseat.SearchBot
	opts   searchseat.Options
}

func NewSearch(seed uint64, mana bool) *Search {
	opts := searchseat.Defaults()
	if mana {
		opts.Kinds["mana"] = true
	}
	return &Search{native: searchseat.NewSearchBot(seed, opts), opts: opts}
}

// NewRedealSearch retains the shipped rejection and rollout budgets. Its
// fallback root is reconstructed from public input, with a separate bounded
// replay cost reported in Trace.PublicReconstruction.
func NewRedealSearch(seed uint64, mana bool) *Search {
	s := NewSearch(seed, mana)
	s.opts.Redeal = true
	s.opts.SpellbenchPublicRedeal = true
	s.native = searchseat.NewSearchBot(seed, s.opts)
	return s
}

func (s *Search) Decide(ctx context.Context, v view.View, d decision.Decision) (decision.Intent, error) {
	return s.native.Decide(ctx, v, d)
}

func (s *Search) Eligible(d *decision.Decision) bool { return searchseat.Eligible(d, s.opts) }

// DecideObserved calls upstream Choose. These configurations read only G.Turn
// from its engine argument: candidates
// use the public decision and collector, and Sample receives public history.
// A constructed engine containing only that public turn enforces this boundary.
// Redeal constructs its root lazily from public history rather than this stub.
func (s *Search) DecideObserved(ctx context.Context, v view.View, d decision.Decision, setup PublicGame, h History, delta Delta) (decision.Intent, Trace, error) {
	bot, err := s.native.DecideBoard(ctx, seat.BoardFromView(v), d)
	if err != nil {
		return decision.Intent{}, Trace{}, err
	}
	if !delta.Live || len(h.Frames) == 0 || !searchseat.Eligible(&d, s.opts) {
		return bot, Trace{Fallback: delta.StopReason}, nil
	}
	if h.Actor != d.Player {
		return decision.Intent{}, Trace{}, fmt.Errorf("search history belongs to another actor")
	}
	c, err := searchprobe.SpellbenchCollector(h.Actor, delta.Aliases)
	if err != nil {
		return decision.Intent{}, Trace{}, err
	}
	e := &rules.Engine{G: &state.Game{Turn: v.Turn}}
	if !h.ActorBoundaries {
		return decision.Intent{}, Trace{}, fmt.Errorf("search requires actor-only public history")
	}
	in, _, trace := searchseat.Choose(setup, h, c, e, &d, bot, h.Frames[len(h.Frames)-1], s.opts)
	return in, trace, nil
}
