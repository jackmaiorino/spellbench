package session

import (
	"encoding/json"
	"fmt"
	"os"
	"strconv"
	"strings"

	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/state"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/mapping"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/observe"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/xview"
)

// Realized is a completed native decision as the engine committed it, in
// the numbering the seat's x_gorge_view_v1 showed: the native decision's
// intent, and each folded follow-up's under its payload key (Task 28b's
// parity audit compares both with the agent's plan).
type Realized struct {
	Seat      state.PlayerID
	Native    uint64
	Kind      decision.Kind
	Intent    decision.Intent
	Followups map[string]decision.Intent
}

func (s *Game) Leaks() int { return s.leaks }

func (s *Game) Realized() []Realized { return s.realized }

// Inconsistent counts answered candidates whose semantic disagrees with the
// native option their op commits.
func (s *Game) Inconsistent() int { return s.inconsistent }

// LeakHits counts string values in a seat decision that name a card hidden
// from the seat. choose_name candidates are skipped: their domain is public.
func LeakHits(sd []byte, hidden map[string]bool) int {
	var v any
	if err := json.Unmarshal(sd, &v); err != nil {
		return 1 // an unreadable decision is never clean
	}
	hits := 0
	var walk func(any)
	walk = func(x any) {
		switch t := x.(type) {
		case string:
			if hidden[t] {
				hits++
			}
		case []any:
			for _, e := range t {
				walk(e)
			}
		case map[string]any:
			if t["kind"] == "choose_name" {
				return
			}
			for _, e := range t {
				walk(e)
			}
		}
	}
	walk(v)
	return hits
}

// hiddenNames lists the names of cards the seat cannot see (the other seat's
// hand, libraries, face-down cards), minus every name the seat can see: any
// visible card, and every name the decision's own observation carries in
// public records (zone records, stack entries of either kind, pending
// triggers) or in known. A stack ability names its source even after the
// source went into a library (Lembas), and that name is public.
func (s *Game) hiddenNames(seat state.PlayerID, obs protocol.Observation) map[string]bool {
	g := s.g.E.G
	hidden, seen := map[string]bool{}, map[string]bool{}
	for i := range g.Objs {
		o := &g.Objs[i]
		if o.Ability != nil || o.Face() == nil {
			continue
		}
		name := o.Face().Name
		switch {
		case observe.Visible(seat, o) && (!o.FaceDown || observe.MayLook(seat, o)):
			seen[name] = true
		case o.Zone == state.ZLibrary || o.Zone == state.ZHand || o.FaceDown:
			hidden[name] = true
		}
	}
	see := func(n *string) {
		if n != nil {
			seen[*n] = true
		}
	}
	for _, p := range obs.Players {
		for _, zone := range [][]protocol.ObjectRecord{p.Hand, p.Battlefield, p.Graveyard, p.Exile, p.Command} {
			for _, rec := range zone {
				see(rec.CardName)
			}
		}
	}
	for _, st := range obs.Stack {
		see(st.CardName)
	}
	for _, pt := range obs.PendingTriggers {
		see(pt.SourceName)
	}
	for _, k := range obs.Known {
		seen[k.CardName] = true
	}
	for n := range seen {
		delete(hidden, n)
	}
	return hidden
}

// realize records a completed native decision's commits in the numbering
// the seat's agent saw: commit[0] in the native decision's payload order,
// and each later intent under the payload key of the follow-up it answered,
// in that follow-up's order. A folded intent (Seq 0) answers the follow-up
// its op's key chain names; one carrying its own Seq (dig's bottom order)
// answers the pose follow-up with that Seq.
func (s *Game) realize(seat state.PlayerID, p *mapping.Pose, op mapping.NativeOp, commit []decision.Intent) {
	x, _ := s.cfg.Ext.(*xview.Extender)
	renum := func(perm []int, in decision.Intent) decision.Intent {
		m := func(xs []int) []int {
			out := make([]int, len(xs))
			for i, v := range xs {
				out[i] = v
				if v >= 0 && v < len(perm) {
					out[i] = perm[v]
				}
			}
			return out
		}
		out := decision.Intent{Choices: m(in.Choices), Rest: m(in.Rest), Payment: decision.ClonePaymentSelection(in.Payment)}
		if x != nil {
			out.Payment = x.PublicPayment(seat, in.Payment)
		}
		return out
	}
	var perm []int
	if x != nil {
		perm = x.Perm(seat)
	}
	r := Realized{Seat: seat, Native: s.nativeCount[seat], Kind: s.native.Kind, Intent: renum(perm, commit[0]),
		Followups: map[string]decision.Intent{}}
	keys := followKeys(op)
	for k, in := range commit[1:] {
		native := ""
		if in.Seq == 0 && k < len(keys) {
			native = keys[k]
		} else {
			for key, fd := range p.Followups {
				if fd.Seq == in.Seq {
					native = key
				}
			}
		}
		if x == nil {
			continue
		}
		if f, ok := x.FollowOf(seat, native); ok {
			r.Followups[f.Key] = renum(f.Perm, in)
		}
	}
	s.realized = append(s.realized, r)
}

// objectField names, per kind, the semantic field that references the
// object of the native option a choose, cast or list op commits.
var objectField = map[string]string{"play_land": "source", "cast_spell": "source", "activate_ability": "source",
	"activate_mana_ability": "source", "special_action": "source", "choose_target": "target",
	"choose_cost_target": "candidate", "select_object": "choice", "declare_attack": "attacker",
	"declare_block": "blocker", "order_pick": "item", "optional_cast": "card", "choose_replacement": "replacement_source"}

// checkConsistent is the semantic-consistency audit: an answered candidate
// must describe the native option its op commits.
func (s *Game) checkConsistent(p *mapping.Pose, c mapping.Cand) {
	if why := s.consistent(p, c); why != "" {
		s.inconsistent++
		fmt.Fprintf(os.Stderr, "gorge audit: %s candidate disagrees with its native option: %s\n", c.Sem.Kind, why)
	}
}

// consistent returns what differs, or "": the object the semantic names is
// the option's object (by v2 id when the seat sees it, else by name, zone
// and owner); a mana candidate's ability_index and mana_choice are its folded
// options'; a mode's mode_index is the option's printed mode; a number's
// value is the option's amount; an attack's defender and a block's attacker
// are the option's.
func (s *Game) consistent(p *mapping.Pose, c mapping.Cand) string {
	op, d, idx := c.Op, p.Native, c.Op.Option
	switch op.Op {
	case "payment":
		if op.Payment == nil {
			return "missing payment witness"
		}
		for _, a := range d.PaymentActions {
			if a.ID == op.Payment.ActionID {
				if c.Sem.Kind != "cast_spell" && c.Sem.Kind != "optional_cost" {
					return "payment on a non-cast candidate"
				}
				var sem map[string]any
				b, _ := json.Marshal(c.Sem)
				json.Unmarshal(b, &sem)
				return s.sameObject(p.Seat, sem["source"], a.Cast.Object, 0, false)
			}
		}
		return "payment action is not offered"
	case "cast":
		if len(op.Covers) == 0 {
			return "a cast op covers no option"
		}
		idx = op.Covers[0]
	case "choose":
	case "list":
		if key, ok := strings.CutPrefix(op.List, "followup:"); ok {
			d = p.Followups[key]
		}
	case "dest":
		if idx < 0 {
			return "" // a looked-at card with no native option
		}
	default:
		return "" // none, finish: no native option
	}
	if d == nil || idx < 0 || idx >= len(d.Options) {
		return fmt.Sprintf("option %d is not offered", idx)
	}
	o := d.Options[idx]
	var sem map[string]any
	b, _ := json.Marshal(c.Sem)
	json.Unmarshal(b, &sem)
	if f := objectField[c.Sem.Kind]; f != "" {
		if why := s.sameObject(p.Seat, sem[f], o.Obj, o.Player, o.Kind == "player"); why != "" {
			return why
		}
	}
	switch c.Sem.Kind {
	case "arrange_card":
		if op.Op == "dest" {
			return s.sameObject(p.Seat, sem["card"], o.Obj, 0, false)
		}
	case "declare_attack":
		if o.Battle != 0 {
			return s.sameObject(p.Seat, sem["defender"], o.Battle, 0, false)
		}
		return s.sameObject(p.Seat, sem["defender"], 0, o.Player, true)
	case "declare_block":
		return s.sameObject(p.Seat, sem["attacker"], o.Attacker, 0, false)
	case "choose_spell_mode":
		index, _, err := mapping.PrintedModes(d)
		if err != nil || fmt.Sprint(sem["mode_index"]) != fmt.Sprint(index[idx]) {
			return fmt.Sprintf("mode_index %v for option %d", sem["mode_index"], idx)
		}
	case "choose_number":
		if fmt.Sprint(sem["value"]) != strconv.Itoa(o.Amount) {
			return fmt.Sprintf("value %v, option amount %d", sem["value"], o.Amount)
		}
	case "activate_mana_ability":
		keys := followKeys(op)
		if len(keys) == 0 {
			return ""
		}
		first, last := p.Followups[keys[0]], p.Followups[keys[len(keys)-1]]
		if first == nil || last == nil {
			return "a folded follow-up is missing"
		}
		f0, fl := first.Options[op.Followup[0]], last.Options[op.Followup[len(op.Followup)-1]]
		if f0.Kind == "mana" && fmt.Sprint(sem["ability_index"]) != strconv.Itoa(f0.Ability) {
			return fmt.Sprintf("ability_index %v, folded ability %d", sem["ability_index"], f0.Ability)
		}
		if sym, ok := mapping.ManaSymbol(fl); ok && sem["mana_choice"] != sym {
			return fmt.Sprintf("mana_choice %v, folded %s", sem["mana_choice"], sym)
		}
	}
	return ""
}

// sameObject reports why ref (an object reference, a target reference or an
// order item, as generic JSON) does not name the native object obj, or the
// seat player when isPlayer.
func (s *Game) sameObject(seat state.PlayerID, ref any, obj state.ObjID, player state.PlayerID, isPlayer bool) string {
	m, _ := ref.(map[string]any)
	if inner, ok := m["object"].(map[string]any); ok {
		m = inner
	}
	if pl, ok := m["player"].(string); ok || isPlayer {
		if !isPlayer || pl != observe.Seat(player) {
			return fmt.Sprintf("player %v, option %s", m["player"], observe.Seat(player))
		}
		return ""
	}
	o := s.g.E.G.Obj(obj)
	switch {
	case obj == 0 || m["trigger"] != nil:
		return "" // no native object to compare, or a trigger item
	case o == nil:
		return fmt.Sprintf("option object %d is gone", obj)
	case m == nil:
		if observe.Visible(seat, o) {
			return fmt.Sprintf("a null reference to visible object %d", obj)
		}
		return ""
	case observe.Visible(seat, o):
		want, err := s.env.IDs.VisibleID(seat, obj)
		if err != nil || m["object_id"] != want {
			return fmt.Sprintf("names %v, the option is %s", m["object_id"], want)
		}
	case m["card_name"] != o.Face().Name || m["zone"] != o.Zone.String() || m["owner_seat"] != observe.Seat(o.Owner):
		// a hidden card shown by a look: compare what its look id stands for
		return fmt.Sprintf("names %v in %v, the option is %s in %s", m["card_name"], m["zone"], o.Face().Name, o.Zone)
	}
	return ""
}
