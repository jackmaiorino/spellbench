package identity

import (
	"maps"

	"github.com/adams-shaun/gorge/rules"
	"github.com/adams-shaun/gorge/state"
)

// CloneFor copies the tracker for a clone of the game (the resample
// self-check): the same move and look counters, open looks, minted ids and
// recorded reference keys, with the shadow re-pointed at e. The copy only
// mints; it never syncs.
func (t *Tracker) CloneFor(e *rules.Engine) *Tracker {
	c := &Tracker{sec: t.sec, shadow: e.G.Clone(), applied: len(e.L.Events),
		moves: maps.Clone(t.moves), looks: maps.Clone(t.looks),
		sourceKeys: maps.Clone(t.sourceKeys), targetKeys: map[state.ObjID][]chosen{},
		attackKeys: maps.Clone(t.attackKeys), blockKeys: maps.Clone(t.blockKeys), before: map[state.ObjID]uint32{}}
	for id, ks := range t.targetKeys {
		c.targetKeys[id] = append([]chosen(nil), ks...)
	}
	for v := range t.open {
		c.open[v] = maps.Clone(t.open[v]) // a nil map (no open look) stays nil
		c.seen[v] = maps.Clone(t.seen[v])
	}
	return c
}
