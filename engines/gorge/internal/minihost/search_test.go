package minihost_test

import (
	"encoding/json"
	"math/rand/v2"
	"strings"
	"testing"

	"github.com/adams-shaun/gorge/events"
	"github.com/adams-shaun/gorge/spellbench-strategies"
	"github.com/adams-shaun/gorge/state"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/agent"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/catalog"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/minihost"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/server"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/testcorpus"
)

// ResampleCheck probes the current observation, including its cached delta.
// It does not replay or independently rebuild the actor's earlier history.
type publicHistoryAudit struct {
	s      *server.Server
	r      *rand.Rand
	checks int
}

func (a *publicHistoryAudit) Round(q []byte) ([]byte, error) {
	if strings.Contains(string(q), `"request_type":"step"`) {
		if err := a.s.ResampleCheck(a.r); err != nil {
			return nil, err
		}
		a.checks++
	}
	return a.s.Handle(q), nil
}

// Five short prefixes exercise the complete transport profile and collector,
// without playing full games or running a benchmark qualification campaign.
func TestPublicSearchHistoryPrefixesOnEveryDeck(t *testing.T) {
	for i, deck := range catalog.Decks() {
		t.Run(deck.CatalogID, func(t *testing.T) {
			h := host(t)
			s := h.Engine.(*minihost.EngineLink).S
			s.EnableAutoPay()
			s.EnableSearch()
			s.SetAudit(true)
			audit := &publicHistoryAudit{s: s, r: rand.New(rand.NewPCG(17, 83))}
			h.Engine = audit
			h.KeepDecisions = true
			h.MaxDecisions, h.MaxSteps = 64, 500
			bot, err := agent.New("bot")
			if err != nil {
				t.Fatal(err)
			}
			res, err := h.Play(uint64(i), deck, "london", []string{"x_gorge_view_v1", strategies.Extension},
				[2]minihost.Link{bot, &minihost.Uniform{}})
			if err != nil {
				t.Fatal(err)
			}
			if res.Terminal.Classification != "truncated" || audit.checks == 0 || s.Leaks() != 0 || s.Inconsistent() != 0 {
				t.Fatalf("prefix audit failed: %+v checks=%d leaks=%d inconsistent=%d", res.Terminal, audit.checks, s.Leaks(), s.Inconsistent())
			}
			checkPublicHistories(t, res)
		})
	}
}

// A completed correctness game per deck exercises late public events, hidden
// moves and retirement after the short prefixes. It is not a rated evaluation
// or evidence that the current-observation probe proves whole-history privacy.
func TestCompletePublicSearchHistoriesOnEveryDeck(t *testing.T) {
	for i, deck := range catalog.Decks() {
		t.Run(deck.CatalogID, func(t *testing.T) {
			play := func(keep bool) minihost.Result {
				h := host(t)
				s := h.Engine.(*minihost.EngineLink).S
				s.EnableAutoPay()
				s.EnableSearch()
				s.SetAudit(true)
				h.KeepDecisions = keep
				a, err := agent.New("bot")
				if err != nil {
					t.Fatal(err)
				}
				b, err := agent.New("bot")
				if err != nil {
					t.Fatal(err)
				}
				result, err := h.Play(uint64(i), deck, "london", []string{"x_gorge_view_v1", strategies.Extension}, [2]minihost.Link{a, b})
				if err != nil {
					t.Fatal(err)
				}
				if result.Terminal.Classification != "natural" || s.Leaks() != 0 || s.Inconsistent() != 0 {
					t.Fatalf("complete history failed: %+v leaks=%d inconsistent=%d", result.Terminal, s.Leaks(), s.Inconsistent())
				}
				return result
			}
			a := play(true)
			checkPublicHistories(t, a)
			b := play(false)
			if a.Digest != b.Digest {
				t.Fatalf("complete public-history replay changed: %s != %s", a.Digest, b.Digest)
			}
			t.Logf("natural_steps=%d digest=%s", a.Steps, a.Digest)
		})
	}
}

func checkPublicHistories(t *testing.T, result minihost.Result) {
	t.Helper()
	for seat, decisions := range result.SeatDecisions {
		history := strategies.History{Actor: state.PlayerID(seat)}
		seen := map[uint32]bool{}
		var last uint64
		for _, raw := range decisions {
			var sd struct {
				Extensions map[string]json.RawMessage `json:"extensions"`
			}
			if err := json.Unmarshal(raw, &sd); err != nil {
				t.Fatal(err)
			}
			var v struct {
				NativeIndex uint64 `json:"native_index"`
			}
			if err := json.Unmarshal(sd.Extensions["x_gorge_view_v1"], &v); err != nil {
				t.Fatal(err)
			}
			if v.NativeIndex == last {
				continue
			}
			last = v.NativeIndex
			var d strategies.Delta
			if err := json.Unmarshal(sd.Extensions[strategies.Extension], &d); err != nil {
				t.Fatal(err)
			}
			if !d.Live {
				t.Fatalf("collector stopped: %s", d.StopReason)
			}
			if err := strategies.AppendDelta(&history, d); err != nil {
				t.Fatal(err)
			}
			for _, f := range d.Frames {
				for _, identity := range f.Identities {
					if identity.ID == 0 || seen[identity.ID] {
						t.Fatal("copy identity was introduced twice")
					}
					seen[identity.ID] = true
				}
				for _, ev := range f.Events {
					if ev.Kind == events.DecisionAsk || ev.Kind == events.DecisionMade {
						t.Fatal("decision transcript in public history")
					}
				}
			}
			for _, ref := range d.Aliases {
				if !seen[ref] {
					t.Fatal("current view alias has no observed identity")
				}
			}
		}
		if len(history.Frames) == 0 {
			t.Fatal("actor received no public history")
		}
		known, err := strategies.ProjectKnownCards(history)
		if err != nil {
			t.Fatal(err)
		}
		t.Logf("seat=%d wire_decisions=%d actor_frames=%d known_claims=%d", seat, len(decisions), len(history.Frames), known.Count())
	}
}

// A bounded protocol/replay check. This deliberate truncation is not a
// completed game or a qualification result.
func TestSearchHistoryStartsAndReplaysThroughTheHost(t *testing.T) {
	deck, _ := catalog.ByID("Burn")
	play := func(policy string) minihost.Result {
		h := host(t)
		s := h.Engine.(*minihost.EngineLink).S
		s.EnableSearch()
		bot, err := agent.New(policy)
		if err != nil {
			t.Fatal(err)
		}
		bot.SetRegistry(testcorpus.Registry(t))
		h.MaxDecisions, h.MaxSteps = 12, 100
		res, err := h.Play(0, deck, "london", []string{"x_gorge_view_v1", strategies.Extension},
			[2]minihost.Link{bot, &minihost.Uniform{}})
		if err != nil {
			t.Fatal(err)
		}
		if res.Terminal.Classification != "truncated" || len(bot.Records()) == 0 {
			t.Fatalf("bounded check did not reach its declared cap: %+v", res.Terminal)
		}
		for _, r := range bot.Records() {
			if r.Search == nil {
				t.Fatal("search path was not invoked")
			}
		}
		return res
	}
	for _, policy := range []string{"search", "search-mana", "search-redeal", "search-mana-redeal"} {
		a, b := play(policy), play(policy)
		if a.Digest != b.Digest {
			t.Fatalf("%s replay digest changed", policy)
		}
	}
}

func TestSearchEngineProfileRequiresTheExplicitFlag(t *testing.T) {
	s := server.New(testcorpus.Registry(t), nil)
	// The default profile and its existing goldens do not enable history.
	before := string(s.Handle([]byte(`{"request_type":"hello","protocol":"spellbench/v2","request_id":"h-before","protocol_minor":0}`)))
	if strings.Contains(before, strategies.Extension) {
		t.Fatal("history enabled without -search")
	}
	s.EnableSearch()
	after := string(s.Handle([]byte(`{"request_type":"hello","protocol":"spellbench/v2","request_id":"h-after","protocol_minor":0}`)))
	if !strings.Contains(after, strategies.Extension) {
		t.Fatal("history profile is absent")
	}
}
