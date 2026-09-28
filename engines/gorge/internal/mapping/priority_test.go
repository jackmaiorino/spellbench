package mapping_test

import (
	"testing"

	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/rules"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/mapping"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
)

func hasOption(d *decision.Decision, kind, mode string) bool {
	for _, o := range d.Options {
		if o.Kind == kind && o.Mode == mode {
			return true
		}
	}
	return false
}

func TestPriorityPassFirstAndNoConcede(t *testing.T) {
	g := untilPending(t, "Burn", 1, func(d *decision.Decision, e *rules.Engine) bool {
		return d.Kind == decision.KPriority && hasOption(d, "cast", "")
	})
	env := envFor(t, g)
	tx, err := mapping.Begin(env, g.E.Pending())
	if err != nil {
		t.Fatal(err)
	}
	p, err := tx.Pose()
	if err != nil {
		t.Fatal(err)
	}
	if p.Candidates[0].Sem.Kind != "pass" || p.Context.Kind != "priority" {
		t.Fatalf("first candidate %s context %s", p.Candidates[0].Sem.Kind, p.Context.Kind)
	}
	for _, c := range p.Candidates {
		if c.Sem.Kind == "cast_spell" && c.Sem.Fields["method"] != "normal" && c.Sem.Fields["method"] != "flashback" {
			t.Errorf("unexpected method %v", c.Sem.Fields["method"])
		}
	}
}

func TestKickerBecomesAFollowUpOptionalCost(t *testing.T) {
	g := untilPending(t, "Rally", 1, func(d *decision.Decision, e *rules.Engine) bool {
		return d.Kind == decision.KPriority && hasOption(d, "cast", "kicked")
	})
	env := envFor(t, g)
	d := g.E.Pending()
	tx, _ := mapping.Begin(env, d)
	p, _ := tx.Pose()
	cast := -1
	for i, c := range p.Candidates {
		if c.Sem.Kind == "cast_spell" && *c.Sem.Fields["source"].(protocol.ObjectRef).CardName == "Goblin Bushwhacker" {
			cast = i
		}
	}
	if cast < 0 {
		t.Fatal("no cast_spell for Goblin Bushwhacker")
	}
	commit, done, err := tx.Answer(cast)
	if err != nil || done || commit != nil {
		t.Fatalf("after cast: commit %v done %v err %v", commit, done, err)
	}
	f, _ := tx.Pose()
	if !f.GroupStart || f.Context.Kind != "choice" || f.Candidates[0].Sem.Kind != "optional_cost" || f.Candidates[0].Sem.Fields["cost"] != "kicker" {
		t.Fatalf("follow-up %+v", f.Candidates)
	}
	for i, c := range f.Candidates {
		if c.Sem.Fields["pay"] == true {
			commit, done, _ = tx.Answer(i)
		}
	}
	if !done || len(commit) != 1 || d.Options[commit[0].Choices[0]].Mode != "kicked" {
		t.Fatalf("kicked commit %v", commit)
	}
}

func TestCastMethodTable(t *testing.T) {
	for _, c := range []struct {
		opt                      decision.Option
		altMode                  string
		method, optional, action string
	}{
		{decision.Option{Kind: "cast"}, "", "normal", "", ""},
		{decision.Option{Kind: "cast", Mode: "kicked"}, "", "normal", "kicker", ""},
		{decision.Option{Kind: "cast", AltCostIndex: 1}, "", "alternative", "", ""},
		{decision.Option{Kind: "cast", Mode: "adventure_alt"}, "Adventure", "adventure", "", ""},
		{decision.Option{Kind: "cast", Mode: "adventure_alt"}, "Omen", "other", "", ""}, // Roost Seek
		{decision.Option{Kind: "cast", Mode: "plot"}, "", "", "", "plot"},
	} {
		m, o, a, ok := mapping.CastMethod(c.opt, c.altMode)
		if !ok || m != c.method || o != c.optional || a != c.action {
			t.Errorf("%+v %s: %q %q %q %v", c.opt, c.altMode, m, o, a, ok)
		}
	}
	if _, _, _, ok := mapping.CastMethod(decision.Option{Kind: "cast", Mode: "multikicked"}, ""); ok {
		t.Error("multikicker is mapped; it must fail closed")
	}
}
