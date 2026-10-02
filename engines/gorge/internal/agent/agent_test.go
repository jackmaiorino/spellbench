package agent_test

import (
	"bytes"
	"encoding/json"
	"strings"
	"testing"

	"github.com/jackmaiorino/spellbench/engines/gorge/internal/agent"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/catalog"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/minihost"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/observe"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/server"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/testcorpus"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/validate"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/wire"
)

func TestAgentDecodesCanonicalizedPayload(t *testing.T) {
	a, _ := agent.New("bot")
	var hello map[string]any
	json.Unmarshal(a.Handle([]byte(`{"request_type":"hello","protocol":"spellbench/v2","request_id":"r-0","protocol_minor":0}`)), &hello)
	if hello["bot"].(map[string]any)["name"] != "gorge-bot" {
		t.Fatalf("hello %v", hello)
	}
	kinds := map[string]bool{}
	for _, k := range server.DecisionKinds {
		kinds[k] = true
	}
	h := &minihost.Host{RunSecret: make([]byte, 32), Engine: &minihost.EngineLink{S: server.New(testcorpus.Registry(t), nil)},
		Profile:  validate.Profile{Kinds: kinds, Flags: observe.Flags, Extensions: map[string]bool{}},
		MaxSteps: 3000, MaxDecisions: 2999, KeepDecisions: true}
	burn, _ := catalog.ByID("Burn")
	b0, _ := agent.New("bot")
	b1, _ := agent.New("lethal-pressure")
	res, err := h.Play(3, burn, "london", []string{"x_gorge_view_v1"}, [2]minihost.Link{b0, b1})
	if err != nil {
		t.Fatal(err) // the host forwards canonical bytes: sorted keys, re-printed integers
	}
	if res.Terminal.Classification == "halted" {
		t.Fatalf("halted: %s", res.Terminal.Reason)
	}
	if b0.Fallbacks()+b1.Fallbacks() > res.Steps/50 {
		t.Fatalf("%d fallbacks in %d steps", b0.Fallbacks()+b1.Fallbacks(), res.Steps)
	}
	canon, _ := wire.CanonicalBytes(res.SeatDecisions[0][0])
	if !strings.Contains(string(canon), `"x_gorge_view_v1"`) {
		t.Fatal("extension missing from the forwarded decision")
	}
}

// A choose before game_start is refused, not a crash, and an over-long line
// is answered malformed_json while the agent keeps serving (G2-26).
func TestAgentAnswersErrorsAndKeepsReading(t *testing.T) {
	a, _ := agent.New("bot")
	var m map[string]any
	json.Unmarshal(a.Handle([]byte(`{"request_type":"choose","protocol":"spellbench/v2","request_id":"r-1","game_id":"g","decision":{"candidates":[]}}`)), &m)
	if m["response_type"] != "error" || m["error"].(map[string]any)["code"] != "malformed_request" {
		t.Fatalf("choose before game_start: %v", m)
	}
	in := strings.Repeat("x", wire.MaxLineBytes+1) + "\n" + `{"request_type":"hello","protocol":"spellbench/v2","request_id":"r-0","protocol_minor":0}` + "\n"
	var w bytes.Buffer
	if err := agent.Serve(strings.NewReader(in), &w, a); err != nil {
		t.Fatal(err)
	}
	lines := strings.Split(strings.TrimSpace(w.String()), "\n")
	if len(lines) != 2 || !strings.Contains(lines[0], `"malformed_json"`) || !strings.Contains(lines[1], `"hello_ok"`) {
		t.Fatalf("answers %q", lines)
	}
}
