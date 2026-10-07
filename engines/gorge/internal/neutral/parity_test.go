package neutral_test

import (
	"encoding/json"
	"fmt"
	"os"
	"slices"
	"sort"
	"strings"
	"testing"

	"github.com/adams-shaun/gorge/view"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/agent"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/catalog"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/minihost"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/neutral"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/observe"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/server"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/testcorpus"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/validate"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/xview"
)

// recorder passes requests to a gorge agent and keeps every choose request.
type recorder struct {
	inner minihost.Link
	seen  [][]byte
}

func (r *recorder) Round(req []byte) ([]byte, error) {
	if strings.Contains(string(req[:min(len(req), 64)]), `"choose"`) {
		r.seen = append(r.seen, slices.Clone(req))
	}
	return r.inner.Round(req)
}

// gorgeGames plays gorge bot mirrors on gorge's own engine and returns each
// choose request: the v2 observation with x_gorge_view_v1 beside it.
func gorgeGames(t *testing.T, games int) [][]byte {
	t.Helper()
	reg := testcorpus.Registry(t)
	kinds := map[string]bool{}
	for _, k := range server.DecisionKinds {
		kinds[k] = true
	}
	var out [][]byte
	for i := 0; i < games; i++ {
		d := catalog.Decks()[i%len(catalog.Decks())]
		h := &minihost.Host{RunSecret: make([]byte, 32), Engine: &minihost.EngineLink{S: server.New(reg, nil)},
			Profile:  validate.Profile{Kinds: kinds, Flags: observe.Flags, Extensions: map[string]bool{"x_gorge_view_v1": true}},
			MaxSteps: 20000, MaxDecisions: 9999}
		var links [2]minihost.Link
		var recs [2]*recorder
		for s := range links {
			a, err := agent.New("bot")
			if err != nil {
				t.Fatal(err)
			}
			recs[s] = &recorder{inner: a}
			links[s] = recs[s]
		}
		if _, err := h.Play(uint64(i), d, "london", []string{"x_gorge_view_v1"}, links); err != nil {
			t.Fatalf("game %d (%s): %v", i, d.CatalogID, err)
		}
		out = append(out, recs[0].seen...)
		out = append(out, recs[1].seen...)
	}
	return out
}

type chooseReq struct {
	Decision protocol.SeatDecision `json:"decision"`
}

// cardFacts is what gorge's Board reads off one card view, without its id.
func cardFacts(zone string, cv view.CardView) string {
	kw := slices.Clone(cv.Keywords)
	sort.Strings(kw)
	var prod string
	if cv.Produces != nil {
		prod = fmt.Sprint(cv.Produces.Colour, cv.Produces.Any)
	}
	return fmt.Sprintf("%s|%s|%q|%s|%s|%d/%d dmg%d tapped=%v sick=%v att=%v attached=%v blocked=%d kw=%v api=%s prod=%s",
		zone, cv.Name, cv.Types, cv.ManaCost, map[bool]string{true: "facedown"}[cv.FaceDown], cv.Power, cv.Toughness,
		cv.Damage, cv.Tapped, cv.SummonSick && zone == "battlefield", cv.Attacking, cv.AttachedTo != 0, len(cv.BlockedBy), kw, cv.SpellAPI, prod)
}

// facts lists a view's Board-relevant facts as sorted lines.
func facts(v view.View) []string {
	out := []string{fmt.Sprintf("viewer=%d active=%d phase=%s turn=%d", v.Viewer, v.Active, v.Phase, v.Turn)}
	for _, p := range v.Players {
		pool := []string{}
		for k, n := range p.Pool {
			if n != 0 {
				pool = append(pool, fmt.Sprint(k, n))
			}
		}
		sort.Strings(pool)
		out = append(out, fmt.Sprintf("p%d life=%d lib=%d hand=%d pool=%v", p.ID, p.Life, p.LibrarySize, p.HandSize, pool))
		for _, z := range []struct {
			name string
			cvs  []view.CardView
		}{{"hand", p.Hand}, {"battlefield", p.Battlefield}, {"graveyard", p.Graveyard}, {"exile", p.Exile}} {
			for _, cv := range z.cvs {
				out = append(out, fmt.Sprintf("p%d %s", p.ID, cardFacts(z.name, cv)))
			}
		}
	}
	for _, sv := range v.Stack {
		cost := ""
		if sv.Kind == "spell" && sv.Card != nil {
			cost = sv.Card.ManaCost
		}
		out = append(out, fmt.Sprintf("stack %v p%d %s", sv.Kind == "spell", sv.Controller, cost))
	}
	sort.Strings(out)
	return out
}

func TestViewMatchesGorgeViewOnGorgeGames(t *testing.T) {
	reg := testcorpus.Registry(t)
	reqs := gorgeGames(t, 5)
	builders := map[string]*neutral.Builder{}
	var checked, differ int
	diffs := map[string]int{}
	for _, raw := range reqs {
		var q chooseReq
		if err := json.Unmarshal(raw, &q); err != nil {
			t.Fatal(err)
		}
		var p xview.Payload
		if err := json.Unmarshal(q.Decision.Extensions["x_gorge_view_v1"], &p); err != nil {
			t.Fatal(err)
		}
		b := builders[q.Decision.ActingSeat]
		if b == nil {
			b = neutral.NewBuilder(reg)
			builders[q.Decision.ActingSeat] = b
		}
		got, err := b.View(&q.Decision.Observation)
		if err != nil {
			t.Fatal(err)
		}
		want, _ := agent.Rebuild(p)
		g, w := facts(got), facts(want)
		checked++
		if !slices.Equal(g, w) {
			differ++
			for _, l := range w {
				if !slices.Contains(g, l) {
					diffs["want "+l]++
				}
			}
			for _, l := range g {
				if !slices.Contains(w, l) {
					diffs["got  "+l]++
				}
			}
		}
	}
	var lines []string
	for l, n := range diffs {
		lines = append(lines, fmt.Sprintf("%5d %s", n, l))
	}
	sort.Strings(lines)
	if os.Getenv("NEUTRAL_VERBOSE") != "" {
		t.Log(strings.Join(lines, "\n"))
	}
	t.Logf("%d of %d views differ", differ, checked)
	if differ != 0 {
		t.Errorf("%d of %d views differ from gorge's own view; first lines:\n%s", differ, checked, strings.Join(lines[:min(len(lines), 40)], "\n"))
	}
}

// twin forwards every request to a gorge agent reading x_gorge_view_v1 and
// to one translating the bare observation, answers with the first and
// counts agreement by the decision's first candidate kind.
type twin struct {
	view, neutral *agent.Server
	agree, total  map[string]int
	examples      map[string][]string
}

func (tw *twin) Round(req []byte) ([]byte, error) {
	a, _ := tw.view.Round(req)
	b, _ := tw.neutral.Round(req)
	var q struct {
		RequestType string                `json:"request_type"`
		Decision    protocol.SeatDecision `json:"decision"`
	}
	if err := json.Unmarshal(req, &q); err != nil || q.RequestType != "choose" {
		if q.RequestType == "game_start" && !strings.Contains(string(b), `"ack"`) {
			return nil, fmt.Errorf("neutral game_start: %s", b)
		}
		return a, nil
	}
	kind := q.Decision.Candidates[0].Semantic.Kind
	if q.Decision.Context.Kind == "priority" {
		kind = "priority"
	}
	if len(q.Decision.Candidates) == 1 {
		kind += "(single)"
	}
	tw.total[kind]++
	var ca, cb struct {
		Selection struct {
			CandidateID int `json:"candidate_id"`
		} `json:"selection"`
	}
	json.Unmarshal(a, &ca)
	json.Unmarshal(b, &cb)
	if q.Decision.Candidates[ca.Selection.CandidateID].Semantic.Kind == "activate_mana_ability" {
		// gorge's engine has its seats float mana; under engine_autopay the
		// neutral seat never does, so these are not comparable.
		tw.total[kind]--
		tw.total["(gorge floated mana)"]++
		return a, nil
	}
	if ca.Selection.CandidateID == cb.Selection.CandidateID {
		tw.agree[kind]++
	} else if len(tw.examples[kind]) < 3 {
		sa, _ := json.Marshal(q.Decision.Candidates[ca.Selection.CandidateID].Semantic)
		sb, _ := json.Marshal(q.Decision.Candidates[cb.Selection.CandidateID].Semantic)
		tw.examples[kind] = append(tw.examples[kind], fmt.Sprintf("gorge %s\n      neutral %s", sa, sb))
	}
	return a, nil
}

func TestDecisionsMatchGorgeOnGorgeGames(t *testing.T) {
	reg := testcorpus.Registry(t)
	kinds := map[string]bool{}
	for _, k := range server.DecisionKinds {
		kinds[k] = true
	}
	tw := &twin{agree: map[string]int{}, total: map[string]int{}, examples: map[string][]string{}}
	games := 10
	for i := 0; i < games; i++ {
		d := catalog.Decks()[i%len(catalog.Decks())]
		srv := server.New(reg, nil)
		srv.EnableAutoPay()
		h := &minihost.Host{RunSecret: make([]byte, 32), Engine: &minihost.EngineLink{S: srv},
			Profile:  validate.Profile{Kinds: kinds, Flags: observe.Flags, Extensions: map[string]bool{"x_gorge_view_v1": true}},
			MaxSteps: 20000, MaxDecisions: 9999}
		var links [2]minihost.Link
		for s := range links {
			va, _ := agent.New("bot-auto-pay")
			na, _ := agent.New("bot-auto-pay")
			na.SetRegistry(reg)
			if err := na.EnableNeutral(); err != nil {
				t.Fatal(err)
			}
			links[s] = &twinSeat{tw: tw, view: va, neutral: na}
		}
		if _, err := h.Play(uint64(i), d, "london", []string{"x_gorge_view_v1"}, links); err != nil {
			t.Fatalf("game %d (%s): %v", i, d.CatalogID, err)
		}
	}
	var lines []string
	agree, total := 0, 0
	for k, n := range tw.total {
		agree += tw.agree[k]
		total += n
		lines = append(lines, fmt.Sprintf("%-32s %5d/%5d", k, tw.agree[k], n))
		for _, e := range tw.examples[k] {
			lines = append(lines, "    "+e)
		}
	}
	sort.Strings(lines)
	t.Logf("agreement %d/%d\n%s", agree, total, strings.Join(lines, "\n"))
	if floated := tw.total["(gorge floated mana)"]; agree != total-floated {
		t.Errorf("the translated decision disagrees with gorge's own %d times in %d", total-floated-agree, total-floated)
	}
}

// twinSeat binds one seat's pair of agents to the shared tally.
type twinSeat struct {
	tw            *twin
	view, neutral *agent.Server
}

func (s *twinSeat) Round(req []byte) ([]byte, error) {
	s.tw.view, s.tw.neutral = s.view, s.neutral
	return s.tw.Round(req)
}
