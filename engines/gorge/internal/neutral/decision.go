package neutral

import (
	"encoding/json"
	"fmt"
	"maps"
	"slices"
	"strconv"
	"strings"

	"github.com/adams-shaun/gorge/cards"
	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/state"
	"github.com/adams-shaun/gorge/view"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/mapping"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/xview"
)

// noOp is the op of a candidate no gorge option stands for (a mana
// activation under engine autopay, or a family not translated yet). No plan
// ever matches it, so the agent's fallback answers such a decision.
var noOp = mapping.NativeOp{Op: "untranslated", Option: -1}

// native is the gorge decision the seat is answering, kept across the v2
// decisions that spend it: the substeps of a group, the later picks of a
// variable selection, or a cast's choose_cast_method.
type native struct {
	index   uint64
	key     string
	d       decision.Decision
	options map[string]int    // option key -> option index
	casts   map[string][]int  // priority: cast source v2 id -> its cast options
	names   map[string]string // priority: cast source v2 id -> its card name
	arrange *arrangement      // an arrangement's partition and order so far
	follow  map[string]decision.Decision
}

// arrangement is a scry-like native decision spent over 2n-1 v2 decisions.
type arrangement struct {
	cards  []string // looked-at card v2 ids, top first
	other  string   // the destination that is not the top
	dest   []string // the partition answered so far, per card
	placed []string // cards placed by ordering picks
	native []int    // dig: each card's option in the dig ask, -1 for none
	fixed  bool     // dig: gorge's engine moves the cards without asking
}

// Session translates one seat's decisions in one game.
type Session struct {
	B      *Builder
	seat   state.PlayerID
	next   uint64
	cur    *native
	last   *protocol.SeatDecision
	Counts map[string]int // untranslated decisions by first candidate kind (audit)
	// activated is the face ability index of each source's latest
	// activation, so its target ask can describe the ability.
	activated map[string]int
	// uses counts this turn's activations of each source, which gorge's
	// view carries as ActivatedThisTurn and its bot budgets: each activated
	// ability seen on the stack counts once for its source.
	uses     map[string]int32
	usesTurn uint32
	seen     map[string]bool // activated-ability stack ids already counted
}

func NewSession(reg *cards.Registry) *Session {
	return &Session{B: NewBuilder(reg), Counts: map[string]int{}, activated: map[string]int{}, uses: map[string]int32{}, seen: map[string]bool{}}
}

// Picked tells the session which candidate of its last decision the seat
// answered. Later decisions of the same native decision depend on it: an
// arrangement's ordering picks follow its partition, and a target ask
// describes the ability its source just activated.
func (s *Session) Picked(i int) {
	if s.last == nil || i < 0 || i >= len(s.last.Candidates) {
		return
	}
	sem := s.last.Candidates[i].Semantic
	switch sem.Kind {
	case "activate_ability":
		if src, err := ref(sem, "source"); err == nil {
			if o, ok := s.abilityOption(src, num(sem, "ability_index")); ok {
				s.activated[src.ObjectID] = o.Ability
			}
		}
	case "arrange_card":
		if s.cur != nil && s.cur.arrange != nil {
			s.cur.arrange.dest = append(s.cur.arrange.dest, str(sem, "destination"))
		}
	case "order_pick":
		if s.cur != nil && s.cur.arrange != nil {
			if it, err := field[protocol.OrderItem](sem, "item"); err == nil && it.Object != nil {
				s.cur.arrange.placed = append(s.cur.arrange.placed, it.Object.ObjectID)
			}
		}
	}
}

// Payload translates a seat decision into what gorge's agent reads from
// x_gorge_view_v1 on gorge's own engine: the view, the native decision and
// one op per candidate. A family it cannot translate yields ops no plan
// matches, so the agent falls back; it is never an error.
func (s *Session) Payload(sd *protocol.SeatDecision) (xview.Payload, error) {
	v, err := s.B.View(&sd.Observation)
	if err != nil {
		return xview.Payload{}, err
	}
	s.seat = v.Viewer
	s.last = sd
	if sd.Observation.Turn != s.usesTurn {
		s.usesTurn, s.uses = sd.Observation.Turn, map[string]int32{}
	}
	for _, e := range sd.Observation.Stack {
		if e.StackKind == "activated_ability" && e.Source != nil && !s.seen[e.ObjectID] {
			s.seen[e.ObjectID] = true
			s.uses[e.Source.ObjectID]++
		}
	}
	for pi := range v.Players {
		for ci := range v.Players[pi].Battlefield {
			cv := &v.Players[pi].Battlefield[ci]
			cv.ActivatedThisTurn = s.uses[s.B.IDs.V2(cv.ID)]
		}
	}
	ops, n, err := s.translate(sd, &v)
	if err != nil {
		return xview.Payload{}, err
	}
	if n == nil {
		ops = make([]mapping.NativeOp, len(sd.Candidates))
		for i := range ops {
			ops[i] = noOp
		}
		s.Counts[sd.Candidates[0].Semantic.Kind]++
		s.cur = nil
		s.next++
		return xview.Payload{Version: 1, NativeIndex: s.next, View: v, Decision: decision.Decision{Player: s.seat}, Ops: ops}, nil
	}
	s.cur = n
	d := n.d
	d.Player = s.seat
	return xview.Payload{Version: 1, NativeIndex: n.index, View: v, Decision: d, Ops: ops, Followups: n.follow}, nil
}

// open starts a new native decision under key.
func (s *Session) open(key string, d decision.Decision) *native {
	s.next++
	return &native{index: s.next, key: key, d: d, options: map[string]int{}}
}

// continuing reports whether the current native decision is the one under key.
func (s *Session) continuing(key string) *native {
	if s.cur != nil && s.cur.key == key {
		return s.cur
	}
	return nil
}

func (s *Session) translate(sd *protocol.SeatDecision, v *view.View) ([]mapping.NativeOp, *native, error) {
	first := sd.Candidates[0].Semantic
	if sd.Context.Kind == "priority" {
		return s.priority(sd, v)
	}
	switch first.Kind {
	case "choose_cast_method":
		return s.castMethod(sd)
	case "choose_target", "finish_target_selection":
		return s.targets(sd, v)
	case "select_object", "finish_selection":
		return s.selection(sd)
	case "choose_cost_target":
		return s.costTargets(sd)
	case "declare_attack":
		return s.attackers(sd, v)
	case "declare_block":
		return s.blockers(sd, v)
	case "choose_boolean", "optional_cast":
		return s.yesNo(sd)
	case "optional_cost":
		return s.optionalCost(sd)
	case "mulligan":
		return s.mulligan(sd)
	case "order_pick":
		return s.order(sd)
	case "arrange_card":
		return s.arrange(sd)
	case "choose_spell_mode":
		return s.modes(sd)
	case "choose_cost_option":
		return s.costOption(sd)
	case "choose_option":
		return s.option(sd)
	case "choose_number":
		return s.numbers(sd)
	case "choose_color":
		return s.colors(sd)
	}
	return nil, nil, nil
}

// --- semantic field readers ---

func field[T any](sem protocol.Semantic, name string) (T, error) {
	var out T
	raw, ok := sem.Fields[name].(json.RawMessage)
	if !ok {
		return out, fmt.Errorf("%s.%s is not an object", sem.Kind, name)
	}
	err := json.Unmarshal(raw, &out)
	return out, err
}

func ref(sem protocol.Semantic, name string) (protocol.ObjectRef, error) {
	return field[protocol.ObjectRef](sem, name)
}

// optRef reads a nullable object reference.
func optRef(sem protocol.Semantic, name string) (*protocol.ObjectRef, error) {
	if sem.Fields[name] == nil {
		return nil, nil
	}
	r, err := ref(sem, name)
	return &r, err
}

func target(sem protocol.Semantic, name string) (*protocol.TargetRef, error) {
	if sem.Fields[name] == nil {
		return nil, nil
	}
	t, err := field[protocol.TargetRef](sem, name)
	return &t, err
}

func num(sem protocol.Semantic, name string) int {
	n, _ := sem.Fields[name].(json.Number)
	i, _ := strconv.Atoi(string(n))
	return i
}

func str(sem protocol.Semantic, name string) string {
	s, _ := sem.Fields[name].(string)
	return s
}

func boolean(sem protocol.Semantic, name string) bool {
	b, _ := sem.Fields[name].(bool)
	return b
}

func targetKey(t protocol.TargetRef) string {
	if t.Player != nil {
		return "player:" + *t.Player
	}
	return t.Object.ObjectID
}

func name(r protocol.ObjectRef) string {
	if r.CardName == nil {
		return "a card"
	}
	return *r.CardName
}

// --- priority ---

// castModes maps a Section 7.4 method to gorge's cast option Mode.
var castModes = map[string]string{"normal": "", "flashback": "flashback", "escape": "escape", "madness": "madness",
	"plot": "plot_cast", "foretell": "foretell_cast", "adventure": "adventure_alt", "split_right": "split_alt",
	"mdfc_back": "modal_spell", "miracle": "miracle", "suspend": "suspend_cast"}

func (s *Session) priority(sd *protocol.SeatDecision, v *view.View) ([]mapping.NativeOp, *native, error) {
	n := s.open("priority", decision.Decision{Kind: decision.KPriority, Min: 1, Max: 1})
	n.casts, n.names = map[string][]int{}, map[string]string{}
	ops := make([]mapping.NativeOp, len(sd.Candidates))
	add := func(o decision.Option) int {
		o.Index = len(n.d.Options)
		n.d.Options = append(n.d.Options, o)
		return o.Index
	}
	for i, c := range sd.Candidates {
		sem := c.Semantic
		ops[i] = noOp
		switch sem.Kind {
		case "pass":
			ops[i] = mapping.NativeOp{Op: "choose", Option: add(decision.Option{Kind: "pass", Label: "Pass priority"})}
		case "play_land":
			src, err := ref(sem, "source")
			if err != nil {
				return nil, nil, err
			}
			o := decision.Option{Kind: "play_land", Label: "Play " + name(src), Obj: s.B.IDs.Of(src.ObjectID)}
			if num(sem, "face") == 1 {
				o.Mode = "modal_land"
			}
			ops[i] = mapping.NativeOp{Op: "choose", Option: add(o)}
		case "cast_spell":
			src, err := ref(sem, "source")
			if err != nil {
				return nil, nil, err
			}
			o := decision.Option{Kind: "cast", Label: "Cast " + name(src), Obj: s.B.IDs.Of(src.ObjectID)}
			method := str(sem, "method")
			switch {
			case sem.Fields["method"] == nil && src.Zone == "graveyard":
				o.Mode = "flashback" // a null method from a graveyard is the card's graveyard cast
			case sem.Fields["method"] == nil:
			case method == "alternative":
				o.AltCostIndex = 1
			default:
				mode, ok := castModes[method]
				if !ok {
					continue
				}
				o.Mode = mode
			}
			idx := add(o)
			n.casts[src.ObjectID], n.names[src.ObjectID] = []int{idx}, name(src)
			ops[i] = mapping.NativeOp{Op: "choose", Option: idx}
			if sem.Fields["method"] == nil && src.Zone == "hand" && s.altCost(sd, src) {
				// gorge offers the alternative cost as a cast of its own,
				// right after the plain cast; the method decision follows.
				alt := add(decision.Option{Kind: "cast", Label: "Cast " + name(src) + " (alternative cost)",
					Obj: o.Obj, AltCostIndex: 1})
				n.casts[src.ObjectID] = append(n.casts[src.ObjectID], alt)
				ops[i] = mapping.NativeOp{Op: "cast", Option: -1, Covers: []int{idx, alt}}
			}
		case "activate_ability":
			src, err := ref(sem, "source")
			if err != nil {
				return nil, nil, err
			}
			o, ok := s.abilityOption(src, num(sem, "ability_index"))
			if !ok {
				continue
			}
			ops[i] = mapping.NativeOp{Op: "choose", Option: add(o)}
		}
		// activate_mana_ability stays untranslated: the engine pays costs
		// itself (engine_autopay), so gorge's bot never floats mana here,
		// exactly as its auto-pay policies drop mana activations.
	}
	return ops, n, nil
}

// altCost reports whether src's own AlternativeCost static offers its cost
// now. Land Grant's condition (no land cards in hand) is read off the hand;
// any other condition is not offered.
func (s *Session) altCost(sd *protocol.SeatDecision, src protocol.ObjectRef) bool {
	f := s.B.face(src.CardName, false, nil)
	if f == nil {
		return false
	}
	for _, st := range f.Statics {
		if st.Mode != "AlternativeCost" || st.Params["ValidCard"] != "Card.Self" {
			continue
		}
		check := st.Params["CheckSVar"]
		if check == "" {
			return true
		}
		if !strings.HasPrefix(f.SVars[check], "Count$ValidHand Land") || st.Params["SVarCompare"] != "EQ0" {
			return false
		}
		for _, p := range sd.Observation.Players {
			if p.Seat != sd.ActingSeat {
				continue
			}
			for _, o := range p.Hand {
				if o.Characteristics != nil && slices.Contains(o.Characteristics.Types, "land") {
					return false
				}
			}
		}
		return true
	}
	return false
}

// abilityOption is gorge's "ability" option for a permanent's non-mana
// activated ability number idx (Section 7.2 order: printed non-mana
// abilities in face order).
func (s *Session) abilityOption(src protocol.ObjectRef, idx int) (decision.Option, bool) {
	f := s.B.face(src.CardName, false, nil)
	if f == nil {
		f = s.B.face(src.CardName, true, nil) // a token's ability
	}
	if f == nil {
		return decision.Option{}, false
	}
	k := 0
	for i, a := range f.Abilities {
		if a.Kind != "AB" || manaAbility(a) {
			continue
		}
		if k == idx {
			return decision.Option{Kind: "ability", Label: f.Name + ": " + a.Params["SpellDescription"],
				Obj: s.B.IDs.Of(src.ObjectID), Ability: i, Cost: a.Params["Cost"], Attach: a.API == "Attach"}, true
		}
		k++
	}
	return decision.Option{}, false
}

// manaAbility mirrors mapping's split of gorge's activated abilities.
func manaAbility(a *cards.SA) bool {
	if a.API != "Mana" && a.API != "ManaReflected" {
		return false
	}
	if v, ok := a.Params["Planeswalker"]; ok && strings.EqualFold(strings.TrimSpace(v), "True") {
		return false
	}
	return !strings.Contains(strings.ToUpper(a.Params["Cost"]), "LOYALTY")
}

// castMethod answers a cast's method from the priority plan: the method of
// the cast option the plan chose.
func (s *Session) castMethod(sd *protocol.SeatDecision) ([]mapping.NativeOp, *native, error) {
	n := s.continuing("priority")
	if n == nil {
		return nil, nil, nil
	}
	ops := make([]mapping.NativeOp, len(sd.Candidates))
	for i, c := range sd.Candidates {
		ops[i] = noOp
		src, err := ref(c.Semantic, "source")
		if err != nil {
			return nil, nil, err
		}
		method := str(c.Semantic, "method")
		opts, ok := n.casts[src.ObjectID]
		if !ok {
			// The spell moved to the stack under a new id: its cast is one
			// of those of the same card name, whichever the plan chose.
			for _, id := range slices.Sorted(maps.Keys(n.casts)) {
				if n.names[id] == name(src) {
					opts = append(opts, n.casts[id]...)
				}
			}
		}
		var covers []int
		for _, opt := range opts {
			o := n.d.Options[opt]
			want := "normal"
			switch {
			case o.AltCostIndex > 0:
				want = "alternative"
			case o.Mode != "":
				for m, mode := range castModes {
					if mode == o.Mode {
						want = m
					}
				}
			}
			if method == want {
				covers = append(covers, opt)
			}
		}
		if len(covers) > 0 {
			ops[i] = mapping.NativeOp{Op: "cast", Option: -1, Covers: covers}
		}
	}
	return ops, n, nil
}

// --- targets and selections ---

// pick is a target or object selection spent over one or more v2
// decisions: a fixed group, or variable picks each closed by a finish.
func (s *Session) pick(sd *protocol.SeatDecision, key string, d decision.Decision, choice func(protocol.Semantic) (*protocol.TargetRef, error),
	opt func(protocol.TargetRef) (decision.Option, error), finish string) ([]mapping.NativeOp, *native, error) {
	first := sd.Candidates[0].Semantic
	n := s.continuing(key)
	started := sd.Group.SubstepIndex > 0 || num(first, "selected_count") > 0
	if n == nil || !started {
		n = s.open(key, d)
		for _, c := range sd.Candidates {
			t, err := choice(c.Semantic)
			if err != nil {
				return nil, nil, err
			}
			if t == nil {
				continue
			}
			o, err := opt(*t)
			if err != nil {
				return nil, nil, err
			}
			o.Index = len(n.d.Options)
			n.options[targetKey(*t)] = o.Index
			n.d.Options = append(n.d.Options, o)
		}
	}
	ops := make([]mapping.NativeOp, len(sd.Candidates))
	for i, c := range sd.Candidates {
		ops[i] = noOp
		if c.Semantic.Kind == finish {
			ops[i] = mapping.NativeOp{Op: "finish", Option: -1}
			continue
		}
		t, err := choice(c.Semantic)
		if err != nil {
			return nil, nil, err
		}
		if t == nil {
			continue
		}
		if k, ok := n.options[targetKey(*t)]; ok {
			ops[i] = mapping.NativeOp{Op: "choose", Option: k}
		}
	}
	return ops, n, nil
}

// targetOption is gorge's target option for t.
func (s *Session) targetOption(v *view.View, t protocol.TargetRef) (decision.Option, error) {
	if t.Player != nil {
		p, err := Seat(*t.Player)
		return decision.Option{Kind: "player", Label: *t.Player, Player: p, Controller: p}, err
	}
	r := *t.Object
	c, err := Seat(r.ControllerSeat)
	if err != nil {
		return decision.Option{}, err
	}
	kind := "permanent"
	switch r.Zone {
	case "stack":
		kind = "spell"
	case "graveyard", "exile", "hand", "library":
		kind = "card"
	}
	return decision.Option{Kind: kind, Label: name(r), Obj: s.B.IDs.Of(r.ObjectID), Player: c, Controller: c}, nil
}

func (s *Session) targets(sd *protocol.SeatDecision, v *view.View) ([]mapping.NativeOp, *native, error) {
	first := sd.Candidates[0].Semantic
	src, err := ref(first, "source")
	if err != nil {
		return nil, nil, err
	}
	slot := num(first, "slot")
	lo, hi := num(first, "minimum"), num(first, "maximum")
	if first.Kind == "finish_target_selection" {
		for _, c := range sd.Candidates {
			if c.Semantic.Kind == "choose_target" {
				lo, hi = num(c.Semantic, "minimum"), num(c.Semantic, "maximum")
				break
			}
		}
	}
	d := decision.Decision{Kind: decision.KTarget, Min: lo, Max: hi, Source: s.B.IDs.Of(src.ObjectID),
		Prompt: "Choose a target", TargetEffect: s.targetEffect(&sd.Observation, src, slot)}
	key := fmt.Sprintf("target|%s|%d", src.ObjectID, slot)
	return s.pick(sd, key, d, func(sem protocol.Semantic) (*protocol.TargetRef, error) {
		if sem.Kind != "choose_target" {
			return nil, nil
		}
		return target(sem, "target")
	}, func(t protocol.TargetRef) (decision.Option, error) { return s.targetOption(v, t) }, "finish_target_selection")
}

// selectKinds maps a select_object purpose to gorge's KChoose option kind.
var selectKinds = map[string]string{"discard": "discard", "sacrifice": "sacrifice", "exile": "exile",
	"search": "search", "return_to_hand": "returncost", "tap": "tapcost", "untap": "untap", "keep": "keep",
	"delve": "exile", "put_into_hand": "dig", "reveal": "reveal", "legend_rule": "keep"}

func (s *Session) selection(sd *protocol.SeatDecision) ([]mapping.NativeOp, *native, error) {
	first := sd.Candidates[0].Semantic
	purpose := str(first, "purpose")
	src, err := optRef(first, "source")
	if err != nil {
		return nil, nil, err
	}
	if purpose == "other" && src != nil {
		if sa := s.chainSA(*src, func(sa *cards.SA) bool {
			return sa.API == "ChangeZone" && strings.EqualFold(sa.Params["Origin"], "Hand") && strings.EqualFold(sa.Params["Destination"], "Library")
		}); sa != nil {
			return s.handToLibrary(sd, *src, sa)
		}
	}
	kind, ok := selectKinds[purpose]
	if !ok {
		return nil, nil, nil
	}
	lo, hi := num(first, "minimum"), num(first, "maximum")
	for _, c := range sd.Candidates {
		if c.Semantic.Kind == "select_object" {
			lo, hi = num(c.Semantic, "minimum"), num(c.Semantic, "maximum")
			break
		}
	}
	d := decision.Decision{Kind: decision.KChoose, Min: lo, Max: hi, Prompt: "Choose " + purpose}
	key := "select|" + purpose
	if src != nil {
		d.Source = s.B.IDs.Of(src.ObjectID)
		key += "|" + src.ObjectID
		if purpose == "discard" {
			d.Kind = decision.KModes // gorge asks an effect's discard as a modal pick
		}
	}
	return s.pick(sd, key, d, func(sem protocol.Semantic) (*protocol.TargetRef, error) {
		if sem.Kind != "select_object" {
			return nil, nil
		}
		return target(sem, "choice")
	}, func(t protocol.TargetRef) (decision.Option, error) {
		if t.Object == nil {
			p, err := Seat(*t.Player)
			return decision.Option{Kind: kind, Label: *t.Player, Player: p}, err
		}
		return decision.Option{Kind: kind, Label: name(*t.Object), Obj: s.B.IDs.Of(t.Object.ObjectID)}, nil
	}, "finish_selection")
}

// chainSA is the first ability in the source spell's chain (its spell
// ability and SubAbilities) that want accepts, or nil.
func (s *Session) chainSA(src protocol.ObjectRef, want func(*cards.SA) bool) *cards.SA {
	f := s.B.face(src.CardName, false, nil)
	if f == nil {
		return nil
	}
	for _, sa := range chain(f, f.SpellAbility()) {
		if want(sa) {
			return sa
		}
	}
	return nil
}

// chain is root and the SubAbilities it leads to, in order.
func chain(f *cards.Face, root *cards.SA) []*cards.SA {
	var out []*cards.SA
	for sa := root; sa != nil && len(out) < 16; {
		out = append(out, sa)
		sub := sa.Params["SubAbility"]
		if sub == "" {
			break
		}
		sa = cards.ResolveSVar(f.SVars, sub)
	}
	return out
}

// handToLibrary is Brainstorm's "put cards from your hand on top": gorge's
// KChoose of hand_move options in hand order, whose answer order is the
// order the cards go on top. v2 selects the cards (select_object), then
// orders them (order_pick library_top).
func (s *Session) handToLibrary(sd *protocol.SeatDecision, src protocol.ObjectRef, sa *cards.SA) ([]mapping.NativeOp, *native, error) {
	first := sd.Candidates[0].Semantic
	key := "handmove|" + src.ObjectID
	n := s.continuing(key)
	if n == nil || (sd.Group.SubstepIndex == 0 && num(first, "selected_count") == 0) {
		lo, hi := num(first, "minimum"), num(first, "maximum")
		n = s.open(key, decision.Decision{Kind: decision.KChoose, Min: lo, Max: hi, Source: s.B.IDs.Of(src.ObjectID),
			Prompt: "Put cards on top", ResumeSA: sa})
		offered := map[string]bool{}
		for _, c := range sd.Candidates {
			if t, err := target(c.Semantic, "choice"); err == nil && t != nil && t.Object != nil {
				offered[t.Object.ObjectID] = true
			}
		}
		for _, p := range sd.Observation.Players {
			if p.Seat != sd.ActingSeat {
				continue
			}
			for _, o := range p.Hand {
				if offered[o.ObjectID] {
					n.options[o.ObjectID] = len(n.d.Options)
					n.d.Options = append(n.d.Options, decision.Option{Index: len(n.d.Options), Kind: "hand_move",
						Label: name(o.ObjectRef), Obj: s.B.IDs.Of(o.ObjectID), Player: s.seat})
				}
			}
		}
	}
	ops := make([]mapping.NativeOp, len(sd.Candidates))
	for i, c := range sd.Candidates {
		ops[i] = noOp
		if c.Semantic.Kind != "select_object" {
			continue
		}
		t, err := target(c.Semantic, "choice")
		if err != nil {
			return nil, nil, err
		}
		if t != nil && t.Object != nil {
			if k, ok := n.options[t.Object.ObjectID]; ok {
				ops[i] = mapping.NativeOp{Op: "choose", Option: k}
			}
		}
	}
	return ops, n, nil
}

// costKinds maps choose_cost_target's cost_kind to gorge's cost option kind.
var costKinds = map[string]string{"sacrifice": "sacrifice", "discard": "discard", "tap": "tapcost",
	"return_to_hand": "returncost", "exile": "exile_cost"}

func (s *Session) costTargets(sd *protocol.SeatDecision) ([]mapping.NativeOp, *native, error) {
	first := sd.Candidates[0].Semantic
	kind, ok := costKinds[str(first, "cost_kind")]
	if !ok {
		return nil, nil, nil
	}
	src, err := ref(first, "source")
	if err != nil {
		return nil, nil, err
	}
	d := decision.Decision{Kind: decision.KChoose, Min: num(first, "minimum"), Max: num(first, "maximum"),
		Source: s.B.IDs.Of(src.ObjectID), Prompt: "Pay " + kind}
	return s.pick(sd, "cost|"+src.ObjectID+"|"+kind, d, func(sem protocol.Semantic) (*protocol.TargetRef, error) {
		r, err := ref(sem, "candidate")
		if err != nil {
			return nil, err
		}
		t := protocol.ObjectTarget(r)
		return &t, nil
	}, func(t protocol.TargetRef) (decision.Option, error) {
		return decision.Option{Kind: kind, Label: name(*t.Object), Obj: s.B.IDs.Of(t.Object.ObjectID)}, nil
	}, "")
}

// --- combat ---

func hasKeyword(cv view.CardView, k string) bool {
	return slices.ContainsFunc(cv.Keywords, func(l string) bool { return strings.EqualFold(cards.KeywordHead(l), k) })
}

func battlefield(v *view.View, seat state.PlayerID) []view.CardView {
	for _, p := range v.Players {
		if p.ID == seat {
			return p.Battlefield
		}
	}
	return nil
}

func isCreature(cv view.CardView) bool {
	return slices.ContainsFunc(strings.Fields(cv.Types), func(t string) bool { return strings.EqualFold(t, "Creature") })
}

// attackers builds gorge's whole declaration at the group's first substep:
// one option per creature the seat could attack with and per opposing
// player. The v2 group asks one creature per substep; each substep's
// candidates map onto that creature's options.
func (s *Session) attackers(sd *protocol.SeatDecision, v *view.View) ([]mapping.NativeOp, *native, error) {
	opp := 1 - s.seat
	n := s.continuing("attack")
	if n == nil || sd.Group.SubstepIndex == 0 {
		n = s.open("attack", decision.Decision{Kind: decision.KAttackers, Min: 0, Prompt: "declare attackers"})
		units := map[string]bool{}
		addUnit := func(id string, label string) {
			if units[id] {
				return
			}
			units[id] = true
			o := decision.Option{Index: len(n.d.Options), Kind: "attacker", Label: "Attack with " + label,
				Obj: s.B.IDs.Of(id), Player: opp}
			n.options[id] = o.Index
			n.d.Options = append(n.d.Options, o)
		}
		first, err := ref(sd.Candidates[0].Semantic, "attacker")
		if err != nil {
			return nil, nil, err
		}
		addUnit(first.ObjectID, name(first))
		for _, p := range sd.Observation.Players {
			if p.Seat != sd.ActingSeat {
				continue
			}
			for _, r := range p.Battlefield {
				cv, ok := findCard(battlefield(v, s.seat), s.B.IDs.Of(r.ObjectID))
				if !ok || !isCreature(cv) || cv.Tapped || hasKeyword(cv, "Defender") || (cv.SummonSick && !hasKeyword(cv, "Haste")) {
					continue
				}
				addUnit(r.ObjectID, cv.Name)
			}
		}
		n.d.Max = len(n.d.Options)
	}
	ops := make([]mapping.NativeOp, len(sd.Candidates))
	for i, c := range sd.Candidates {
		ops[i] = noOp
		a, err := ref(c.Semantic, "attacker")
		if err != nil {
			return nil, nil, err
		}
		k, ok := n.options[a.ObjectID]
		if !ok {
			continue
		}
		def, err := target(c.Semantic, "defender")
		if err != nil {
			return nil, nil, err
		}
		unit := s.B.IDs.Of(a.ObjectID)
		switch {
		case def == nil:
			ops[i] = mapping.NativeOp{Op: "none", Option: -1, Unit: unit}
		case def.Player != nil:
			ops[i] = mapping.NativeOp{Op: "choose", Option: k, Unit: unit}
		}
	}
	return ops, n, nil
}

func findCard(cvs []view.CardView, id state.ObjID) (view.CardView, bool) {
	for _, cv := range cvs {
		if cv.ID == id {
			return cv, true
		}
	}
	return view.CardView{}, false
}

// protected reports whether attacker a has protection from a blocker of
// these colors (Guardian of the Guildpact's "from monocolored", or from a
// color), read off its Forge keyword lines.
func protected(a view.CardView, colors []string) bool {
	for _, k := range a.Keywords {
		k = strings.ToLower(k)
		if !strings.HasPrefix(k, "protection") {
			continue
		}
		if strings.Contains(k, "monocolor") && len(colors) == 1 {
			return true
		}
		for _, c := range colors {
			if strings.Contains(k, "card."+c) || strings.HasSuffix(k, " "+c) || strings.HasSuffix(k, ":"+c) {
				return true
			}
		}
	}
	return false
}

// blockers builds gorge's whole block declaration at the group's first
// substep: one option per (untapped creature, attacker it could block).
func (s *Session) blockers(sd *protocol.SeatDecision, v *view.View) ([]mapping.NativeOp, *native, error) {
	n := s.continuing("block")
	if n == nil || sd.Group.SubstepIndex == 0 {
		n = s.open("block", decision.Decision{Kind: decision.KBlockers, Min: 0, Prompt: "declare blockers"})
		var attackers []view.CardView
		for _, cv := range battlefield(v, 1-s.seat) {
			if cv.Attacking {
				attackers = append(attackers, cv)
			}
		}
		colors := map[string][]string{}
		for _, p := range sd.Observation.Players {
			for _, o := range p.Battlefield {
				if o.Characteristics != nil {
					colors[o.ObjectID] = o.Characteristics.Colors
				}
			}
		}
		first, err := ref(sd.Candidates[0].Semantic, "blocker")
		if err != nil {
			return nil, nil, err
		}
		for _, b := range battlefield(v, s.seat) {
			if !isCreature(b) || (b.Tapped && b.ID != s.B.IDs.Of(first.ObjectID)) {
				continue
			}
			for _, a := range attackers {
				if hasKeyword(a, "Flying") && !hasKeyword(b, "Flying") && !hasKeyword(b, "Reach") {
					continue
				}
				if protected(a, colors[s.B.IDs.V2(b.ID)]) {
					continue
				}
				o := decision.Option{Index: len(n.d.Options), Kind: "block", Label: b.Name + " blocks " + a.Name,
					Obj: b.ID, Attacker: a.ID, Player: s.seat, Group: fmt.Sprintf("blocker:%d", b.ID)}
				if hasKeyword(a, "Menace") {
					o.MinBlockers = 2
				}
				n.options[s.B.IDs.V2(b.ID)+">"+s.B.IDs.V2(a.ID)] = o.Index
				n.d.Options = append(n.d.Options, o)
			}
		}
		n.d.Max = len(n.d.Options)
	}
	ops := make([]mapping.NativeOp, len(sd.Candidates))
	for i, c := range sd.Candidates {
		ops[i] = noOp
		b, err := ref(c.Semantic, "blocker")
		if err != nil {
			return nil, nil, err
		}
		a, err := optRef(c.Semantic, "attacker")
		if err != nil {
			return nil, nil, err
		}
		unit := s.B.IDs.Of(b.ObjectID)
		if a == nil {
			ops[i] = mapping.NativeOp{Op: "none", Option: -1, Unit: unit}
			continue
		}
		if k, ok := n.options[b.ObjectID+">"+a.ObjectID]; ok {
			ops[i] = mapping.NativeOp{Op: "choose", Option: k, Unit: unit}
		}
	}
	return ops, n, nil
}

// --- small choices ---

// yesNo is gorge's two-option ask for a yes/no choice: "yes" then "no", in
// the decision kind gorge poses for that purpose.
func (s *Session) yesNo(sd *protocol.SeatDecision) ([]mapping.NativeOp, *native, error) {
	first := sd.Candidates[0].Semantic
	d := decision.Decision{Kind: decision.KChoose, Min: 1, Max: 1, Prompt: "Choose",
		Options: []decision.Option{{Index: 0, Kind: "yes", Label: "Yes"}, {Index: 1, Kind: "no", Label: "No"}}}
	field := "value"
	switch {
	case first.Kind == "optional_cast":
		field, d.Kind, d.ResumeKind = "cast_it", decision.KTriggerOptional, str(first, "method")
	case first.Kind == "optional_cost":
		field = "pay"
		d.Options[0].Kind, d.Options[1].Kind = "trigger_cost_pay", "trigger_cost_decline"
	case str(first, "purpose") == "optional_trigger" || str(first, "purpose") == "may_ability":
		d.Kind = decision.KTriggerOptional
	case str(first, "purpose") == "optional_replacement":
		d.Kind = decision.KReplacement
		d.Options[0].Kind, d.Options[1].Kind = "madness_exile", "madness_graveyard"
	}
	n := s.open("yesno", d)
	ops := make([]mapping.NativeOp, len(sd.Candidates))
	for i, c := range sd.Candidates {
		ops[i] = noOp
		if c.Semantic.Kind != first.Kind {
			continue // a mana activation offered beside a resolution payment
		}
		k := 1
		if boolean(c.Semantic, field) {
			k = 0
		}
		ops[i] = mapping.NativeOp{Op: "choose", Option: k}
	}
	return ops, n, nil
}

// optionalCost is gorge's unless-cost ask (pay or decline) for
// unless_payment, and its pay-or-decline ask for other optional costs.
func (s *Session) optionalCost(sd *protocol.SeatDecision) ([]mapping.NativeOp, *native, error) {
	first := sd.Candidates[0].Semantic
	for _, c := range sd.Candidates {
		if c.Semantic.Kind == "optional_cost" {
			first = c.Semantic
			break
		}
	}
	if str(first, "cost") != "unless_payment" {
		return s.yesNo(sd)
	}
	n := s.open("unless", decision.Decision{Kind: decision.KModes, Min: 1, Max: 1, ResumeKind: "unless_pay",
		Prompt: "Pay the cost?", Options: []decision.Option{
			{Index: 0, Kind: "mode", Label: "Pay", Mode: decision.ModeUnlessPay},
			{Index: 1, Kind: "mode", Label: "Decline", Mode: decision.ModeUnlessDecline}}})
	ops := make([]mapping.NativeOp, len(sd.Candidates))
	for i, c := range sd.Candidates {
		ops[i] = noOp
		if c.Semantic.Kind != "optional_cost" {
			continue
		}
		k := 1
		if boolean(c.Semantic, "pay") {
			k = 0
		}
		ops[i] = mapping.NativeOp{Op: "choose", Option: k}
	}
	return ops, n, nil
}

func (s *Session) mulligan(sd *protocol.SeatDecision) ([]mapping.NativeOp, *native, error) {
	n := s.open("mulligan", decision.Decision{Kind: decision.KMulligan, Min: 1, Max: 1, Prompt: "Keep or mulligan?",
		Options: []decision.Option{{Index: 0, Kind: "keep", Label: "Keep"}, {Index: 1, Kind: "mulligan", Label: "Mulligan"}}})
	ops := make([]mapping.NativeOp, len(sd.Candidates))
	for i, c := range sd.Candidates {
		k := 1
		if boolean(c.Semantic, "keep") {
			k = 0
		}
		ops[i] = mapping.NativeOp{Op: "choose", Option: k}
	}
	return ops, n, nil
}

func (s *Session) modes(sd *protocol.SeatDecision) ([]mapping.NativeOp, *native, error) {
	first := sd.Candidates[0].Semantic
	src, err := ref(first, "source")
	if err != nil {
		return nil, nil, err
	}
	key := "modes|" + src.ObjectID
	n := s.continuing(key)
	if n == nil || sd.Group.SubstepIndex == 0 {
		// gorge offers only the eligible modes, in printed order.
		n = s.open(key, decision.Decision{Kind: decision.KModes, Min: num(first, "minimum"), Max: num(first, "maximum"),
			Source: s.B.IDs.Of(src.ObjectID), Prompt: "Choose a mode"})
		var modes []int
		for _, c := range sd.Candidates {
			modes = append(modes, num(c.Semantic, "mode_index"))
		}
		slices.Sort(modes)
		for _, k := range slices.Compact(modes) {
			n.options[strconv.Itoa(k)] = len(n.d.Options)
			n.d.Options = append(n.d.Options, decision.Option{Index: len(n.d.Options), Kind: "mode", Label: fmt.Sprintf("Mode %d", k+1)})
		}
	}
	ops := make([]mapping.NativeOp, len(sd.Candidates))
	for i, c := range sd.Candidates {
		ops[i] = noOp
		if k, ok := n.options[strconv.Itoa(num(c.Semantic, "mode_index"))]; ok {
			ops[i] = mapping.NativeOp{Op: "choose", Option: k}
		}
	}
	return ops, n, nil
}

// costOption is a choice between a spell's optional costs (Highway
// Robbery: discard a card or sacrifice a land). gorge poses the same choice
// as the modes of the spell's GenericChoice, in printed order; each
// candidate is matched to the printed choice whose cost names its words.
func (s *Session) costOption(sd *protocol.SeatDecision) ([]mapping.NativeOp, *native, error) {
	src, err := ref(sd.Candidates[0].Semantic, "source")
	if err != nil {
		return nil, nil, err
	}
	var printed []string
	if f := s.B.face(src.CardName, false, nil); f != nil {
		if root := f.SpellAbility(); root != nil && root.API == "GenericChoice" {
			for _, c := range strings.Split(root.Params["Choices"], ",") {
				cost := ""
				if sa := cards.ResolveSVar(f.SVars, strings.TrimSpace(c)); sa != nil {
					cost = strings.ToLower(sa.Params["UnlessCost"] + " " + sa.Params["Cost"])
				}
				printed = append(printed, cost)
			}
		}
	}
	rank := func(choice string) int {
		for i, cost := range printed {
			for _, w := range strings.Split(choice, "_") {
				w = strings.TrimSuffix(strings.Replace(w, "sacrifice", "sac", 1), "s")
				if len(w) > 2 && strings.Contains(cost, w) {
					return i
				}
			}
		}
		return len(printed)
	}
	choices := make([]string, len(sd.Candidates))
	for i, c := range sd.Candidates {
		choices[i] = str(c.Semantic, "choice")
	}
	order := slices.Clone(choices)
	slices.SortStableFunc(order, func(a, b string) int { return rank(a) - rank(b) })
	n := s.open("costoption|"+src.ObjectID, decision.Decision{Kind: decision.KModes, Min: 1, Max: 1,
		Source: s.B.IDs.Of(src.ObjectID), Prompt: "Choose a cost"})
	for _, c := range order {
		n.d.Options = append(n.d.Options, decision.Option{Index: len(n.d.Options), Kind: "mode", Label: c})
	}
	ops := make([]mapping.NativeOp, len(sd.Candidates))
	for i, c := range choices {
		ops[i] = mapping.NativeOp{Op: "choose", Option: slices.Index(order, c)}
	}
	return ops, n, nil
}

// option is an effect's choice among numbered options (Winding Way's
// creature or land). gorge offers them in the same printed order and takes
// the first, whether it poses them as a type choice or as modes.
func (s *Session) option(sd *protocol.SeatDecision) ([]mapping.NativeOp, *native, error) {
	first := sd.Candidates[0].Semantic
	src, err := optRef(first, "source")
	if err != nil {
		return nil, nil, err
	}
	d := decision.Decision{Kind: decision.KModes, Min: 1, Max: 1, Prompt: "Choose an option"}
	kind := "mode"
	var labels []string
	if src != nil {
		d.Source = s.B.IDs.Of(src.ObjectID)
		if sa := s.chainSA(*src, func(sa *cards.SA) bool { return sa.API == "ChooseType" }); sa != nil {
			d.Kind, kind = decision.KChoose, "type"
			labels = strings.Split(sa.Params["ValidTypes"], ",")
		}
	}
	var idx []int
	for _, c := range sd.Candidates {
		idx = append(idx, num(c.Semantic, "option_index"))
	}
	slices.Sort(idx)
	idx = slices.Compact(idx)
	n := s.open("option", d)
	for _, k := range idx {
		label := fmt.Sprintf("Option %d", k+1)
		if k < len(labels) {
			label = strings.TrimSpace(labels[k])
		}
		n.d.Options = append(n.d.Options, decision.Option{Index: len(n.d.Options), Kind: kind, Label: label})
	}
	ops := make([]mapping.NativeOp, len(sd.Candidates))
	for i, c := range sd.Candidates {
		ops[i] = mapping.NativeOp{Op: "choose", Option: slices.Index(idx, num(c.Semantic, "option_index"))}
	}
	return ops, n, nil
}

func (s *Session) numbers(sd *protocol.SeatDecision) ([]mapping.NativeOp, *native, error) {
	first := sd.Candidates[0].Semantic
	kind := "number"
	if str(first, "purpose") == "x_value" {
		kind = "x"
	}
	n := s.open("number", decision.Decision{Kind: decision.KChoose, Min: 1, Max: 1, Prompt: "Choose a number"})
	ops := make([]mapping.NativeOp, len(sd.Candidates))
	for i, c := range sd.Candidates {
		val := num(c.Semantic, "value")
		n.d.Options = append(n.d.Options, decision.Option{Index: i, Kind: kind, Label: strconv.Itoa(val), Value: val})
		ops[i] = mapping.NativeOp{Op: "choose", Option: i}
	}
	return ops, n, nil
}

var colorSymbols = map[string]string{"white": "W", "blue": "U", "black": "B", "red": "R", "green": "G"}

func (s *Session) colors(sd *protocol.SeatDecision) ([]mapping.NativeOp, *native, error) {
	n := s.open("color", decision.Decision{Kind: decision.KChoose, Min: 1, Max: 1, Prompt: "Choose a color"})
	ops := make([]mapping.NativeOp, len(sd.Candidates))
	for i, c := range sd.Candidates {
		color := str(c.Semantic, "color")
		n.d.Options = append(n.d.Options, decision.Option{Index: i, Kind: "color", Label: title(color),
			ManaSymbol: colorSymbols[color]})
		ops[i] = mapping.NativeOp{Op: "choose", Option: i}
	}
	return ops, n, nil
}

// --- target effects ---

// targetEffect describes what a target ask's ability does, as gorge's
// engine does for its own target asks: the API of the slot-th targeting
// ability in the source's chain, its removal shape, and a literal or X
// damage amount.
func (s *Session) targetEffect(o *protocol.Observation, src protocol.ObjectRef, slot int) *decision.TargetEffect {
	var entry *protocol.StackEntry
	for i := range o.Stack {
		if o.Stack[i].ObjectID == src.ObjectID {
			entry = &o.Stack[i]
		}
	}
	var f *cards.Face
	var root *cards.SA
	var x *uint32
	switch {
	case entry != nil && entry.StackKind == "spell":
		if f = s.B.face(entry.CardName, false, nil); f != nil {
			root = f.SpellAbility()
		}
		x = entry.XValue
	case src.Zone == "battlefield":
		// An ability being activated is announced from its permanent.
		i, ok := s.activated[src.ObjectID]
		if f = s.B.face(src.CardName, false, nil); f != nil && ok && i < len(f.Abilities) {
			root = f.Abilities[i]
		}
	}
	if root == nil {
		return nil
	}
	var sa *cards.SA
	k := 0
	for _, c := range chain(f, root) {
		if _, ok := c.Params["ValidTgts"]; ok {
			if k == slot {
				sa = c
				break
			}
			k++
		}
	}
	if sa == nil {
		return nil
	}
	out := &decision.TargetEffect{API: sa.API, Removal: removal(sa)}
	if sa.API == "DealDamage" || sa.API == "DamageAll" {
		out.Damage = &decision.DamageEffect{}
		raw := strings.TrimSpace(sa.Params["NumDmg"])
		if n, err := strconv.Atoi(raw); err == nil && n >= 0 {
			out.Damage.Amount = &n
		} else if raw == "X" && x != nil {
			n := int(*x)
			out.Damage.Amount = &n
		}
	}
	return out
}

// removal is gorge's targetRemoval (rules/stack.go), which is unexported.
func removal(sa *cards.SA) *decision.RemovalEffect {
	switch sa.API {
	case "Destroy", "DestroyAll":
		return &decision.RemovalEffect{Kind: "destroy"}
	case "Sacrifice", "SacrificeAll":
		return &decision.RemovalEffect{Kind: "sacrifice"}
	case "ChangeZone", "ChangeZoneAll":
		dest := strings.ToLower(strings.TrimSpace(sa.Params["Destination"]))
		kind := map[string]string{"exile": "exile", "hand": "bounce", "graveyard": "graveyard", "library": "library", "command": "command"}[dest]
		if kind == "" {
			return nil
		}
		return &decision.RemovalEffect{Kind: kind, Destination: dest}
	}
	return nil
}

// --- ordering and arrangement ---

// order is an order_pick block gorge asks as one ordered answer: trigger
// order, or the cards a mulligan puts on the bottom.
func (s *Session) order(sd *protocol.SeatDecision) ([]mapping.NativeOp, *native, error) {
	first := sd.Candidates[0].Semantic
	purpose := str(first, "purpose")
	if purpose == "arrangement" {
		return s.arrange(sd)
	}
	switch purpose {
	case "library_top", "other":
		return s.placed(sd)
	}
	var kind decision.Kind
	var optKind string
	switch purpose {
	case "triggers":
		kind, optKind = decision.KTriggerOrder, "trigger"
	case "mulligan_bottom":
		kind, optKind = decision.KMulligan, "bottom"
	default:
		return nil, nil, nil
	}
	key := "order|" + purpose
	n := s.continuing(key)
	pos := num(first, "position")
	if n == nil || pos == 0 {
		count := num(first, "count")
		n = s.open(key, decision.Decision{Kind: kind, Min: count, Max: count, Prompt: "Order"})
		for _, c := range sd.Candidates {
			it, err := field[json.RawMessage](c.Semantic, "item")
			if err != nil {
				return nil, nil, err
			}
			o := decision.Option{Index: len(n.d.Options), Kind: optKind, Label: "item"}
			var obj struct {
				Object *protocol.ObjectRef `json:"object"`
			}
			if json.Unmarshal(it, &obj) == nil && obj.Object != nil {
				o.Obj, o.Label = s.B.IDs.Of(obj.Object.ObjectID), name(*obj.Object)
			}
			n.options[string(it)] = o.Index
			n.d.Options = append(n.d.Options, o)
		}
		if kind == decision.KTriggerOrder {
			n.d.Min, n.d.Max = len(n.d.Options), len(n.d.Options)
		}
	}
	ops := make([]mapping.NativeOp, len(sd.Candidates))
	for i, c := range sd.Candidates {
		ops[i] = noOp
		it, err := field[json.RawMessage](c.Semantic, "item")
		if err != nil {
			return nil, nil, err
		}
		if k, ok := n.options[string(it)]; ok {
			ops[i] = mapping.NativeOp{Op: "list", Option: k, List: "choices", Position: pos}
		}
	}
	return ops, n, nil
}

// placed orders the cards a selection just chose: Brainstorm's cards going
// on top, or discarded cards going to the graveyard. gorge's answer order
// is their order. An ordering with no selection before it (a reveal sent
// to the graveyard) is one gorge's engine fixes without asking.
func (s *Session) placed(sd *protocol.SeatDecision) ([]mapping.NativeOp, *native, error) {
	ops := make([]mapping.NativeOp, len(sd.Candidates))
	n := s.cur
	if n == nil || !(strings.HasPrefix(n.key, "handmove|") || strings.HasPrefix(n.key, "select|")) {
		n = s.open("fixed", decision.Decision{})
		for i := range ops {
			ops[i] = noOp
		}
		ops[0] = mapping.NativeOp{Op: "fixed", Option: -1}
		return ops, n, nil
	}
	pos := num(sd.Candidates[0].Semantic, "position")
	for i, c := range sd.Candidates {
		ops[i] = noOp
		it, err := field[protocol.OrderItem](c.Semantic, "item")
		if err != nil || it.Object == nil {
			continue
		}
		if k, ok := n.options[it.Object.ObjectID]; ok {
			ops[i] = mapping.NativeOp{Op: "list", Option: k, List: "choices", Position: pos}
		}
	}
	return ops, n, nil
}

// arrangeKinds maps an arrangement purpose to gorge's KArrange pile-B kind.
var arrangeKinds = map[string]string{"scry": "bottom", "surveil": "graveyard", "look_at_top": "bottom"}

// arrange is a scry, surveil or look-at-top arrangement: gorge's KArrange,
// whose answer is the cards kept on top in order (pile A) and, for scry,
// the order of the rest. The looked-at cards are in the observation's
// known list with their positions from the top.
func (s *Session) arrange(sd *protocol.SeatDecision) ([]mapping.NativeOp, *native, error) {
	first := sd.Candidates[0].Semantic
	if (first.Kind == "arrange_card" && str(first, "purpose") == "dig") || (s.cur != nil && s.cur.key == "dig") {
		return s.dig(sd)
	}
	if first.Kind == "arrange_card" && num(first, "card_index") == 0 && sd.Group.SubstepIndex == 0 {
		purpose := str(first, "purpose")
		other, ok := arrangeKinds[purpose]
		if !ok {
			return nil, nil, nil
		}
		count := num(first, "card_count")
		type looked struct {
			id  string
			pos uint32
		}
		var cards []looked
		for _, k := range sd.Observation.Known {
			if k.OwnerSeat == sd.ActingSeat && k.Zone == "library" && k.ObjectID != nil && k.PositionFromTop != nil && k.How == "looked_at" {
				cards = append(cards, looked{*k.ObjectID, *k.PositionFromTop})
			}
		}
		slices.SortFunc(cards, func(a, b looked) int { return int(a.pos) - int(b.pos) })
		if len(cards) != count {
			return nil, nil, nil
		}
		d := decision.Decision{Kind: decision.KArrange, Min: 0, Max: count, Restable: other == "bottom", Prompt: purpose}
		if purpose == "look_at_top" {
			d.Min = count
		}
		if src, err := optRef(first, "source"); err == nil && src != nil {
			d.Source = s.B.IDs.Of(src.ObjectID)
		}
		n := s.open("arrange", d)
		n.arrange = &arrangement{other: other}
		for _, c := range cards {
			n.arrange.cards = append(n.arrange.cards, c.id)
		}
		for _, ci := range hiddenOrder(sd, n.arrange.cards) {
			id := n.arrange.cards[ci]
			o := decision.Option{Index: len(n.d.Options), Kind: other, Label: knownName(sd, id), Obj: s.B.IDs.Of(id)}
			n.options[id] = o.Index
			n.d.Options = append(n.d.Options, o)
		}
		s.cur = n
	}
	n := s.continuing("arrange")
	if n == nil || n.arrange == nil {
		return nil, nil, nil
	}
	a := n.arrange
	ops := make([]mapping.NativeOp, len(sd.Candidates))
	for i, c := range sd.Candidates {
		ops[i] = noOp
		switch c.Semantic.Kind {
		case "arrange_card":
			card, err := ref(c.Semantic, "card")
			if err != nil {
				return nil, nil, err
			}
			k, ok := n.options[card.ObjectID]
			dst := str(c.Semantic, "destination")
			if ok && (dst == "top" || dst == a.other) {
				ops[i] = mapping.NativeOp{Op: "dest", Option: k, List: dst}
			}
		case "order_pick":
			it, err := field[protocol.OrderItem](c.Semantic, "item")
			if err != nil || it.Object == nil {
				continue
			}
			k, ok := n.options[it.Object.ObjectID]
			ci := slices.Index(a.cards, it.Object.ObjectID)
			if !ok || ci < 0 || ci >= len(a.dest) {
				continue
			}
			dst := a.dest[ci]
			pos := 0
			for _, p := range a.placed {
				if j := slices.Index(a.cards, p); j >= 0 && j < len(a.dest) && a.dest[j] == dst {
					pos++
				}
			}
			list := "choices"
			if dst != "top" {
				list = "rest"
			}
			ops[i] = mapping.NativeOp{Op: "list", Option: k, List: list, Position: pos}
		}
	}
	return ops, n, nil
}

// looked lists the acting seat's top count library cards it now knows
// (looked at or revealed), top first, or nil when any is missing.
func looked(sd *protocol.SeatDecision, count int) []string {
	type card struct {
		id  string
		pos uint32
	}
	var cs []card
	for _, k := range sd.Observation.Known {
		if k.OwnerSeat == sd.ActingSeat && k.Zone == "library" && k.ObjectID != nil && k.PositionFromTop != nil &&
			(k.How == "looked_at" || k.How == "revealed") && int(*k.PositionFromTop) < count {
			cs = append(cs, card{*k.ObjectID, *k.PositionFromTop})
		}
	}
	slices.SortFunc(cs, func(a, b card) int { return int(a.pos) - int(b.pos) })
	if len(cs) != count {
		return nil
	}
	ids := make([]string, count)
	for i, c := range cs {
		if int(c.pos) != i {
			return nil
		}
		ids[i] = c.id
	}
	return ids
}

// knownName is the card name the observation's known list gives id.
func knownName(sd *protocol.SeatDecision, id string) string {
	for _, k := range sd.Observation.Known {
		if k.ObjectID != nil && *k.ObjectID == id {
			return k.CardName
		}
	}
	return "a card"
}

// hiddenOrder lists the indices of library cards ids in the order gorge's
// agent is shown them: by card name, then object id, so an option's place
// never tells the library order (xview's sortHidden).
func hiddenOrder(sd *protocol.SeatDecision, ids []string) []int {
	order := make([]int, len(ids))
	for i := range order {
		order[i] = i
	}
	slices.SortStableFunc(order, func(a, b int) int {
		return strings.Compare(knownName(sd, ids[a])+"\x00"+ids[a], knownName(sd, ids[b])+"\x00"+ids[b])
	})
	return order
}

// dig is a Dig's look: v2 partitions the window (hand or bottom) and then
// orders it. gorge asks a KChoose of the eligible cards ("dig", in window
// order) and, when two or more go to the bottom, their bottom order as the
// follow-up dig_bottom. A Dig whose cards all move without a choice
// (Winding Way's "all cards of the chosen type", the rest to the graveyard)
// is one gorge's engine answers itself.
func (s *Session) dig(sd *protocol.SeatDecision) ([]mapping.NativeOp, *native, error) {
	first := sd.Candidates[0].Semantic
	if first.Kind == "arrange_card" && num(first, "card_index") == 0 && sd.Group.SubstepIndex == 0 {
		src, err := optRef(first, "source")
		if err != nil || src == nil {
			return nil, nil, err
		}
		sa := s.chainSA(*src, func(sa *cards.SA) bool { return sa.API == "Dig" })
		ids := looked(sd, num(first, "card_count"))
		if sa == nil || ids == nil {
			return nil, nil, nil
		}
		param := func(k string) string { return strings.TrimSpace(sa.Params[k]) }
		dest, dest2 := param("DestinationZone"), param("DestinationZone2")
		n := s.open("dig", decision.Decision{})
		n.arrange = &arrangement{cards: ids}
		switch {
		case strings.EqualFold(param("ChangeNum"), "All") || (dest2 != "" && !strings.EqualFold(dest2, "Library")):
			n.arrange.fixed = true
		case dest == "" || strings.EqualFold(dest, "Hand"):
			valid := strings.Split(param("ChangeValid"), ",")
			eligible := func(id string) bool {
				name := ""
				for _, k := range sd.Observation.Known {
					if k.ObjectID != nil && *k.ObjectID == id {
						name = k.CardName
					}
				}
				f := s.B.face(&name, false, nil)
				if f == nil {
					return false
				}
				for _, v := range valid {
					if slices.Contains(f.Types, strings.TrimSpace(v)) {
						return true
					}
				}
				return false
			}
			if slices.ContainsFunc(valid, func(v string) bool { return strings.ContainsAny(v, ".+") }) {
				return nil, nil, nil
			}
			d := decision.Decision{Kind: decision.KChoose, Prompt: "dig", ResumeSA: sa}
			if src != nil {
				d.Source = s.B.IDs.Of(src.ObjectID)
			}
			n.arrange.native = make([]int, len(ids))
			for ci := range n.arrange.native {
				n.arrange.native[ci] = -1
			}
			for _, ci := range hiddenOrder(sd, ids) {
				if eligible(ids[ci]) {
					n.arrange.native[ci] = len(d.Options)
					d.Options = append(d.Options, decision.Option{Index: len(d.Options), Kind: "dig", Label: knownName(sd, ids[ci]), Obj: s.B.IDs.Of(ids[ci]), Player: s.seat})
				}
			}
			changeNum, err := strconv.Atoi(param("ChangeNum"))
			anyNum := strings.EqualFold(param("ChangeNum"), "Any")
			if err != nil && !anyNum {
				return nil, nil, nil
			}
			if anyNum {
				changeNum = len(d.Options)
			}
			d.Max = min(changeNum, len(d.Options))
			if !anyNum && !strings.EqualFold(param("Optional"), "True") {
				d.Min = d.Max
			}
			n.d = d
		default:
			return nil, nil, nil
		}
		s.cur = n
	}
	n := s.continuing("dig")
	if n == nil || n.arrange == nil {
		return nil, nil, nil
	}
	a := n.arrange
	ops := make([]mapping.NativeOp, len(sd.Candidates))
	for i := range ops {
		ops[i] = noOp
	}
	if a.fixed {
		ops[0] = mapping.NativeOp{Op: "fixed", Option: -1}
		return ops, n, nil
	}
	var bottom []int
	for _, ci := range hiddenOrder(sd, a.cards) {
		if ci < len(a.dest) && a.dest[ci] == "bottom" {
			bottom = append(bottom, ci)
		}
	}
	if len(a.dest) == len(a.cards) && len(bottom) >= 2 && n.follow == nil {
		fd := decision.Decision{Kind: decision.KArrange, Min: len(bottom), Max: len(bottom), ResumeKind: "dig_arrange",
			ResumeSA: n.d.ResumeSA, Source: n.d.Source, Player: s.seat, Prompt: "Put the remaining cards on the bottom of your library in any order"}
		for j, ci := range bottom {
			fd.Options = append(fd.Options, decision.Option{Index: j, Kind: "dig_bottom", Label: knownName(sd, a.cards[ci]), Obj: s.B.IDs.Of(a.cards[ci]), Player: s.seat})
		}
		n.follow = map[string]decision.Decision{"dig_bottom": fd}
	}
	for i, c := range sd.Candidates {
		switch c.Semantic.Kind {
		case "arrange_card":
			card, err := ref(c.Semantic, "card")
			if err != nil {
				return nil, nil, err
			}
			ci := slices.Index(a.cards, card.ObjectID)
			if dst := str(c.Semantic, "destination"); ci >= 0 && (dst == "hand" || dst == "bottom") {
				ops[i] = mapping.NativeOp{Op: "dest", Option: a.native[ci], List: dst, Position: ci}
			}
		case "order_pick":
			it, err := field[protocol.OrderItem](c.Semantic, "item")
			if err != nil || it.Object == nil {
				continue
			}
			ci := slices.Index(a.cards, it.Object.ObjectID)
			if ci < 0 || ci >= len(a.dest) {
				continue
			}
			dst := a.dest[ci]
			pos := 0
			for _, p := range a.placed {
				if j := slices.Index(a.cards, p); j >= 0 && j < len(a.dest) && a.dest[j] == dst {
					pos++
				}
			}
			switch {
			case dst == "hand":
				ops[i] = mapping.NativeOp{Op: "list", Option: a.native[ci], List: "choices", Position: pos}
			case dst == "bottom" && len(bottom) == 1:
				// gorge moves a lone remainder without asking dig_bottom.
				ops[i] = mapping.NativeOp{Op: "dest", Option: -1, List: "bottom"}
			case dst == "bottom":
				ops[i] = mapping.NativeOp{Op: "list", Option: slices.Index(bottom, ci), List: "followup:dig_bottom", Position: pos}
			}
		}
	}
	return ops, n, nil
}
