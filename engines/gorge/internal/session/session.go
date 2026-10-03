// Package session runs one v2 game over a gorge engine.
package session

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"reflect"
	"strconv"

	"github.com/adams-shaun/gorge/cards"
	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/rules"
	"github.com/adams-shaun/gorge/state"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/gamecfg"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/identity"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/mapping"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/observe"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/secrets"
)

type Extender interface {
	Extend(env *mapping.Env, p *mapping.Pose, nativeIndex uint64) (map[string]json.RawMessage, error)
}

type Config struct {
	AutoPay    bool
	Reg        *cards.Registry
	Provenance protocol.Provenance
	Ext        Extender
	Audit      bool // qualification only: leak scan and realized intents
}

type Game struct {
	ID                     string
	cfg                    Config
	g                      *gamecfg.Game
	env                    *mapping.Env
	tx                     mapping.Transaction
	native                 *decision.Decision
	pose                   *mapping.Pose
	resp                   *protocol.DecisionResponse
	term                   *protocol.TerminalResponse
	step, decisions        uint64
	seatStep, groupID      [2]uint64
	nativeCount            [2]uint64
	maxSteps, maxDecisions uint64
	leaks, inconsistent    int
	realized               []Realized
	fresh                  bool // the pending pose is its transaction's first
}

func Start(cfg Config, gameID string, req *protocol.ResetReq, sec *secrets.Game, decks [2][]*cards.Card) (*Game, error) {
	start := state.PlayerID(0)
	if req.Rules.StartingSeat != nil && *req.Rules.StartingSeat == "p1" {
		start = 1
	}
	g, err := gamecfg.New(cfg.Reg, sec, decks, gamecfg.Rules{Mulligan: req.Rules.Mulligan, StartingSeat: start})
	if err != nil {
		return nil, err
	}
	tr := identity.New(g.E, sec)
	dom := map[string]bool{}
	for _, n := range req.Rules.Names {
		dom[n] = true
	}
	s := &Game{ID: gameID, cfg: cfg, g: g, maxSteps: req.MaxSteps, maxDecisions: req.MaxDecisions,
		env: &mapping.Env{AutoPay: cfg.AutoPay, G: g, IDs: tr, Obs: &observe.Projector{E: g.E, IDs: tr}, Domain: dom, Slots: map[string]uint32{}}}
	s.advance()
	return s, nil
}

func (s *Game) Pending() (*protocol.DecisionResponse, *protocol.TerminalResponse) {
	if s.term != nil {
		return nil, s.term
	}
	return s.resp, nil
}

func (s *Game) EngineHead() string { return s.g.E.L.Head() }

func (s *Game) recoverPanic() {
	if r := recover(); r != nil {
		fmt.Fprintf(os.Stderr, "gorge engine panic: %v\n", r)
		if _, ok := r.(*rules.LivelockError); ok {
			s.halt("livelock")
		} else {
			s.halt("panic")
		}
	}
}

func (s *Game) advance() {
	defer s.recoverPanic()
	for s.term == nil {
		if s.tx == nil {
			e := s.g.E
			if e.G.Over {
				s.natural()
				return
			}
			d := e.Pending()
			if d == nil {
				s.halt("no_pending_decision")
				return
			}
			if in, ok, err := mapping.Internal(s.env, d); ok || err != nil {
				if err == nil {
					err = s.submit(in, nil)
				}
				if err != nil {
					s.halt(cause(err, "submit_rejected"))
					return
				}
				continue
			}
			if d.Kind == decision.KPriority {
				s.env.Action, s.env.Slots = nil, map[string]uint32{}
			}
			tx, err := mapping.Begin(s.env, d)
			if err != nil {
				s.halt(cause(err, "unmapped_decision"))
				return
			}
			s.tx, s.native = tx, d
			s.nativeCount[d.Player]++
			s.fresh = true
		}
		p, err := s.tx.Pose()
		if err != nil {
			s.halt(cause(err, "dead_end"))
			return
		}
		if p.GroupStart {
			if s.decisions >= s.maxDecisions {
				s.truncate("max_decisions")
				return
			}
			if s.step+uint64(p.SubstepCount) > s.maxSteps {
				s.truncate("max_steps")
				return
			}
		}
		if err := s.present(p); err != nil {
			s.halt(cause(err, "projection"))
		}
		return
	}
}

func (s *Game) present(p *mapping.Pose) error {
	var holder *state.PlayerID
	if p.Context.Kind == "priority" || (s.env.Action != nil && s.env.Action.Seat == p.Seat) {
		h := p.Seat
		holder = &h
	}
	known := append([]protocol.Known(nil), p.Known...)
	observe.SortKnown(known)
	obs, err := s.env.Obs.Observation(p.Seat, observe.State{PriorityHolder: holder, Known: known})
	if err != nil {
		return err
	}
	sd := protocol.SeatDecision{ActingSeat: observe.Seat(p.Seat), SeatStep: s.seatStep[p.Seat],
		Group:   protocol.Group{GroupID: s.groupID[p.Seat], SubstepIndex: p.SubstepIndex, SubstepCount: p.SubstepCount},
		Context: p.Context, Observation: obs, Extensions: map[string]json.RawMessage{}}
	for i, c := range p.Candidates {
		sd.Candidates = append(sd.Candidates, protocol.Candidate{CandidateID: uint32(i), Semantic: c.Sem})
	}
	if s.cfg.Ext != nil {
		ext, err := s.cfg.Ext.Extend(s.env, p, s.nativeCount[p.Seat])
		if err != nil {
			return err
		}
		sd.Extensions = ext
	}
	if s.cfg.Audit {
		b, err := json.Marshal(sd)
		if err != nil {
			return err
		}
		s.leaks += LeakHits(b, s.hiddenNames(p.Seat, obs))
	}
	s.pose = p
	s.resp = &protocol.DecisionResponse{ResponseType: "decision", Protocol: protocol.Name, GameID: s.ID, Step: s.step,
		SeatDecision: sd, Provenance: s.cfg.Provenance}
	return nil
}

func EchoEqual(echo json.RawMessage, sem protocol.Semantic) bool {
	decode := func(b []byte) (any, bool) {
		d := json.NewDecoder(bytes.NewReader(b))
		d.UseNumber()
		var v any
		return v, d.Decode(&v) == nil
	}
	a, ok := decode(echo)
	raw, _ := json.Marshal(sem)
	b, _ := decode(raw)
	return ok && reflect.DeepEqual(a, b)
}

func (s *Game) Step(req *protocol.StepReq) *protocol.Error {
	switch {
	case s.term != nil:
		return protocol.Errf(protocol.CodeGameAlreadyTerminal, "the game has ended")
	case req.ExpectedStep != s.step:
		return protocol.Errf(protocol.CodeExpectedStepMismatch, fmt.Sprintf("pending step is %d", s.step))
	case req.CandidateID >= uint64(len(s.pose.Candidates)):
		return protocol.Errf(protocol.CodeCandidateIDOutOfRange, "no such candidate")
	case !EchoEqual(req.Echo, s.pose.Candidates[req.CandidateID].Sem):
		return protocol.Errf(protocol.CodeSemanticEchoMismatch, "semantic_echo differs from the candidate")
	}
	s.answer(int(req.CandidateID))
	return nil
}

func (s *Game) actionObject(op mapping.NativeOp) state.ObjID {
	if op.Payment != nil {
		for _, a := range s.native.PaymentActions {
			if a.ID == op.Payment.ActionID {
				return a.Cast.Object
			}
		}
	}
	idx := op.Option
	if op.Op == "cast" && len(op.Covers) > 0 {
		idx = op.Covers[0]
	}
	if idx >= 0 && idx < len(s.native.Options) {
		return s.native.Options[idx].Obj
	}
	return 0
}

func (s *Game) answer(i int) {
	defer s.recoverPanic()
	p := s.pose
	seat := p.Seat
	op := p.Candidates[i].Op
	s.fresh = false
	if s.cfg.Audit {
		s.checkConsistent(p, p.Candidates[i])
	}
	if p.Context.Kind == "priority" {
		if obj := s.actionObject(op); obj != 0 {
			s.env.Action = &mapping.ActionContext{Seat: seat, Obj: obj, Since: s.g.E.G.NextID}
		}
	}
	commit, done, err := s.tx.Answer(i)
	s.step++
	s.seatStep[seat]++
	if p.SubstepIndex+1 == p.SubstepCount {
		s.groupID[seat]++
		s.decisions++
	}
	if err != nil {
		s.halt(cause(err, "dead_end"))
		return
	}
	keys := followKeys(op)
	for k, in := range commit {
		var want *decision.Decision
		if k > 0 && in.Seq == 0 && k-1 < len(keys) {
			want = p.Followups[keys[k-1]]
		}
		if err := s.submit(in, want); err != nil {
			s.halt(cause(err, "submit_rejected"))
			return
		}
	}
	if done {
		if s.cfg.Audit && len(commit) > 0 {
			s.realize(seat, p, op, commit) // commit[0] always answers the transaction's own native decision
		}
		s.tx = nil
		s.env.CloseLooks()
	}
	s.advance()
}

var errFollowup = errors.New("engine_contract_failure:followup_mismatch")

// followKeys names the pose follow-ups a candidate's folded intents answer,
// in commit order: "<option>", then "<option>/<first follow-up option>"
// (Tasks 15 and 21 key them so).
func followKeys(op mapping.NativeOp) []string {
	keys := make([]string, 0, len(op.Followup))
	key := strconv.Itoa(op.Option)
	for _, f := range op.Followup {
		keys = append(keys, key)
		key += "/" + strconv.Itoa(f)
	}
	return keys
}

// sameAsk reports whether the pending decision is the one the lookahead saw:
// the same kind, player and options (kind, object, mana symbol, ability).
func sameAsk(d, want *decision.Decision) bool {
	if d.Kind != want.Kind || d.Player != want.Player || len(d.Options) != len(want.Options) {
		return false
	}
	for i, o := range d.Options {
		w := want.Options[i]
		if o.Kind != w.Kind || o.Obj != w.Obj || o.ManaSymbol != w.ManaSymbol || o.Ability != w.Ability {
			return false
		}
	}
	return true
}

// submit sends one intent. A folded follow-up (Seq 0) is filled from the
// pending decision only after that decision is shown to be the lookahead's
// (want); otherwise the game halts followup_mismatch.
func (s *Game) submit(in decision.Intent, want *decision.Decision) error {
	d := s.g.E.Pending()
	if d == nil {
		return errFollowup
	}
	if in.Seq == 0 {
		if want == nil || !sameAsk(d, want) {
			return errFollowup
		}
		in.Seq, in.Player = d.Seq, d.Player
	}
	if in.Seq != d.Seq || in.Player != d.Player {
		return errFollowup
	}
	if err := s.g.Submit(in); err != nil {
		fmt.Fprintf(os.Stderr, "gorge rejected intent %+v: %v\n", in, err)
		return err
	}
	return s.env.IDs.Sync(s.g.E)
}
