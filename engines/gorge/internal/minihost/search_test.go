package minihost_test

import (
	"strings"
	"testing"

	"github.com/adams-shaun/gorge/spellbench-strategies"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/agent"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/catalog"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/minihost"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/server"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/testcorpus"
)

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
	for _, policy := range []string{"search", "search-mana"} {
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
