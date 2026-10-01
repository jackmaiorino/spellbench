package xview

import (
	"strconv"

	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/state"
	"github.com/adams-shaun/gorge/view"
)

type rekeyer func(state.ObjID) state.ObjID

func (r rekeyer) card(cv *view.CardView) {
	cv.ID = r(cv.ID)
	cv.Token = "#" + strconv.FormatUint(uint64(cv.ID), 10)
	if cv.AttachedTo != 0 {
		cv.AttachedTo = r(cv.AttachedTo)
	}
	for i := range cv.BlockedBy {
		cv.BlockedBy[i] = r(cv.BlockedBy[i])
	}
}

func (r rekeyer) cards(cvs []view.CardView) {
	for i := range cvs {
		r.card(&cvs[i])
	}
}

func (r rekeyer) view(v *view.View) {
	for pi := range v.Players {
		p := &v.Players[pi]
		for _, z := range [][]view.CardView{p.Hand, p.Battlefield, p.Graveyard, p.Exile, p.Command, p.Commanders, p.PlanarDeck} {
			r.cards(z)
		}
		if p.LibraryTop != nil {
			r.card(p.LibraryTop)
		}
		for i := range p.PotentialActions {
			if p.PotentialActions[i].Obj != 0 {
				p.PotentialActions[i].Obj = r(p.PotentialActions[i].Obj)
			}
		}
		if p.CmdDamage != nil {
			m := map[state.ObjID]int32{}
			for id, v := range p.CmdDamage {
				m[r(id)] = v
			}
			p.CmdDamage = m
		}
	}
	for i := range v.Stack {
		s := &v.Stack[i]
		s.ID = r(s.ID)
		if s.Source != 0 {
			s.Source = r(s.Source)
		}
		for j := range s.Targets {
			if s.Targets[j].Obj != 0 {
				s.Targets[j].Obj = r(s.Targets[j].Obj)
			}
		}
		if s.Card != nil {
			r.card(s.Card)
		}
	}
	for i := range v.Pending {
		v.Pending[i].Source = r(v.Pending[i].Source)
	}
	v.Decision = nil // carried separately in Payload.Decision
}

func (r rekeyer) decision(d *decision.Decision, seq uint64) {
	d.Seq = seq
	d.PaymentActions, d.PaymentFallback = nil, nil
	if d.Source != 0 {
		d.Source = r(d.Source)
	}
	for i := range d.Options {
		o := &d.Options[i]
		for _, p := range []*state.ObjID{&o.Obj, &o.Attacker, &o.Battle} {
			if *p != 0 {
				*p = r(*p)
			}
		}
	}
}
