package neutral_test

import (
	"encoding/json"
	"fmt"
	"slices"
	"strings"
	"testing"

	"github.com/jackmaiorino/spellbench/engines/gorge/internal/agent"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/testcorpus"
)

// These tests replay decision shapes mtg-kernel posed to the neutral agent in
// its first Spy and CawGates games (where gorge's bot fell back before), and
// require every answer to come from the bot's own plan: no fallback, no
// forced answer.

// table is a kernel game in progress for seat p0: the observation the
// agent sees, which tests change between decisions.
type table struct {
	t   *testing.T
	a   *agent.Server
	obs protocol.Observation
	req int
}

func newTable(t *testing.T, decklist ...string) *table {
	t.Helper()
	reg := testcorpus.Registry(t)
	a, err := agent.New("bot-auto-pay")
	if err != nil {
		t.Fatal(err)
	}
	a.SetRegistry(reg)
	if err := a.EnableNeutral(); err != nil {
		t.Fatal(err)
	}
	var rows []string
	for _, n := range decklist {
		rows = append(rows, fmt.Sprintf(`{"name":%q,"count":4}`, n))
	}
	deck := `{"name":"Test","decklist":[` + strings.Join(rows, ",") + `]}`
	for _, line := range []string{
		`{"request_type":"hello","protocol":"spellbench/v2","request_id":"r-0"}`,
		`{"request_type":"game_start","protocol":"spellbench/v2","request_id":"r-1","game_id":"g","seat":"p0","agent_seed":7,"own_deck":` + deck + `,"opponent_deck":` + deck + `}`,
	} {
		if out := a.Handle([]byte(line)); strings.Contains(string(out), `"error"`) {
			t.Fatalf("%s", out)
		}
	}
	tb := &table{t: t, a: a, req: 2}
	if err := json.Unmarshal([]byte(kernelObs), &tb.obs); err != nil {
		t.Fatal(err)
	}
	tb.obs.Players[0].Hand = nil
	tb.obs.Players[0].HandCount = 0
	return tb
}

func objRef(id, name, zone string) protocol.ObjectRef {
	return protocol.ObjectRef{ObjectID: id, CardName: &name, OwnerSeat: "p0", ControllerSeat: "p0", Zone: zone}
}

func (tb *table) hand(cards ...string) {
	tb.obs.Players[0].Hand = nil
	for i, n := range cards {
		types := []string{"instant"}
		if strings.HasSuffix(n, "Gate") || n == "Island" || n == "Forest" {
			types = []string{"land"}
		}
		tb.obs.Players[0].Hand = append(tb.obs.Players[0].Hand, protocol.ObjectRecord{
			ObjectRef:       objRef(fmt.Sprintf("o-h%d", i), n, "hand"),
			Characteristics: &protocol.Characteristics{Types: types, Supertypes: []string{}, Subtypes: []string{}, Colors: []string{}, Keywords: []string{}}})
	}
	tb.obs.Players[0].HandCount = uint32(len(cards))
}

func (tb *table) spell(id, name string) string {
	tb.obs.Stack = []protocol.StackEntry{{ObjectRef: objRef(id, name, "stack"), StackKind: "spell",
		Characteristics: &protocol.Characteristics{Types: []string{"sorcery"}, Supertypes: []string{}, Subtypes: []string{}, Colors: []string{}, Keywords: []string{}},
		Targets:         []*protocol.TargetRef{}}}
	b, _ := json.Marshal(objRef(id, name, "stack"))
	return string(b)
}

// look puts the named cards on top of p0's library, known as how.
func (tb *table) look(how string, names ...string) []string {
	tb.obs.Known = nil
	var refs []string
	for i, n := range names {
		id, pos := fmt.Sprintf("o-l%d", i), uint32(i)
		tb.obs.Known = append(tb.obs.Known, protocol.Known{OwnerSeat: "p0", Zone: "library", CardName: n, ObjectID: &id, PositionFromTop: &pos, How: how})
		b, _ := json.Marshal(objRef(id, n, "library"))
		refs = append(refs, string(b))
	}
	return refs
}

// ask poses one decision and returns the semantic the agent chose.
func (tb *table) ask(ctx string, group [2]int, cands []string) map[string]any {
	tb.t.Helper()
	obs, _ := json.Marshal(tb.obs)
	var cs []string
	for i, c := range cands {
		cs = append(cs, fmt.Sprintf(`{"candidate_id":%d,"semantic":%s,"display_text":null}`, i, c))
	}
	sd := fmt.Sprintf(`{"acting_seat":"p0","seat_step":%d,"group":{"group_id":%d,"substep_index":%d,"substep_count":%d},"context":%s,"observation":%s,"candidates":[%s],"extensions":{}}`,
		tb.req, tb.req, group[0], group[1], ctx, obs, strings.Join(cs, ","))
	out := tb.a.Handle([]byte(fmt.Sprintf(`{"request_type":"choose","protocol":"spellbench/v2","request_id":"r-%d","game_id":"g","decision":%s}`, tb.req, sd)))
	tb.req++
	var resp struct {
		Selection *struct {
			CandidateID int `json:"candidate_id"`
		} `json:"selection"`
	}
	if err := json.Unmarshal(out, &resp); err != nil || resp.Selection == nil {
		tb.t.Fatalf("agent answered %s", out)
	}
	var sem map[string]any
	if err := json.Unmarshal([]byte(cands[resp.Selection.CandidateID]), &sem); err != nil {
		tb.t.Fatal(err)
	}
	return sem
}

func (tb *table) clean() {
	tb.t.Helper()
	if tb.a.Fallbacks() != 0 || tb.a.Forced() != 0 {
		tb.t.Fatalf("%d fallbacks, %d forced", tb.a.Fallbacks(), tb.a.Forced())
	}
}

func choiceCtx(src string, purpose string) string {
	p := "null"
	if purpose != "" {
		p = `"` + purpose + `"`
	}
	return `{"kind":"choice","source":` + src + `,"purpose":` + p + `,"text":null,"rewind":false}`
}

func objectID(v any) string {
	m, _ := v.(map[string]any)
	if o, ok := m["object"].(map[string]any); ok {
		m = o
	}
	id, _ := m["object_id"].(string)
	return id
}

// TestKernelBrainstorm: select two hand cards (purpose other), then order
// them on top. gorge's bot puts back the first two cards in hand order.
func TestKernelBrainstorm(t *testing.T) {
	tb := newTable(t, "Brainstorm", "Island", "Counterspell", "Preordain")
	src := tb.spell("o-bs", "Brainstorm")
	tb.hand("Preordain", "Island", "Counterspell", "Island")
	remaining := slices.Clone(tb.obs.Players[0].Hand)
	var picked []string
	for sel := 0; sel < 2; sel++ {
		var cands []string
		for _, h := range remaining {
			b, _ := json.Marshal(h.ObjectRef)
			cands = append(cands, fmt.Sprintf(`{"kind":"select_object","source":%s,"purpose":"other","choice":{"object":%s},"selected_count":%d,"minimum":2,"maximum":2}`, src, b, sel))
		}
		got := objectID(tb.ask(choiceCtx(src, "other"), [2]int{sel, 2}, cands)["choice"])
		picked = append(picked, got)
		remaining = slices.DeleteFunc(remaining, func(r protocol.ObjectRecord) bool { return r.ObjectID == got })
	}
	if !slices.Equal(picked, []string{"o-h0", "o-h1"}) {
		t.Fatalf("put back %v, want the first two cards in hand", picked)
	}
	var cands []string
	for _, id := range []string{"o-h1", "o-h0"} { // the kernel offers them by name
		cands = append(cands, fmt.Sprintf(`{"kind":"order_pick","source":%s,"purpose":"library_top","item":{"object":{"object_id":%q,"card_name":null,"owner_seat":"p0","controller_seat":"p0","zone":"hand"}},"position":0,"count":2}`, src, id))
	}
	if got := objectID(tb.ask(choiceCtx(src, "library_top"), [2]int{0, 1}, cands)["item"]); got != "o-h0" {
		t.Fatalf("top card %s, want gorge's first choice o-h0", got)
	}
	tb.clean()
}

// TestKernelLeadTheStampede: the dig partition and the bottom order. gorge
// takes every creature and leaves the rest on the bottom in window order.
func TestKernelLeadTheStampede(t *testing.T) {
	tb := newTable(t, "Lead the Stampede", "Wall of Roots", "Lotus Petal", "Masked Vandal", "Forest")
	src := tb.spell("o-lts", "Lead the Stampede")
	window := []string{"Wall of Roots", "Lotus Petal", "Masked Vandal", "Forest", "Island"}
	refs := tb.look("looked_at", window...)
	creature := []bool{true, false, true, false, false}
	dest := map[string]string{}
	steps := 2*len(window) - 1
	for i := range window {
		var cands []string
		for _, d := range []string{"bottom", "hand"} {
			if d == "hand" && !creature[i] {
				continue
			}
			cands = append(cands, fmt.Sprintf(`{"kind":"arrange_card","source":%s,"purpose":"dig","card":%s,"card_index":%d,"card_count":%d,"destination":%q}`,
				src, refs[i], i, len(window), d))
		}
		dest[fmt.Sprintf("o-l%d", i)] = tb.ask(choiceCtx(src, "dig"), [2]int{i, steps}, cands)["destination"].(string)
	}
	if dest["o-l0"] != "hand" || dest["o-l2"] != "hand" {
		t.Fatalf("partition %v, want both creatures in hand", dest)
	}
	// Ordering: bottom first (by name), then hand.
	var order []string
	for _, d := range []string{"bottom", "hand"} {
		var block []int
		for i := range window {
			if dest[fmt.Sprintf("o-l%d", i)] == d {
				block = append(block, i)
			}
		}
		slices.SortFunc(block, func(x, y int) int { return strings.Compare(window[x], window[y]) })
		for len(block) > 0 && len(order) < len(window)-1 {
			var cands []string
			for _, i := range block {
				cands = append(cands, fmt.Sprintf(`{"kind":"order_pick","source":%s,"purpose":"arrangement","item":{"object":%s},"position":%d,"count":%d}`,
					src, refs[i], len(order), len(window)))
			}
			got := objectID(tb.ask(choiceCtx(src, "arrangement"), [2]int{len(window) + len(order), steps}, cands)["item"])
			order = append(order, got)
			block = slices.DeleteFunc(block, func(i int) bool { return fmt.Sprintf("o-l%d", i) == got })
		}
	}
	if !slices.Equal(order[:3], []string{"o-l1", "o-l3", "o-l4"}) {
		t.Fatalf("bottom order %v, want window order o-l1 o-l3 o-l4", order[:3])
	}
	tb.clean()
}

// TestKernelWindingWay: the type choice is gorge's first offer (creature);
// the reveal's moves are gorge's engine's, so each single or ordering pick
// is answered without a fallback.
func TestKernelWindingWay(t *testing.T) {
	tb := newTable(t, "Winding Way", "Generous Ent", "Land Grant", "Forest")
	src := tb.spell("o-ww", "Winding Way")
	var opts []string
	for i := 0; i < 2; i++ {
		opts = append(opts, fmt.Sprintf(`{"kind":"choose_option","source":%s,"purpose":"effect_option","option_index":%d,"option_count":2,"option_label":null}`, src, i))
	}
	if got := tb.ask(choiceCtx(src, "effect_option"), [2]int{0, 1}, opts)["option_index"]; got != 0.0 {
		t.Fatalf("chose option %v, want creature (0)", got)
	}
	window := []string{"Land Grant", "Generous Ent", "Forest", "Generous Ent"}
	refs := tb.look("revealed", window...)
	dests := []string{"graveyard", "hand", "graveyard", "hand"}
	for i := range window {
		c := fmt.Sprintf(`{"kind":"arrange_card","source":%s,"purpose":"dig","card":%s,"card_index":%d,"card_count":4,"destination":%q}`, src, refs[i], i, dests[i])
		tb.ask(choiceCtx(src, "dig"), [2]int{i, 7}, []string{c})
	}
	for pos, block := range [][]int{{2, 0}, {1}} {
		var cands []string
		for _, i := range block {
			cands = append(cands, fmt.Sprintf(`{"kind":"order_pick","source":%s,"purpose":"arrangement","item":{"object":%s},"position":%d,"count":4}`, src, refs[i], pos))
		}
		tb.ask(choiceCtx(src, "arrangement"), [2]int{4 + pos, 7}, cands)
	}
	tb.clean()
}

// TestKernelOnlyEligibleModes: Sagu Wildling's ask offers its second mode
// alone; gorge offers only the eligible modes, so the bot's plan is it.
func TestKernelOnlyEligibleModes(t *testing.T) {
	tb := newTable(t, "Sagu Wildling", "Forest")
	src := tb.spell("o-sw", "Sagu Wildling")
	c := fmt.Sprintf(`{"kind":"choose_spell_mode","source":%s,"mode_index":1,"mode_count":2,"selected_count":0,"minimum":1,"maximum":1}`, src)
	tb.ask(choiceCtx(src, ""), [2]int{0, 1}, []string{c})
	tb.clean()
}

// TestKernelLandGrantMethod: with no land in hand, Land Grant's cast covers
// gorge's plain and alternative-cost casts; the method follows the plan.
func TestKernelLandGrantMethod(t *testing.T) {
	tb := newTable(t, "Land Grant", "Forest")
	tb.hand("Land Grant")
	b, _ := json.Marshal(tb.obs.Players[0].Hand[0].ObjectRef)
	cast := tb.ask(priority, [2]int{0, 1}, []string{`{"kind":"pass"}`, `{"kind":"cast_spell","source":` + string(b) + `,"method":null}`})
	if cast["kind"] != "cast_spell" {
		t.Fatalf("the bot passed: %v", cast)
	}
	tb.obs.Players[0].Hand = nil
	src := tb.spell("o-h0", "Land Grant")
	var cands []string
	for _, m := range []string{"alternative", "normal"} {
		cands = append(cands, fmt.Sprintf(`{"kind":"choose_cast_method","source":%s,"method":%q}`, src, m))
	}
	tb.ask(choiceCtx(src, ""), [2]int{0, 1}, cands)
	tb.clean()
}
