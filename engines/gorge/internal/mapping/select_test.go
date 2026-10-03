package mapping_test

import (
	"slices"
	"strings"
	"testing"

	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/rules"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/mapping"
)

func TestSearchCandidatesAreSortedAndKnown(t *testing.T) {
	g := untilPending(t, "Wildfire", 1, func(d *decision.Decision, e *rules.Engine) bool {
		return d.Kind == decision.KChoose && len(d.Options) > 1 && d.Options[0].Kind == "search"
	})
	env := envFor(t, g)
	tx, _ := mapping.Begin(env, g.E.Pending())
	p, err := tx.Pose()
	if err != nil {
		t.Fatal(err)
	}
	var prev string
	finish := false
	for _, c := range p.Candidates {
		switch c.Sem.Kind {
		case "finish_selection":
			finish = true
		case "select_object":
			if c.Sem.Fields["purpose"] != "search" {
				t.Fatalf("purpose %v", c.Sem.Fields["purpose"])
			}
			key := c.SortName + "\x00" + c.SortID
			if key < prev {
				t.Fatalf("hidden candidates out of (name, id) order")
			}
			prev = key
		}
	}
	if !finish || len(p.Known) == 0 || p.Known[0].How != "searching" || p.Known[0].PositionFromTop != nil {
		t.Fatalf("finish %v known %+v", finish, p.Known)
	}
}

// gorge offers only Thraben Charm's eligible modes; each candidate still
// names the printed mode and the printed count of three (G2-10).
func TestModalSpellNamesPrintedModes(t *testing.T) {
	printed := func(e *rules.Engine, d *decision.Decision) []string {
		var out []string
		for _, c := range strings.Split(e.G.Obj(d.Source).Face().SpellAbility().Params["Choices"], ",") {
			out = append(out, strings.TrimSpace(c))
		}
		return out
	}
	g := untilPending(t, "CawGates", 17, func(d *decision.Decision, e *rules.Engine) bool {
		if d.Kind != decision.KModes || e.G.Obj(d.Source) == nil || e.G.Obj(d.Source).Face().Name != "Thraben Charm" {
			return false
		}
		return len(d.ResumeModes) > 0 && d.ResumeModes[0] != printed(e, d)[0] // the first printed mode was filtered out
	})
	env := envFor(t, g)
	d := g.E.Pending()
	names := printed(g.E, d)
	tx, _ := mapping.Begin(env, d)
	p, err := tx.Pose()
	if err != nil {
		t.Fatal(err)
	}
	for _, c := range p.Candidates {
		if c.Sem.Kind != "choose_spell_mode" {
			continue
		}
		want := uint32(slices.Index(names, d.ResumeModes[c.Op.Option]))
		if c.Sem.Fields["mode_index"] != want || c.Sem.Fields["mode_count"] != uint32(3) {
			t.Fatalf("option %d: %+v, want mode_index %d of 3", c.Op.Option, c.Sem.Fields, want)
		}
	}
}
