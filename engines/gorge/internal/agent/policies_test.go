package agent

import (
	"context"
	"encoding/json"
	"errors"
	"math/rand/v2"
	"reflect"
	"testing"

	"github.com/adams-shaun/gorge/botpolicy"
	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/seat"
	"github.com/adams-shaun/gorge/view"
)

func nativePolicy(key string, seed uint64) seat.Seat {
	switch key {
	case "bot":
		return seat.NewBot(seed)
	case "bot-auto-pay":
		b := seat.NewBot(seed)
		b.EnableAutoPayMana()
		return b
	case "lethal-pressure":
		return seat.NewLethalPressureBot(seed)
	case "lethal-pressure-auto-pay":
		b := seat.NewLethalPressureBot(seed)
		b.EnableAutoPayMana()
		return b
	case "ar8":
		return seat.NewCombinedLethalBot(seed)
	case "blocks":
		return seat.NewBlocksBot(seed)
	case "explore":
		return seat.NewExploreBot(seed)
	default:
		return &nativeLegacy{rand.New(rand.NewPCG(seed, seed^0x9e3779b97f4a7c15))}
	}
}

type nativeLegacy struct{ r *rand.Rand }

func (s *nativeLegacy) Decide(_ context.Context, v view.View, d decision.Decision) (decision.Intent, error) {
	return botpolicy.LegacyDecide(seat.BoardFromView(v), &d, s.r), nil
}

// Compare the wrapper with independent upstream constructors over repeated
// random-consuming mulligans and priority, attack and block decisions.
func TestPoliciesPreserveNativeBehaviorAndIdentity(t *testing.T) {
	v := view.View{Viewer: 0, Turn: 1, Step: "main1", Players: []view.PlayerView{
		{Life: 20, Battlefield: []view.CardView{{ID: 7, Name: "attacker", Types: "Creature", Power: 4, Toughness: 4}}},
		{Life: 5, Battlefield: []view.CardView{{ID: 9, Name: "blocker", Types: "Creature", Power: 2, Toughness: 2}}},
	}}
	ds := []decision.Decision{
		{Kind: decision.KMulligan, Min: 1, Max: 1, Options: []decision.Option{{Index: 0, Kind: "keep"}, {Index: 1, Kind: "mulligan"}}},
		{Kind: decision.KPriority, Min: 1, Max: 1, Options: []decision.Option{{Index: 0, Kind: "pass"}, {Index: 1, Kind: "play_land", Obj: 3}}},
		{Kind: decision.KAttackers, Min: 0, Max: 1, Options: []decision.Option{{Index: 0, Kind: "attack", Obj: 7, Player: 1}}},
		{Kind: decision.KBlockers, Min: 0, Max: 1, Options: []decision.Option{{Index: 0, Kind: "block", Obj: 7, Attacker: 9}}},
	}
	seen := map[string]bool{}
	for _, p := range Policies() {
		t.Run(p.Key, func(t *testing.T) {
			if seen[p.Name] {
				t.Fatalf("duplicate published identity %q", p.Name)
			}
			seen[p.Name] = true
			s, err := New(p.Key)
			if err != nil {
				t.Fatal(err)
			}
			var hello struct {
				Bot struct{ Name, Version string }
			}
			json.Unmarshal(s.Handle([]byte(`{"request_type":"hello","request_id":"h"}`)), &hello)
			if hello.Bot.Name != p.Name || hello.Bot.Version != Version {
				t.Fatalf("identity %+v", hello.Bot)
			}
			for _, seed := range []uint64{1, 2, 54321} {
				s.Handle([]byte(`{"request_type":"game_start","engine_profile":{"engine_defaults":{"mana_payment":"engine_autopay"}},"agent_seed":` + fmtSeed(seed) + `}`))
				oracle := nativePolicy(p.Key, seed)
				for n := 0; n < 12; n++ {
					for _, d := range ds {
						want, err := oracle.Decide(context.Background(), v, d)
						if err != nil {
							t.Fatal(err)
						}
						if got := s.decide(v, d); !reflect.DeepEqual(got, want) {
							t.Fatalf("seed %d decision %s: got %+v, native %+v", seed, d.Kind, got, want)
						}
					}
				}
			}
		})
	}
}

func fmtSeed(seed uint64) string { b, _ := json.Marshal(seed); return string(b) }

func TestDefaultCastProfileIsAnAlias(t *testing.T) {
	p, err := lookupPolicy("cast-profile")
	if err != nil || p.Key != "bot" || p.Name != "gorge-bot" {
		t.Fatalf("default cast-profile is not the bot alias: %+v %v", p, err)
	}
	w, err := botpolicy.LoadCastProfile(botpolicy.DefaultCastProfileName)
	if err != nil || w != botpolicy.DefaultCastWeights {
		t.Fatalf("pinned cast-profile no longer equals default: %+v %v", w, err)
	}
	for _, key := range []string{"search", "policynet", "unknown"} {
		if _, err := New(key); err == nil {
			t.Fatalf("unfinished policy %s silently substituted a bot", key)
		}
	}
}

func TestAutoPayRequiresTheDeclaredEngineMode(t *testing.T) {
	s, _ := New("bot-auto-pay")
	var reply map[string]any
	json.Unmarshal(s.Handle([]byte(`{"request_type":"game_start","agent_seed":1}`)), &reply)
	if reply["response_type"] != "error" || s.bot != nil {
		t.Fatalf("undeclared auto-pay was accepted: %v", reply)
	}
}

type failedPolicy struct{}

func (failedPolicy) Decide(context.Context, view.View, decision.Decision) (decision.Intent, error) {
	return decision.Intent{}, errors.New("native policy failure")
}

func TestPolicyFailureIsAnAgentError(t *testing.T) {
	s, _ := New("bot")
	s.bot = failedPolicy{}
	var reply map[string]any
	json.Unmarshal(s.Handle([]byte(`{"request_type":"choose","request_id":"c","decision":{"candidates":[{"candidate_id":0,"semantic":{"kind":"pass"}}],"extensions":{"x_gorge_view_v1":{"version":1,"native_index":1,"decision":{"kind":"priority"},"ops":[{"op":"choose","option":0}]}}}}`)), &reply)
	if reply["response_type"] != "error" || s.Fallbacks() != 0 {
		t.Fatalf("failed policy was replaced with a choice: %v", reply)
	}
}
