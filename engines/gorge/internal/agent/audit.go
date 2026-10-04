package agent

// SearchCoverage records observed work, without views, decisions, intents or
// sampled worlds. The qualification command and real subprocess use one fold.
type SearchCoverage struct {
	Natives, Eligible, Attempted, Covered                                                                      int
	Attempts, Accepted, Worlds, Rollouts, Submits, Terminal, Capped                                            int
	Redealt, ReconstructionAttempts, ReconstructionSubmits, ReconstructionNodes, ReconstructionBudgetExhausted int
	RedealRefusals, Reasons, Kinds                                                                             map[string]int
}

func (s SearchCoverage) Pass() bool { return s.Eligible > 0 && s.Covered > 0 }

func SummarizeSearch(records map[uint64]*Record) SearchCoverage {
	out := SearchCoverage{Reasons: map[string]int{}, Kinds: map[string]int{}, RedealRefusals: map[string]int{}}
	for _, rec := range records {
		tr := rec.Search
		if tr == nil {
			continue
		}
		out.Natives++
		if rec.SearchEligible {
			out.Eligible++
		}
		if tr.Attempts > 0 {
			out.Attempted++
		}
		if tr.Covered {
			out.Covered++
			out.Kinds[tr.Kind]++
		}
		out.Attempts += tr.Attempts
		out.Accepted += tr.Accepted
		out.Worlds += tr.Worlds
		out.Rollouts += tr.Rollouts
		out.Submits += tr.Submits
		out.Terminal += tr.Terminal
		out.Capped += tr.Capped
		out.Redealt += tr.Redealt
		if tr.PublicReconstruction != nil {
			out.ReconstructionAttempts += tr.PublicReconstruction.Attempts
			out.ReconstructionSubmits += tr.PublicReconstruction.Submits
			out.ReconstructionNodes += tr.PublicReconstruction.Nodes
			out.ReconstructionBudgetExhausted += tr.PublicReconstruction.BudgetExhausted
		}
		if tr.RedealRefused != "" {
			out.RedealRefusals[tr.RedealRefused]++
		}
		if rec.SearchEligible && !tr.Covered {
			reason := tr.Fallback
			if reason == "" {
				reason = "fewer_than_two_candidates"
			}
			out.Reasons[reason]++
		}
	}
	return out
}

type PolicyAudit struct {
	Schema                           string `json:"schema"`
	Policy                           string `json:"policy"`
	BotName                          string `json:"bot_name"`
	Version                          string `json:"version"`
	GameID                           string `json:"game_id"`
	Seat                             string `json:"seat"`
	GameStarted                      bool   `json:"game_started"`
	GameOverReceived                 bool   `json:"game_over_received"`
	NativeDecisions                  int    `json:"native_decisions"`
	ForcedNatives, FallbackNatives   int
	ForcedSubsteps, FallbackSubsteps int
	Search                           SearchCoverage `json:"search"`
}

// Audit contains only public session labels and aggregate adapter/search work.
// It neither reads an engine nor serializes the records' underlying objects.
func (s *Server) Audit() PolicyAudit {
	a := PolicyAudit{Schema: "spellbench-gorge-policy-audit/v1", Policy: s.policy,
		BotName: s.identity.Name, Version: Version, GameID: s.gameID, Seat: s.auditSeat,
		GameStarted: s.bot != nil, GameOverReceived: s.gameOverReceived,
		NativeDecisions: len(s.records), Search: SummarizeSearch(s.records)}
	for _, r := range s.records {
		if r.Forced > 0 {
			a.ForcedNatives++
		}
		if r.Fallbacks > 0 {
			a.FallbackNatives++
		}
		a.ForcedSubsteps += r.Forced
		a.FallbackSubsteps += r.Fallbacks
	}
	return a
}
