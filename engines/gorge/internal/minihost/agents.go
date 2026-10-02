package minihost

import (
	"encoding/json"
	"fmt"
	"math/rand/v2"
)

type Link interface {
	Round(req []byte) ([]byte, error)
}

type agentReq struct {
	RequestType string          `json:"request_type"`
	RequestID   string          `json:"request_id"`
	AgentSeed   uint64          `json:"agent_seed"`
	Decision    json.RawMessage `json:"decision"`
}

func reply(id, typ string, extra string) []byte {
	return []byte(fmt.Sprintf(`{"response_type":%q,"protocol":"spellbench/v2","request_id":%q%s}`, typ, id, extra))
}

// Uniform picks uniformly with a PCG seeded from agent_seed.
type Uniform struct{ r *rand.Rand }

func (u *Uniform) Round(req []byte) ([]byte, error) {
	var q agentReq
	if err := json.Unmarshal(req, &q); err != nil {
		return nil, err
	}
	switch q.RequestType {
	case "hello":
		return reply(q.RequestID, "hello_ok", `,"bot":{"name":"uniform-go","version":"1"}`), nil
	case "game_start":
		u.r = rand.New(rand.NewPCG(q.AgentSeed, 1))
		return reply(q.RequestID, "ack", ""), nil
	case "choose":
		var d struct{ Candidates []json.RawMessage }
		json.Unmarshal(q.Decision, &d)
		return reply(q.RequestID, "choice", fmt.Sprintf(`,"selection":{"candidate_id":%d}`, u.r.IntN(len(d.Candidates)))), nil
	}
	return reply(q.RequestID, "ack", ""), nil
}

// First always picks candidate 0.
type First struct{}

func (First) Round(req []byte) ([]byte, error) {
	var q agentReq
	if err := json.Unmarshal(req, &q); err != nil {
		return nil, err
	}
	switch q.RequestType {
	case "hello":
		return reply(q.RequestID, "hello_ok", `,"bot":{"name":"first-go","version":"1"}`), nil
	case "choose":
		return reply(q.RequestID, "choice", `,"selection":{"candidate_id":0}`), nil
	}
	return reply(q.RequestID, "ack", ""), nil
}
