package agent_test

import (
	"bytes"
	"encoding/json"
	"fmt"
	"slices"
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

func gameStart(a *agent.Server, seed uint64) {
	a.Handle([]byte(fmt.Sprintf(`{"request_type":"game_start","protocol":"spellbench/v2","request_id":"r-0","game_id":"g","seat":"p0","agent_seed":%d}`, seed)))
}

// mulliganChoose poses a keep/mulligan native decision, the one policy path
// that consumes the bot's own PCG (mulligan with probability 1/3).
func mulliganChoose(native uint64) []byte {
	return []byte(fmt.Sprintf(`{"request_type":"choose","protocol":"spellbench/v2","request_id":"c-%d","game_id":"g","decision":{"candidates":[{"candidate_id":0,"semantic":{"kind":"keep"}},{"candidate_id":1,"semantic":{"kind":"mulligan"}}],"extensions":{"x_gorge_view_v1":{"version":1,"native_index":%d,"view":{},"decision":{"player":0,"kind":"mulligan","min":1,"max":1,"options":[{"index":0,"kind":"keep","label":"Keep"},{"index":1,"kind":"mulligan","label":"Mulligan"}]},"policy_facts":{},"ops":[{"op":"choose","option":0},{"op":"choose","option":1}]}}}}`, native, native))
}

func TestAgentHelloRequiresTheViewExtension(t *testing.T) {
	a, _ := agent.New("bot")
	var hello map[string]any
	json.Unmarshal(a.Handle([]byte(`{"request_type":"hello","protocol":"spellbench/v2","request_id":"r-0","protocol_minor":0}`)), &hello)
	exts, _ := hello["requires"].(map[string]any)["extensions"].([]any)
	if len(exts) != 1 || exts[0] != "x_gorge_view_v1" {
		t.Fatalf("requires.extensions %v, want [x_gorge_view_v1]", hello["requires"])
	}
}

// The bot is gorge's own PCG seeded from agent_seed: two seeds must give
// observably different bots, visible in the recorded intents.
func TestAgentSeedsBotsFromAgentSeed(t *testing.T) {
	answers := func(seed uint64) [][]int {
		a, _ := agent.New("bot")
		gameStart(a, seed)
		var out [][]int
		for n := uint64(0); n < 12; n++ {
			a.Handle(mulliganChoose(n))
			out = append(out, a.Records()[n].Intent.Choices)
		}
		return out
	}
	if slices.EqualFunc(answers(1), answers(2), slices.Equal) {
		t.Fatal("agent_seeds 1 and 2 produced identical bots")
	}
}

func TestAgentResetsRecordsAtGameStart(t *testing.T) {
	a, _ := agent.New("bot")
	gameStart(a, 1)
	a.Handle(mulliganChoose(0))
	if len(a.Records()) != 1 {
		t.Fatalf("%d records after one choose, want 1", len(a.Records()))
	}
	gameStart(a, 2)
	if len(a.Records()) != 0 {
		t.Fatalf("%d records carried into the next game", len(a.Records()))
	}
}

// With no x_gorge_view_v1 the agent fails closed on the first candidate's
// actual id, which need not be 0.
func TestAgentMissingExtensionAnswersTheFirstCandidateID(t *testing.T) {
	a, _ := agent.New("bot")
	gameStart(a, 1)
	var m map[string]any
	json.Unmarshal(a.Handle([]byte(`{"request_type":"choose","protocol":"spellbench/v2","request_id":"c-0","game_id":"g","decision":{"candidates":[{"candidate_id":5,"semantic":{"kind":"pass"}},{"candidate_id":7,"semantic":{"kind":"pass"}}]}}`)), &m)
	if got := m["selection"].(map[string]any)["candidate_id"]; got != float64(5) {
		t.Fatalf("missing extension selected %v, want the first candidate's id 5", got)
	}
}
