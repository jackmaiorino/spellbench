// Package identity issues Section 5.3 object ids: per viewer, fresh on every
// zone change and on every look into a hidden zone, from the game secret.
//
// gorge keeps one ObjID across zone changes, so the Tracker replays each new
// engine event through events.Apply on a shadow state.Game and counts every
// zone change exactly, including round trips inside one engine step. A shadow
// that disagrees with the engine is a hard error (halted).
//
// London mulligans: gorge defers every redraw until each un-kept seat has
// declared (rules/mulligan.go: handleMulligan only counts, and
// resolveMulliganRedraws runs after the declaration pass). A mulliganing
// seat's hand moves, hand to library to hand, in the Submit that completes the
// pass (its own only when it declares last), so callers must not expect an
// immediate redraw.
package identity

import (
	"errors"
	"fmt"

	"github.com/adams-shaun/gorge/events"
	"github.com/adams-shaun/gorge/rules"
	"github.com/adams-shaun/gorge/state"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/secrets"
)

var (
	ErrIDCollision    = errors.New("engine_contract_failure:id_collision")
	ErrShadowDiverged = errors.New("engine_contract_failure:identity_shadow_diverged")
)

type lookKey struct {
	viewer state.PlayerID
	key    string
}

// Tracker mints one game's ids. Sync it after every engine step, before
// minting: keys count the zone changes it has folded.
type Tracker struct {
	sec     *secrets.Game
	shadow  *state.Game
	applied int
	moves   map[state.ObjID]uint32
	looks   map[lookKey]uint32
	open    [2]map[string]uint32
	seen    [2]map[string]string
	zbuf    []state.Zone
}

// New tracks e from its current state.
func New(e *rules.Engine, sec *secrets.Game) *Tracker {
	return &Tracker{sec: sec, shadow: e.G.Clone(), applied: len(e.L.Events),
		moves: map[state.ObjID]uint32{}, looks: map[lookKey]uint32{},
		seen: [2]map[string]string{{}, {}}}
}

// Sync folds the events appended since the last call into the shadow game,
// counting every zone change per object, then checks the shadow against the engine.
func (t *Tracker) Sync(e *rules.Engine) error {
	for ; t.applied < len(e.L.Events); t.applied++ {
		t.zbuf = t.zbuf[:0]
		for i := range t.shadow.Objs {
			t.zbuf = append(t.zbuf, t.shadow.Objs[i].Zone)
		}
		events.Apply(t.shadow, e.L.Events[t.applied])
		for i := range t.zbuf {
			if t.shadow.Objs[i].Zone != t.zbuf[i] {
				t.moves[t.shadow.Objs[i].ID]++
			}
		}
	}
	if len(t.shadow.Objs) != len(e.G.Objs) {
		return fmt.Errorf("%w: %d shadow objects, %d engine objects", ErrShadowDiverged, len(t.shadow.Objs), len(e.G.Objs))
	}
	for i := range e.G.Objs {
		if e.G.Objs[i].Zone != t.shadow.Objs[i].Zone {
			return fmt.Errorf("%w: object %d", ErrShadowDiverged, e.G.Objs[i].ID)
		}
	}
	return nil
}

// Key is the internal key of Section 5.3: stable for one stay in one zone.
func (t *Tracker) Key(id state.ObjID) string { return fmt.Sprintf("%d:z%d", id, t.moves[id]) }

func (t *Tracker) mint(viewer state.PlayerID, msg string) (string, error) {
	oid := t.sec.ObjectID(msg)
	if prev, ok := t.seen[viewer][oid]; ok && prev != msg {
		return "", ErrIDCollision
	}
	t.seen[viewer][oid] = msg
	return oid, nil
}

// VisibleID is the id of an object in a zone viewer sees, for its current stay.
func (t *Tracker) VisibleID(viewer state.PlayerID, id state.ObjID) (string, error) {
	return t.mint(viewer, fmt.Sprintf("p%d:%s", viewer, t.Key(id)))
}

// OpenLook starts one effect's look for viewer; CloseLook ends it. Opening a
// look while one is open closes that one first, so its looks still count and
// no look id is reused.
func (t *Tracker) OpenLook(viewer state.PlayerID) {
	t.CloseLook(viewer)
	t.open[viewer] = map[string]uint32{}
}

func (t *Tracker) CloseLook(viewer state.PlayerID) {
	for key := range t.open[viewer] {
		t.looks[lookKey{viewer, key}]++
	}
	t.open[viewer] = nil
}

// LookID is the id the open look gives an object in a zone hidden from viewer
// (a library, or the other seat's hand). An object the viewer sees already has
// its VisibleID, so it is refused rather than given a second id.
func (t *Tracker) LookID(viewer state.PlayerID, id state.ObjID) (string, error) {
	m := t.open[viewer]
	if m == nil {
		return "", errors.New("engine_contract_failure:look_not_open")
	}
	if o := t.shadow.Obj(id); o == nil || sees(viewer, o) {
		return "", fmt.Errorf("engine_contract_failure:look_not_hidden: object %d", id)
	}
	key := t.Key(id)
	n, ok := m[key]
	if !ok {
		n = t.looks[lookKey{viewer, key}]
		m[key] = n
	}
	return t.mint(viewer, fmt.Sprintf("p%d:%s:look:%d", viewer, key, n))
}

// sees reports whether viewer sees o in its zone: every public zone, and its
// own hand. It matches the rule observe.Visible (Task 11) applies to records.
func sees(viewer state.PlayerID, o *state.Object) bool {
	switch o.Zone {
	case state.ZBattlefield, state.ZGraveyard, state.ZExile, state.ZStack, state.ZCommand:
		return true
	case state.ZHand:
		return o.Owner == viewer
	}
	return false
}
