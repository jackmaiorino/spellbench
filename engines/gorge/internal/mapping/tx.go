// Package mapping turns one gorge decision into a transaction of v2
// decisions. The real engine advances only through the intents a
// transaction returns from Answer; clones answer every "what if".
package mapping

import (
	"errors"
	"fmt"

	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/state"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/gamecfg"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/identity"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/observe"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
)

var (
	ErrDeadEnd            = errors.New("engine_contract_failure:dead_end")
	ErrUnmapped           = errors.New("engine_contract_failure:unmapped_decision")
	ErrCandidateLimit     = errors.New("engine_contract_failure:candidate_limit")
	ErrDuplicate          = errors.New("engine_contract_failure:duplicate_candidates")
	ErrUnresolvableSource = errors.New("engine_contract_failure:unresolvable_source")
)

// ActionContext is the acting seat's priority action in progress: the object
// it acts from, and Since, the engine's next object id when the action began
// (stack objects with a smaller id were on the stack before it).
type ActionContext struct {
	Seat  state.PlayerID
	Obj   state.ObjID
	Since state.ObjID
}

type Env struct {
	AutoPay bool
	G       *gamecfg.Game
	Obs     *observe.Projector
	IDs     *identity.Tracker
	Action  *ActionContext
	Domain  map[string]bool
	Slots   map[string]uint32 // target slot counter per action (key: v2 id of the source)
	Looking [2]bool
}

// OpenLook starts the look a transaction needs before it mints look ids.
// The look lasts until the transaction completes (Section 5.3: ids are
// stable within one effect's decisions); the session calls CloseLooks.
func (e *Env) OpenLook(seat state.PlayerID) {
	if !e.Looking[seat] {
		e.IDs.OpenLook(seat)
		e.Looking[seat] = true
	}
}

func (e *Env) CloseLooks() {
	for s := range e.Looking {
		if e.Looking[s] {
			e.IDs.CloseLook(state.PlayerID(s))
			e.Looking[s] = false
		}
	}
}

// NativeOp is what a candidate means natively; x_gorge_view_v1 carries it
// (ids rekeyed) so a native agent can map its answer onto candidates.
// Op: "choose" (native option, plus folded follow-ups keyed "<option>" and
// "<option>/<follow-up option>"), "finish", "none" (a declaration unit
// declines), "cast" (a cast_spell standing for several native variants,
// listed in Covers), "list" (Option at Position of the native list named by
// List: "choices", "rest" or "followup:<key>"), "dest" (an arrangement
// partition, Task 19b).
type NativeOp struct {
	Payment  *decision.PaymentSelection `json:"payment,omitempty"`
	Op       string                     `json:"op"`
	Option   int                        `json:"option"`
	Followup []int                      `json:"followup,omitempty"`
	List     string                     `json:"list,omitempty"`
	Position int                        `json:"position,omitempty"`
	Unit     state.ObjID                `json:"unit,omitempty"`
	Covers   []int                      `json:"covers,omitempty"`
}

type Cand struct {
	Sem              protocol.Semantic
	Op               NativeOp
	Hidden           bool
	SortName, SortID string
}

type Pose struct {
	Seat                       state.PlayerID
	Context                    protocol.Context
	GroupStart                 bool
	SubstepIndex, SubstepCount uint32
	Candidates                 []Cand
	Known                      []protocol.Known
	Look                       bool
	Native                     *decision.Decision
	Followups                  map[string]*decision.Decision
}

type Transaction interface {
	Pose() (*Pose, error)
	Answer(i int) (commit []decision.Intent, done bool, err error)
}

type Builder func(*Env, *decision.Decision) (Transaction, error)

var builders = map[string]Builder{}

func Register(route string, f Builder) { builders[route] = f }

func Begin(env *Env, d *decision.Decision) (Transaction, error) {
	r := Route(d)
	if f, ok := builders[r]; ok {
		return f(env, d)
	}
	return nil, fmt.Errorf("%w:%s", ErrUnmapped, r)
}

// InternalFunc answers a decision the engine makes itself, under a declared
// rule, without posing it (Section 7.6 and controller decision 3).
type InternalFunc func(*Env, *decision.Decision) (decision.Intent, error)

var internals = map[string]InternalFunc{}

// RegisterInternal makes route an engine-internal answer (Tasks 16 and 21).
func RegisterInternal(route string, f InternalFunc) { internals[route] = f }

// Internal answers d when its route is engine-internal; ok is false otherwise.
func Internal(env *Env, d *decision.Decision) (in decision.Intent, ok bool, err error) {
	f, ok := internals[Route(d)]
	if !ok {
		return decision.Intent{}, false, nil
	}
	in, err = f(env, d)
	return in, true, err
}

func Intent(d *decision.Decision, choices ...int) decision.Intent {
	return decision.Intent{Seq: d.Seq, Player: d.Player, Choices: choices}
}

func purpose(s string) *string { return &s }

// ExpandActivate turns one native "activate" option into candidates. Task 15
// replaces it with the lookahead version that folds colour and cost follow-ups.
var ExpandActivate = func(env *Env, d *decision.Decision, o decision.Option, src protocol.ObjectRef) ([]Cand, map[string]*decision.Decision, error) {
	return []Cand{{Sem: protocol.ActivateManaAbility(src, 0, nil, nil), Op: NativeOp{Op: "choose", Option: o.Index}}}, nil, nil
}
