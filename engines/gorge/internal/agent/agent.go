// Package agent serves gorge's bots in the Spellbench v2 agent role, reading
// only the forwarded seat decision, its declared extensions and public decks.
package agent

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"strings"

	"github.com/adams-shaun/gorge/cards"
	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/seat"
	"github.com/adams-shaun/gorge/spellbench-strategies"
	"github.com/adams-shaun/gorge/state"
	"github.com/adams-shaun/gorge/view"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/wire"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/xview"
)

// Record is how the agent played one native decision, for Task 28b's parity
// audit: the bot's plan (its intent, and its answers to the folded follow-ups
// it was asked, keyed as the payload keys them) and the substeps no op
// matched: Forced when the decision had a single candidate, Fallbacks
// otherwise, with the first reason.
type Record struct {
	NativeIntent   decision.Intent
	Translation    string
	Intent         decision.Intent
	Followups      map[string]decision.Intent
	Forced         int
	Fallbacks      int
	Reason         string
	Search         *strategies.Trace
	SearchEligible bool
}

type Server struct {
	policy            string
	identity          Policy
	bot               seat.Seat
	plan              *Plan
	fallbacks         int
	forced            int
	records           map[uint64]*Record // the current game's native decisions (parity audit)
	registry          *cards.Registry
	searchSetup       strategies.PublicGame
	searchHistory     strategies.History
	gameID, auditSeat string
	gameOverReceived  bool
	neutral           *neutralGame // set when the seat plays another engine's game (EnableNeutral)
}

func New(policy string) (*Server, error) {
	p, err := lookupPolicy(policy)
	if err != nil {
		return nil, err
	}
	return &Server{policy: p.Key, identity: p, records: map[uint64]*Record{}}, nil
}

// Fallbacks counts substeps answered by the fallback rule; Forced counts
// single-candidate substeps no op matched (the unless-cost restriction of
// controller decision 2, say). Both are per process, across games.
func (s *Server) Fallbacks() int { return s.fallbacks }

func (s *Server) Forced() int { return s.forced }

// Records exposes the current game's native decisions to Task 28b's audit.
func (s *Server) Records() map[uint64]*Record { return s.records }

func (s *Server) PolicyKey() string { return s.policy }

func (s *Server) Round(req []byte) ([]byte, error) { return s.Handle(req), nil }

type candidate struct {
	CandidateID uint32         `json:"candidate_id"`
	Semantic    map[string]any `json:"semantic"` // read generically: the agent needs only kinds and a few fields
}

type request struct {
	Rules struct {
		Mulligan string `json:"mulligan"`
	} `json:"rules"`
	RequestType   string      `json:"request_type"`
	RequestID     string      `json:"request_id"`
	GameID        string      `json:"game_id"`
	AgentSeed     uint64      `json:"agent_seed"`
	Seat          string      `json:"seat"`
	OwnDeck       *searchDeck `json:"own_deck"`
	OpponentDeck  *searchDeck `json:"opponent_deck"`
	EngineProfile struct {
		EngineDefaults map[string]*string `json:"engine_defaults"`
	} `json:"engine_profile"`
	Decision struct {
		Candidates []candidate                `json:"candidates"`
		Extensions map[string]json.RawMessage `json:"extensions"`
	} `json:"decision"`
}

func out(v map[string]any) []byte { b, _ := json.Marshal(v); return b }

func errorLine(id, code, msg string) []byte {
	return out(map[string]any{"response_type": "error", "protocol": protocol.Name, "request_id": id,
		"error": map[string]string{"code": code, "message": msg}})
}

// Handle answers one request line. A failure inside the agent answers
// internal_error (Section 10.5) instead of ending the process.
func (s *Server) Handle(line []byte) (resp []byte) {
	var q request
	dec := json.NewDecoder(bytes.NewReader(line))
	dec.UseNumber() // amounts compare as integers, never as floats
	if err := dec.Decode(&q); err != nil {
		return errorLine("", "malformed_json", err.Error())
	}
	defer func() {
		if r := recover(); r != nil {
			fmt.Fprintln(os.Stderr, "gorge agent: internal error:", r)
			resp = errorLine(q.RequestID, "internal_error", "the agent failed")
		}
	}()
	base := map[string]any{"protocol": protocol.Name, "request_id": q.RequestID}
	switch q.RequestType {
	case "hello":
		base["response_type"] = "hello_ok"
		base["bot"] = map[string]string{"name": s.identity.Name, "version": Version}
		if s.neutral != nil {
			base["bot"] = map[string]string{"name": s.identity.Name, "version": Version + "/" + NeutralVersion}
		}
		base["requires"] = map[string][]string{"observation": {}, "extensions": {"x_gorge_view_v1"}}
		base["extensions_accepted"] = []string{"x_gorge_view_v1"}
		if s.neutral != nil {
			base["requires"] = map[string][]string{"observation": {"keywords"}, "extensions": {}}
			base["extensions_accepted"] = []string{}
		} else if strings.HasPrefix(s.policy, "search") {
			extensions := []string{"x_gorge_view_v1", strategies.Extension}
			base["requires"] = map[string][]string{"observation": {}, "extensions": extensions}
			base["extensions_accepted"] = extensions
		}
	case "game_start":
		// Atomic cast witnesses are offered through x_gorge_view_v1. They do
		// not imply that the engine answers every trigger-cost mana decision.
		if s.neutral != nil {
			if err := s.startNeutral(q); err != nil {
				return errorLine(q.RequestID, "malformed_request", err.Error())
			}
		} else if strings.HasPrefix(s.policy, "search") {
			if err := s.startSearch(q); err != nil {
				return errorLine(q.RequestID, "malformed_request", err.Error())
			}
		}
		s.bot = s.identity.New(q.AgentSeed)
		s.gameID, s.auditSeat, s.gameOverReceived = q.GameID, q.Seat, false
		s.plan = nil
		s.records = map[uint64]*Record{}
		base["response_type"] = "ack"
	case "choose":
		if s.bot == nil {
			return errorLine(q.RequestID, "malformed_request", "choose before game_start")
		}
		if s.neutral != nil {
			s.neutral.line = line
		}
		base["response_type"] = "choice"
		base["selection"] = map[string]uint32{"candidate_id": s.choose(q)}
	case "game_over":
		s.gameOverReceived = true
		base["response_type"] = "ack"
	default:
		base["response_type"] = "ack"
	}
	return out(base)
}

// Serve answers request lines until the input ends. An over-long line is
// answered malformed_json and the next line is read (Section 2).
func Serve(r io.Reader, w io.Writer, s *Server) error {
	in := wire.NewReader(r)
	for {
		line, err := in.ReadLine()
		var resp []byte
		switch {
		case errors.Is(err, io.EOF):
			return nil
		case errors.Is(err, wire.ErrLineTooLong):
			resp = errorLine("", "malformed_json", "line exceeds 8 MiB")
		case err != nil:
			return err
		default:
			resp = s.Handle(line)
		}
		if _, err := w.Write(append(resp, '\n')); err != nil {
			return err
		}
	}
}

// A failed native policy becomes an agent error through Handle's recovery.
// It must never silently play the fallback policy instead.
func (s *Server) decide(v view.View, d decision.Decision) (in decision.Intent) {
	in, err := s.bot.Decide(context.Background(), v, d)
	if err != nil {
		panic(err)
	}
	return in
}

func (s *Server) choose(q request) uint32 {
	cands := q.Decision.Candidates
	if len(cands) == 0 {
		s.fallbacks++
		return 0 // no candidate exists to name: the selection is unusable either way
	}
	var p xview.Payload
	if s.neutral != nil {
		var err error
		if p, err = s.translate(q); err != nil {
			fmt.Fprintln(os.Stderr, "gorge agent: decision untranslatable:", err)
			s.fallbacks++
			return cands[0].CandidateID
		}
	} else {
		raw, ok := q.Decision.Extensions["x_gorge_view_v1"]
		if !ok {
			s.fallbacks++
			return cands[0].CandidateID
		}
		if err := json.Unmarshal(raw, &p); err != nil || len(p.Ops) != len(cands) {
			fmt.Fprintln(os.Stderr, "gorge agent: payload unusable:", err)
			s.fallbacks++
			return cands[0].CandidateID
		}
	}
	v, d := Rebuild(p)
	ask := func(nd decision.Decision) decision.Intent {
		vv := v // a follow-up is asked with the same view, showing that decision
		vv.Decision = &nd
		return s.decide(vv, nd)
	}
	if s.plan == nil || s.plan.native != p.NativeIndex {
		var trace *strategies.Trace
		var in decision.Intent
		var searchEligible bool
		if bot, ok := s.bot.(*strategies.Search); ok {
			searchEligible = bot.Eligible(&d)
			in, trace = s.decideSearch(q, v, d, bot)
		} else {
			in = ask(d)
		}
		s.plan = NewPlan(p.NativeIndex, in)
		s.records[p.NativeIndex] = &Record{NativeIntent: s.plan.intent, Intent: s.plan.intent, Followups: s.plan.follow, Search: trace, SearchEligible: searchEligible}
	}
	sems := make([]map[string]any, len(cands))
	for i, c := range cands {
		sems[i] = c.Semantic
	}
	i, miss := Pick(p, sems, s.plan, ask)
	if s.neutral != nil && s.neutral.session != nil {
		s.neutral.session.Picked(i)
	}
	if miss == "" && s.plan.intent.Payment != nil && p.Ops[i].Op == "choose" && p.Ops[i].Payment != nil {
		r := s.records[p.NativeIndex]
		r.Intent = decision.Intent{Choices: []int{p.Ops[i].Option}}
		r.Translation = "pool-only payment to existing cast"
	}
	if miss != "" {
		r := s.records[p.NativeIndex]
		if miss == "forced" {
			s.forced++
			r.Forced++
		} else {
			s.fallbacks++
			r.Fallbacks++
		}
		if r.Reason == "" {
			r.Reason = fmt.Sprintf("%s: no %v candidate of %d matches the plan", miss, sems[0]["kind"], len(sems))
		}
		fmt.Fprintln(os.Stderr, "gorge agent: native", p.NativeIndex, r.Reason)
	}
	return cands[i].CandidateID
}

// Rebuild returns the bot's inputs, restoring the server-side policy facts.
func Rebuild(p xview.Payload) (view.View, decision.Decision) {
	v, d := p.View, p.Decision
	f := p.Facts
	d.EffectOptional, d.CopyOfCopy, d.AffordableTargets = f.EffectOptional, f.CopyOfCopy, f.AffordableTargets
	d.TargetsWithSameController, d.SetPropMode, d.ResumeKind = f.TargetsWithSameController, decision.SetPropMode(f.SetPropMode), f.ResumeKind
	if f.ResumeAPI != "" {
		d.ResumeSA = &cards.SA{API: f.ResumeAPI, Params: map[string]string{"UnlessCost": f.ResumeUnlessCost}}
	}
	for i := range d.Options {
		if i < len(f.Options) {
			o := f.Options[i]
			d.Options[i].Attach, d.Options[i].Grant, d.Options[i].Controller = o.Attach, o.Grant, state.PlayerID(o.Controller)
			d.Options[i].SetProps, d.Options[i].BlockMust, d.Options[i].AttackMust = o.SetProps, o.BlockMust, o.AttackMust
		}
	}
	flags := map[state.ObjID]xview.ProducesFacts{}
	for _, pf := range f.Produces {
		flags[pf.Card] = pf
	}
	for pi := range v.Players {
		pv := &v.Players[pi]
		for _, zone := range [][]view.CardView{pv.Hand, pv.Battlefield, pv.Graveyard, pv.Exile, pv.Command, pv.Commanders} {
			for i := range zone {
				if pf, ok := flags[zone[i].ID]; ok && zone[i].Produces != nil {
					pr := *zone[i].Produces
					pr.Indeterminate, pr.Reflected = pf.Indeterminate, pf.Reflected
					zone[i].Produces = &pr
				}
			}
		}
	}
	v.Decision = &d
	return v, d
}
