package session_test

import (
	"math/rand/v2"
	"slices"
	"testing"

	"github.com/adams-shaun/gorge/cards"
	"github.com/adams-shaun/gorge/decision"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/catalog"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/secrets"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/session"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/testcorpus"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/xview"
)

func startAudited(t *testing.T, deck string, maxSteps uint64) *session.Game {
	t.Helper()
	return startConfig(t, deck, maxSteps, session.Config{Reg: testcorpus.Registry(t), Ext: xview.New(), Audit: true})
}

func startExtended(t *testing.T, deck string, maxSteps uint64) *session.Game {
	t.Helper()
	return startConfig(t, deck, maxSteps, session.Config{Reg: testcorpus.Registry(t), Ext: xview.New()})
}

func startConfig(t *testing.T, deck string, maxSteps uint64, cfg session.Config) *session.Game {
	t.Helper()
	d, _ := catalog.ByID(deck)
	cs, err := catalog.Resolve(cfg.Reg, d)
	if err != nil {
		t.Fatal(err)
	}
	seat := "p0"
	req := &protocol.ResetReq{GameID: "g-w", Format: "pauper-bo1", MaxDecisions: 100000, MaxSteps: maxSteps,
		Rules: protocol.Rules{Mulligan: "london", StartingPlayer: "host_assigned", StartingSeat: &seat, Names: catalog.PoolNames()}}
	g, err := session.Start(cfg, "g-w", req, secrets.NewGame(make([]byte, 32)), [2][]*cards.Card{cs, cs})
	if err != nil {
		t.Fatal(err)
	}
	return g
}

// phaseRank orders phase_step values after declare_blockers, so a pose past
// the declare_blockers step proves the turn's combat damage was assigned.
var phaseRank = map[string]int{"untap": 0, "upkeep": 1, "draw": 2, "precombat_main": 3,
	"beginning_of_combat": 4, "declare_attackers": 5, "declare_blockers": 6, "combat_damage": 7,
	"end_of_combat": 8, "postcombat_main": 9, "end_step": 10, "cleanup": 11}

// divisionNeeding mirrors gorge rules.divisionNeeding from the public
// observation: a non-trample attacker with power above zero and two or more
// live blockers, whose legal divisions fit the engine's 128-option bound.
func divisionNeeding(obs protocol.Observation) (out []string) {
	blockedBy := map[string][]string{} // attacker object_id -> live blocker ids
	power := map[string]int32{}
	trample := map[string]bool{}
	for _, p := range obs.Players {
		for _, bf := range p.Battlefield {
			if bf.Permanent == nil {
				continue
			}
			for _, a := range bf.Permanent.BlockedAttackers {
				blockedBy[a.ObjectID] = append(blockedBy[a.ObjectID], bf.ObjectID)
			}
			if bf.Permanent.Attacking && bf.Characteristics != nil && bf.Characteristics.Power != nil {
				power[bf.ObjectID] = *bf.Characteristics.Power
				trample[bf.ObjectID] = slices.Contains(bf.Characteristics.Keywords, "trample")
			}
		}
	}
	for a, bs := range blockedBy {
		if len(bs) < 2 || power[a] <= 0 || trample[a] {
			continue
		}
		// C(power+n-1, n-1), saturating above gorge's maxDivisionOptions 128.
		n, pw := len(bs), int(power[a])
		k, total := n-1, pw+n-1
		if k > total-k {
			k = total - k
		}
		count := int64(1)
		for i := 0; i < k && count <= 128; i++ {
			count = count * int64(total-i) / int64(i+1)
		}
		if count <= 128 {
			out = append(out, a)
		}
	}
	return out
}

// Task 16's parked acceptance item: the audited live runs must witness a
// declare_block candidate answered (the consistency audit's declare_block
// branch) and a combat damage division answered (the engine-order internal
// answer, whose failure would halt the game), in uniform games of the five
// catalog decks — not only in fixtures.
func TestAuditedUniformGamesWitnessBlocksAndDivisions(t *testing.T) {
	blocks, realizedBlocks, divisions := 0, 0, 0
	for _, deck := range []string{"Wildfire", "Rally", "Spy", "Burn", "CawGates"} {
		g := startAudited(t, deck, 4000)
		r := rand.New(rand.NewPCG(3, 7))
		pending := map[string]bool{} // divisionNeeding attackers of this turn's last declare_blockers pose
		turn := uint32(0)
		deckBlocks, deckDivisions := 0, 0
		for {
			dec, term := g.Pending()
			if term != nil {
				if term.Classification == "halted" {
					t.Fatalf("%s halted: %s", deck, term.Reason)
				}
				break
			}
			obs := dec.SeatDecision.Observation
			if obs.Turn != turn {
				pending, turn = map[string]bool{}, obs.Turn
			}
			switch {
			case phaseRank[obs.PhaseStep] == 6:
				pending = map[string]bool{} // recompute at every pose; the last one before damage stands
				for _, a := range divisionNeeding(obs) {
					pending[a] = true
				}
			case phaseRank[obs.PhaseStep] > 6 && len(pending) > 0:
				// The turn passed damage assignment with these attackers
				// double-blocked: gorge posed each division and the session
				// answered it internally, or the game would have halted.
				deckDivisions += len(pending)
				pending = map[string]bool{}
			}
			k := r.IntN(len(dec.SeatDecision.Candidates))
			c := dec.SeatDecision.Candidates[k]
			if c.Semantic.Kind == "declare_block" {
				if a, _ := c.Semantic.Fields["attacker"].(*protocol.ObjectRef); a != nil {
					deckBlocks++ // a real block answer: the audit's declare_block branch ran
				}
			}
			if perr := g.Step(&protocol.StepReq{GameID: "g-w", ExpectedStep: dec.Step, CandidateID: uint64(k),
				Echo: echo(t, c.Semantic)}); perr != nil {
				t.Fatalf("%s: %v", deck, perr)
			}
		}
		if g.Leaks() != 0 || g.Inconsistent() != 0 {
			t.Fatalf("%s: %d leak-scan hits, %d inconsistent candidates", deck, g.Leaks(), g.Inconsistent())
		}
		realized := 0
		for _, rl := range g.Realized() {
			if rl.Kind == decision.KBlockers {
				realized++
			}
		}
		t.Logf("%s: %d answered declare_block candidates, %d realized block decisions, %d answered divisions",
			deck, deckBlocks, realized, deckDivisions)
		blocks += deckBlocks
		realizedBlocks += realized
		divisions += deckDivisions
	}
	if blocks == 0 || realizedBlocks == 0 {
		t.Fatalf("no declare_block witness in live audited games: %d answered candidates, %d realized block decisions",
			blocks, realizedBlocks)
	}
	if divisions == 0 {
		t.Fatal("no combat damage division was answered in live audited games")
	}
}
