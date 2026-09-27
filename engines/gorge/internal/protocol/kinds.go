package protocol

import (
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"reflect"
	"slices"
)

// KindFields is Section 7.2 and 7.3: each kind's fields, all required, no others.
var KindFields = map[string][]string{
	"pass":                    {},
	"play_land":               {"source", "face"},
	"cast_spell":              {"source", "method"},
	"activate_mana_ability":   {"source", "ability_index", "mana_choice", "cost_target"},
	"activate_ability":        {"source", "ability_index"},
	"special_action":          {"source", "action"},
	"choose_target":           {"source", "slot", "target", "selected_count", "minimum", "maximum"},
	"finish_target_selection": {"source", "slot", "selected_count"},
	"choose_cost_target":      {"source", "cost_kind", "candidate", "selected_count", "minimum", "maximum"},
	"choose_cast_method":      {"source", "method"},
	"choose_spell_mode":       {"source", "mode_index", "mode_count", "selected_count", "minimum", "maximum"},
	"choose_option":           {"source", "purpose", "option_index", "option_count", "option_label"},
	"choose_color":            {"source", "purpose", "color"},
	"choose_number":           {"source", "purpose", "value", "minimum", "maximum"},
	"choose_boolean":          {"source", "purpose", "value"},
	"choose_name":             {"source", "purpose", "value"},
	"select_object":           {"source", "purpose", "choice", "selected_count", "minimum", "maximum"},
	"finish_selection":        {"source", "purpose", "selected_count"},
	"optional_cost":           {"source", "cost", "pay"},
	"choose_cost_option":      {"source", "choice"},
	"optional_cast":           {"card", "method", "cast_it"},
	"mulligan":                {"hand_size", "mulligans_taken", "keep"},
	"order_pick":              {"source", "purpose", "item", "position", "count"},
	"arrange_card":            {"source", "purpose", "card", "card_index", "card_count", "destination"},
	"choose_replacement":      {"affected", "event", "replacement_source", "replacement_index", "replacement_count"},
	"choose_starting_player":  {"player"},
	"declare_attack":          {"attacker", "defender"},
	"declare_block":           {"blocker", "attacker"},
	"distribute":              {"source", "purpose", "recipient", "amount", "remaining"},
	"choose_pile":             {"source", "purpose", "pile_index", "piles"},
}

var PriorityKinds = map[string]bool{"pass": true, "play_land": true, "cast_spell": true,
	"activate_mana_ability": true, "activate_ability": true, "special_action": true}

// Vocab is Section 6.10 and 7.4, keyed "<kind>.<field>" or a shared name.
var Vocab = map[string][]string{
	"select_object.purpose":        {"discard", "sacrifice", "exile", "destroy", "return_to_hand", "search", "reveal", "put_onto_battlefield", "put_into_hand", "put_into_graveyard", "legend_rule", "tap", "untap", "delve", "convoke", "attach", "keep", "vote", "modes", "other"},
	"finish_selection.purpose":     {"discard", "sacrifice", "exile", "destroy", "return_to_hand", "search", "reveal", "put_onto_battlefield", "put_into_hand", "put_into_graveyard", "legend_rule", "tap", "untap", "delve", "convoke", "attach", "keep", "vote", "modes", "other"},
	"choose_boolean.purpose":       {"may_ability", "optional_trigger", "may_cast", "change_copy_targets", "optional_replacement", "reveal", "other"},
	"choose_number.purpose":        {"x_value", "amount", "life_payment", "cost_repetitions", "vote", "other"},
	"choose_option.purpose":        {"effect_option", "top_or_bottom", "odd_or_even", "vote", "other"},
	"choose_color.purpose":         {"mana", "protection", "effect", "other"},
	"choose_name.purpose":          {"card_name", "creature_type", "card_type", "land_type", "basic_land_type", "other"},
	"order_pick.purpose":           {"triggers", "library_top", "library_bottom", "mulligan_bottom", "arrangement", "other"},
	"arrange_card.purpose":         {"scry", "surveil", "dig", "look_at_top", "pile_split", "other"},
	"arrange_card.destination":     {"top", "bottom", "graveyard", "exile", "hand", "battlefield", "pile_0", "pile_1"},
	"distribute.purpose":           {"damage", "combat_damage", "counters", "mana", "life", "other"},
	"choose_pile.purpose":          {"effect", "other"},
	"method":                       {"normal", "alternative", "flashback", "escape", "evoke", "overload", "adventure", "disturb", "foretell", "plot", "mdfc_back", "split_left", "split_right", "fuse", "prototype", "morph", "disguise", "madness", "miracle", "cascade", "discover", "rebound", "suspend", "free", "other"},
	"optional_cost.cost":           {"kicker", "buyback", "entwine", "conspire", "casualty", "bargain", "gift", "offspring", "copy", "unless_payment", "additional", "other"},
	"choose_cost_target.cost_kind": {"sacrifice", "discard", "exile", "tap", "untap", "return_to_hand", "reveal", "remove_counter", "other"},
	"special_action.action":        {"turn_face_up", "plot", "foretell", "suspend", "unlock_door", "other"},
	"choose_replacement.event":     {"zone_change", "damage", "draw", "enter_battlefield", "counters", "life", "other"},
	"color":                        {"white", "blue", "black", "red", "green"},
	"mana_symbol":                  {"W", "U", "B", "R", "G", "C"},
	"card_type":                    {"artifact", "battle", "conspiracy", "creature", "dungeon", "enchantment", "instant", "kindred", "land", "phenomenon", "plane", "planeswalker", "scheme", "sorcery", "vanguard"},
}

// Semantic is a candidate's tagged object: Kind plus that kind's fields.
// Constructors store Go values (ObjectRef, TargetRef, OrderItem, their
// pointers for nullable fields, uint32, int32, string, *string, bool).
// UnmarshalJSON, the host's side, stores strings, bools, null (nil) and numbers
// (json.Number), and keeps objects and arrays as json.RawMessage: a generic map
// would re-sort the keys of nested references, so Marshal could not reproduce
// the engine's bytes.
type Semantic struct {
	Kind   string
	Fields map[string]any
}

func (s Semantic) MarshalJSON() ([]byte, error) {
	m := make(map[string]any, len(s.Fields)+1)
	for k, v := range s.Fields {
		m[k] = v
	}
	m["kind"] = s.Kind
	return json.Marshal(m)
}

// UnmarshalJSON accepts an object whose kind is a string; Check judges the
// other fields.
func (s *Semantic) UnmarshalJSON(b []byte) error {
	var raw map[string]json.RawMessage
	if err := json.Unmarshal(b, &raw); err != nil {
		return fmt.Errorf("semantic: %w", err)
	}
	k, ok := raw["kind"]
	if !ok || k[0] != '"' {
		return errors.New("semantic: not an object with a string kind")
	}
	var kind string
	if err := json.Unmarshal(k, &kind); err != nil {
		return fmt.Errorf("semantic kind: %w", err)
	}
	delete(raw, "kind")
	fields := make(map[string]any, len(raw))
	for name, v := range raw {
		switch v[0] {
		case '{', '[':
			fields[name] = v
		case '"':
			var str string
			if err := json.Unmarshal(v, &str); err != nil {
				return fmt.Errorf("semantic field %s: %w", name, err)
			}
			fields[name] = str
		case 't', 'f':
			fields[name] = v[0] == 't'
		case 'n':
			fields[name] = nil
		default:
			fields[name] = json.Number(v) // the literal, as UseNumber keeps it
		}
	}
	s.Kind, s.Fields = kind, fields
	return nil
}

func sem(kind string, kv ...any) Semantic {
	f := make(map[string]any, len(kv)/2)
	for i := 0; i < len(kv); i += 2 {
		f[kv[i].(string)] = kv[i+1]
	}
	return Semantic{Kind: kind, Fields: f}
}

func Pass() Semantic { return sem("pass") }
func PlayLand(src ObjectRef, face uint32) Semantic {
	return sem("play_land", "source", src, "face", face)
}
func CastSpell(src ObjectRef, method string) Semantic {
	return sem("cast_spell", "source", src, "method", method)
}
func ActivateManaAbility(src ObjectRef, idx uint32, mana *string, cost *TargetRef) Semantic {
	return sem("activate_mana_ability", "source", src, "ability_index", idx, "mana_choice", mana, "cost_target", cost)
}
func ActivateAbility(src ObjectRef, idx uint32) Semantic {
	return sem("activate_ability", "source", src, "ability_index", idx)
}
func SpecialAction(src ObjectRef, action string) Semantic {
	return sem("special_action", "source", src, "action", action)
}
func ChooseTarget(src ObjectRef, slot uint32, t TargetRef, sel, lo, hi uint32) Semantic {
	return sem("choose_target", "source", src, "slot", slot, "target", t, "selected_count", sel, "minimum", lo, "maximum", hi)
}
func FinishTargetSelection(src ObjectRef, slot, sel uint32) Semantic {
	return sem("finish_target_selection", "source", src, "slot", slot, "selected_count", sel)
}
func ChooseCostTarget(src ObjectRef, costKind string, cand ObjectRef, sel, lo, hi uint32) Semantic {
	return sem("choose_cost_target", "source", src, "cost_kind", costKind, "candidate", cand, "selected_count", sel, "minimum", lo, "maximum", hi)
}
func ChooseSpellMode(src ObjectRef, idx, count, sel, lo, hi uint32) Semantic {
	return sem("choose_spell_mode", "source", src, "mode_index", idx, "mode_count", count, "selected_count", sel, "minimum", lo, "maximum", hi)
}
func ChooseColor(src *ObjectRef, purpose, color string) Semantic {
	return sem("choose_color", "source", src, "purpose", purpose, "color", color)
}
func ChooseNumber(src *ObjectRef, purpose string, v, lo, hi int32) Semantic {
	return sem("choose_number", "source", src, "purpose", purpose, "value", v, "minimum", lo, "maximum", hi)
}
func ChooseBoolean(src *ObjectRef, purpose string, v bool) Semantic {
	return sem("choose_boolean", "source", src, "purpose", purpose, "value", v)
}
func ChooseName(src *ObjectRef, purpose, v string) Semantic {
	return sem("choose_name", "source", src, "purpose", purpose, "value", v)
}
func SelectObject(src *ObjectRef, purpose string, choice TargetRef, sel, lo, hi uint32) Semantic {
	return sem("select_object", "source", src, "purpose", purpose, "choice", choice, "selected_count", sel, "minimum", lo, "maximum", hi)
}
func FinishSelection(src *ObjectRef, purpose string, sel uint32) Semantic {
	return sem("finish_selection", "source", src, "purpose", purpose, "selected_count", sel)
}
func OptionalCost(src ObjectRef, cost string, pay bool) Semantic {
	return sem("optional_cost", "source", src, "cost", cost, "pay", pay)
}
func OptionalCast(card ObjectRef, method string, castIt bool) Semantic {
	return sem("optional_cast", "card", card, "method", method, "cast_it", castIt)
}
func Mulligan(handSize, taken uint32, keep bool) Semantic {
	return sem("mulligan", "hand_size", handSize, "mulligans_taken", taken, "keep", keep)
}
func OrderPick(src *ObjectRef, purpose string, item OrderItem, pos, count uint32) Semantic {
	return sem("order_pick", "source", src, "purpose", purpose, "item", item, "position", pos, "count", count)
}
func ArrangeCard(src *ObjectRef, purpose string, card ObjectRef, idx, count uint32, dest string) Semantic {
	return sem("arrange_card", "source", src, "purpose", purpose, "card", card, "card_index", idx, "card_count", count, "destination", dest)
}
func ChooseReplacement(affected TargetRef, event string, replSrc *ObjectRef, idx, count uint32) Semantic {
	return sem("choose_replacement", "affected", affected, "event", event, "replacement_source", replSrc, "replacement_index", idx, "replacement_count", count)
}
func DeclareAttack(attacker ObjectRef, defender *TargetRef) Semantic {
	return sem("declare_attack", "attacker", attacker, "defender", defender)
}
func DeclareBlock(blocker ObjectRef, attacker *ObjectRef) Semantic {
	return sem("declare_block", "blocker", blocker, "attacker", attacker)
}
func Distribute(src *ObjectRef, purpose string, recipient TargetRef, amount, remaining uint32) Semantic {
	return sem("distribute", "source", src, "purpose", purpose, "recipient", recipient, "amount", amount, "remaining", remaining)
}

func inVocab(list, v string) bool { return slices.Contains(Vocab[list], v) }

// show renders a field value for an error message as its JSON.
func show(v any) string {
	if b, err := json.Marshal(v); err == nil {
		return string(b)
	}
	return fmt.Sprint(v)
}

// integer is how Check reads every number: a Go integer type (constructors) or
// a json.Number (UnmarshalJSON). Anything else is an error, including a float64
// from a decoder without UseNumber and a literal with a fraction or exponent.
func integer(v any) (int64, error) {
	if n, ok := v.(json.Number); ok {
		i, err := n.Int64()
		if err != nil {
			return 0, fmt.Errorf("%s is not an integer", n)
		}
		return i, nil
	}
	switch rv := reflect.ValueOf(v); rv.Kind() {
	case reflect.Int, reflect.Int8, reflect.Int16, reflect.Int32, reflect.Int64:
		return rv.Int(), nil
	case reflect.Uint, reflect.Uint8, reflect.Uint16, reflect.Uint32, reflect.Uint64:
		if n := rv.Uint(); n <= math.MaxInt64 {
			return int64(n), nil
		}
		return 0, fmt.Errorf("%d is out of range", rv.Uint())
	}
	return 0, fmt.Errorf("%s (%T) is not an integer", show(v), v)
}

// numbers reads a semantic's number fields through integer, checks each
// against its Section 4.4 type, and keeps the first error.
type numbers struct {
	s   Semantic
	err error
}

func (n *numbers) read(k string, lo, hi int64, typ string) int64 {
	v, err := integer(n.s.Fields[k])
	if err == nil && (v < lo || v > hi) {
		err = fmt.Errorf("%d is not a %s", v, typ)
	}
	if err != nil && n.err == nil {
		n.err = fmt.Errorf("%s.%s: %w", n.s.Kind, k, err)
	}
	return v
}

func (n *numbers) u32(k string) int64 { return n.read(k, 0, math.MaxUint32, "u32") }
func (n *numbers) i32(k string) int64 { return n.read(k, math.MinInt32, math.MaxInt32, "i32") }

// checkWord checks a vocabulary field against Vocab[list]. The value is a
// string, or a *string as constructors store nullable fields; null passes only
// when nullable.
func (s Semantic) checkWord(field, list string, nullable bool) error {
	var w string
	switch v := s.Fields[field].(type) {
	case string:
		w = v
	case *string:
		if v == nil {
			return s.nullWord(field, nullable)
		}
		w = *v
	case nil:
		return s.nullWord(field, nullable)
	default:
		return fmt.Errorf("%s.%s %s (%T) is not a string", s.Kind, field, show(v), v)
	}
	if !inVocab(list, w) {
		return fmt.Errorf("%s.%s %q not in vocabulary", s.Kind, field, w)
	}
	return nil
}

func (s Semantic) nullWord(field string, nullable bool) error {
	if nullable {
		return nil
	}
	return fmt.Errorf("%s.%s is null", s.Kind, field)
}

// twoArrays reports whether piles encodes as exactly two JSON arrays, built by
// a constructor or kept raw by UnmarshalJSON.
func twoArrays(piles any) bool {
	b, err := json.Marshal(piles)
	var two []json.RawMessage
	if err != nil || json.Unmarshal(b, &two) != nil || len(two) != 2 {
		return false
	}
	return two[0][0] == '[' && two[1][0] == '['
}

// Check enforces Section 7.3's field constraints and the vocabularies, for
// constructed and decoded semantics alike. A malformed value is an error, never
// a panic. Fields with neither a constraint nor a vocabulary (references, face,
// slot, bools) are not type-checked.
func (s Semantic) Check() error {
	want, ok := KindFields[s.Kind]
	if !ok {
		return fmt.Errorf("unknown kind %q", s.Kind)
	}
	if len(want) != len(s.Fields) {
		return fmt.Errorf("%s has %d fields, want %d", s.Kind, len(s.Fields), len(want))
	}
	for _, f := range want {
		if _, ok := s.Fields[f]; !ok {
			return fmt.Errorf("%s lacks %s", s.Kind, f)
		}
	}
	if err := s.checkConstraints(); err != nil {
		return err
	}
	for _, f := range []string{"purpose", "cost", "cost_kind", "action", "event", "destination"} {
		if _, ok := Vocab[s.Kind+"."+f]; ok {
			if err := s.checkWord(f, s.Kind+"."+f, false); err != nil {
				return err
			}
		}
	}
	return nil
}

func (s Semantic) checkConstraints() error {
	n := &numbers{s: s}
	var err error
	switch s.Kind {
	case "choose_target", "choose_cost_target", "select_object":
		lo, hi, sel := n.u32("minimum"), n.u32("maximum"), n.u32("selected_count")
		if !(lo <= hi && sel < hi) {
			err = fmt.Errorf("%s counts out of range", s.Kind)
		}
	case "choose_spell_mode":
		idx, count := n.u32("mode_index"), n.u32("mode_count")
		lo, hi, sel := n.u32("minimum"), n.u32("maximum"), n.u32("selected_count")
		if !(idx < count && lo <= hi && hi <= count && sel < hi) {
			err = fmt.Errorf("choose_spell_mode counts out of range")
		}
	case "choose_option":
		if !(n.u32("option_index") < n.u32("option_count")) {
			err = fmt.Errorf("choose_option option_index out of range")
		}
	case "choose_number":
		v, lo, hi := n.i32("value"), n.i32("minimum"), n.i32("maximum")
		if !(lo <= v && v <= hi) {
			err = fmt.Errorf("choose_number %d outside [%d,%d]", v, lo, hi)
		}
	case "order_pick":
		if !(n.u32("position") < n.u32("count")) {
			err = fmt.Errorf("order_pick position out of range")
		}
	case "arrange_card":
		if !(n.u32("card_index") < n.u32("card_count")) {
			err = fmt.Errorf("arrange_card card_index out of range")
		}
	case "choose_replacement":
		idx, count := n.u32("replacement_index"), n.u32("replacement_count")
		if !(2 <= count && idx < count) {
			err = fmt.Errorf("choose_replacement counts out of range")
		}
	case "distribute":
		if !(n.u32("amount") <= n.u32("remaining")) {
			err = fmt.Errorf("distribute amount exceeds remaining")
		}
	case "choose_pile":
		if n.u32("pile_index") > 1 || !twoArrays(s.Fields["piles"]) {
			err = fmt.Errorf("choose_pile needs pile_index 0 or 1 and exactly two piles")
		}
	case "choose_color":
		err = s.checkWord("color", "color", false)
	case "activate_mana_ability":
		err = s.checkWord("mana_choice", "mana_symbol", true)
	case "cast_spell", "choose_cast_method", "optional_cast":
		// Only cast_spell may leave method null, when choose_cast_method follows (Section 7.2).
		err = s.checkWord("method", "method", s.Kind == "cast_spell")
	}
	if n.err != nil {
		return n.err
	}
	return err
}
