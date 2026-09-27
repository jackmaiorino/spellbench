package protocol_test

import (
	"encoding/json"
	"errors"
	"math"
	"sort"
	"strings"
	"testing"

	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
)

func TestThirtyKinds(t *testing.T) {
	if len(protocol.KindFields) != 30 {
		t.Fatalf("%d kinds, spec Section 7 lists 30", len(protocol.KindFields))
	}
	if len(protocol.PriorityKinds) != 6 {
		t.Fatalf("%d priority kinds, want 6", len(protocol.PriorityKinds))
	}
}

func keys(t *testing.T, s protocol.Semantic) []string {
	b, err := json.Marshal(s)
	if err != nil {
		t.Fatal(err)
	}
	var m map[string]any
	json.Unmarshal(b, &m)
	var ks []string
	for k := range m {
		if k != "kind" {
			ks = append(ks, k)
		}
	}
	sort.Strings(ks)
	return ks
}

// everyConstructor returns one semantic from each constructor.
func everyConstructor() []protocol.Semantic {
	name := "Lightning Bolt"
	r := protocol.ObjectRef{ObjectID: "o-0a3647243d16bf78", CardName: &name, OwnerSeat: "p0", ControllerSeat: "p0", Zone: "hand"}
	tgt := protocol.PlayerTarget("p1")
	return []protocol.Semantic{
		protocol.Pass(), protocol.PlayLand(r, 0), protocol.CastSpell(r, "normal"),
		protocol.ActivateManaAbility(r, 0, nil, nil), protocol.ActivateAbility(r, 1), protocol.SpecialAction(r, "plot"),
		protocol.ChooseTarget(r, 0, tgt, 0, 1, 1), protocol.FinishTargetSelection(r, 0, 1),
		protocol.ChooseCostTarget(r, "sacrifice", r, 0, 1, 1), protocol.ChooseSpellMode(r, 0, 2, 0, 1, 1),
		protocol.ChooseColor(nil, "effect", "red"), protocol.ChooseNumber(&r, "x_value", 2, 0, 4),
		protocol.ChooseBoolean(nil, "optional_trigger", true), protocol.ChooseName(&r, "card_type", "creature"),
		protocol.SelectObject(nil, "discard", protocol.ObjectTarget(r), 0, 1, 1), protocol.FinishSelection(nil, "search", 0),
		protocol.OptionalCost(r, "kicker", true), protocol.OptionalCast(r, "madness", false), protocol.Mulligan(7, 0, true),
		protocol.OrderPick(nil, "mulligan_bottom", protocol.ObjectItem(r), 0, 1),
		protocol.ArrangeCard(&r, "scry", r, 0, 2, "top"),
		protocol.ChooseReplacement(tgt, "damage", nil, 0, 2), protocol.DeclareAttack(r, &tgt), protocol.DeclareBlock(r, nil),
		protocol.Distribute(&r, "combat_damage", protocol.ObjectTarget(r), 1, 3),
	}
}

func TestConstructorsEmitExactlyTheSpecFields(t *testing.T) {
	for _, s := range everyConstructor() {
		want := append([]string(nil), protocol.KindFields[s.Kind]...)
		sort.Strings(want)
		got := keys(t, s)
		if len(got) != len(want) {
			t.Errorf("%s fields %v, want %v", s.Kind, got, want)
			continue
		}
		for i := range got {
			if got[i] != want[i] {
				t.Errorf("%s fields %v, want %v", s.Kind, got, want)
			}
		}
		if err := s.Check(); err != nil {
			t.Errorf("%s: %v", s.Kind, err)
		}
	}
}

func TestCheckEnforcesFieldConstraints(t *testing.T) {
	name := "x"
	r := protocol.ObjectRef{ObjectID: "o-1", CardName: &name, OwnerSeat: "p0", ControllerSeat: "p0", Zone: "stack"}
	for _, s := range []protocol.Semantic{
		protocol.ChooseTarget(r, 0, protocol.PlayerTarget("p0"), 1, 1, 1),            // selected_count < maximum
		protocol.ChooseSpellMode(r, 2, 2, 0, 1, 1),                                   // mode_index < mode_count
		protocol.ChooseNumber(nil, "amount", 5, 0, 4),                                // minimum <= value <= maximum
		protocol.ChooseReplacement(protocol.PlayerTarget("p0"), "damage", nil, 0, 1), // 2 <= count
		protocol.Distribute(nil, "damage", protocol.PlayerTarget("p1"), 4, 3),        // amount <= remaining
		protocol.ChooseColor(nil, "effect", "colorless"),                             // vocabulary
	} {
		if err := s.Check(); err == nil {
			t.Errorf("%s %v accepted", s.Kind, s.Fields)
		}
	}
}

func TestTargetRefAndNullableFields(t *testing.T) {
	b, _ := json.Marshal(protocol.DeclareBlock(protocol.ObjectRef{ObjectID: "o-1", OwnerSeat: "p1", ControllerSeat: "p1", Zone: "battlefield"}, nil))
	// Map keys are sorted by encoding/json; struct fields keep declaration order.
	want := `{"attacker":null,"blocker":{"object_id":"o-1","card_name":null,"owner_seat":"p1","controller_seat":"p1","zone":"battlefield"},"kind":"declare_block"}`
	if string(b) != want {
		t.Fatalf("got %s", b)
	}
	b, _ = json.Marshal(protocol.PlayerTarget("p0"))
	if string(b) != `{"player":"p0"}` {
		t.Fatalf("player target %s", b)
	}
}

// checked runs Check and reports a panic as a test failure, so one bad case
// cannot abort the others.
func checked(t *testing.T, s protocol.Semantic) (err error) {
	t.Helper()
	defer func() {
		if p := recover(); p != nil {
			t.Errorf("%s: Check panicked: %v", s.Kind, p)
			err = errors.New("panic")
		}
	}()
	return s.Check()
}

func decoded(t *testing.T, text string) protocol.Semantic {
	t.Helper()
	var s protocol.Semantic
	if err := json.Unmarshal([]byte(text), &s); err != nil {
		t.Fatalf("%s: %v", text, err)
	}
	return s
}

// A host decodes the engine's JSON; the decoded semantic must pass Check and
// re-marshal to the same bytes.
func TestDecodedSemanticsRoundTrip(t *testing.T) {
	for _, s := range everyConstructor() {
		b, err := json.Marshal(s)
		if err != nil {
			t.Fatal(err)
		}
		var d protocol.Semantic
		if err := json.Unmarshal(b, &d); err != nil {
			t.Errorf("%s: %v", s.Kind, err)
			continue
		}
		if err := checked(t, d); err != nil {
			t.Errorf("decoded %s: %v", s.Kind, err)
		}
		if again, _ := json.Marshal(d); string(again) != string(b) {
			t.Errorf("%s round trip\n got %s\nwant %s", s.Kind, again, b)
		}
	}
}

// Task 25's host decodes whole decision responses into these types.
func TestDecodedDecisionKeepsItsCandidates(t *testing.T) {
	sd := protocol.SeatDecision{ActingSeat: "p0", Context: protocol.Context{Kind: "choice"}}
	for i, s := range everyConstructor() {
		sd.Candidates = append(sd.Candidates, protocol.Candidate{CandidateID: uint32(i), Semantic: s})
	}
	b, err := json.Marshal(protocol.DecisionResponse{ResponseType: "decision", Protocol: protocol.Name, SeatDecision: sd})
	if err != nil {
		t.Fatal(err)
	}
	var back protocol.DecisionResponse
	if err := json.Unmarshal(b, &back); err != nil {
		t.Fatal(err)
	}
	for _, c := range back.SeatDecision.Candidates {
		if err := checked(t, c.Semantic); err != nil {
			t.Errorf("candidate %d: %v", c.CandidateID, err)
		}
	}
	if again, _ := json.Marshal(back); string(again) != string(b) {
		t.Errorf("decision round trip\n got %s\nwant %s", again, b)
	}
}

func TestSemanticDecodeNeedsAKindedObject(t *testing.T) {
	for _, text := range []string{`null`, `[]`, `"pass"`, `7`, `{}`, `{"kind":null}`, `{"kind":7}`} {
		var s protocol.Semantic
		if err := json.Unmarshal([]byte(text), &s); err == nil {
			t.Errorf("%s decoded as %+v", text, s)
		}
	}
	var c protocol.Candidate
	if err := json.Unmarshal([]byte(`{"candidate_id":0,"semantic":null,"display_text":null}`), &c); err == nil {
		t.Errorf("null semantic decoded as %+v", c.Semantic)
	}
}

func TestCheckReadsNumbersExactly(t *testing.T) {
	d := decoded(t, `{"kind":"choose_number","source":null,"purpose":"x_value","value":-2,"minimum":-3,"maximum":4}`)
	if d.Fields["value"] != json.Number("-2") {
		t.Fatalf("value decoded as %T %v, want json.Number", d.Fields["value"], d.Fields["value"])
	}
	if err := checked(t, d); err != nil {
		t.Fatalf("decoded choose_number: %v", err)
	}
	if err := checked(t, decoded(t, `{"kind":"choose_number","source":null,"purpose":"x_value","value":5,"minimum":0,"maximum":4}`)); err == nil {
		t.Error("decoded choose_number outside its range accepted")
	}
	// Generically decoded fields (float64): an error, not a panic.
	generic := protocol.Semantic{Kind: "choose_number", Fields: map[string]any{"source": nil, "purpose": "x_value",
		"value": float64(1), "minimum": float64(0), "maximum": float64(2)}}
	if err := checked(t, generic); err == nil {
		t.Error("float64 numbers accepted")
	}
	// Any Go integer type is read.
	s := protocol.OrderPick(nil, "triggers", protocol.ObjectItem(protocol.ObjectRef{ObjectID: "o-1"}), 0, 2)
	s.Fields["position"], s.Fields["count"] = int(1), uint64(2)
	if err := checked(t, s); err != nil {
		t.Errorf("Go integer types: %v", err)
	}
	// Anything else is refused, as are values outside the field's u32 or i32 range.
	for name, mutate := range map[string]func(protocol.Semantic){
		"fraction":            func(s protocol.Semantic) { s.Fields["position"] = json.Number("0.5") },
		"exponent":            func(s protocol.Semantic) { s.Fields["position"] = json.Number("0e0") },
		"string":              func(s protocol.Semantic) { s.Fields["position"] = "0" },
		"null":                func(s protocol.Semantic) { s.Fields["position"] = nil },
		"negative u32":        func(s protocol.Semantic) { s.Fields["position"] = json.Number("-1") },
		"u32 overflow":        func(s protocol.Semantic) { s.Fields["count"] = uint64(math.MaxUint32 + 1) },
		"uint64 beyond int64": func(s protocol.Semantic) { s.Fields["count"] = uint64(math.MaxUint64) },
	} {
		s := protocol.OrderPick(nil, "triggers", protocol.ObjectItem(protocol.ObjectRef{ObjectID: "o-1"}), 0, 2)
		mutate(s)
		if err := checked(t, s); err == nil {
			t.Errorf("order_pick with %s %v accepted", name, s.Fields)
		}
	}
	i32 := protocol.ChooseNumber(nil, "amount", 1, 0, 4)
	i32.Fields["maximum"] = json.Number("2147483648")
	if err := checked(t, i32); err == nil {
		t.Error("choose_number maximum beyond i32 accepted")
	}
}

// Section 7.3's remaining constraints, the mana_choice vocabulary, and a null
// cast_spell method (Section 7.2).
func TestCheckCoversTheRemainingConstraints(t *testing.T) {
	name := "x"
	r := protocol.ObjectRef{ObjectID: "o-1", CardName: &name, OwnerSeat: "p0", ControllerSeat: "p0", Zone: "stack"}
	option := func(idx, count uint32) protocol.Semantic {
		return protocol.Semantic{Kind: "choose_option", Fields: map[string]any{"source": nil, "purpose": "effect_option",
			"option_index": idx, "option_count": count, "option_label": nil}}
	}
	pile := func(idx uint32, piles any) protocol.Semantic {
		return protocol.Semantic{Kind: "choose_pile", Fields: map[string]any{"source": &r, "purpose": "effect", "pile_index": idx, "piles": piles}}
	}
	with := func(s protocol.Semantic, k string, v any) protocol.Semantic { s.Fields[k] = v; return s }
	g, x := "G", "X"
	for _, s := range []protocol.Semantic{
		option(1, 2),
		pile(1, [][]protocol.ObjectRef{{}, {r}}),
		protocol.ActivateManaAbility(r, 0, &g, nil),
		with(protocol.CastSpell(r, "normal"), "method", nil),
		with(protocol.CastSpell(r, "normal"), "method", (*string)(nil)),
		{Kind: "choose_cast_method", Fields: map[string]any{"source": r, "method": "flashback"}},
		decoded(t, `{"kind":"choose_pile","source":null,"purpose":"other","pile_index":0,"piles":[[{"object_id":"o-2","card_name":"Island","owner_seat":"p1","controller_seat":"p1","zone":"library"}],[]]}`),
		decoded(t, `{"kind":"cast_spell","source":{"object_id":"o-1","card_name":"x","owner_seat":"p0","controller_seat":"p0","zone":"hand"},"method":null}`),
		decoded(t, `{"kind":"activate_mana_ability","source":{"object_id":"o-1","card_name":"x","owner_seat":"p0","controller_seat":"p0","zone":"battlefield"},"ability_index":0,"mana_choice":"W","cost_target":null}`),
	} {
		if err := checked(t, s); err != nil {
			t.Errorf("%s %v: %v", s.Kind, s.Fields, err)
		}
	}
	for _, s := range []protocol.Semantic{
		option(2, 2),                                 // option_index < option_count
		pile(2, [][]protocol.ObjectRef{{}, {r}}),     // pile_index is 0 or 1
		pile(0, [][]protocol.ObjectRef{{r}}),         // exactly two piles
		pile(0, [][]protocol.ObjectRef{{}, {}, {r}}), // exactly two piles
		pile(0, []any{[]protocol.ObjectRef{}, r}),    // each pile is an array
		pile(0, nil),
		protocol.ActivateManaAbility(r, 0, &x, nil), // mana_choice is a symbol or null
		with(protocol.ActivateManaAbility(r, 0, nil, nil), "mana_choice", 5),
		protocol.CastSpell(r, "bogus"),
		with(protocol.OptionalCast(r, "madness", true), "method", nil), // null only for cast_spell
		{Kind: "choose_cast_method", Fields: map[string]any{"source": r, "method": nil}},
		{Kind: "choose_cast_method", Fields: map[string]any{"source": r, "method": "bogus"}},
		with(protocol.FinishSelection(nil, "search", 0), "purpose", nil), // vocabulary fields are strings
		decoded(t, `{"kind":"choose_pile","source":null,"purpose":"effect","pile_index":0,"piles":[[],[],[]]}`),
		decoded(t, `{"kind":"activate_mana_ability","source":{"object_id":"o-1","card_name":"x","owner_seat":"p0","controller_seat":"p0","zone":"battlefield"},"ability_index":0,"mana_choice":"w","cost_target":null}`),
	} {
		if err := checked(t, s); err == nil {
			t.Errorf("%s %v accepted", s.Kind, s.Fields)
		}
	}
}

// Section 9.3: extensions is an object, {} when the engine emits none.
func TestExtensionsMarshalAsAnObject(t *testing.T) {
	b, err := json.Marshal(protocol.DecisionResponse{})
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(b), `"extensions":{}`) {
		t.Errorf("nil extensions marshal as %s", b)
	}
	sd := protocol.SeatDecision{Extensions: map[string]json.RawMessage{"x_gorge_view_v1": json.RawMessage(`{"a":1}`)}}
	if b, _ = json.Marshal(sd); !strings.Contains(string(b), `"extensions":{"x_gorge_view_v1":{"a":1}}`) {
		t.Errorf("extensions marshal as %s", b)
	}
}
