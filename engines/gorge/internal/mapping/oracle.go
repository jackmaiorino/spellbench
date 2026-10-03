package mapping

import "github.com/adams-shaun/gorge/decision"

// Accepts reports whether the engine accepts the intent sequence, judged on a
// clone (Decision.Validate first, as the cheap filter).
func Accepts(env *Env, ins ...decision.Intent) bool {
	if len(ins) > 0 {
		if d := env.G.E.Pending(); d != nil && d.Validate(ins[0]) != nil {
			return false
		}
	}
	_, err := env.G.Probe(ins...)
	return err == nil
}
