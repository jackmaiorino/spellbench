package mapping_test

import (
	"encoding/json"
	"errors"
	"testing"

	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/events"
	"github.com/adams-shaun/gorge/state"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/agent"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/gamecfg"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/mapping"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/observe"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/testcorpus"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/testgame"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/validate"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/xview"
)

// These event-built preconditions use the real native copy ask and submit
// path. They reproduce Chain Lightning retaining a ceased inherited token.
func ceasedCopyTarget(t *testing.T) (*gamecfg.Game, *mapping.Env, *decision.Decision) {
	t.Helper()
	reg := testcorpus.Registry(t)
	g := testgame.New(t, reg, "Rally", "Rally", 7, "none")
	var spell state.ObjID
	for i := range g.E.G.Objs {
		o := &g.E.G.Objs[i]
		if o.Owner == 0 && o.Face() != nil && o.Face().Name == "Chain Lightning" {
			spell = o.ID
			break
		}
	}
	if spell == 0 || reg.Tokens["r_1_1_goblin"] == nil {
		t.Fatal("missing public copy fixture definitions")
	}
	emit := func(ev events.Event) { events.Emit(g.E.G, g.E.L, ev) }
	emit(events.Event{Kind: events.TokenCreate, Player: 1, Text: "r_1_1_goblin"})
	target := g.E.G.NextID - 1
	if o := g.E.G.Obj(target); o == nil || !o.IsToken || o.Zone != state.ZBattlefield {
		t.Fatal("token mint failed")
	}
	emit(events.Event{Kind: events.PutOnStack, Obj: spell, Player: 0, From: g.E.G.Obj(spell).Zone, To: state.ZStack})
	emit(events.Event{Kind: events.TargetsChosen, Obj: spell, IDs: []state.ObjID{target}})
	emit(events.Event{Kind: events.MoveZone, Obj: target, Player: 1, From: state.ZBattlefield, To: state.ZGraveyard})
	emit(events.Event{Kind: events.MoveZone, Obj: target, Player: 1, From: state.ZGraveyard, To: state.ZCeased})
	emit(events.Event{Kind: events.StackCopy, Obj: spell, Player: 0, Amount: 1})
	if !g.E.AskCopyTargets() {
		t.Fatal("native copy target ask missing")
	}
	d := g.E.Pending()
	if d.ResumeKind != "copy_targets" || d.Min != 1 || d.Max != 1 || len(d.Options) != 3 || d.Options[0].Obj != target {
		t.Fatalf("unexpected native copy ask: %+v", d)
	}
	env := envFor(t, g)
	ref, err := env.Obs.Ref(d.Player, target)
	if err != nil || ref != nil {
		t.Fatalf("ceased target reference %+v, error %v", ref, err)
	}
	return g, env, d
}

func TestCopyCanKeepCeasedInheritedTokenOrRetargetPlayer(t *testing.T) {
	for _, retarget := range []bool{false, true} {
		t.Run(map[bool]string{false: "keep", true: "retarget"}[retarget], func(t *testing.T) {
			g, env, d := ceasedCopyTarget(t)
			tx, err := mapping.Begin(env, d)
			if err != nil {
				t.Fatal(err)
			}
			p, err := tx.Pose()
			if err != nil {
				t.Fatal(err)
			}
			if len(p.Candidates) != len(d.Options) {
				t.Fatal("copy mapping omitted a native option")
			}
			choice := -1
			sems := make([]map[string]any, len(p.Candidates))
			for i, c := range p.Candidates {
				if err := c.Sem.Check(); err != nil {
					t.Fatal(err)
				}
				data, _ := json.Marshal(c.Sem)
				json.Unmarshal(data, &sems[i])
				if c.Op.Option == 0 {
					if c.Sem.Kind != "choose_boolean" || c.Sem.Fields["purpose"] != "change_copy_targets" || c.Sem.Fields["value"] != false {
						t.Fatalf("keep-current candidate %+v", c.Sem)
					}
					if !retarget {
						choice = i
					}
				} else {
					if c.Sem.Kind != "choose_target" {
						t.Fatalf("retarget candidate %+v", c.Sem)
					}
					if retarget && d.Options[c.Op.Option].Kind == "player" && d.Options[c.Op.Option].Player == 1 {
						choice = i
					}
				}
			}
			if choice < 0 {
				t.Fatal("wanted native choice missing")
			}
			obs, err := env.Obs.Observation(d.Player, observe.State{})
			if err != nil {
				t.Fatal(err)
			}
			sd := protocol.SeatDecision{ActingSeat: observe.Seat(d.Player), Context: p.Context,
				Group: protocol.Group{SubstepCount: 1}, Observation: obs, Extensions: map[string]json.RawMessage{}}
			for i, c := range p.Candidates {
				sd.Candidates = append(sd.Candidates, protocol.Candidate{CandidateID: uint32(i), Semantic: c.Sem})
			}
			stream := validate.NewStream(validate.Profile{Kinds: map[string]bool{"choose_boolean": true, "choose_target": true}, Flags: observe.Flags})
			if err := stream.Check(sd); err != nil {
				t.Fatal(err)
			}
			ext, err := xview.New().Extend(env, p, 7)
			if err != nil {
				t.Fatal(err)
			}
			var payload xview.Payload
			if err := json.Unmarshal(ext["x_gorge_view_v1"], &payload); err != nil {
				t.Fatal(err)
			}
			planned := decision.Intent{Seq: 7, Player: d.Player, Choices: []int{payload.Ops[choice].Option}}
			picked, miss := agent.Pick(payload, sems, agent.NewPlan(7, planned), nil)
			if picked != choice || miss != "" {
				t.Fatalf("native plan changed: choice=%d got=%d miss=%s", choice, picked, miss)
			}
			commit, done, err := tx.Answer(picked)
			if err != nil || !done || len(commit) != 1 || len(commit[0].Choices) != 1 || commit[0].Choices[0] != p.Candidates[choice].Op.Option {
				t.Fatalf("native target intent changed: %+v %v %v", commit, done, err)
			}
			if err := g.Submit(commit[0]); err != nil {
				t.Fatal(err)
			}
			want := int32(20)
			if retarget {
				want = 17
			}
			if got := g.E.G.Players[1].Life; got != want {
				t.Fatalf("copy resolution life=%d, want %d", got, want)
			}
		})
	}
}

func TestCeasedCopyTargetDoesNotAcquireObjectReference(t *testing.T) {
	_, env, d := ceasedCopyTarget(t)
	if _, err := mapping.TargetOf(env, d, d.Options[0]); !errors.Is(err, mapping.ErrUnmapped) {
		t.Fatalf("ceased token acquired an object reference: %v", err)
	}
}
