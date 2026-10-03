// Package server implements the Spellbench v2 environment role for gorge.
package server

import (
	"crypto/sha256"
	"errors"
	"io"
	"slices"

	"github.com/adams-shaun/gorge/cards"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/catalog"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/observe"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/secrets"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/session"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/wire"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/xview"
)

// cached is one answered request: the SHA-256 of its line and the response.
type cached struct {
	sum  [32]byte
	resp []byte
}

type Server struct {
	reg     *cards.Registry
	engine  protocol.Engine
	game    *session.Game
	gameIDs map[string]bool
	// cache holds every response since the last accepted reset, by request
	// id (Section 4.1): an identical retransmission of any of them returns
	// its bytes, a changed payload is request_id_reuse_mismatch. Clearing it
	// at each accepted reset bounds it by one game's traffic.
	cache map[string]cached
	audit bool
}

func New(reg *cards.Registry, sourceRevision *string) *Server {
	return &Server{reg: reg, engine: engineIdentity(sourceRevision), gameIDs: map[string]bool{}, cache: map[string]cached{}}
}

func marshal(v any) []byte {
	b, _ := wire.Canonical(v) // any valid layout is allowed; canonical keeps goldens stable
	return b
}

func errResp(id string, e *protocol.Error) []byte {
	return marshal(protocol.ErrorResponse{ResponseType: "error", Protocol: protocol.Name, RequestID: id,
		Error: protocol.ErrorBody{Code: e.Code, Message: e.Message}})
}

func (s *Server) Handle(line []byte) []byte {
	req, perr := protocol.Decode(line)
	if perr != nil {
		return errResp(req.ID, perr)
	}
	sum := sha256.Sum256(line)
	if c, ok := s.cache[req.ID]; ok {
		if c.sum == sum {
			return c.resp
		}
		return errResp(req.ID, protocol.Errf(protocol.CodeRequestIDReuseMismatch, "request_id reused with a different payload"))
	}
	prev := s.game
	out := s.dispatch(req)
	if s.game != prev { // an accepted reset starts a new game
		clear(s.cache)
	}
	s.cache[req.ID] = cached{sum: sum, resp: out}
	return out
}

func (s *Server) dispatch(req protocol.Request) []byte {
	switch req.Type {
	case "hello":
		return marshal(helloOK(req.ID, s.engine, observe.Flags))
	case "reset":
		return s.reset(req)
	case "step":
		return s.stepReq(req)
	case "validate_deck":
		v := req.ValidateDeck
		if v.Format != "pauper-bo1" {
			return errResp(req.ID, protocol.Errf(protocol.CodeUnsupportedFormat, v.Format))
		}
		if _, ok := catalog.ByID(v.Deck.CatalogID); v.Deck.IsDecklist || !ok {
			return errResp(req.ID, protocol.Errf(protocol.CodeUnsupportedDeck, "only the engine catalog decks are playable"))
		}
		return marshal(protocol.DeckOK{ResponseType: "deck_ok", Protocol: protocol.Name, RequestID: req.ID})
	default: // probe_resample: this engine has no probe (Section 9.7)
		return errResp(req.ID, protocol.Errf(protocol.CodeUnsupportedRequest, req.Type+" is not implemented"))
	}
}

func (s *Server) respond(id string, g *session.Game) []byte {
	dec, term := g.Pending()
	if term != nil {
		t := *term
		t.RequestID = id
		return marshal(t)
	}
	d := *dec
	d.RequestID = id
	return marshal(d)
}

func (s *Server) reset(req protocol.Request) []byte {
	r := req.Reset
	switch {
	case s.game != nil && !terminal(s.game):
		return errResp(req.ID, protocol.Errf(protocol.CodeGameAlreadyActive, "a game is active"))
	case s.gameIDs[r.GameID]:
		return errResp(req.ID, protocol.Errf(protocol.CodeMalformedRequest, "game_id reused"))
	case r.Format != "pauper-bo1":
		return errResp(req.ID, protocol.Errf(protocol.CodeUnsupportedFormat, r.Format))
	}
	var decks [2][]*cards.Card
	for i, spec := range r.Decks {
		d, ok := catalog.ByID(spec.CatalogID)
		if spec.IsDecklist || !ok {
			return errResp(req.ID, protocol.Errf(protocol.CodeUnsupportedDeck, "only the engine catalog decks are playable"))
		}
		if spec.DeckID != d.DeckID() {
			return errResp(req.ID, protocol.Errf(protocol.CodeDeckIDMismatch, "deck_id does not match "+d.CatalogID))
		}
		cs, err := catalog.Resolve(s.reg, d)
		if err != nil {
			return errResp(req.ID, protocol.Errf(protocol.CodeUnsupportedDeck, err.Error()))
		}
		decks[i] = cs
	}
	switch {
	case r.Rules.StartingPlayer != "host_assigned":
		return errResp(req.ID, protocol.Errf(protocol.CodeUnsupportedRule, "starting_player"))
	case r.Rules.Probe:
		return errResp(req.ID, protocol.Errf(protocol.CodeUnsupportedRule, "probe"))
	}
	// A repeated name never arrives: the decoder refuses it as
	// malformed_request, the same code a wrong domain_id hash gets here.
	if dom := wire.DomainID(r.Rules.Names); dom != r.Rules.DomainID {
		return errResp(req.ID, protocol.Errf(protocol.CodeMalformedRequest, "card_name_domain.domain_id does not hash its distinct names"))
	}
	for _, x := range r.Rules.Extensions {
		if x != "x_gorge_view_v1" {
			return errResp(req.ID, protocol.Errf(protocol.CodeUnsupportedRule, "extension "+x))
		}
	}
	sec, err := secrets.ParseGame(r.GameSecret)
	if err != nil {
		return errResp(req.ID, protocol.Errf(protocol.CodeMalformedRequest, err.Error()))
	}
	cfg := session.Config{Reg: s.reg, Provenance: provenance(s.engine), Audit: s.audit}
	if slices.Contains(r.Rules.Extensions, "x_gorge_view_v1") {
		cfg.Ext = xview.New()
	}
	// Section 9.2: a game the engine cannot start (for example gamecfg's
	// CheckRandomness failure, returned by session.Start as a plain error) is
	// unsupported_deck, and the failure consumes neither the game id nor a slot.
	g, err := startSession(cfg, r.GameID, r, sec, decks)
	if err != nil {
		return errResp(req.ID, protocol.Errf(protocol.CodeUnsupportedDeck, "engine could not start: "+err.Error()))
	}
	s.game = g
	s.gameIDs[r.GameID] = true
	return s.respond(req.ID, g)
}

// startSession is session.Start, named so tests can pin the reset failure
// mapping of Section 9.2.
var startSession = session.Start

func terminal(g *session.Game) bool { _, t := g.Pending(); return t != nil }

func (s *Server) stepReq(req protocol.Request) []byte {
	switch {
	case s.game == nil:
		return errResp(req.ID, protocol.Errf(protocol.CodeStepBeforeReset, "no game"))
	case req.Step.GameID != s.game.ID:
		return errResp(req.ID, protocol.Errf(protocol.CodeGameIDMismatch, "another game is active"))
	}
	if perr := s.game.Step(req.Step); perr != nil {
		return errResp(req.ID, perr)
	}
	return s.respond(req.ID, s.game)
}

// Serve runs the stdio loop until stdin closes.
func Serve(r io.Reader, w io.Writer, s *Server) error {
	in := wire.NewReader(r)
	for {
		line, err := in.ReadLine()
		switch {
		case errors.Is(err, io.EOF):
			return nil
		case errors.Is(err, wire.ErrLineTooLong):
			if _, err := w.Write(append(errResp("", protocol.Errf(protocol.CodeMalformedJSON, "line exceeds 8 MiB")), '\n')); err != nil {
				return err
			}
			continue
		case err != nil:
			return err
		}
		if _, err := w.Write(append(s.Handle(line), '\n')); err != nil {
			return err
		}
	}
}
