package observe

import (
	"sort"

	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
)

func KnownEntry(ref protocol.ObjectRef, how string, fromTop *uint32) protocol.Known {
	id := ref.ObjectID
	return protocol.Known{OwnerSeat: ref.OwnerSeat, Zone: ref.Zone, CardName: *ref.CardName, ObjectID: &id,
		PositionFromTop: fromTop, How: how}
}

func lessU(a, b *uint32) (bool, bool) {
	switch {
	case a == nil && b == nil:
		return false, false
	case a == nil:
		return true, true
	case b == nil:
		return false, true
	case *a != *b:
		return *a < *b, true
	}
	return false, false
}

func lessS(a, b *string) (bool, bool) {
	switch {
	case a == nil && b == nil:
		return false, false
	case a == nil:
		return true, true
	case b == nil:
		return false, true
	case *a != *b:
		return *a < *b, true
	}
	return false, false
}

// SortKnown is Section 6.7's order: owner_seat, zone, card_name,
// position_from_top, position_from_bottom, how, object_id (nulls first).
func SortKnown(ks []protocol.Known) {
	sort.SliceStable(ks, func(i, j int) bool {
		a, b := ks[i], ks[j]
		if a.OwnerSeat != b.OwnerSeat {
			return a.OwnerSeat < b.OwnerSeat
		}
		if a.Zone != b.Zone {
			return a.Zone < b.Zone
		}
		if a.CardName != b.CardName {
			return a.CardName < b.CardName
		}
		if l, ok := lessU(a.PositionFromTop, b.PositionFromTop); ok {
			return l
		}
		if l, ok := lessU(a.PositionFromBottom, b.PositionFromBottom); ok {
			return l
		}
		if a.How != b.How {
			return a.How < b.How
		}
		l, _ := lessS(a.ObjectID, b.ObjectID)
		return l
	})
}
