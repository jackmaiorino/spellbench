// Package agent serves gorge's bots in the Spellbench v2 agent role, reading
// only the forwarded seat decision and its x_gorge_view_v1 extension.
package agent

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"

	"github.com/adams-shaun/gorge/cards"
	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/seat"
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
	Intent    decision.Intent
	Followups map[string]decision.Intent
	Forced    int
	Fallbacks int
	Reason    string
}

type Server struct {
	policy    string
	bot       seat.Seat
	plan      *Plan
	fallbacks int
	forced    int
	records   map[uint64]*Record // the current game's native decisions (parity audit)
}

func New(policy string) (*Server, error) {
	if policy != "bot" && policy != "lethal-pressure" {
		return nil, fmt.Errorf("unknown policy %q", policy)
	}
	return &Server{policy: policy, records: map[uint64]*Record{}}, nil
}

// Fallbacks counts substeps answered by the fallback rule; Forced counts
// single-candidate substeps no op matched (the unless-cost restriction of
// controller decision 2, say). Both are per process, across games.
func (s *Server) Fallbacks() int { return s.fallbacks }

func (s *Server) Forced() int { return s.forced }

// Records exposes the current game's native decisions to Task 28b's audit.
func (s *Server) Records() map[uint64]*Record { return s.records }

func (s *Server) Round(req []byte) ([]byte, error) { return s.Handle(req), nil }

type candidate struct {
	CandidateID uint32         `json:"candidate_id"`
	Semantic    map[string]any `json:"semantic"` // read generically: the agent needs only kinds and a few fields
}

type request struct {
	RequestType string `json:"request_type"`
	RequestID   string `json:"request_id"`
	AgentSeed   uint64 `json:"agent_seed"`
	Decision    struct {
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
		name := map[string]string{"bot": "gorge-bot", "lethal-pressure": "gorge-lethal-pressure"}[s.policy]
		base["response_type"] = "hello_ok"
		base["bot"] = map[string]string{"name": name, "version": "gorge-26257e0eda17/adapter-0.1.0"}
		base["requires"] = map[string][]string{"observation": {}, "extensions": {"x_gorge_view_v1"}}
		base["extensions_accepted"] = []string{"x_gorge_view_v1"}
	case "game_start":
		if s.policy == "lethal-pressure" {
			s.bot = seat.NewLethalPressureBot(q.AgentSeed)
		} else {
			s.bot = seat.NewBot(q.AgentSeed)
		}
		s.plan = nil
		s.records = map[uint64]*Record{}
		base["response_type"] = "ack"
	case "choose":
		if s.bot == nil {
			return errorLine(q.RequestID, "malformed_request", "choose before game_start")
		}
		base["response_type"] = "choice"
		base["selection"] = map[string]uint32{"candidate_id": s.choose(q)}
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

// decide asks the bot. A panic answers an empty intent, so no op matches and
// the substep falls back, counted.
func (s *Server) decide(v view.View, d decision.Decision) (in decision.Intent) {
	defer func() {
		if r := recover(); r != nil {
			fmt.Fprintln(os.Stderr, "gorge agent: bot panic:", r)
			in = decision.Intent{}
		}
	}()
	in, _ = s.bot.Decide(context.Background(), v, d)
	return in
}

func (s *Server) choose(q request) uint32 {
	cands := q.Decision.Candidates
	if len(cands) == 0 {
		s.fallbacks++
		return 0 // no candidate exists to name: the selection is unusable either way
	}
	raw, ok := q.Decision.Extensions["x_gorge_view_v1"]
	if !ok {
		s.fallbacks++
		return cands[0].CandidateID
	}
	var p xview.Payload
	if err := json.Unmarshal(raw, &p); err != nil || len(p.Ops) != len(cands) {
		fmt.Fprintln(os.Stderr, "gorge agent: payload unusable:", err)
		s.fallbacks++
		return cands[0].CandidateID
	}
	v, d := Rebuild(p)
	ask := func(nd decision.Decision) decision.Intent {
		vv := v // a follow-up is asked with the same view, showing that decision
		vv.Decision = &nd
		return s.decide(vv, nd)
	}
	if s.plan == nil || s.plan.native != p.NativeIndex {
		s.plan = NewPlan(p.NativeIndex, ask(d))
		s.records[p.NativeIndex] = &Record{Intent: s.plan.intent, Followups: s.plan.follow}
	}
	sems := make([]map[string]any, len(cands))
	for i, c := range cands {
		sems[i] = c.Semantic
	}
	i, miss := Pick(p, sems, s.plan, ask)
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
