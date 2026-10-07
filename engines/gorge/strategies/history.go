package strategies

import (
	"fmt"
	"maps"
	"reflect"

	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/internal/searchprobe"
	"github.com/adams-shaun/gorge/rules"
	"github.com/adams-shaun/gorge/state"
)

const Extension = "x_gorge_search_v1"

// Delta transports owned, actor-redacted frames. Aliases bind the current
// x_gorge_view_v1 IDs to history IDs; neither ID is an engine allocation ID.
type Delta struct {
	Version    int               `json:"version"`
	Actor      state.PlayerID    `json:"actor"`
	From       int               `json:"from"`
	Frames     []Frame           `json:"frames"`
	Answers    map[int][]Action  `json:"answers"`
	Live       bool              `json:"live"`
	StopReason string            `json:"stop_reason"`
	Aliases    map[uint32]uint32 `json:"aliases"`
}

// AppendDelta refuses lost, reordered, or mismatched history. Retrying the
// same native decision is handled by the agent's existing native-index plan.
func AppendDelta(h *History, d Delta) error {
	if d.Version != 1 || d.Actor != h.Actor || d.From != len(h.Frames) {
		return fmt.Errorf("search history delta is out of sequence")
	}
	for _, f := range d.Frames {
		if f.Decision == nil || f.Decision.Player != h.Actor {
			return fmt.Errorf("opponent observation boundary in search history")
		}
	}
	for i, answer := range d.Answers {
		if i < 0 || i >= len(h.Frames)+len(d.Frames) {
			return fmt.Errorf("answer outside actor search history")
		}
		if i < len(h.Frames) && (h.Frames[i].Decision == nil || h.Frames[i].Decision.Player != h.Actor) {
			return fmt.Errorf("answer outside actor search history")
		}
		if old, ok := h.Answers[i]; ok && !reflect.DeepEqual(old, answer) {
			return fmt.Errorf("search history answer changed")
		}
	}
	h.ActorBoundaries = true
	h.Frames = append(h.Frames, d.Frames...)
	if h.Answers == nil {
		h.Answers = map[int][]Action{}
	}
	for i, answer := range d.Answers {
		h.Answers[i] = answer
	}
	return nil
}

type stream struct {
	c             *searchprobe.Collector
	h             History
	pos           int
	stopped       bool
	stopReason    string
	sent, answers int
	cacheIndex    uint64
	cache         *Delta
}

// Driver observes each native ask, including engine-internal and folded asks.
// Its capture/answer loop follows native Feed, with copy identities forgotten
// when knowledge is lost. Delivery coalesces this internal feed into public
// actor boundaries. The wire never carries the internal frame indices.
type Driver struct {
	seats [2]stream
	seq   uint64
}

func NewDriver() *Driver {
	d := &Driver{}
	for i := range d.seats {
		actor := state.PlayerID(i)
		d.seats[i] = stream{c: searchprobe.NewCollector(actor), h: History{Actor: actor, Answers: map[int][]Action{}}}
	}
	return d
}

func (d *Driver) Observe(e *rules.Engine) {
	if e.Pending() == nil || e.Pending().Seq == d.seq {
		return
	}
	d.seq = e.Pending().Seq
	for i := range d.seats {
		s := &d.seats[i]
		if s.stopped {
			continue
		}
		frame, err := s.c.SpellbenchCapture(e, e.L.Events[s.pos:])
		if err != nil {
			s.stopped, s.stopReason = true, "observation_unavailable"
			continue
		}
		s.h.Frames = append(s.h.Frames, frame)
		s.pos = len(e.L.Events)
	}
}

func (d *Driver) RecordAnswer(ask *decision.Decision, in decision.Intent) error {
	s := &d.seats[ask.Player]
	if s.stopped {
		return nil
	}
	answer, err := s.c.Actions(ask, in)
	if err != nil {
		return err
	}
	s.h.Answers[len(s.h.Frames)-1] = answer
	return nil
}

func (d *Driver) Alias(actor state.PlayerID, id state.ObjID) uint32 {
	return d.seats[actor].c.SpellbenchAlias(id)
}

func (d *Driver) Delta(actor state.PlayerID, index uint64, aliases map[uint32]uint32) Delta {
	s := &d.seats[actor]
	if s.cache != nil && s.cacheIndex == index {
		return *s.cache
	}
	public := PublicHistory(s.h)
	out := Delta{Version: 1, Actor: actor, From: s.sent, Frames: public.Frames[s.sent:], Answers: map[int][]Action{},
		Live: !s.stopped, StopReason: s.stopReason, Aliases: aliases}
	for i, a := range public.Answers {
		if i >= s.answers {
			out.Answers[i] = a
		}
	}
	s.sent = len(public.Frames)
	s.answers = max(0, s.sent-1) // the last frame may be answered after this payload
	s.cacheIndex, s.cache = index, &out
	return out
}

func (d *Driver) Clone() *Driver {
	c := *d
	for i := range c.seats {
		s := &c.seats[i]
		s.c = s.c.Clone()
		s.h.Frames = append([]Frame(nil), s.h.Frames...)
		s.h.Answers = maps.Clone(s.h.Answers)
		// Stored frames, action slices and delivered deltas are immutable.
	}
	return &c
}

// PublicNames are names this actor already saw in its public history. The
// qualification's literal-name scanner must not call remembered facts a leak.
func (d *Driver) PublicNames(actor state.PlayerID) map[string]bool {
	out := map[string]bool{}
	for _, f := range PublicHistory(d.seats[actor].h).Frames {
		for _, id := range f.Identities {
			if id.Name != "" {
				out[id.Name] = true
			}
		}
	}
	return out
}
