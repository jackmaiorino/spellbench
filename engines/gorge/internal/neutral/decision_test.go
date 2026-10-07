package neutral_test

import (
	"encoding/json"
	"strings"
	"testing"

	"github.com/adams-shaun/gorge/decision"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/agent"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/neutral"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/testcorpus"
)

// kernelObs is a Burn mirror observation shaped as mtg-kernel sends it: the
// viewer holds Lightning Bolt and a Mountain with two Mountains in play, and
// the opponent has a 1/1 Voldaren Epicure.
const kernelObs = `{"viewer":"p0","turn":3,"phase_step":"precombat_main","active_seat":"p0","priority_seat":"p0",
 "passed_seats":[],"day_night":null,"stack":[],"pending_triggers":null,"known":[],
 "players":[
  {"seat":"p0","life":20,"poison":null,"counters":null,"mana_pool":{"W":0,"U":0,"B":0,"R":0,"G":0,"C":0},
   "lands_played_this_turn":0,"mulligans_taken":0,"designations":[],"progress":null,"hand_count":2,"library_count":51,
   "hand":[
    {"object_id":"o-bolt","card_name":"Lightning Bolt","owner_seat":"p0","controller_seat":"p0","zone":"hand","full_name":null,
     "face_down":false,"token":false,"copy":false,"characteristics":{"supertypes":[],"types":["instant"],"subtypes":[],
     "colors":["red"],"mana_value":1,"power":null,"toughness":null,"keywords":[]},"permanent":null,"exiled_by":null},
    {"object_id":"o-mtn3","card_name":"Mountain","owner_seat":"p0","controller_seat":"p0","zone":"hand","full_name":null,
     "face_down":false,"token":false,"copy":false,"characteristics":{"supertypes":["basic"],"types":["land"],"subtypes":["mountain"],
     "colors":[],"mana_value":0,"power":null,"toughness":null,"keywords":[]},"permanent":null,"exiled_by":null}],
   "battlefield":[
    {"object_id":"o-mtn1","card_name":"Mountain","owner_seat":"p0","controller_seat":"p0","zone":"battlefield","full_name":null,
     "face_down":false,"token":false,"copy":false,"characteristics":{"supertypes":["basic"],"types":["land"],"subtypes":["mountain"],
     "colors":[],"mana_value":0,"power":null,"toughness":null,"keywords":[]},
     "permanent":{"tapped":false,"summoning_sick":false,"damage":0,"counters":{},"attached_to":null,"attacking":false,
      "attack_target":null,"blocking":false,"blocked_attackers":[],"phased_out":false,"statuses":[],"class_level":null,"chosen":[]},
     "exiled_by":null}],
   "graveyard":[],"exile":[],"command":[]},
  {"seat":"p1","life":17,"poison":null,"counters":null,"mana_pool":{"W":0,"U":0,"B":0,"R":0,"G":0,"C":0},
   "lands_played_this_turn":0,"mulligans_taken":0,"designations":[],"progress":null,"hand_count":4,"library_count":50,"hand":null,
   "battlefield":[
    {"object_id":"o-epi","card_name":"Voldaren Epicure","owner_seat":"p1","controller_seat":"p1","zone":"battlefield","full_name":null,
     "face_down":false,"token":false,"copy":false,"characteristics":{"supertypes":[],"types":["creature"],"subtypes":["vampire"],
     "colors":["red"],"mana_value":1,"power":1,"toughness":1,"keywords":[]},
     "permanent":{"tapped":false,"summoning_sick":false,"damage":0,"counters":{},"attached_to":null,"attacking":false,
      "attack_target":null,"blocking":false,"blocked_attackers":[],"phased_out":false,"statuses":[],"class_level":null,"chosen":[]},
     "exiled_by":null}],
   "graveyard":[],"exile":[],"command":[]}]}`

func ref(id, name, zone string) string {
	owner := "p0"
	if id == "o-epi" {
		owner = "p1"
	}
	return `{"object_id":"` + id + `","card_name":"` + name + `","owner_seat":"` + owner + `","controller_seat":"` + owner + `","zone":"` + zone + `"}`
}

func seatDecision(t *testing.T, ctx, group string, cands ...string) protocol.SeatDecision {
	t.Helper()
	body := `{"acting_seat":"p0","seat_step":4,"group":` + group + `,"context":` + ctx + `,"observation":` + kernelObs + `,"candidates":[`
	for i, c := range cands {
		if i > 0 {
			body += ","
		}
		body += `{"candidate_id":` + string(rune('0'+i)) + `,"semantic":` + c + `,"display_text":null}`
	}
	body += `],"extensions":{}}`
	var sd protocol.SeatDecision
	if err := json.Unmarshal([]byte(body), &sd); err != nil {
		t.Fatal(err)
	}
	return sd
}

const priority = `{"kind":"priority","source":null,"purpose":null,"text":null,"rewind":false}`

// TestKernelCastPlanSpansTheMethodDecision follows a kernel cast: cast_spell
// with a null method, then choose_cast_method. The plan made at priority
// answers the method and the target, which are decisions of their own.
func TestKernelCastPlanSpansTheMethodDecision(t *testing.T) {
	reg := testcorpus.Registry(t)
	s := neutral.NewSession(reg)
	sd := seatDecision(t, priority, `{"group_id":4,"substep_index":0,"substep_count":1}`,
		`{"kind":"pass"}`,
		`{"kind":"play_land","source":`+ref("o-mtn3", "Mountain", "hand")+`,"face":0}`,
		`{"kind":"cast_spell","source":`+ref("o-bolt", "Lightning Bolt", "hand")+`,"method":null}`,
		`{"kind":"activate_mana_ability","source":`+ref("o-mtn1", "Mountain", "battlefield")+`,"ability_index":0,"mana_choice":null,"cost_target":null}`)
	p, err := s.Payload(&sd)
	if err != nil {
		t.Fatal(err)
	}
	if p.Decision.Kind != decision.KPriority || len(p.Decision.Options) != 3 || p.Ops[3].Op != "untranslated" {
		t.Fatalf("priority options %+v ops %+v", p.Decision.Options, p.Ops)
	}
	if p.View.Players[0].Hand[0].ManaCost != "R" || p.View.Players[1].Battlefield[0].Power != 1 {
		t.Fatalf("view lacks printed or observed facts: %+v", p.View.Players)
	}
	castOpt := p.Ops[2].Option
	if o := p.Decision.Options[castOpt]; o.Kind != "cast" || o.Obj == 0 {
		t.Fatalf("cast option %+v", o)
	}
	method := seatDecision(t, `{"kind":"choice","source":`+ref("o-bolt", "Lightning Bolt", "hand")+`,"purpose":null,"text":null,"rewind":false}`,
		`{"group_id":5,"substep_index":0,"substep_count":1}`,
		`{"kind":"choose_cast_method","source":`+ref("o-bolt", "Lightning Bolt", "hand")+`,"method":"normal"}`)
	m, err := s.Payload(&method)
	if err != nil {
		t.Fatal(err)
	}
	if m.NativeIndex != p.NativeIndex || m.Ops[0].Op != "cast" || m.Ops[0].Covers[0] != castOpt {
		t.Fatalf("cast method is not the priority plan's: %+v (native %d, priority %d)", m.Ops, m.NativeIndex, p.NativeIndex)
	}
}

// TestKernelBoltTargetsTheOpponent plays kernel-shaped requests through the
// neutral agent: Lightning Bolt goes at the opposing player or its creature,
// never at the caster, and the target effect names its 3 damage.
func TestKernelBoltTargetsTheOpponent(t *testing.T) {
	reg := testcorpus.Registry(t)
	stack := `[{"object_id":"o-boltS","card_name":"Lightning Bolt","owner_seat":"p0","controller_seat":"p0","zone":"stack",
	  "stack_kind":"spell","source":null,"face_down":false,"copy":false,"characteristics":{"supertypes":[],"types":["instant"],
	  "subtypes":[],"colors":["red"],"mana_value":1,"power":null,"toughness":null,"keywords":[]},"targets":[],"divided":null,
	  "modes":null,"x_value":null,"text":null}]`
	src := ref("o-boltS", "Lightning Bolt", "stack")
	tgt := func(i int, target string) string {
		return `{"candidate_id":` + string(rune('0'+i)) + `,"semantic":{"kind":"choose_target","source":` + src +
			`,"slot":0,"target":` + target + `,"selected_count":0,"minimum":1,"maximum":1},"display_text":null}`
	}
	sdJSON := `{"acting_seat":"p0","seat_step":5,"group":{"group_id":5,"substep_index":0,"substep_count":1},
	 "context":{"kind":"choice","source":` + src + `,"purpose":null,"text":null,"rewind":false},"observation":` + kernelObs + `,
	 "candidates":[` + tgt(0, `{"player":"p0"}`) + `,` + tgt(1, `{"player":"p1"}`) + `,` +
		tgt(2, `{"object":`+ref("o-epi", "Voldaren Epicure", "battlefield")+`}`) + `],"extensions":{}}`
	var sd protocol.SeatDecision
	if err := json.Unmarshal([]byte(sdJSON), &sd); err != nil {
		t.Fatal(err)
	}
	if err := json.Unmarshal([]byte(stack), &sd.Observation.Stack); err != nil {
		t.Fatal(err)
	}
	p, err := neutral.NewSession(reg).Payload(&sd)
	if err != nil {
		t.Fatal(err)
	}
	te := p.Decision.TargetEffect
	if te == nil || te.API != "DealDamage" || te.Damage == nil || te.Damage.Amount == nil || *te.Damage.Amount != 3 {
		t.Fatalf("target effect %+v", te)
	}
	if p.Decision.Kind != decision.KTarget || len(p.Decision.Options) != 3 {
		t.Fatalf("target decision %+v", p.Decision)
	}
	full, _ := json.Marshal(sd)
	full = []byte(strings.Replace(string(full), `"stack":[]`, `"stack":`+stack, 1))
	a, _ := agent.New("bot-auto-pay")
	a.SetRegistry(reg)
	if err := a.EnableNeutral(); err != nil {
		t.Fatal(err)
	}
	deck := `{"name":"Burn","decklist":[{"name":"Lightning Bolt","count":4},{"name":"Mountain","count":18},{"name":"Voldaren Epicure","count":4}]}`
	for _, line := range []string{
		`{"request_type":"hello","protocol":"spellbench/v2","request_id":"r-0"}`,
		`{"request_type":"game_start","protocol":"spellbench/v2","request_id":"r-1","game_id":"g","seat":"p0","agent_seed":7,"own_deck":` + deck + `,"opponent_deck":` + deck + `}`,
	} {
		if out := a.Handle([]byte(line)); strings.Contains(string(out), `"error"`) {
			t.Fatalf("%s", out)
		}
	}
	out := a.Handle([]byte(`{"request_type":"choose","protocol":"spellbench/v2","request_id":"r-2","game_id":"g","decision":` + string(full) + `}`))
	var choice struct {
		Selection struct {
			CandidateID int `json:"candidate_id"`
		} `json:"selection"`
	}
	if err := json.Unmarshal(out, &choice); err != nil || choice.Selection.CandidateID == 0 {
		t.Fatalf("bot answered %s", out)
	}
	if a.Fallbacks() != 0 {
		t.Fatalf("%d fallbacks", a.Fallbacks())
	}
}
