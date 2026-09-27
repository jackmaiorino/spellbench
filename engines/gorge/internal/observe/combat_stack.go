package observe

import (
	"fmt"
	"strings"

	"github.com/adams-shaun/gorge/state"
	"github.com/adams-shaun/gorge/view"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
)

// blockMap inverts the attackers' BlockedBy lists: blocker -> attackers it
// blocks. gorge keeps zero tombstones for removed blockers; they are skipped.
func (b *builder) blockMap() map[state.ObjID][]state.ObjID {
	if b.blocking == nil {
		b.blocking = map[state.ObjID][]state.ObjID{}
		g := b.p.E.G
		for i := range g.Objs {
			a := &g.Objs[i]
			if a.Zone == state.ZBattlefield && a.IsAttacking {
				for _, blk := range a.BlockedBy {
					if blk != 0 {
						b.blocking[blk] = append(b.blocking[blk], a.ID)
					}
				}
			}
		}
	}
	return b.blocking
}

// sameRef references id, or nil once id has changed zones since key was
// taken (Sections 5.1, 6.4 and 6.5: a reference to an object that left is
// null). known is false for a reference the tracker never recorded, which
// follows the current object.
func (b *builder) sameRef(id state.ObjID, key string, known bool) (*protocol.ObjectRef, error) {
	if known && key != b.p.IDs.Key(id) {
		return nil, nil
	}
	return b.p.Ref(b.viewer, id)
}

func (b *builder) permanent(o *state.Object) (*protocol.Permanent, error) {
	pm := &protocol.Permanent{Tapped: o.Tapped, SummoningSick: o.SummonSick, Damage: u32(o.Damage),
		Counters: map[string]uint32{}, BlockedAttackers: []protocol.ObjectRef{}}
	for _, c := range o.Counters {
		// gorge's own status markers (Shield, Deathtouched) ride an ordinary
		// counter for want of a status field; they are engine internals, never
		// one of Section 6.10's counters.
		if c.N > 0 && !state.InternalCounterMarker(c.Kind) {
			pm.Counters[Counter(c.Kind)] += uint32(c.N)
		}
	}
	if o.AttachedTo != 0 {
		r, err := b.p.Ref(b.viewer, o.AttachedTo)
		if err != nil {
			return nil, err
		}
		if r != nil {
			t := protocol.ObjectTarget(*r)
			pm.AttachedTo = &t
		}
	}
	if o.IsAttacking {
		pm.Attacking = true
		if o.AttackingBattle != 0 {
			key, known := b.p.IDs.AttackKey(o.ID)
			r, err := b.sameRef(o.AttackingBattle, key, known)
			if err != nil {
				return nil, err
			}
			if r != nil {
				t := protocol.ObjectTarget(*r)
				pm.AttackTarget = &t
			}
		} else {
			t := protocol.PlayerTarget(Seat(o.Attacking))
			pm.AttackTarget = &t
		}
	}
	attackers := b.blockMap()[o.ID]
	pm.Blocking = len(attackers) > 0 || b.p.IDs.Blocking(o.ID)
	for _, a := range attackers {
		r, err := b.p.Ref(b.viewer, a)
		if err != nil {
			return nil, err
		}
		if r != nil {
			pm.BlockedAttackers = append(pm.BlockedAttackers, *r)
		}
	}
	return pm, nil
}

var stackKinds = map[state.StackObjKind]string{state.StackKindSpell: "spell",
	state.StackKindActivated: "activated_ability", state.StackKindTriggered: "triggered_ability"}

func (b *builder) stackAndPending(obs *protocol.Observation, v view.View) error {
	g := b.p.E.G
	for _, sv := range v.Stack {
		o := g.Obj(sv.ID)
		ref, err := b.p.Ref(b.viewer, sv.ID)
		if err != nil {
			return err
		}
		kind, ok := stackKinds[o.StackKind]
		if ref == nil || !ok || (o.Ability != nil) == (o.StackKind == state.StackKindSpell) {
			// Never a partial stack (Section 9.5): the game halts instead.
			return fmt.Errorf("engine_contract_failure:stack_entry %d", sv.ID)
		}
		se := protocol.StackEntry{ObjectRef: *ref, StackKind: kind, FaceDown: o.FaceDown, Copy: o.IsCopy,
			Targets: []*protocol.TargetRef{}}
		if o.Ability != nil {
			src := g.Obj(o.Source)
			key, known := b.p.IDs.SourceKey(o.ID)
			// Section 6.5: an ability's source is null once that source has
			// left. The tracker's recorded key, not gorge's SourceIncarnation,
			// decides (gorge leaves SourceIncarnation 0 on an ordinary ability
			// while its permanent sits at incarnation 1, so an incarnation
			// comparison would null live sources). A key mismatch means the
			// source changed zones since the ability was put on the stack. For
			// a triggered ability the key is taken when the trigger is put on
			// the stack, so a dies, sacrificed or cycled source already sits in
			// the graveyard at that key: that source has left too. (Sources
			// taken from a hand or library are nulled by visibility instead.)
			gone := known && o.StackKind == state.StackKindTriggered && src != nil &&
				src.Zone == state.ZGraveyard && key == b.p.IDs.Key(o.Source)
			if src != nil && !gone {
				if se.Source, err = b.sameRef(o.Source, key, known); err != nil {
					return err
				}
			}
		} else {
			se.Characteristics = b.p.Characteristics(b.viewer, o)
		}
		for i, t := range o.Targets {
			if t.IsPlayer {
				pt := protocol.PlayerTarget(Seat(t.Player))
				se.Targets = append(se.Targets, &pt)
				continue
			}
			key, known := b.p.IDs.TargetKey(o.ID, i)
			r, err := b.sameRef(t.Obj, key, known)
			if err != nil {
				return err
			}
			if r == nil {
				se.Targets = append(se.Targets, nil)
			} else {
				ot := protocol.ObjectTarget(*r)
				se.Targets = append(se.Targets, &ot)
			}
		}
		se.Modes, se.XValue = modesAndX(o)
		obs.Stack = append(obs.Stack, se)
	}
	for _, pt := range b.p.E.PendingTriggers() {
		src := g.Obj(pt.Source)
		if src != nil && !Visible(b.viewer, src) {
			continue // Section 6.6: a trigger from a hidden, unrevealed source is omitted
		}
		entry := protocol.PendingTrigger{ControllerSeat: Seat(pt.Controller), Optional: pt.Optional}
		if src != nil {
			var err error
			if entry.Source, err = b.p.Ref(b.viewer, pt.Source); err != nil {
				return err
			}
			entry.SourceName = b.p.name(b.viewer, src)
		}
		obs.PendingTriggers = append(obs.PendingTriggers, entry)
	}
	return nil
}

func modesAndX(o *state.Object) ([]uint32, *uint32) {
	f := o.Face()
	sa := o.Ability
	if sa == nil && f != nil {
		sa = f.SpellAbility()
	}
	var modes []uint32
	if sa != nil && sa.Params["Choices"] != "" {
		modes = []uint32{}
		choices := strings.Split(sa.Params["Choices"], ",")
		for _, m := range o.ChosenModes {
			for i, c := range choices {
				if strings.TrimSpace(c) == m {
					modes = append(modes, uint32(i))
				}
			}
		}
	}
	var x *uint32
	if f != nil && o.Ability == nil && strings.Contains(f.ManaCost, "X") {
		v := u32(o.X)
		x = &v
	}
	return modes, x
}
