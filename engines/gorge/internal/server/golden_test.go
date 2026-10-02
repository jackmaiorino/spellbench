package server_test

import (
	"bufio"
	"bytes"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/adams-shaun/gorge/cards"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/catalog"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/minihost"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/observe"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/server"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/testcorpus"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/validate"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/wire"
)

var update = flag.Bool("update", false, "regenerate goldens")

// record is one transcript line. A request that is not JSON at all
// (malformed_json) is kept as the string raw, since message must be an object.
type record struct {
	Dir     string          `json:"dir"`
	Message json.RawMessage `json:"message,omitempty"`
	Raw     string          `json:"raw,omitempty"`
}

func TestGoldensReplayByteExact(t *testing.T) {
	dir := filepath.Join("..", "..", "testdata", "goldens")
	if *update {
		if err := writeGoldens(t, dir); err != nil {
			t.Fatal(err)
		}
	}
	files, _ := filepath.Glob(filepath.Join(dir, "*.transcript.jsonl"))
	if len(files) < 27 {
		t.Fatalf("%d golden files, want at least 27", len(files))
	}
	var digests map[string]string
	if b, err := os.ReadFile(filepath.Join(dir, "digests.json")); err != nil || json.Unmarshal(b, &digests) != nil || len(digests) != 5 {
		t.Fatalf("digests.json: %v, %d entries, want 5", err, len(digests))
	}
	for _, f := range files {
		s := server.New(testcorpus.Registry(t), nil)
		fh, err := os.Open(f)
		if err != nil {
			t.Fatal(err)
		}
		sc := bufio.NewScanner(fh)
		sc.Buffer(make([]byte, 1<<20), 9<<20)
		var last []byte
		var dig *wire.GameDigest // Section 11.8 over the engine lines, from the reset on
		for sc.Scan() {
			var r record
			if err := json.Unmarshal(sc.Bytes(), &r); err != nil {
				t.Fatalf("%s: %v", f, err)
			}
			switch {
			case r.Dir == "host_to_engine" && r.Raw != "":
				last = s.Handle([]byte(r.Raw))
			case r.Dir == "host_to_engine":
				last = s.Handle(r.Message)
			case r.Dir == "engine_to_host" && string(last) != string(r.Message):
				t.Fatalf("%s: engine response differs:\n got %s\nwant %s", filepath.Base(f), last, r.Message)
			}
			if (r.Dir == "host_to_engine" || r.Dir == "engine_to_host") && r.Raw == "" {
				msg, err := wire.WithoutRequestID(r.Message)
				switch {
				case err != nil:
					t.Fatalf("%s: %v", f, err)
				case dig == nil:
					dig, err = wire.NewGameDigest(msg)
				default:
					err = dig.Chain(msg)
				}
				if err != nil {
					t.Fatalf("%s: %v", f, err)
				}
			}
		}
		fh.Close()
		name := strings.TrimSuffix(filepath.Base(f), ".transcript.jsonl")
		if want, ok := digests[name]; ok && (dig == nil || dig.String() != want) {
			t.Fatalf("%s: replayed digest %v, digests.json has %s", name, dig, want)
		}
	}
}

func writeTranscript(path string, recs []record) error {
	var b bytes.Buffer
	enc := json.NewEncoder(&b) // one compact line per record, no HTML escaping
	enc.SetEscapeHTML(false)
	for _, r := range recs {
		if err := enc.Encode(r); err != nil {
			return err
		}
	}
	return os.WriteFile(path, b.Bytes(), 0o644)
}

// recorder wraps a link and appends both directions of every exchange.
type recorder struct {
	inner    minihost.Link
	to, from string
	recs     *[]record
}

func (r *recorder) Round(req []byte) ([]byte, error) {
	out, err := r.inner.Round(req)
	*r.recs = append(*r.recs, record{Dir: r.to, Message: req}, record{Dir: r.from, Message: out})
	return out, err
}

func playRecorded(reg *cards.Registry, i uint64, deck catalog.Deck, maxSteps uint64) ([]record, minihost.Result, error) {
	var recs []record
	kinds := map[string]bool{}
	for _, k := range server.DecisionKinds {
		kinds[k] = true
	}
	h := &minihost.Host{RunSecret: make([]byte, 32),
		Engine:   &recorder{inner: &minihost.EngineLink{S: server.New(reg, nil)}, to: "host_to_engine", from: "engine_to_host", recs: &recs},
		Profile:  validate.Profile{Kinds: kinds, Flags: observe.Flags, Extensions: map[string]bool{}},
		MaxSteps: maxSteps, MaxDecisions: maxSteps}
	agents := [2]minihost.Link{
		&recorder{inner: &minihost.Uniform{}, to: "host_to_agent", from: "agent_to_host", recs: &recs},
		&recorder{inner: &minihost.Uniform{}, to: "host_to_agent", from: "agent_to_host", recs: &recs}}
	res, err := h.Play(i, deck, "london", []string{}, agents)
	return recs, res, err
}

// firstGroup finds the first engine decision containing needle, and not
// exclude when it is set, whose group has at least minSize substeps, and
// returns the step that group started at and its size.
func firstGroup(recs []record, needle, exclude string, minSize uint64) (start, size uint64, ok bool) {
	for _, r := range recs {
		msg := string(r.Message)
		if r.Dir != "engine_to_host" || !strings.Contains(msg, needle) || (exclude != "" && strings.Contains(msg, exclude)) {
			continue
		}
		var d struct {
			Step         uint64 `json:"step"`
			SeatDecision struct {
				Group struct {
					SubstepIndex uint64 `json:"substep_index"`
					SubstepCount uint64 `json:"substep_count"`
				} `json:"group"`
			} `json:"seat_decision"`
		}
		if json.Unmarshal(r.Message, &d) == nil && d.SeatDecision.Group.SubstepCount >= minSize {
			return d.Step - d.SeatDecision.Group.SubstepIndex, d.SeatDecision.Group.SubstepCount, true
		}
	}
	return 0, 0, false
}

func writeGoldens(t *testing.T, dir string) error {
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return err
	}
	reg := testcorpus.Registry(t)
	hello := []byte(`{"request_type":"hello","protocol":"spellbench/v2","request_id":"h-1","protocol_minor":0}`)
	step := func(game string, exp, cand int, echo string) []byte {
		return []byte(fmt.Sprintf(`{"request_type":"step","protocol":"spellbench/v2","request_id":"s-1","game_id":%q,"expected_step":%d,"selection":{"candidate_id":%d,"semantic_echo":%s}}`, game, exp, cand, echo))
	}
	// Goldens are generated without x_gorge_view_v1: its payload carries gorge
	// cost strings compiled from Forge scripts, which this module never ships.
	noExt := `"extensions":["x_gorge_view_v1"]=>"extensions":[]`
	burn := reset("r-1", "g-1", "Burn", noExt)
	pass := `{"kind":"pass"}`
	scenarios := []struct {
		name  string
		lines [][]byte
	}{
		{"hello", [][]byte{hello}},
		{"malformed_json", [][]byte{[]byte(`{"request_type":`)}},
		{"malformed_request", [][]byte{[]byte(`{"request_type":"hello","protocol":"spellbench/v2","request_id":"h-1"}`)}},
		{"protocol_mismatch", [][]byte{[]byte(`{"request_type":"hello","protocol":"spellbench/v1","request_id":"h-1","protocol_minor":0}`)}},
		{"request_id_reuse_mismatch", [][]byte{hello, []byte(`{"request_type":"hello","protocol":"spellbench/v2","request_id":"h-1","protocol_minor":1}`)}},
		{"step_before_reset", [][]byte{step("g-1", 0, 0, pass)}},
		{"game_already_active", [][]byte{burn, reset("r-2", "g-2", "Burn", noExt)}},
		{"game_id_mismatch", [][]byte{burn, step("g-9", 0, 0, pass)}},
		{"expected_step_mismatch", [][]byte{burn, step("g-1", 5, 0, pass)}},
		{"candidate_id_out_of_range", [][]byte{burn, step("g-1", 0, 4095, pass)}},
		{"semantic_echo_mismatch", [][]byte{burn, step("g-1", 0, 0, `{"kind":"nonsense"}`)}},
		{"unsupported_format", [][]byte{reset("r-1", "g-1", "Burn", `"format":"pauper-bo1"=>"format":"modern-bo1"`)}},
		{"unsupported_deck", [][]byte{reset("r-1", "g-1", "Burn", `"catalog_id":"Burn"}}]=>"catalog_id":"Terror"}}]`)}},
		{"deck_id_mismatch", [][]byte{reset("r-1", "g-1", "Burn", `"deck_id":"sha256:=>"deck_id":"sha256:0`)}},
		{"unsupported_rule", [][]byte{reset("r-1", "g-1", "Burn", `"probe":false=>"probe":true`)}},
		{"unsupported_request", [][]byte{[]byte(`{"request_type":"probe_resample","protocol":"spellbench/v2","request_id":"p-1","game_id":"g-1","samples":4}`)}},
		{"game_already_terminal", [][]byte{reset("r-1", "g-1", "Burn", `"max_steps":100000=>"max_steps":0`), step("g-1", 0, 0, pass)}},
	}
	for _, d := range catalog.Decks() {
		scenarios = append(scenarios, struct {
			name  string
			lines [][]byte
		}{"reset_first_decision_" + strings.ToLower(d.CatalogID), [][]byte{reset("r-1", "g-1", d.CatalogID, noExt)}})
	}
	for _, sc := range scenarios {
		s := server.New(reg, nil)
		var recs []record
		for _, l := range sc.lines {
			in := record{Dir: "host_to_engine", Message: l}
			if !json.Valid(l) {
				in = record{Dir: "host_to_engine", Raw: string(l)}
			}
			recs = append(recs, in, record{Dir: "engine_to_host", Message: s.Handle(l)})
		}
		if err := writeTranscript(filepath.Join(dir, sc.name+".transcript.jsonl"), recs); err != nil {
			return err
		}
	}
	// Game scenarios: whole host, engine and agent exchanges of seeded Uniform games.
	digests := map[string]string{}
	burnDeck, _ := catalog.ByID("Burn")
	recs, res, err := playRecorded(reg, 0, burnDeck, 300)
	if err != nil {
		return err
	}
	if err := writeTranscript(filepath.Join(dir, "uniform_game_burn.transcript.jsonl"), recs); err != nil {
		return err
	}
	digests["uniform_game_burn"] = res.Digest
	// Group shapes: the first seeded game that reaches each, cut by max_steps
	// right after that group (a cap never splits a group).
	// Arrangements and order blocks need three substeps or more, so a scry 1
	// or a one-card bottom block never stands in for a full group; an order
	// block is one outside an arrangement, so the two goldens differ.
	targets := []struct {
		name, needle, exclude string
		minSize               uint64
	}{
		{"arrangement", `"kind":"arrange_card"`, "", 3},
		{"attack_declaration", `"kind":"declare_attack"`, "", 1},
		{"order_pick", `"kind":"order_pick"`, `"purpose":"arrangement"`, 3},
		{"mana_payment", `"purpose":"mana_payment"`, "", 1},
	}
	for _, tg := range targets {
		found := false
		for i := uint64(0); i < 20 && !found; i++ {
			for _, d := range catalog.Decks() {
				full, _, err := playRecorded(reg, i, d, 3000)
				if err != nil {
					return err
				}
				start, size, ok := firstGroup(full, tg.needle, tg.exclude, tg.minSize)
				if !ok {
					continue
				}
				cut, res, err := playRecorded(reg, i, d, start+size)
				if err != nil {
					return err
				}
				if err := writeTranscript(filepath.Join(dir, tg.name+".transcript.jsonl"), cut); err != nil {
					return err
				}
				digests[tg.name] = res.Digest
				found = true
				break
			}
		}
		if !found {
			return fmt.Errorf("no seeded Uniform game reached %s", tg.name)
		}
	}
	b, _ := json.MarshalIndent(digests, "", "  ")
	return os.WriteFile(filepath.Join(dir, "digests.json"), append(b, '\n'), 0o644)
}
