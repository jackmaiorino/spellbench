// Package identity issues Section 5.3 object ids: per viewer, fresh on every
// zone change and on every look into a hidden zone, from the game secret.
//
// gorge keeps one ObjID across zone changes, so the Tracker replays each new
// engine event through events.Apply on a shadow state.Game and counts every
// zone change exactly, including round trips inside one engine step. A shadow
// that disagrees with the engine is a hard error (halted). As it folds events
// it also records the key each stack source, target, attacked permanent and
// blocker was taken at, so a reference whose object has since changed zones
// can be sent as null (G1-3).
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

// chosen is one stack target as it was when chosen: the object and its key.
type chosen struct {
	obj state.ObjID
	key string
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
	// References that must turn null when their object changes zones (G1-3):
	// the key each was taken at. gorge keeps one ObjID across zone changes, so
	// a live ObjID alone cannot tell a stale reference from a current one.
	sourceKeys map[state.ObjID]string   // stack ability -> its source's key when put on the stack
	targetKeys map[state.ObjID][]chosen // stack object -> its targets' keys when chosen
	attackKeys map[state.ObjID]string   // attacker -> the attacked battle's or planeswalker's key
	blockKeys  map[state.ObjID]string   // blocker declared this combat -> its key when declared
	before     map[state.ObjID]uint32   // move counts at the start of this Sync batch, for objects that moved in it
}

// New tracks e from its current state.
func New(e *rules.Engine, sec *secrets.Game) *Tracker {
	return &Tracker{sec: sec, shadow: e.G.Clone(), applied: len(e.L.Events),
		moves: map[state.ObjID]uint32{}, looks: map[lookKey]uint32{},
		seen:       [2]map[string]string{{}, {}},
		sourceKeys: map[state.ObjID]string{}, targetKeys: map[state.ObjID][]chosen{},
		attackKeys: map[state.ObjID]string{}, blockKeys: map[state.ObjID]string{}, before: map[state.ObjID]uint32{}}
}

func keyOf(id state.ObjID, moves uint32) string { return fmt.Sprintf("%d:z%d", id, moves) }

// Sync folds the events appended since the last call into the shadow game,
// counting every zone change per object, then checks the shadow against the engine.
func (t *Tracker) Sync(e *rules.Engine) error {
	clear(t.before)
	for ; t.applied < len(e.L.Events); t.applied++ {
		ev := e.L.Events[t.applied]
		n := len(t.shadow.Objs)
		t.zbuf = t.zbuf[:0]
		for i := range t.shadow.Objs {
			t.zbuf = append(t.zbuf, t.shadow.Objs[i].Zone)
		}
		events.Apply(t.shadow, ev)
		for i := range t.zbuf {
			if t.shadow.Objs[i].Zone != t.zbuf[i] {
				id := t.shadow.Objs[i].ID
				if _, ok := t.before[id]; !ok {
					t.before[id] = t.moves[id]
				}
				t.moves[id]++
			}
		}
		t.record(ev, n)
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

// record notes, after event ev (which may have minted the objects from index
// n on), the keys that stack references and attack targets were taken at.
//   - An ability's source: for an activated ability, its key at the start of
//     this Sync batch, before the cost events (a cycled card is discarded
//     before its ability is pushed); for a triggered ability, its key when
//     the trigger is put on the stack.
//   - A target: its key when chosen.
//   - A battle or planeswalker attack target: its key when declared.
//   - A declared blocker: its key when declared, until combat ends or it is
//     removed from combat.
func (t *Tracker) record(ev events.Event, n int) {
	g := t.shadow
	for i := n; i < len(g.Objs); i++ {
		o := &g.Objs[i]
		if o.Ability == nil || o.Zone != state.ZStack || o.Source == 0 {
			continue
		}
		mc := t.moves[o.Source]
		if b, ok := t.before[o.Source]; ok && o.StackKind == state.StackKindActivated {
			mc = b
		}
		t.sourceKeys[o.ID] = keyOf(o.Source, mc)
	}
	for _, id := range g.Stack {
		o := g.Obj(id)
		if o == nil {
			continue
		}
		have := t.targetKeys[id]
		if len(have) > len(o.Targets) {
			have = have[:len(o.Targets)]
		}
		for j, tg := range o.Targets {
			obj := tg.Obj
			if tg.IsPlayer {
				obj = 0
			}
			if j < len(have) && have[j].obj == obj {
				continue
			}
			c := chosen{obj: obj}
			if obj != 0 {
				c.key = t.Key(obj)
			}
			if j < len(have) {
				have[j] = c
			} else {
				have = append(have, c)
			}
		}
		t.targetKeys[id] = have
	}
	if ev.Kind == events.DeclareAttackers && ev.Obj != 0 {
		for _, id := range ev.IDs {
			t.attackKeys[id] = t.Key(ev.Obj)
		}
	}
	if ev.Kind == events.DeclareBlockers {
		for _, pr := range ev.Pairs {
			if pr[1] != 0 {
				t.blockKeys[pr[1]] = t.Key(pr[1])
			}
		}
	}
	if ev.Kind == events.EndCombatReset {
		if ev.Obj == 0 {
			clear(t.attackKeys)
			clear(t.blockKeys)
		} else {
			delete(t.blockKeys, ev.Obj)
		}
	}
}

// Key is the internal key of Section 5.3: stable for one stay in one zone.
func (t *Tracker) Key(id state.ObjID) string { return keyOf(id, t.moves[id]) }

// SourceKey is the key the source of stack ability id had when the ability
// was put on the stack. ok is false for an ability the tracker never saw
// pushed (one already on the stack when the tracker was created).
func (t *Tracker) SourceKey(id state.ObjID) (key string, ok bool) {
	key, ok = t.sourceKeys[id]
	return key, ok
}

// TargetKey is the key target i of stack object id had when it was chosen.
func (t *Tracker) TargetKey(id state.ObjID, i int) (key string, ok bool) {
	ks := t.targetKeys[id]
	if i >= len(ks) || ks[i].obj == 0 {
		return "", false
	}
	return ks[i].key, true
}

// AttackKey is the key of the battle or planeswalker attacker was declared
// against, while that combat lasts.
func (t *Tracker) AttackKey(attacker state.ObjID) (key string, ok bool) {
	key, ok = t.attackKeys[attacker]
	return key, ok
}

// Blocking reports whether id was declared as a blocker this combat and has
// neither changed zones nor been removed from combat since: CR 509.1h keeps it
// a blocking creature after its attacker leaves.
func (t *Tracker) Blocking(id state.ObjID) bool {
	key, ok := t.blockKeys[id]
	return ok && key == t.Key(id)
}

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
// own hand. It mirrors observe.Visible (Task 11), the rule that decides which
// objects get a VisibleID; observe imports this package, so the rule cannot
// be shared, and a change to either must be made to both.
func sees(viewer state.PlayerID, o *state.Object) bool {
	switch o.Zone {
	case state.ZBattlefield, state.ZGraveyard, state.ZExile, state.ZStack, state.ZCommand:
		return true
	case state.ZHand:
		return o.Owner == viewer
	}
	return false
}
