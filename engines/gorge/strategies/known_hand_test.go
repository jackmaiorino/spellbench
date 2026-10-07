package strategies

import (
	"encoding/json"
	"reflect"
	"testing"

	"github.com/adams-shaun/gorge/events"
	"github.com/adams-shaun/gorge/internal/searchprobe"
	"github.com/adams-shaun/gorge/rules"
	"github.com/adams-shaun/gorge/state"
)

// Logged public returns and hidden draws are knowledge boundary fixtures.
// They do not claim to be naturally played complete games.
func returnedKnownOpponentHand(t *testing.T) (*rules.Engine, PublicGame, *searchprobe.Collector, History, state.ObjID, uint32) {
	t.Helper()
	e, setup, c, h, id, _ := shuffledKnownLibrary(t, 1)
	for _, move := range []events.Event{
		{Kind: events.MoveZone, Obj: id, Player: 1, From: state.ZLibrary, To: state.ZGraveyard},
		{Kind: events.MoveZone, Obj: id, Player: 0, From: state.ZGraveyard, To: state.ZHand},
	} {
		pos := len(e.L.Events)
		events.Emit(e.G, e.L, move)
		f, err := c.SpellbenchCapture(e, e.L.Events[pos:])
		if err != nil {
			t.Fatal(err)
		}
		h.Frames = append(h.Frames, f)
	}
	old := c.SpellbenchAlias(id)
	if old == 0 {
		t.Fatal("publicly returned card has no observer identity")
	}
	return e, setup, c, h, id, old
}

func TestPublicKnownHandKeepsNameWithoutRetiredCopyAfterHiddenDraw(t *testing.T) {
	e, setup, c, h, id, old := returnedKnownOpponentHand(t)
	pos := len(e.L.Events)
	drawn := e.G.Zone(state.ZLibrary, 1)[0]
	events.Emit(e.G, e.L, events.Event{Kind: events.Draw, Obj: drawn, Player: 1, From: state.ZLibrary, To: state.ZHand, Secret: true})
	f, err := c.SpellbenchCapture(e, e.L.Events[pos:])
	if err != nil {
		t.Fatal(err)
	}
	h.Frames = append(h.Frames, f)
	if c.SpellbenchAlias(id) != 0 {
		t.Fatal("hidden mixing retained an opponent copy link")
	}
	known, err := searchprobe.ProjectKnownCards(h)
	if err != nil {
		t.Fatal(err)
	}
	want := []searchprobe.SpellbenchHandMinimum{{Player: 1, Name: "Goblin Piker", Count: 1}}
	if !reflect.DeepEqual(known.SpellbenchAnonymousHands, want) {
		t.Fatalf("known hand names = %+v, want %+v", known.SpellbenchAnonymousHands, want)
	}
	for _, hand := range known.Hands {
		for _, card := range hand.Cards {
			if card.ID == old {
				t.Fatal("retired copy remains a physical hand claim")
			}
		}
	}
	if err := known.Holds(searchprobe.World{Engine: e, Observer: c}); err != nil {
		t.Fatal(err)
	}
	bad := e.CloneHypothetical(83)
	events.Emit(bad.G, bad.L, events.Event{Kind: events.MoveZone, Obj: id, Player: 1, From: state.ZHand, To: state.ZLibrary})
	if known.Holds(searchprobe.World{Engine: bad, Observer: c}) == nil {
		t.Fatal("a world missing the known hand name passed")
	}
	for i := 0; i+1 < len(h.Frames); i++ {
		h.Frames[i].Decision = nil
	}
	h = PublicHistory(h)
	result, err := searchprobe.Sample(setup, h, searchprobe.SampleOptions{Seed: 54321, Attempts: 2, Worlds: 16, MaxSubmits: 30,
		Redeal: &searchprobe.RedealBase{Engine: e, Observer: c}})
	if err != nil || result.Accepted != 0 || result.Redealt != 16 || result.RedealRefused != "" {
		t.Fatalf("anonymous hand redeal failed: %v %+v", err, result)
	}
	for _, world := range result.Worlds {
		if err := known.Holds(world); err != nil {
			t.Fatal(err)
		}
		if world.Observer.SpellbenchAlias(id) != 0 {
			t.Fatal("redeal restored a retired wire copy link")
		}
	}
}

func TestPublicKnownHandDoesNotDistinguishHiddenDrawnCopies(t *testing.T) {
	a, _, ca, ha, _, _ := returnedKnownOpponentHand(t)
	b, _, cb, hb, _, _ := returnedKnownOpponentHand(t)
	draws := []state.ObjID{a.G.Zone(state.ZLibrary, 1)[0], b.G.Zone(state.ZLibrary, 1)[1]}
	if draws[0] == draws[1] {
		t.Fatal("fixture must draw different physical cards")
	}
	for i, branch := range []struct {
		e *rules.Engine
		c *searchprobe.Collector
		h *History
	}{{a, ca, &ha}, {b, cb, &hb}} {
		pos := len(branch.e.L.Events)
		events.Emit(branch.e.G, branch.e.L, events.Event{Kind: events.Draw, Obj: draws[i], Player: 1, From: state.ZLibrary, To: state.ZHand, Secret: true})
		f, err := branch.c.SpellbenchCapture(branch.e, branch.e.L.Events[pos:])
		if err != nil {
			t.Fatal(err)
		}
		branch.h.Frames = append(branch.h.Frames, f)
	}
	wa, _ := json.Marshal(ha)
	wb, _ := json.Marshal(hb)
	if string(wa) != string(wb) {
		t.Fatal("public histories distinguish hidden drawn copies")
	}
	ka, err := searchprobe.ProjectKnownCards(ha)
	if err != nil {
		t.Fatal(err)
	}
	kb, err := searchprobe.ProjectKnownCards(hb)
	if err != nil || !reflect.DeepEqual(ka, kb) {
		t.Fatal("knowledge distinguishes hidden drawn copies")
	}
}

func TestPublicKnownHandConsumesVisibleExitAfterMixing(t *testing.T) {
	e, _, c, h, id, _ := returnedKnownOpponentHand(t)
	for _, move := range []events.Event{
		{Kind: events.Draw, Obj: e.G.Zone(state.ZLibrary, 1)[0], Player: 1, From: state.ZLibrary, To: state.ZHand, Secret: true},
		{Kind: events.MoveZone, Obj: id, Player: 1, From: state.ZHand, To: state.ZGraveyard},
	} {
		pos := len(e.L.Events)
		events.Emit(e.G, e.L, move)
		f, err := c.SpellbenchCapture(e, e.L.Events[pos:])
		if err != nil {
			t.Fatal(err)
		}
		h.Frames = append(h.Frames, f)
	}
	known, err := searchprobe.ProjectKnownCards(h)
	if err != nil || len(known.SpellbenchAnonymousHands) != 0 {
		t.Fatalf("visible exit retained hand claim: %v %+v", err, known)
	}
	if err := known.Holds(searchprobe.World{Engine: e, Observer: c}); err != nil {
		t.Fatal(err)
	}
}
