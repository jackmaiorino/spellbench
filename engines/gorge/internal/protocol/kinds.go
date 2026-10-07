package protocol

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"reflect"
	"regexp"
	"slices"
	"strings"
)

type slot struct{ name, typ string }

// kindTable is Sections 7.2 and 7.3: each kind's fields in order, all required
// and no others, with the type Check enforces:
//   - R and T: an object reference (Section 5.1) and a target reference (5.2);
//   - item: order_pick.item, {"object": R} or {"trigger": {...}};
//   - [X]: an array of X;
//   - u32 and i32 (Section 4.4), bool, string, and seat (p0 or p1);
//   - snake: an open lowercase snake_case word (Section 4.4);
//   - any other name: a string from Vocab[name].
//
// A "|null" suffix also allows null.
var kindTable = map[string][]slot{
	"pass":                    {},
	"play_land":               {{"source", "R"}, {"face", "u32"}},
	"cast_spell":              {{"source", "R"}, {"method", "method|null"}},
	"activate_mana_ability":   {{"source", "R"}, {"ability_index", "u32"}, {"mana_choice", "mana_symbol|null"}, {"cost_target", "T|null"}},
	"activate_ability":        {{"source", "R"}, {"ability_index", "u32"}},
	"special_action":          {{"source", "R"}, {"action", "special_action.action"}},
	"choose_target":           {{"source", "R"}, {"slot", "u32"}, {"target", "T"}, {"selected_count", "u32"}, {"minimum", "u32"}, {"maximum", "u32"}},
	"finish_target_selection": {{"source", "R"}, {"slot", "u32"}, {"selected_count", "u32"}},
	"choose_cost_target":      {{"source", "R"}, {"cost_kind", "choose_cost_target.cost_kind"}, {"candidate", "R"}, {"selected_count", "u32"}, {"minimum", "u32"}, {"maximum", "u32"}},
	"choose_cast_method":      {{"source", "R"}, {"method", "method"}},
	"choose_spell_mode":       {{"source", "R"}, {"mode_index", "u32"}, {"mode_count", "u32"}, {"selected_count", "u32"}, {"minimum", "u32"}, {"maximum", "u32"}},
	"choose_option":           {{"source", "R|null"}, {"purpose", "choose_option.purpose"}, {"option_index", "u32"}, {"option_count", "u32"}, {"option_label", "string|null"}},
	"choose_color":            {{"source", "R|null"}, {"purpose", "choose_color.purpose"}, {"color", "color"}},
	"choose_number":           {{"source", "R|null"}, {"purpose", "choose_number.purpose"}, {"value", "i32"}, {"minimum", "i32"}, {"maximum", "i32"}},
	"choose_boolean":          {{"source", "R|null"}, {"purpose", "choose_boolean.purpose"}, {"value", "bool"}},
	"choose_name":             {{"source", "R|null"}, {"purpose", "choose_name.purpose"}, {"value", "string"}},
	"select_object":           {{"source", "R|null"}, {"purpose", "select_object.purpose"}, {"choice", "T"}, {"selected_count", "u32"}, {"minimum", "u32"}, {"maximum", "u32"}},
	"finish_selection":        {{"source", "R|null"}, {"purpose", "finish_selection.purpose"}, {"selected_count", "u32"}},
	"optional_cost":           {{"source", "R"}, {"cost", "optional_cost.cost"}, {"pay", "bool"}},
	"choose_cost_option":      {{"source", "R"}, {"choice", "snake"}},
	"optional_cast":           {{"card", "R"}, {"method", "method"}, {"cast_it", "bool"}},
	"mulligan":                {{"hand_size", "u32"}, {"mulligans_taken", "u32"}, {"keep", "bool"}},
	"order_pick":              {{"source", "R|null"}, {"purpose", "order_pick.purpose"}, {"item", "item"}, {"position", "u32"}, {"count", "u32"}},
	"arrange_card":            {{"source", "R|null"}, {"purpose", "arrange_card.purpose"}, {"card", "R"}, {"card_index", "u32"}, {"card_count", "u32"}, {"destination", "arrange_card.destination"}},
	"choose_replacement":      {{"affected", "T"}, {"event", "choose_replacement.event"}, {"replacement_source", "R|null"}, {"replacement_index", "u32"}, {"replacement_count", "u32"}},
	"choose_starting_player":  {{"player", "seat"}},
	"declare_attack":          {{"attacker", "R"}, {"defender", "T|null"}},
	"declare_block":           {{"blocker", "R"}, {"attacker", "R|null"}},
	"distribute":              {{"source", "R|null"}, {"purpose", "distribute.purpose"}, {"recipient", "T"}, {"amount", "u32"}, {"remaining", "u32"}},
	"choose_pile":             {{"source", "R|null"}, {"purpose", "choose_pile.purpose"}, {"pile_index", "u32"}, {"piles", "[[R]]"}},
}

// The nested objects, typed the same way.
var (
	refShape     = []slot{{"object_id", "string"}, {"card_name", "string|null"}, {"owner_seat", "seat"}, {"controller_seat", "seat"}, {"zone", "zone"}}
	triggerShape = []slot{{"source", "R|null"}, {"source_name", "string|null"}, {"ability_index", "u32|null"}, {"event_objects", "[R]"}, {"instance", "u32"}, {"label", "string|null"}}
	targetForms  = map[string]string{"player": "seat", "object": "R"}
	itemForms    = map[string]string{"object": "R", "trigger": "trigger"}
	snakeCase    = regexp.MustCompile(`^[a-z][a-z0-9_]*$`)
)

// KindFields is Section 7.2 and 7.3: each kind's fields, all required, no others.
var KindFields = func() map[string][]string {
	m := make(map[string][]string, len(kindTable))
	for kind, slots := range kindTable {
		m[kind] = make([]string, len(slots))
		for i, s := range slots {
			m[kind][i] = s.name
		}
	}
	return m
}()

var PriorityKinds = map[string]bool{"pass": true, "play_land": true, "cast_spell": true,
	"activate_mana_ability": true, "activate_ability": true, "special_action": true}

// Vocab is Sections 5.1, 6.10 and 7.4, keyed "<kind>.<field>" or a shared name.
var Vocab = map[string][]string{
	"zone":                         {"library", "hand", "battlefield", "graveyard", "stack", "exile", "command"},
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

// isNull reports whether v marshals as JSON null.
func isNull(v any) bool {
	if v == nil {
		return true
	}
	switch rv := reflect.ValueOf(v); rv.Kind() {
	case reflect.Pointer, reflect.Map, reflect.Slice, reflect.Interface:
		return rv.IsNil()
	}
	return false
}

// text reads a string field: a string, or a *string as constructors store
// nullable ones.
func text(v any) (string, error) {
	switch x := v.(type) {
	case string:
		return x, nil
	case *string:
		if x != nil {
			return *x, nil
		}
	}
	return "", fmt.Errorf("%s (%T) is not a string", show(v), v)
}

// asDecoded returns a reference, target, item or array as UnmarshalJSON-style
// values (maps, slices, strings, bools, nil and json.Number), so a built value
// is judged exactly as its JSON would be. A TargetRef or OrderItem must set
// exactly one member, since MarshalJSON would hide the other.
func asDecoded(v any) (any, error) {
	switch v.(type) {
	case map[string]any, []any:
		return v, nil
	}
	if isNull(v) {
		return nil, nil
	}
	if r, ok := v.(interface{ oneMember() bool }); ok && !r.oneMember() {
		return nil, fmt.Errorf("%T must set exactly one member", v)
	}
	b, ok := v.(json.RawMessage)
	if !ok {
		var err error
		if b, err = json.Marshal(v); err != nil {
			return nil, err
		}
	}
	d := json.NewDecoder(bytes.NewReader(b))
	d.UseNumber()
	var g any
	if err := d.Decode(&g); err != nil {
		return nil, err
	}
	return g, nil
}

// checkValue checks v against a kindTable type.
func checkValue(typ string, v any) error {
	base, nullable := strings.CutSuffix(typ, "|null")
	elem, isArray := strings.CutPrefix(base, "[")
	if isArray || base == "R" || base == "T" || base == "item" || base == "trigger" {
		var err error
		if v, err = asDecoded(v); err != nil {
			return err
		}
	}
	if isNull(v) {
		if nullable {
			return nil
		}
		return errors.New("is null")
	}
	switch {
	case isArray:
		a, ok := v.([]any)
		if !ok {
			return fmt.Errorf("%s is not an array", show(v))
		}
		for i, e := range a {
			if err := checkValue(strings.TrimSuffix(elem, "]"), e); err != nil {
				return fmt.Errorf("[%d]: %w", i, err)
			}
		}
		return nil
	case base == "R":
		return checkObject(v, refShape)
	case base == "trigger":
		return checkObject(v, triggerShape)
	case base == "T":
		return checkOneOf(v, targetForms)
	case base == "item":
		return checkOneOf(v, itemForms)
	case base == "u32":
		return inRange(v, 0, math.MaxUint32, base)
	case base == "i32":
		return inRange(v, math.MinInt32, math.MaxInt32, base)
	case base == "bool":
		if _, ok := v.(bool); !ok {
			return fmt.Errorf("%s is not a bool", show(v))
		}
		return nil
	}
	w, err := text(v)
	switch {
	case err != nil:
		return err
	case base == "string":
	case base == "seat":
		if w != "p0" && w != "p1" {
			return fmt.Errorf("%q is not a seat", w)
		}
	case base == "snake":
		if !snakeCase.MatchString(w) {
			return fmt.Errorf("%q is not a snake_case word", w)
		}
	case Vocab[base] == nil:
		return fmt.Errorf("unknown type %q", typ)
	case !inVocab(base, w):
		return fmt.Errorf("%q not in vocabulary %s", w, base)
	}
	return nil
}

func inRange(v any, lo, hi int64, typ string) error {
	n, err := integer(v)
	if err == nil && (n < lo || n > hi) {
		err = fmt.Errorf("%d is not a %s", n, typ)
	}
	return err
}

// checkObject checks that v is an object with exactly shape's fields.
func checkObject(v any, shape []slot) error {
	m, ok := v.(map[string]any)
	if !ok {
		return fmt.Errorf("%s is not an object", show(v))
	}
	if len(m) != len(shape) {
		return fmt.Errorf("%s has %d fields, want %d", show(v), len(m), len(shape))
	}
	for _, sl := range shape {
		fv, ok := m[sl.name]
		if !ok {
			return fmt.Errorf("%s lacks %s", show(v), sl.name)
		}
		if err := checkValue(sl.typ, fv); err != nil {
			return fmt.Errorf("%s: %w", sl.name, err)
		}
	}
	return nil
}

// checkOneOf checks that v is an object with exactly one of forms' members.
func checkOneOf(v any, forms map[string]string) error {
	m, ok := v.(map[string]any)
	if !ok || len(m) != 1 {
		return fmt.Errorf("%s is not an object with one member", show(v))
	}
	for k, fv := range m {
		typ, ok := forms[k]
		if !ok {
			return fmt.Errorf("unknown member %q", k)
		}
		if err := checkValue(typ, fv); err != nil {
			return fmt.Errorf("%s: %w", k, err)
		}
	}
	return nil
}

// Check enforces Sections 7.2 and 7.3 for constructed and decoded semantics
// alike: a known kind, exactly its fields, each field's kindTable type, the
// field constraints, and the static choose_name domain. A malformed value is
// an error, never a panic.
func (s Semantic) Check() error {
	slots, ok := kindTable[s.Kind]
	if !ok {
		return fmt.Errorf("unknown kind %q", s.Kind)
	}
	if len(slots) != len(s.Fields) {
		return fmt.Errorf("%s has %d fields, want %d", s.Kind, len(s.Fields), len(slots))
	}
	for _, sl := range slots {
		v, ok := s.Fields[sl.name]
		if !ok {
			return fmt.Errorf("%s lacks %s", s.Kind, sl.name)
		}
		if err := checkValue(sl.typ, v); err != nil {
			return fmt.Errorf("%s.%s: %w", s.Kind, sl.name, err)
		}
	}
	return s.checkConstraints()
}

// num and str read fields Check has already typed.
func (s Semantic) num(k string) int64  { n, _ := integer(s.Fields[k]); return n }
func (s Semantic) str(k string) string { w, _ := text(s.Fields[k]); return w }

// checkConstraints is Section 7.3's field constraints, plus the card_type
// domain of choose_name (Section 7.5 names the card types of Section 6.10).
func (s Semantic) checkConstraints() error {
	n := s.num
	switch s.Kind {
	case "choose_target", "choose_cost_target", "select_object":
		if sel, lo, hi := n("selected_count"), n("minimum"), n("maximum"); !(lo <= hi && sel < hi) {
			return fmt.Errorf("%s selected_count %d, minimum %d, maximum %d", s.Kind, sel, lo, hi)
		}
	case "choose_spell_mode":
		idx, count, sel, lo, hi := n("mode_index"), n("mode_count"), n("selected_count"), n("minimum"), n("maximum")
		if !(idx < count && lo <= hi && hi <= count && sel < hi) {
			return fmt.Errorf("choose_spell_mode mode_index %d, mode_count %d, selected_count %d, minimum %d, maximum %d", idx, count, sel, lo, hi)
		}
	case "choose_option":
		if idx, count := n("option_index"), n("option_count"); !(idx < count) {
			return fmt.Errorf("choose_option option_index %d, option_count %d", idx, count)
		}
	case "choose_number":
		if v, lo, hi := n("value"), n("minimum"), n("maximum"); !(lo <= v && v <= hi) {
			return fmt.Errorf("choose_number %d outside [%d,%d]", v, lo, hi)
		}
	case "order_pick":
		if pos, count := n("position"), n("count"); !(pos < count) {
			return fmt.Errorf("order_pick position %d, count %d", pos, count)
		}
	case "arrange_card":
		if idx, count := n("card_index"), n("card_count"); !(idx < count) {
			return fmt.Errorf("arrange_card card_index %d, card_count %d", idx, count)
		}
	case "choose_replacement":
		if idx, count := n("replacement_index"), n("replacement_count"); !(2 <= count && idx < count) {
			return fmt.Errorf("choose_replacement replacement_index %d, replacement_count %d", idx, count)
		}
	case "distribute":
		if amount, remaining := n("amount"), n("remaining"); !(amount <= remaining) {
			return fmt.Errorf("distribute amount %d, remaining %d", amount, remaining)
		}
	case "choose_pile":
		piles, _ := asDecoded(s.Fields["piles"])
		if a, _ := piles.([]any); !(n("pile_index") <= 1 && len(a) == 2) {
			return fmt.Errorf("choose_pile pile_index %d with %d piles", n("pile_index"), len(a))
		}
	case "choose_name":
		if s.str("purpose") == "card_type" && !inVocab("card_type", s.str("value")) {
			return fmt.Errorf("choose_name card_type %q is not a card type", s.str("value"))
		}
	}
	return nil
}
