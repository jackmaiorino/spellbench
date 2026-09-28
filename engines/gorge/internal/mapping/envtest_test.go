package mapping_test

import (
	"testing"

	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/rules"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/gamecfg"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/identity"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/mapping"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/observe"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/testcorpus"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/testgame"
)

func envFor(t *testing.T, g *gamecfg.Game) *mapping.Env {
	tr := identity.New(g.E, g.Secret)
	if err := tr.Sync(g.E); err != nil {
		t.Fatal(err)
	}
	return &mapping.Env{G: g, IDs: tr, Obs: &observe.Projector{E: g.E, IDs: tr}, Slots: map[string]uint32{}}
}

// untilPending plays bots (no mulligans) until a pending decision satisfies pred.
func untilPending(t *testing.T, deck string, secret byte, pred func(*decision.Decision, *rules.Engine) bool) *gamecfg.Game {
	return untilPendingRules(t, deck, secret, "none", pred)
}

// untilPendingRules is untilPending with the mulligan rule ("london" or "none").
func untilPendingRules(t *testing.T, deck string, secret byte, mulligan string, pred func(*decision.Decision, *rules.Engine) bool) *gamecfg.Game {
	reg := testcorpus.Registry(t)
	for s := secret; s < secret+20; s++ {
		g := testgame.New(t, reg, deck, deck, s, mulligan)
		if testgame.RunUntil(t, g, testgame.Bots(uint64(s)), func(e *rules.Engine) bool {
			d := e.Pending()
			return d != nil && pred(d, e)
		}, 30000) {
			return g
		}
	}
	t.Fatalf("no %s game reached the wanted decision", deck)
	return nil
}

// answerAll drives a transaction to completion picking candidate pick(pose).
func answerAll(t *testing.T, tx mapping.Transaction, pick func(*mapping.Pose) int) []decision.Intent {
	var commits []decision.Intent
	for {
		p, err := tx.Pose()
		if err != nil {
			t.Fatal(err)
		}
		c, done, err := tx.Answer(pick(p))
		if err != nil {
			t.Fatal(err)
		}
		commits = append(commits, c...)
		if done {
			return commits
		}
	}
}
