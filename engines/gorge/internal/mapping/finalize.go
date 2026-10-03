package mapping

import (
	"encoding/json"
	"fmt"
	"sort"
)

// Finalize applies Section 7.1: candidates referencing hidden-zone cards are
// ordered among themselves by (card_name, object_id); pass is candidate 0;
// semantics are pairwise distinct; at most 4096 candidates.
func Finalize(p *Pose) error {
	var slots []int
	var hidden []Cand
	for i, c := range p.Candidates {
		if c.Hidden {
			slots = append(slots, i)
			hidden = append(hidden, c)
		}
	}
	sort.SliceStable(hidden, func(i, j int) bool {
		if hidden[i].SortName != hidden[j].SortName {
			return hidden[i].SortName < hidden[j].SortName
		}
		return hidden[i].SortID < hidden[j].SortID
	})
	for k, i := range slots {
		p.Candidates[i] = hidden[k]
	}
	for i, c := range p.Candidates {
		if c.Sem.Kind == "pass" && i != 0 {
			p.Candidates = append([]Cand{c}, append(p.Candidates[:i:i], p.Candidates[i+1:]...)...)
			break
		}
	}
	if len(p.Candidates) == 0 {
		return ErrDeadEnd
	}
	if len(p.Candidates) > 4096 {
		return ErrCandidateLimit
	}
	seen := map[string]bool{}
	for _, c := range p.Candidates {
		b, err := json.Marshal(c.Sem)
		if err != nil {
			return err
		}
		if seen[string(b)] {
			return fmt.Errorf("%w: %s", ErrDuplicate, b)
		}
		seen[string(b)] = true
	}
	return nil
}
