package session

import (
	"bytes"
	"errors"
	"fmt"
	"maps"
	"math/rand/v2"

	"github.com/adams-shaun/gorge/state"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/gamecfg"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/mapping"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/observe"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/wire"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/xview"
)

var ErrResample = errors.New("noninterference self-check failed")

// ResampleCheck rebuilds the pending seat decision from a clone whose hidden
// state was redrawn and requires byte equality with the real one.
func (s *Game) ResampleCheck(r *rand.Rand) error {
	// Only a transaction's first pose was built from this very state; every
	// later one (a follow-up group, the next pick of a variable selection, the
	// substeps of a group) carries answers the clone never saw.
	if s.resp == nil || s.native == nil || s.pose == nil || !s.fresh {
		return nil
	}
	seat := s.pose.Seat
	other := 1 - seat
	c := s.g.E.Clone()
	pinned := map[state.ObjID]bool{} // cards whose place the seat knows
	for _, o := range s.native.Options {
		pinned[o.Obj] = true
	}
	var wholeLook [2]bool
	for _, k := range s.pose.Known {
		if k.Zone != "library" {
			continue
		}
		p := state.PlayerID(0)
		if k.OwnerSeat == "p1" {
			p = 1
		}
		lib := c.G.Zone(state.ZLibrary, p)
		switch {
		case k.PositionFromTop == nil:
			wholeLook[p] = true
		case int(*k.PositionFromTop) < len(lib):
			pinned[lib[*k.PositionFromTop]] = true
		}
	}
	for p := state.PlayerID(0); p < 2; p++ {
		lib := append([]state.ObjID(nil), c.G.Zone(state.ZLibrary, p)...)
		var free []int
		for i, id := range lib {
			if !pinned[id] {
				free = append(free, i)
			}
		}
		for i := len(free) - 1; i > 0; i-- {
			j := r.IntN(i + 1)
			lib[free[i]], lib[free[j]] = lib[free[j]], lib[free[i]]
		}
		c.G.SetZone(state.ZLibrary, p, lib)
	}
	if !wholeLook[other] {
		hand := append([]state.ObjID(nil), c.G.Zone(state.ZHand, other)...)
		lib := append([]state.ObjID(nil), c.G.Zone(state.ZLibrary, other)...)
		for i := range hand {
			if len(lib) == 0 || pinned[hand[i]] {
				continue
			}
			j := r.IntN(len(lib))
			if pinned[lib[j]] {
				continue
			}
			hand[i], lib[j] = lib[j], hand[i]
			c.G.Obj(hand[i]).Zone, c.G.Obj(lib[j]).Zone = state.ZHand, state.ZLibrary
		}
		c.G.SetZone(state.ZHand, other, hand)
		c.G.SetZone(state.ZLibrary, other, lib)
	}
	g := &gamecfg.Game{E: c, Secret: s.g.Secret}
	tr := s.env.IDs.CloneFor(c)
	env := &mapping.Env{AutoPay: s.env.AutoPay, G: g, IDs: tr, Obs: &observe.Projector{E: c, IDs: tr, Mulls: s.env.Obs.Mulls},
		Action: s.env.Action, Domain: s.env.Domain, Slots: maps.Clone(s.env.Slots), Looking: s.env.Looking}
	twin := &Game{ID: s.ID, cfg: s.cfg, g: g, env: env, step: s.step, decisions: s.decisions,
		seatStep: s.seatStep, groupID: s.groupID, nativeCount: s.nativeCount, maxSteps: s.maxSteps, maxDecisions: s.maxDecisions}
	if x, ok := s.cfg.Ext.(*xview.Extender); ok {
		twin.cfg.Ext = x.Clone()
	}
	twin.cfg.Audit = false
	d := c.Pending()
	tx, err := mapping.Begin(env, d)
	if err != nil {
		return fmt.Errorf("%w: %v", ErrResample, err)
	}
	twin.tx, twin.native = tx, d
	p, err := tx.Pose()
	if err != nil {
		return fmt.Errorf("%w: %v", ErrResample, err)
	}
	if err := twin.present(p); err != nil {
		return fmt.Errorf("%w: %v", ErrResample, err)
	}
	a, _ := wire.Canonical(s.resp.SeatDecision)
	b, _ := wire.Canonical(twin.resp.SeatDecision)
	if !bytes.Equal(a, b) {
		return fmt.Errorf("%w at step %d", ErrResample, s.step)
	}
	return nil
}
