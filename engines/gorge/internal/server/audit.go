package server

import (
	"math/rand/v2"

	"github.com/jackmaiorino/spellbench/engines/gorge/internal/session"
)

// SetAudit turns the qualification audit on for games reset afterwards.
func (s *Server) SetAudit(on bool) { s.audit = on }

// Leaks, Inconsistent, Realized and ResampleCheck report on the current game.
func (s *Server) Leaks() int {
	if s.game == nil {
		return 0
	}
	return s.game.Leaks()
}

func (s *Server) Inconsistent() int {
	if s.game == nil {
		return 0
	}
	return s.game.Inconsistent()
}

func (s *Server) Realized() []session.Realized {
	if s.game == nil {
		return nil
	}
	return s.game.Realized()
}

func (s *Server) ResampleCheck(r *rand.Rand) error {
	if s.game == nil {
		return nil
	}
	return s.game.ResampleCheck(r)
}
