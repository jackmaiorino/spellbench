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
	s := protocol.OrderPick(nil, "triggers", protocol.ObjectItem(ref), 0, 2)
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
		s := protocol.OrderPick(nil, "triggers", protocol.ObjectItem(ref), 0, 2)
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

// specTypes is this test's own transcription of the field types in Sections
// 7.2 and 7.3: R and T are object and target references, word is a
// vocabulary value, snake an open snake_case word, piles two arrays of R.
var specTypes = map[string][][2]string{
	"pass":                    {},
	"play_land":               {{"source", "R"}, {"face", "u32"}},
	"cast_spell":              {{"source", "R"}, {"method", "word|null"}},
	"activate_mana_ability":   {{"source", "R"}, {"ability_index", "u32"}, {"mana_choice", "word|null"}, {"cost_target", "T|null"}},
	"activate_ability":        {{"source", "R"}, {"ability_index", "u32"}},
	"special_action":          {{"source", "R"}, {"action", "word"}},
	"choose_target":           {{"source", "R"}, {"slot", "u32"}, {"target", "T"}, {"selected_count", "u32"}, {"minimum", "u32"}, {"maximum", "u32"}},
	"finish_target_selection": {{"source", "R"}, {"slot", "u32"}, {"selected_count", "u32"}},
	"choose_cost_target":      {{"source", "R"}, {"cost_kind", "word"}, {"candidate", "R"}, {"selected_count", "u32"}, {"minimum", "u32"}, {"maximum", "u32"}},
	"choose_cast_method":      {{"source", "R"}, {"method", "word"}},
	"choose_spell_mode":       {{"source", "R"}, {"mode_index", "u32"}, {"mode_count", "u32"}, {"selected_count", "u32"}, {"minimum", "u32"}, {"maximum", "u32"}},
	"choose_option":           {{"source", "R|null"}, {"purpose", "word"}, {"option_index", "u32"}, {"option_count", "u32"}, {"option_label", "string|null"}},
	"choose_color":            {{"source", "R|null"}, {"purpose", "word"}, {"color", "word"}},
	"choose_number":           {{"source", "R|null"}, {"purpose", "word"}, {"value", "i32"}, {"minimum", "i32"}, {"maximum", "i32"}},
	"choose_boolean":          {{"source", "R|null"}, {"purpose", "word"}, {"value", "bool"}},
	"choose_name":             {{"source", "R|null"}, {"purpose", "word"}, {"value", "string"}},
	"select_object":           {{"source", "R|null"}, {"purpose", "word"}, {"choice", "T"}, {"selected_count", "u32"}, {"minimum", "u32"}, {"maximum", "u32"}},
	"finish_selection":        {{"source", "R|null"}, {"purpose", "word"}, {"selected_count", "u32"}},
	"optional_cost":           {{"source", "R"}, {"cost", "word"}, {"pay", "bool"}},
	"choose_cost_option":      {{"source", "R"}, {"choice", "snake"}},
	"optional_cast":           {{"card", "R"}, {"method", "word"}, {"cast_it", "bool"}},
	"mulligan":                {{"hand_size", "u32"}, {"mulligans_taken", "u32"}, {"keep", "bool"}},
	"order_pick":              {{"source", "R|null"}, {"purpose", "word"}, {"item", "item"}, {"position", "u32"}, {"count", "u32"}},
	"arrange_card":            {{"source", "R|null"}, {"purpose", "word"}, {"card", "R"}, {"card_index", "u32"}, {"card_count", "u32"}, {"destination", "word"}},
	"choose_replacement":      {{"affected", "T"}, {"event", "word"}, {"replacement_source", "R|null"}, {"replacement_index", "u32"}, {"replacement_count", "u32"}},
	"choose_starting_player":  {{"player", "seat"}},
	"declare_attack":          {{"attacker", "R"}, {"defender", "T|null"}},
	"declare_block":           {{"blocker", "R"}, {"attacker", "R|null"}},
	"distribute":              {{"source", "R|null"}, {"purpose", "word"}, {"recipient", "T"}, {"amount", "u32"}, {"remaining", "u32"}},
	"choose_pile":             {{"source", "R|null"}, {"purpose", "word"}, {"pile_index", "u32"}, {"piles", "piles"}},
}

func TestKindFieldsMatchTheSpecTable(t *testing.T) {
	if len(protocol.KindFields) != len(specTypes) {
		t.Fatalf("%d kinds, spec table %d", len(protocol.KindFields), len(specTypes))
	}
	for kind, slots := range specTypes {
		got := protocol.KindFields[kind]
		if len(got) != len(slots) {
			t.Errorf("%s fields %v, spec %v", kind, got, slots)
			continue
		}
		for i, sl := range slots {
			if got[i] != sl[0] {
				t.Errorf("%s fields %v, spec %v", kind, got, slots)
			}
		}
	}
}

// baselines returns one valid semantic of every kind.
func baselines() map[string]protocol.Semantic {
	out := map[string]protocol.Semantic{}
	for _, s := range everyConstructor() {
		out[s.Kind] = s
	}
	for _, s := range []protocol.Semantic{
		{Kind: "choose_cast_method", Fields: map[string]any{"source": ref, "method": "flashback"}},
		{Kind: "choose_option", Fields: map[string]any{"source": nil, "purpose": "effect_option",
			"option_index": uint32(0), "option_count": uint32(2), "option_label": nil}},
		{Kind: "choose_cost_option", Fields: map[string]any{"source": ref, "choice": "sacrifice_land"}},
		{Kind: "choose_starting_player", Fields: map[string]any{"player": "p1"}},
		{Kind: "choose_pile", Fields: map[string]any{"source": nil, "purpose": "effect", "pile_index": uint32(1),
			"piles": [][]protocol.ObjectRef{{}, {ref}}}},
	} {
		out[s.Kind] = s
	}
	return out
}

// with returns a copy of s with field k set to v.
func with(s protocol.Semantic, k string, v any) protocol.Semantic {
	f := make(map[string]any, len(s.Fields))
	for key, val := range s.Fields {
		f[key] = val
	}
	f[k] = v
	return protocol.Semantic{Kind: s.Kind, Fields: f}
}

// mk builds a semantic from field pairs.
func mk(kind string, kv ...any) protocol.Semantic {
	f := map[string]any{}
	for i := 0; i < len(kv); i += 2 {
		f[kv[i].(string)] = kv[i+1]
	}
	return protocol.Semantic{Kind: kind, Fields: f}
}

// both runs Check on s as built and on s decoded from its JSON, as a host
// reads it.
func both(t *testing.T, s protocol.Semantic) (built, wire error) {
	t.Helper()
	built = checked(t, s)
	b, err := json.Marshal(s)
	if err != nil {
		return built, err
	}
	var d protocol.Semantic
	if err := json.Unmarshal(b, &d); err != nil {
		return built, err
	}
	return built, checked(t, d)
}

var (
	island = "Island"
	ref    = protocol.ObjectRef{ObjectID: "o-2", CardName: &island, OwnerSeat: "p1", ControllerSeat: "p1", Zone: "battlefield"}
)

// refMap is ref as decoded JSON, edited.
func refMap(edit func(map[string]any)) map[string]any {
	m := map[string]any{"object_id": "o-2", "card_name": "Island", "owner_seat": "p1", "controller_seat": "p1", "zone": "battlefield"}
	if edit != nil {
		edit(m)
	}
	return m
}

// trigger is an order_pick trigger item's body as decoded JSON, edited.
func trigger(edit func(map[string]any)) map[string]any {
	m := map[string]any{"source": refMap(nil), "source_name": "Island", "ability_index": 0,
		"event_objects": []any{refMap(nil)}, "instance": 1, "label": nil}
	if edit != nil {
		edit(m)
	}
	return m
}

type value struct {
	name string
	v    any
}

// wrongValues returns values that a field of the given spec type must refuse.
func wrongValues(typ string) []value {
	base, nullable := strings.CutSuffix(typ, "|null")
	var out []value
	if !nullable {
		out = append(out, value{"null", nil})
	}
	badRef := func(name string, edit func(map[string]any)) value { return value{name, refMap(edit)} }
	switch base {
	case "u32":
		out = append(out, value{"-1", -1}, value{"2^32", uint64(1) << 32}, value{"1.5", json.Number("1.5")},
			value{"1e0", json.Number("1e0")}, value{`"0"`, "0"}, value{"true", true}, value{"{}", map[string]any{}})
	case "i32":
		out = append(out, value{"2^31", int64(math.MaxInt32) + 1}, value{"-2^31-1", int64(math.MinInt32) - 1},
			value{"0.5", json.Number("0.5")}, value{`"0"`, "0"}, value{"false", false})
	case "bool":
		out = append(out, value{`"yes"`, "yes"}, value{`"true"`, "true"}, value{"1", 1}, value{"{}", map[string]any{}})
	case "string":
		out = append(out, value{"5", 5}, value{"true", true}, value{"{}", map[string]any{}}, value{"[]", []any{}})
	case "word":
		out = append(out, value{`"bogus"`, "bogus"}, value{`""`, ""}, value{"5", 5}, value{"true", true})
	case "snake":
		out = append(out, value{`"Not Snake"`, "Not Snake"}, value{`"1st"`, "1st"}, value{`"a-b"`, "a-b"},
			value{`""`, ""}, value{"5", 5})
	case "seat":
		out = append(out, value{`"p7"`, "p7"}, value{`"P0"`, "P0"}, value{`""`, ""}, value{"0", 0})
	case "R":
		out = append(out, value{"7", 7}, value{`"o-2"`, "o-2"}, value{"[]", []any{}}, value{"{}", map[string]any{}},
			value{"zero ObjectRef", protocol.ObjectRef{}}, value{"player target", protocol.PlayerTarget("p0")},
			badRef("ref without zone", func(m map[string]any) { delete(m, "zone") }),
			badRef("ref with an extra key", func(m map[string]any) { m["x"] = 1 }),
			badRef("owner_seat p7", func(m map[string]any) { m["owner_seat"] = "p7" }),
			badRef("controller_seat null", func(m map[string]any) { m["controller_seat"] = nil }),
			badRef("zone deck", func(m map[string]any) { m["zone"] = "deck" }),
			badRef("object_id 5", func(m map[string]any) { m["object_id"] = 5 }),
			badRef("object_id null", func(m map[string]any) { m["object_id"] = nil }),
			badRef("card_name 5", func(m map[string]any) { m["card_name"] = 5 }))
	case "T":
		out = append(out, value{"zero TargetRef", protocol.TargetRef{}}, value{`{"object":null}`, map[string]any{"object": nil}},
			value{"{}", map[string]any{}}, value{`{"player":"p7"}`, map[string]any{"player": "p7"}},
			value{"player and object", map[string]any{"player": "p0", "object": refMap(nil)}},
			value{`{"target":"p0"}`, map[string]any{"target": "p0"}},
			value{"object with a bad ref", map[string]any{"object": refMap(func(m map[string]any) { m["zone"] = "deck" })}},
			value{"bare ref", ref}, value{`"p0"`, "p0"}, value{"5", 5})
	case "item":
		badTrigger := func(name string, edit func(map[string]any)) value {
			return value{name, map[string]any{"trigger": trigger(edit)}}
		}
		out = append(out, value{"zero OrderItem", protocol.OrderItem{}}, value{`{"trigger":null}`, map[string]any{"trigger": nil}},
			value{`{"object":null}`, map[string]any{"object": nil}}, value{"[]", []any{}}, value{"{}", map[string]any{}},
			value{"object and trigger", map[string]any{"object": refMap(nil), "trigger": trigger(nil)}},
			value{`{"card":R}`, map[string]any{"card": refMap(nil)}}, value{"bare ref", refMap(nil)},
			badTrigger("trigger without instance", func(m map[string]any) { delete(m, "instance") }),
			badTrigger("trigger with an extra key", func(m map[string]any) { m["x"] = 1 }),
			badTrigger("trigger instance -1", func(m map[string]any) { m["instance"] = -1 }),
			badTrigger(`trigger ability_index "x"`, func(m map[string]any) { m["ability_index"] = "x" }),
			badTrigger("trigger source 5", func(m map[string]any) { m["source"] = 5 }),
			badTrigger("trigger source_name 5", func(m map[string]any) { m["source_name"] = 5 }),
			badTrigger("trigger label 5", func(m map[string]any) { m["label"] = 5 }),
			badTrigger("trigger event_objects null", func(m map[string]any) { m["event_objects"] = nil }),
			badTrigger("trigger event_objects [5]", func(m map[string]any) { m["event_objects"] = []any{5} }))
	case "piles":
		out = append(out, value{`[[1,2],["x"]]`, []any{[]any{1, 2}, []any{"x"}}},
			value{"refs, not arrays", []any{refMap(nil), refMap(nil)}},
			value{"a null pile", []any{[]any{refMap(nil)}, nil}},
			value{"a bad ref in a pile", []any{[]any{refMap(func(m map[string]any) { m["zone"] = "deck" })}, []any{}}},
			value{`"piles"`, "piles"}, value{"{}", map[string]any{}})
	}
	return out
}

// validValues returns values other than the baseline's that a field of the
// given spec type must accept. Numbers are covered by the constraint tests.
func validValues(typ string) []value {
	base, nullable := strings.CutSuffix(typ, "|null")
	var out []value
	if nullable {
		out = append(out, value{"null", nil})
		switch base {
		case "R":
			out = append(out, value{"nil *ObjectRef", (*protocol.ObjectRef)(nil)})
		case "T":
			out = append(out, value{"nil *TargetRef", (*protocol.TargetRef)(nil)})
		case "string", "word":
			out = append(out, value{"nil *string", (*string)(nil)})
		}
	}
	tgt := protocol.ObjectTarget(ref)
	switch base {
	case "R":
		out = append(out, value{"ObjectRef", ref}, value{"*ObjectRef", &ref},
			value{"null card_name", refMap(func(m map[string]any) { m["card_name"] = nil })},
			value{"zone exile", refMap(func(m map[string]any) { m["zone"] = "exile" })})
	case "T":
		out = append(out, value{"player p0", protocol.PlayerTarget("p0")}, value{"object", tgt}, value{"*TargetRef", &tgt},
			value{`{"player":"p1"}`, map[string]any{"player": "p1"}})
	case "item":
		out = append(out, value{"object item", protocol.ObjectItem(ref)},
			value{"empty trigger", protocol.OrderItem{Trigger: &protocol.TriggerItem{EventObjects: []protocol.ObjectRef{}}}},
			value{"trigger", map[string]any{"trigger": trigger(nil)}},
			value{"trigger with nulls", map[string]any{"trigger": trigger(func(m map[string]any) {
				m["source"], m["source_name"], m["ability_index"], m["event_objects"] = nil, nil, nil, []any{}
			})}})
	case "piles":
		out = append(out, value{"Go piles", [][]protocol.ObjectRef{{ref}, {}}},
			value{"decoded piles", []any{[]any{}, []any{refMap(nil), refMap(nil)}}})
	case "seat":
		out = append(out, value{"p0", "p0"}, value{"p1", "p1"})
	case "snake":
		out = append(out, value{"decline", "decline"}, value{"a1_b", "a1_b"})
	case "bool":
		out = append(out, value{"true", true}, value{"false", false})
	}
	return out
}

// Every field slot of every kind refuses values of the wrong type, built or
// decoded.
func TestEverySlotRejectsAWrongValue(t *testing.T) {
	base := baselines()
	for kind, slots := range specTypes {
		for _, sl := range slots {
			for _, w := range wrongValues(sl[1]) {
				if built, wire := both(t, with(base[kind], sl[0], w.v)); built == nil || wire == nil {
					t.Errorf("%s.%s = %s accepted (built: %v, decoded: %v)", kind, sl[0], w.name, built, wire)
				}
			}
		}
	}
}

func TestEverySlotAcceptsItsValidForms(t *testing.T) {
	base := baselines()
	if len(base) != len(specTypes) {
		t.Fatalf("%d baselines for %d kinds", len(base), len(specTypes))
	}
	for kind, slots := range specTypes {
		if built, wire := both(t, base[kind]); built != nil || wire != nil {
			t.Errorf("baseline %s rejected (built: %v, decoded: %v)", kind, built, wire)
		}
		for _, sl := range slots {
			vals := validValues(sl[1])
			if w, ok := base[kind].Fields[sl[0]].(string); ok {
				vals = append(vals, value{"*string", &w})
			}
			for _, v := range vals {
				if built, wire := both(t, with(base[kind], sl[0], v.v)); built != nil || wire != nil {
					t.Errorf("%s.%s = %s rejected (built: %v, decoded: %v)", kind, sl[0], v.name, built, wire)
				}
			}
		}
	}
}

// A zero TargetRef or OrderItem marshals as {"object":null} or
// {"trigger":null}; one with both members set marshals as its first member.
// Check refuses all three in every target and item slot.
func TestZeroAndDoubleReferencesFailCheck(t *testing.T) {
	base := baselines()
	p0 := "p0"
	for kind, slots := range specTypes {
		for _, sl := range slots {
			var bad []value
			switch strings.TrimSuffix(sl[1], "|null") {
			case "T":
				bad = []value{{"zero TargetRef", protocol.TargetRef{}}, {"&zero TargetRef", &protocol.TargetRef{}},
					{"TargetRef with both members", protocol.TargetRef{Player: &p0, Object: &ref}}}
			case "item":
				bad = []value{{"zero OrderItem", protocol.OrderItem{}}, {"&zero OrderItem", &protocol.OrderItem{}},
					{"OrderItem with both members", protocol.OrderItem{Object: &ref, Trigger: &protocol.TriggerItem{EventObjects: []protocol.ObjectRef{}}}}}
			}
			for _, b := range bad {
				if err := checked(t, with(base[kind], sl[0], b.v)); err == nil {
					t.Errorf("%s.%s = %s accepted", kind, sl[0], b.name)
				}
			}
		}
	}
	for _, text := range []string{
		`{"kind":"choose_target","source":{"object_id":"o-1","card_name":"x","owner_seat":"p0","controller_seat":"p0","zone":"stack"},"slot":0,"target":{"object":null},"selected_count":0,"minimum":1,"maximum":1}`,
		`{"kind":"order_pick","source":null,"purpose":"triggers","item":{"trigger":null},"position":0,"count":1}`,
	} {
		if err := checked(t, decoded(t, text)); err == nil {
			t.Errorf("%s accepted", text)
		}
	}
}

// Each clause of Section 7.3's field constraints, the choose_name card-type
// domain, and the field set, violated alone and met at its boundary.
func TestCheckEnforcesEachConstraintClause(t *testing.T) {
	R := refMap(nil)
	target := func(sel, lo, hi int) protocol.Semantic {
		return mk("choose_target", "source", R, "slot", 0, "target", map[string]any{"player": "p1"}, "selected_count", sel, "minimum", lo, "maximum", hi)
	}
	costTarget := func(sel, lo, hi int) protocol.Semantic {
		return mk("choose_cost_target", "source", R, "cost_kind", "sacrifice", "candidate", R, "selected_count", sel, "minimum", lo, "maximum", hi)
	}
	selectObject := func(sel, lo, hi int) protocol.Semantic {
		return mk("select_object", "source", nil, "purpose", "discard", "choice", map[string]any{"object": R}, "selected_count", sel, "minimum", lo, "maximum", hi)
	}
	mode := func(idx, count, sel, lo, hi int) protocol.Semantic {
		return mk("choose_spell_mode", "source", R, "mode_index", idx, "mode_count", count, "selected_count", sel, "minimum", lo, "maximum", hi)
	}
	option := func(idx, count int) protocol.Semantic {
		return mk("choose_option", "source", nil, "purpose", "vote", "option_index", idx, "option_count", count, "option_label", "yes")
	}
	number := func(v, lo, hi int64) protocol.Semantic {
		return mk("choose_number", "source", nil, "purpose", "amount", "value", v, "minimum", lo, "maximum", hi)
	}
	pick := func(pos, count int) protocol.Semantic {
		return mk("order_pick", "source", nil, "purpose", "triggers", "item", map[string]any{"object": R}, "position", pos, "count", count)
	}
	arrange := func(idx, count int) protocol.Semantic {
		return mk("arrange_card", "source", nil, "purpose", "scry", "card", R, "card_index", idx, "card_count", count, "destination", "bottom")
	}
	replacement := func(idx, count int) protocol.Semantic {
		return mk("choose_replacement", "affected", map[string]any{"player": "p0"}, "event", "damage", "replacement_source", nil,
			"replacement_index", idx, "replacement_count", count)
	}
	distribute := func(amount, remaining int) protocol.Semantic {
		return mk("distribute", "source", nil, "purpose", "damage", "recipient", map[string]any{"player": "p1"}, "amount", amount, "remaining", remaining)
	}
	pile := func(idx int, piles ...any) protocol.Semantic {
		return mk("choose_pile", "source", nil, "purpose", "effect", "pile_index", idx, "piles", piles)
	}
	name := func(purpose, v string) protocol.Semantic {
		return mk("choose_name", "source", nil, "purpose", purpose, "value", v)
	}
	color := func(kv ...any) protocol.Semantic {
		return mk("choose_color", append([]any{"source", nil, "purpose", "effect"}, kv...)...)
	}
	for name, s := range map[string]protocol.Semantic{
		"choose_target minimum > maximum":              target(0, 2, 1),
		"choose_target selected_count = maximum":       target(1, 1, 1),
		"choose_cost_target minimum > maximum":         costTarget(0, 2, 1),
		"choose_cost_target selected_count = maximum":  costTarget(1, 1, 1),
		"select_object minimum > maximum":              selectObject(0, 2, 1),
		"select_object selected_count = maximum":       selectObject(1, 1, 1),
		"choose_spell_mode mode_index = mode_count":    mode(2, 2, 0, 1, 1),
		"choose_spell_mode minimum > maximum":          mode(0, 3, 0, 2, 1),
		"choose_spell_mode maximum > mode_count":       mode(0, 2, 0, 1, 3),
		"choose_spell_mode selected_count = maximum":   mode(0, 2, 1, 1, 1),
		"choose_option option_index = option_count":    option(2, 2),
		"choose_number value < minimum":                number(-1, 0, 4),
		"choose_number value > maximum":                number(5, 0, 4),
		"order_pick position = count":                  pick(2, 2),
		"arrange_card card_index = card_count":         arrange(2, 2),
		"choose_replacement replacement_count = 1":     replacement(0, 1),
		"choose_replacement index = count":             replacement(2, 2),
		"distribute amount > remaining":                distribute(4, 3),
		"choose_pile pile_index 2":                     pile(2, []any{}, []any{R}),
		"choose_pile with one pile":                    pile(0, []any{R}),
		"choose_pile with three piles":                 pile(0, []any{}, []any{}, []any{R}),
		"choose_pile with no piles":                    pile(0),
		"choose_name card_type bogus":                  name("card_type", "bogus"),
		"choose_name card_type Creature":               name("card_type", "Creature"),
		"pass with an extra field":                     mk("pass", "x", 1),
		"choose_color with an extra field":             color("color", "red", "extra", 1),
		"choose_color without color":                   color(),
		"choose_color with colour instead of color":    color("colour", "red"),
		"choose_color with sauce instead of source":    mk("choose_color", "sauce", nil, "purpose", "effect", "color", "red"),
		"reserved kind pay_mana":                       mk("pay_mana"),
		"reserved kind narrow_number":                  mk("narrow_number", "source", nil, "purpose", "other", "minimum", 0, "maximum", 1),
		"kind missing":                                 mk(""),
		"choose_number minimum beyond i32":             number(0, math.MinInt32-1, 4),
		"play_land face beyond u32":                    mk("play_land", "source", R, "face", uint64(math.MaxUint32)+1),
		"order_pick position -1":                       pick(-1, 2),
		"choose_starting_player player null":           mk("choose_starting_player", "player", nil),
		"choose_cost_option choice with a capital":     mk("choose_cost_option", "source", R, "choice", "Decline"),
		"cast_spell method bogus":                      mk("cast_spell", "source", R, "method", "bogus"),
		"activate_mana_ability mana_choice lower case": mk("activate_mana_ability", "source", R, "ability_index", 0, "mana_choice", "w", "cost_target", nil),
	} {
		if built, wire := both(t, s); built == nil || wire == nil {
			t.Errorf("%s accepted (built: %v, decoded: %v)", name, built, wire)
		}
	}
	for name, s := range map[string]protocol.Semantic{
		"choose_target minimum = maximum":                   target(0, 1, 1),
		"choose_target selected_count = maximum - 1":        target(1, 0, 2),
		"choose_cost_target minimum = maximum":              costTarget(0, 1, 1),
		"choose_cost_target selected_count = maximum - 1":   costTarget(1, 0, 2),
		"select_object minimum = maximum":                   selectObject(0, 1, 1),
		"select_object selected_count = maximum - 1":        selectObject(1, 0, 2),
		"choose_spell_mode at every boundary":               mode(1, 2, 1, 2, 2),
		"choose_option option_index = option_count - 1":     option(1, 2),
		"choose_number value = minimum":                     number(-3, -3, 4),
		"choose_number value = maximum":                     number(4, -3, 4),
		"choose_number over the whole i32 range":            number(math.MinInt32, math.MinInt32, math.MaxInt32),
		"choose_number value = i32 maximum":                 number(math.MaxInt32, 0, math.MaxInt32),
		"order_pick position = count - 1":                   pick(1, 2),
		"arrange_card card_index = card_count - 1":          arrange(1, 2),
		"choose_replacement replacement_count = 2":          replacement(0, 2),
		"choose_replacement index = count - 1":              replacement(1, 2),
		"distribute amount = remaining":                     distribute(3, 3),
		"choose_pile pile_index 0":                          pile(0, []any{}, []any{R}),
		"choose_pile pile_index 1":                          pile(1, []any{R}, []any{}),
		"choose_name card_type creature":                    name("card_type", "creature"),
		"choose_name card_type kindred":                     name("card_type", "kindred"),
		"choose_name creature_type goblin":                  name("creature_type", "goblin"),
		"choose_name card_name Lightning Bolt":              name("card_name", "Lightning Bolt"),
		"choose_color":                                      color("color", "red"),
		"pass":                                              mk("pass"),
		"play_land face = u32 maximum":                      mk("play_land", "source", R, "face", uint64(math.MaxUint32)),
		"mulligan counts as Go int, uint64 and json.Number": mk("mulligan", "hand_size", 7, "mulligans_taken", uint64(1), "keep", true),
		"finish_selection selected_count as json.Number":    mk("finish_selection", "source", nil, "purpose", "modes", "selected_count", json.Number("3")),
	} {
		if built, wire := both(t, s); built != nil || wire != nil {
			t.Errorf("%s rejected (built: %v, decoded: %v)", name, built, wire)
		}
	}
}

// TargetRef decoding (observation targets: attached_to, attack_target, stack
// targets) accepts exactly {"player": seat} or {"object": ref}.
func TestTargetRefDecodingIsStrict(t *testing.T) {
	obj := `{"object_id":"o-1","card_name":null,"owner_seat":"p0","controller_seat":"p0","zone":"battlefield"}`
	for _, text := range []string{`null`, `{}`, `[]`, `"p0"`, `{"object":null}`, `{"player":null}`, `{"player":"p7"}`,
		`{"player":"p0","x":1}`, `{"player":"p0","object":` + obj + `}`, `{"target":"p0"}`} {
		var tr protocol.TargetRef
		if err := json.Unmarshal([]byte(text), &tr); err == nil {
			t.Errorf("%s decoded as %+v", text, tr)
		}
	}
	for _, text := range []string{`{"player":"p1"}`, `{"object":` + obj + `}`} {
		var tr protocol.TargetRef
		if err := json.Unmarshal([]byte(text), &tr); err != nil {
			t.Errorf("%s: %v", text, err)
		} else if b, _ := json.Marshal(tr); string(b) != text {
			t.Errorf("%s re-marshals as %s", text, b)
		}
	}
	var p protocol.Permanent
	if err := json.Unmarshal([]byte(`{"attached_to":{"object":null}}`), &p); err == nil {
		t.Error(`attached_to {"object":null} decoded`)
	}
	if err := json.Unmarshal([]byte(`{"attached_to":null,"attack_target":{"player":"p1"}}`), &p); err != nil || p.AttachedTo != nil {
		t.Errorf("valid permanent targets: %v %+v", err, p)
	}
}

// Section 6.3's progress object and Section 4.2's u32 protocol_minor.
func TestProgressAndProtocolMinorTypes(t *testing.T) {
	text := `{"dungeon":"Tomb of Annihilation","dungeon_room":null,"ring_tempted":2,"speed":null}`
	var p protocol.PlayerObs
	if err := json.Unmarshal([]byte(`{"progress":`+text+`}`), &p); err != nil {
		t.Fatal(err)
	}
	if b, _ := json.Marshal(p.Progress); string(b) != text {
		t.Errorf("progress re-marshals as %s", b)
	}
	var h protocol.HelloOK
	if err := json.Unmarshal([]byte(`{"protocol_minor":4294967296}`), &h); err == nil {
		t.Error("protocol_minor 2^32 decoded")
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
	// The guarantee sits on the small map, not on the whole decision.
	if b, _ = json.Marshal(protocol.ExtensionMap(nil)); string(b) != `{}` {
		t.Errorf("nil ExtensionMap marshals as %s", b)
	}
	// A host decoding an engine's null still sees it (Task 9's check).
	var back protocol.SeatDecision
	if err := json.Unmarshal([]byte(`{"extensions":null}`), &back); err != nil || back.Extensions != nil {
		t.Errorf("decoded null extensions: %v %v", err, back.Extensions)
	}
}
