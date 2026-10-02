package server_test

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"slices"
	"strings"
	"testing"

	"github.com/jackmaiorino/spellbench/engines/gorge/internal/catalog"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/server"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/testcorpus"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/wire"
)

func resp(t *testing.T, b []byte) map[string]any {
	var m map[string]any
	if err := json.Unmarshal(b, &m); err != nil {
		t.Fatalf("%s: %v", b, err)
	}
	return m
}

func code(t *testing.T, b []byte) string {
	m := resp(t, b)
	if m["response_type"] != "error" {
		return ""
	}
	return m["error"].(map[string]any)["code"].(string)
}

func reset(id, gameID, deck, mutate string) []byte {
	d, _ := catalog.ByID(deck)
	names, _ := json.Marshal(catalog.PoolNames())
	dom := wire.DomainID(catalog.PoolNames())
	line := fmt.Sprintf(`{"request_type":"reset","protocol":"spellbench/v2","request_id":%q,"game_id":%q,"format":"pauper-bo1","seats":[{"seat":"p0","deck":{"deck_id":%q,"catalog_id":%q}},{"seat":"p1","deck":{"deck_id":%q,"catalog_id":%q}}],"rules":{"opponent_decklist":"visible","mulligan":"london","starting_player":"host_assigned","starting_seat":"p0","card_name_domain":{"domain_id":%q,"names":%s},"extensions":["x_gorge_view_v1"],"probe":false},"game_secret":"%s","max_decisions":10000,"max_steps":100000}`,
		id, gameID, d.DeckID(), deck, d.DeckID(), deck, dom, names, strings.Repeat("ab", 32))
	if mutate != "" {
		parts := strings.SplitN(mutate, "=>", 2)
		line = strings.Replace(line, parts[0], parts[1], 1)
	}
	return []byte(line)
}

func TestHelloDeclaresTheProfile(t *testing.T) {
	s := server.New(testcorpus.Registry(t), nil)
	m := resp(t, s.Handle([]byte(`{"request_type":"hello","protocol":"spellbench/v2","request_id":"h-1","protocol_minor":3}`)))
	if m["protocol_minor"].(float64) != 0 || len(m["decision_kinds"].([]any)) != 24 || len(m["catalog"].([]any)) != 5 ||
		len(m["observation"].(map[string]any)) != 13 || m["rewind"] != false ||
		m["engine_defaults"].(map[string]any)["combat_damage_assignment"] != "engine_order" {
		t.Fatalf("hello_ok %v", m)
	}
	if slices.Contains(server.DecisionKinds, "distribute") {
		t.Fatal("distribute declared, but combat damage follows engine_order")
	}
}

func TestResetErrors(t *testing.T) {
	cases := map[string]string{
		`"format":"pauper-bo1"=>"format":"modern-bo1"`:                                                                         "unsupported_format",
		`"catalog_id":"Burn"}}]=>"catalog_id":"Terror"}}]`:                                                                     "unsupported_deck",
		`"starting_player":"host_assigned","starting_seat":"p0"=>"starting_player":"toss_winner_chooses","starting_seat":null`: "unsupported_rule",
		`"extensions":["x_gorge_view_v1"]=>"extensions":["x_other"]`:                                                           "unsupported_rule",
		`"probe":false=>"probe":true`:                                                                                          "unsupported_rule",
	}
	for mutate, want := range cases {
		s := server.New(testcorpus.Registry(t), nil)
		if got := code(t, s.Handle(reset("r-1", "g-1", "Burn", mutate))); got != want {
			t.Errorf("%s: got %q, want %q", mutate, got, want)
		}
	}
	// deck_id_mismatch: the wrong id must keep Section 4.3's form, since the
	// decoder refuses a malformed deck_id before the server runs.
	d, _ := catalog.ByID("Burn")
	zero := "sha256:" + strings.Repeat("0", 64)
	s := server.New(testcorpus.Registry(t), nil)
	if got := code(t, s.Handle(reset("r-1", "g-1", "Burn", `"deck_id":"`+d.DeckID()+`"=>"deck_id":"`+zero+`"`))); got != "deck_id_mismatch" {
		t.Errorf("deck_id tampered: got %q, want %q", got, "deck_id_mismatch")
	}
	s = server.New(testcorpus.Registry(t), nil)
	if got := code(t, s.Handle(reset("r-1", "g-1", "Burn", ""))); got != "" {
		t.Fatalf("valid reset: %s", got)
	}
	if got := code(t, s.Handle(reset("r-2", "g-2", "Burn", ""))); got != "game_already_active" {
		t.Fatalf("second reset: %s", got)
	}
}

func TestStepErrorOrder(t *testing.T) {
	s := server.New(testcorpus.Registry(t), nil)
	step := func(id, game string, exp, cand int, echo string) string {
		return code(t, s.Handle([]byte(fmt.Sprintf(`{"request_type":"step","protocol":"spellbench/v2","request_id":%q,"game_id":%q,"expected_step":%d,"selection":{"candidate_id":%d,"semantic_echo":%s}}`, id, game, exp, cand, echo))))
	}
	if got := step("s-0", "g-1", 0, 0, `{"kind":"pass"}`); got != "step_before_reset" {
		t.Fatalf("got %s", got)
	}
	first := resp(t, s.Handle(reset("r-1", "g-1", "Burn", "")))
	cands := first["seat_decision"].(map[string]any)["candidates"].([]any)
	sem, _ := json.Marshal(cands[0].(map[string]any)["semantic"])
	if got := step("s-1", "g-9", 0, 0, string(sem)); got != "game_id_mismatch" {
		t.Fatalf("got %s", got)
	}
	if got := step("s-2", "g-1", 5, 0, string(sem)); got != "expected_step_mismatch" {
		t.Fatalf("got %s", got)
	}
	if got := step("s-3", "g-1", 0, 4095, string(sem)); got != "candidate_id_out_of_range" {
		t.Fatalf("got %s", got)
	}
	if got := step("s-4", "g-1", 0, 0, `{"kind":"nonsense"}`); got != "semantic_echo_mismatch" {
		t.Fatalf("got %s", got)
	}
}

func TestRetransmissionIsIdempotentAndReuseFails(t *testing.T) {
	s := server.New(testcorpus.Registry(t), nil)
	line := reset("r-1", "g-1", "Burn", "")
	a := s.Handle(line)
	b := s.Handle(line)
	if string(a) != string(b) {
		t.Fatal("retransmitted reset returned different bytes")
	}
	if got := code(t, s.Handle(reset("r-1", "g-1", "Spy", ""))); got != "request_id_reuse_mismatch" {
		t.Fatalf("reuse with different bytes: %s", got)
	}
	hello := `{"request_type":"hello","protocol":"spellbench/v2","request_id":"h-9","protocol_minor":0}`
	h := s.Handle([]byte(hello))
	// Section 4.1: an identical retransmission of an older request of this
	// game returns its cached response, without side effects.
	if got := s.Handle(line); string(got) != string(a) {
		t.Fatalf("older identical retransmission: %s", got)
	}
	if got := s.Handle([]byte(hello)); string(got) != string(h) {
		t.Fatal("retransmitted hello returned different bytes")
	}
	if got := code(t, s.Handle([]byte(strings.Replace(hello, `"protocol_minor":0`, `"protocol_minor":1`, 1)))); got != "request_id_reuse_mismatch" {
		t.Fatalf("older id with different bytes: %s", got)
	}
}

func TestAcceptedResetClearsTheCache(t *testing.T) {
	s := server.New(testcorpus.Registry(t), nil)
	line := reset("r-1", "g-1", "Burn", `"max_decisions":10000=>"max_decisions":0`)
	term := s.Handle(line)
	if resp(t, term)["response_type"] != "terminal" {
		t.Fatalf("max_decisions 0: %s", term)
	}
	if got := code(t, s.Handle(reset("r-9", "g-1", "Burn", ""))); got != "malformed_request" {
		t.Fatalf("game_id reused across games: %s", got)
	}
	second := s.Handle(reset("r-2", "g-2", "Burn", ""))
	if resp(t, second)["response_type"] != "decision" {
		t.Fatalf("reset after a terminal game: %s", second)
	}
	// The accepted reset cleared the cache (G2-21): r-1's line is dispatched
	// again and meets the active game, not the cached terminal response.
	if got := code(t, s.Handle(line)); got != "game_already_active" {
		t.Fatalf("an id from the cleared game was still cached: %s", got)
	}
}

func TestValidateDeckAndProbe(t *testing.T) {
	s := server.New(testcorpus.Registry(t), nil)
	vd := func(id, format, deck string) []byte {
		return s.Handle([]byte(fmt.Sprintf(`{"request_type":"validate_deck","protocol":"spellbench/v2","request_id":%q,"format":%q,"deck":%s}`, id, format, deck)))
	}
	if got := code(t, vd("v-1", "modern-bo1", `{"catalog_id":"Burn"}`)); got != "unsupported_format" {
		t.Fatalf("format: %s", got)
	}
	if got := code(t, vd("v-2", "pauper-bo1", `{"catalog_id":"Terror"}`)); got != "unsupported_deck" {
		t.Fatalf("unknown catalog: %s", got)
	}
	if got := code(t, vd("v-3", "pauper-bo1", `{"decklist":[{"name":"Mountain","count":60}]}`)); got != "unsupported_deck" {
		t.Fatalf("decklist: %s", got)
	}
	if m := resp(t, vd("v-4", "pauper-bo1", `{"catalog_id":"Burn"}`)); m["response_type"] != "deck_ok" {
		t.Fatalf("valid deck: %v", m)
	}
	probe := `{"request_type":"probe_resample","protocol":"spellbench/v2","request_id":"p-1","game_id":"g-1","samples":3}`
	if got := code(t, s.Handle([]byte(probe))); got != "unsupported_request" {
		t.Fatalf("probe_resample from an engine without the probe: %s", got)
	}
}

func TestServeFraming(t *testing.T) {
	hello := `{"request_type":"hello","protocol":"spellbench/v2","request_id":"h-1","protocol_minor":0}`
	long := `{"p":"` + strings.Repeat("x", wire.MaxLineBytes) + `"}`
	in := strings.NewReader(hello + "\n" + long + "\n" + hello + "\n")
	var out bytes.Buffer
	if err := server.Serve(in, &out, server.New(testcorpus.Registry(t), nil)); err != nil {
		t.Fatal(err)
	}
	lines := strings.Split(strings.TrimRight(out.String(), "\n"), "\n")
	if len(lines) != 3 {
		t.Fatalf("%d responses", len(lines))
	}
	if resp(t, []byte(lines[0]))["response_type"] != "hello_ok" {
		t.Fatalf("first: %s", lines[0])
	}
	if got := code(t, []byte(lines[1])); got != "malformed_json" {
		t.Fatalf("long line: %s", got)
	}
	if resp(t, []byte(lines[2]))["response_type"] != "hello_ok" {
		t.Fatalf("resync: %s", lines[2])
	}
}

// failAfter fails every Write after the first n.
type failAfter struct {
	n, calls int
	err      error
	buf      bytes.Buffer
}

func (f *failAfter) Write(p []byte) (int, error) {
	f.calls++
	if f.calls > f.n {
		return 0, f.err
	}
	return f.buf.Write(p)
}

func TestServeSurfacesTheLongLineWriteError(t *testing.T) {
	hello := `{"request_type":"hello","protocol":"spellbench/v2","request_id":"h-1","protocol_minor":0}`
	long := `{"p":"` + strings.Repeat("x", wire.MaxLineBytes) + `"}`
	boom := errors.New("sink closed")
	// The hello_ok write succeeds; the over-long line's malformed_json frame fails.
	w := &failAfter{n: 1, err: boom}
	err := server.Serve(strings.NewReader(hello+"\n"+long+"\n"+hello+"\n"), w, server.New(testcorpus.Registry(t), nil))
	if !errors.Is(err, boom) {
		t.Fatalf("Serve returned %v, want the writer's error", err)
	}
	if w.calls != 2 {
		t.Fatalf("the error surfaced after %d writes, want 2", w.calls)
	}
}

func TestParseFailuresAreNeverCached(t *testing.T) {
	s := server.New(testcorpus.Registry(t), nil)
	bad := []byte(`{"request_type":"hello","protocol":"spellbench/v2","request_id":"h-1","protocol_minor":0,"protocol_minor":0}`)
	if got := code(t, s.Handle(bad)); got != "malformed_json" {
		t.Fatalf("duplicate key: %s", got)
	}
	// A second, different parse failure gets its own parse error, never a
	// request_id_reuse_mismatch against the first (G2-21: never cached).
	bad2 := []byte(`{"request_type":"hello","protocol":"spellbench/v2","request_id":"h-2","protocol_minor":1,"protocol_minor":1}`)
	if got := code(t, s.Handle(bad2)); got != "malformed_json" {
		t.Fatalf("second parse failure: %s", got)
	}
	good := []byte(`{"request_type":"hello","protocol":"spellbench/v2","request_id":"h-1","protocol_minor":0}`)
	if got := code(t, s.Handle(good)); got != "" {
		t.Fatalf("the parse failure consumed the id: %s", got)
	}
	h := s.Handle(good)
	if got := s.Handle(good); string(got) != string(h) {
		t.Fatal("retransmission after a parse failure differs")
	}
}
