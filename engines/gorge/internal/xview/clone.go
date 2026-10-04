package xview

import (
	"maps"
	"slices"

	"github.com/adams-shaun/gorge/state"
)

// Clone copies the per-seat id tables, so a rebuilt payload numbers ids
// exactly as the real one did.
func (x *Extender) Clone() *Extender {
	c := &Extender{}
	for s, t := range x.tables {
		c.tables[s] = &table{ints: maps.Clone(t.ints), next: t.next}
		c.last[s] = slices.Clone(x.last[s])
		c.lastFollow[s] = maps.Clone(x.lastFollow[s])
		c.lastPayments[s] = maps.Clone(x.lastPayments[s])
	}
	return c
}

// Perm is the native -> payload option renumbering of the seat's last
// payload. The audit reads it; no agent ever receives it.
func (x *Extender) Perm(seat state.PlayerID) []int { return x.last[seat] }

// FollowOf is the payload key and renumbering of the folded follow-up the
// seat's last payload keyed nativeKey natively (audit only).
func (x *Extender) FollowOf(seat state.PlayerID, nativeKey string) (Follow, bool) {
	f, ok := x.lastFollow[seat][nativeKey]
	return f, ok
}
