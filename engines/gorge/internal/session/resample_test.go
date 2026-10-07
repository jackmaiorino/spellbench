package session_test

import (
	"math/rand/v2"
	"testing"

	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
)

func TestResamplingHiddenStateNeverChangesTheSeatDecision(t *testing.T) {
	for _, deck := range []string{"Wildfire", "Rally", "Spy", "Burn", "CawGates"} {
		g := start(t, deck, 2000)
		r := rand.New(rand.NewPCG(1, 2))
		for n := 0; n < 400; n++ {
			dec, term := g.Pending()
			if term != nil {
				if term.Classification == "halted" {
					t.Fatalf("%s halted: %s", deck, term.Reason)
				}
				break
			}
			if n%7 == 0 {
				if err := g.ResampleCheck(r); err != nil {
					t.Fatalf("%s step %d: %v", deck, dec.Step, err)
				}
			}
			k := r.IntN(len(dec.SeatDecision.Candidates))
			if perr := g.Step(&protocol.StepReq{GameID: "g-t", ExpectedStep: dec.Step, CandidateID: uint64(k),
				Echo: echo(t, dec.SeatDecision.Candidates[k].Semantic)}); perr != nil {
				t.Fatal(perr)
			}
		}
	}
}

// The same self-check with x_gorge_view_v1 wired in: the twin rebuilds the
// extension from the cloned id tables, and the whole seat decision —
// extension included — must still be byte-equal (Task 24's re-extension path
// under the resample check).
func TestResamplingWithExtensionNeverChangesTheSeatDecision(t *testing.T) {
	for _, deck := range []string{"Wildfire", "Rally", "Spy", "Burn", "CawGates"} {
		g := startAudited(t, deck, 2000)
		r := rand.New(rand.NewPCG(5, 6))
		for n := 0; n < 400; n++ {
			dec, term := g.Pending()
			if term != nil {
				if term.Classification == "halted" {
					t.Fatalf("%s halted: %s", deck, term.Reason)
				}
				break
			}
			if n%7 == 0 {
				if err := g.ResampleCheck(r); err != nil {
					t.Fatalf("%s step %d: %v", deck, dec.Step, err)
				}
			}
			k := r.IntN(len(dec.SeatDecision.Candidates))
			if perr := g.Step(&protocol.StepReq{GameID: "g-w", ExpectedStep: dec.Step, CandidateID: uint64(k),
				Echo: echo(t, dec.SeatDecision.Candidates[k].Semantic)}); perr != nil {
				t.Fatal(perr)
			}
		}
		if g.Leaks() != 0 || g.Inconsistent() != 0 {
			t.Fatalf("%s: %d leak-scan hits, %d inconsistent candidates", deck, g.Leaks(), g.Inconsistent())
		}
	}
}

// The audits report; they never alter the game. The same uniform answer
// stream over an audited and a plain session, both extended, must walk the
// identical engine history (the event log head matches at every step) to the
// same terminal.
func TestAuditNeverChangesTheGame(t *testing.T) {
	for _, deck := range []string{"Wildfire", "Rally", "Spy", "Burn", "CawGates"} {
		plain, audited := startExtended(t, deck, 2000), startAudited(t, deck, 2000)
		r := rand.New(rand.NewPCG(7, 8))
		for n := 0; n < 400; n++ {
			pd, pt := plain.Pending()
			ad, at := audited.Pending()
			if (pt == nil) != (at == nil) {
				t.Fatalf("%s step %d: plain and audited games diverged on termination", deck, n)
			}
			if pt != nil {
				if pt.Classification != at.Classification || pt.Outcome != at.Outcome || pt.Reason != at.Reason ||
					pt.StepCount != at.StepCount || pt.DecisionCount != at.DecisionCount {
					t.Fatalf("%s: terminals %+v and %+v", deck, pt, at)
				}
				break
			}
			if plain.EngineHead() != audited.EngineHead() {
				t.Fatalf("%s step %d: the audit changed the engine history", deck, pd.Step)
			}
			if len(pd.SeatDecision.Candidates) != len(ad.SeatDecision.Candidates) {
				t.Fatalf("%s step %d: the audit changed the candidates", deck, pd.Step)
			}
			k := r.IntN(len(pd.SeatDecision.Candidates))
			echoK := echo(t, pd.SeatDecision.Candidates[k].Semantic)
			if perr := plain.Step(&protocol.StepReq{GameID: "g-t", ExpectedStep: pd.Step, CandidateID: uint64(k), Echo: echoK}); perr != nil {
				t.Fatalf("%s plain: %v", deck, perr)
			}
			if perr := audited.Step(&protocol.StepReq{GameID: "g-w", ExpectedStep: ad.Step, CandidateID: uint64(k), Echo: echoK}); perr != nil {
				t.Fatalf("%s audited: %v", deck, perr)
			}
		}
	}
}
