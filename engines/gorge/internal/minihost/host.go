// Package minihost is an in-process Spellbench v2 host for this adapter's
// tests and qualification: canonical forwarding, the validator subset,
// secrets and the game digest. Not a replacement for the reference host.
package minihost

import (
	"encoding/hex"
	"encoding/json"
	"fmt"

	"github.com/jackmaiorino/spellbench/engines/gorge/internal/catalog"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/secrets"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/server"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/validate"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/wire"
)

type EngineLink struct{ S *server.Server }

func (e *EngineLink) Round(req []byte) ([]byte, error) { return e.S.Handle(req), nil }

type Host struct {
	RunSecret              []byte
	Engine                 Link
	Profile                validate.Profile
	MaxSteps, MaxDecisions uint64
	// KeepDecisions keeps every forwarded seat decision in the Result. They
	// run 10 to 35 KB each with the extension, so only tests that read them
	// turn it on.
	KeepDecisions bool
	n             int
}

type Result struct {
	Terminal      protocol.TerminalResponse
	Digest        string
	Steps         int
	SeatDecisions [2][][]byte // only with Host.KeepDecisions
}

func (h *Host) id() string { h.n++; return fmt.Sprintf("h-%d", h.n) }

func (h *Host) Play(i uint64, deck catalog.Deck, mulligan string, extensions []string, agents [2]Link) (Result, error) {
	var res Result
	gameID := secrets.GameID(h.RunSecret, i)
	names := catalog.PoolNames()
	domain := wire.DomainID(names)
	seat0 := "p0"
	reset := map[string]any{"request_type": "reset", "protocol": protocol.Name, "request_id": h.id(), "game_id": gameID,
		"format": "pauper-bo1",
		"seats": []any{map[string]any{"seat": "p0", "deck": map[string]any{"deck_id": deck.DeckID(), "catalog_id": deck.CatalogID}},
			map[string]any{"seat": "p1", "deck": map[string]any{"deck_id": deck.DeckID(), "catalog_id": deck.CatalogID}}},
		"rules": map[string]any{"opponent_decklist": "visible", "mulligan": mulligan, "starting_player": "host_assigned",
			"starting_seat": seat0, "card_name_domain": map[string]any{"domain_id": domain, "names": names},
			"extensions": extensions, "probe": false},
		"game_secret": hex.EncodeToString(secrets.GameSecret(h.RunSecret, i)), "max_decisions": h.MaxDecisions, "max_steps": h.MaxSteps}
	resetBytes, _ := wire.Canonical(reset)
	noID, _ := wire.WithoutRequestID(resetBytes)
	dig, err := wire.NewGameDigest(noID)
	if err != nil {
		return res, err
	}
	hello, err := h.Engine.Round([]byte(fmt.Sprintf(`{"request_type":"hello","protocol":"spellbench/v2","request_id":%q,"protocol_minor":0}`, h.id())))
	if err != nil {
		return res, err
	}
	var engineProfile protocol.HelloOK
	if err := json.Unmarshal(hello, &engineProfile); err != nil || engineProfile.ResponseType != "hello_ok" {
		return res, fmt.Errorf("invalid engine hello: %s", hello)
	}
	for s, a := range agents {
		seat := fmt.Sprintf("p%d", s)
		// A minimal game_start: only the fields this adapter's agents read.
		// P's host sends the full message; Task 30 runs the agent under it.
		start, _ := wire.Canonical(map[string]any{"request_type": "game_start", "protocol": protocol.Name, "request_id": "r-0",
			"game_id": gameID, "seat": seat, "agent_seed": secrets.AgentSeed(h.RunSecret, i, seat),
			"engine_profile": map[string]any{"engine_defaults": engineProfile.EngineDefaults}})
		ack, err := a.Round(start)
		if err != nil {
			return res, err
		}
		var response struct {
			ResponseType string `json:"response_type"`
		}
		if err := json.Unmarshal(ack, &response); err != nil || response.ResponseType != "ack" {
			return res, fmt.Errorf("agent game_start failed: %s", ack)
		}
	}
	// The game's profile enables its extensions before any stream exists;
	// the host's own profile is never mutated.
	prof := h.Profile
	prof.Extensions = map[string]bool{}
	for k, v := range h.Profile.Extensions {
		prof.Extensions[k] = v
	}
	for _, x := range extensions {
		prof.Extensions[x] = true
	}
	streams := [2]*validate.Stream{validate.NewStream(prof), validate.NewStream(prof)}
	out, _ := h.Engine.Round(resetBytes)
	agentReq := [2]int{1, 1}
	for {
		chain, _ := wire.WithoutRequestID(out)
		if err := dig.Chain(chain); err != nil {
			return res, err
		}
		var head struct {
			ResponseType string                `json:"response_type"`
			Step         uint64                `json:"step"`
			SeatDecision protocol.SeatDecision `json:"seat_decision"`
			Error        *protocol.ErrorBody   `json:"error"`
		}
		if err := json.Unmarshal(out, &head); err != nil {
			return res, err
		}
		switch head.ResponseType {
		case "terminal":
			json.Unmarshal(out, &res.Terminal)
			res.Digest = dig.String()
			return res, nil
		case "error":
			return res, fmt.Errorf("engine error %s: %s", head.Error.Code, head.Error.Message)
		}
		sd := head.SeatDecision
		seat := 0
		if sd.ActingSeat == "p1" {
			seat = 1
		}
		// V3 across the two streams: while one seat's group is partial, the
		// engine poses nothing to the other seat (Section 8).
		if streams[1-seat].InGroup() {
			return res, fmt.Errorf("validator: V3: decision for %s while the other seat's group is partial", sd.ActingSeat)
		}
		if err := streams[seat].Check(sd); err != nil {
			return res, fmt.Errorf("validator: %w", err)
		}
		// Forward the host's canonical re-serialization (Section 11.2).
		var raw struct {
			SeatDecision json.RawMessage `json:"seat_decision"`
		}
		json.Unmarshal(out, &raw)
		canon, err := wire.CanonicalBytes(raw.SeatDecision)
		if err != nil {
			return res, err
		}
		if h.KeepDecisions {
			res.SeatDecisions[seat] = append(res.SeatDecisions[seat], canon)
		}
		choose := fmt.Sprintf(`{"request_type":"choose","protocol":"spellbench/v2","request_id":"r-%d","game_id":%q,"decision":%s,"clock":{"remaining_ms":600000,"max_decision_ms":60000}}`,
			agentReq[seat], gameID, canon)
		agentReq[seat]++
		ans, err := agents[seat].Round([]byte(choose))
		if err != nil {
			return res, err
		}
		var choice struct {
			ResponseType string `json:"response_type"`
			Selection    *struct {
				CandidateID *uint32 `json:"candidate_id"`
			} `json:"selection"`
		}
		if err := json.Unmarshal(ans, &choice); err != nil || choice.ResponseType != "choice" || choice.Selection == nil || choice.Selection.CandidateID == nil || int(*choice.Selection.CandidateID) >= len(sd.Candidates) {
			return res, fmt.Errorf("invalid selection %s", ans)
		}
		selected := *choice.Selection.CandidateID
		echo, _ := json.Marshal(sd.Candidates[selected].Semantic)
		step := []byte(fmt.Sprintf(`{"request_type":"step","protocol":"spellbench/v2","request_id":%q,"game_id":%q,"expected_step":%d,"selection":{"candidate_id":%d,"semantic_echo":%s}}`,
			h.id(), gameID, head.Step, selected, echo))
		sc, _ := wire.WithoutRequestID(step)
		if err := dig.Chain(sc); err != nil {
			return res, err
		}
		res.Steps++
		out, _ = h.Engine.Round(step)
	}
}
