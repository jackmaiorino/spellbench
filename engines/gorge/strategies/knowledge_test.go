package strategies

import (
	"encoding/json"
	"reflect"
	"testing"

	"github.com/adams-shaun/gorge/cards"
	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/events"
	"github.com/adams-shaun/gorge/internal/searchprobe"
	"github.com/adams-shaun/gorge/rules"
	"github.com/adams-shaun/gorge/state"
)

// This is a knowledge boundary fixture, not a naturally played game. Logged
// public moves place one unique creature into a library and then shuffle it.
// The collector must lose its copy link while retaining its known name/count.
func shuffledKnownLibrary(t *testing.T, player state.PlayerID) (*rules.Engine, PublicGame, *searchprobe.Collector, History, state.ObjID, uint32) {
	t.Helper()
	_, setup := fixture(t, 17, true)
	deck := make([]*cards.Card, 20)
	for i := range deck {
		deck[i] = setup.Decks[0][0]
	}
	deck[19] = setup.Decks[0][19]
	setup.Decks[player] = deck
	e, err := rules.NewHypothetical(rules.Config{Seed: 17, Names: setup.Names, Decks: setup.Decks}, []rules.ChanceDraw{{Bound: 2, Value: 0}})
	if err != nil {
		t.Fatal(err)
	}
	if err := e.AdvanceHypothetical(); err != nil {
		t.Fatal(err)
	}
	c := searchprobe.NewCollector(0)
	h := History{Actor: 0, ActorBoundaries: true}
	capture := func(burst []events.Event) {
		f, err := c.SpellbenchCapture(e, burst)
		if err != nil {
			t.Fatal(err)
		}
		h.Frames = append(h.Frames, f)
	}
	capture(e.L.Events)
	var id state.ObjID
	for _, zone := range []state.Zone{state.ZHand, state.ZLibrary} {
		for _, obj := range e.G.Zone(zone, player) {
			if e.G.Obj(obj).Card.Faces[0].Name == "Goblin Piker" {
				id = obj
			}
		}
	}
	if id == 0 {
		t.Fatal("unique creature missing from fixture")
	}
	pos := len(e.L.Events)
	events.Emit(e.G, e.L, events.Event{Kind: events.MoveZone, Obj: id, Player: player, From: e.G.Obj(id).Zone, To: state.ZBattlefield})
	capture(e.L.Events[pos:])
	old := c.SpellbenchAlias(id)
	pos = len(e.L.Events)
	events.Emit(e.G, e.L, events.Event{Kind: events.MoveZone, Obj: id, Player: player, From: state.ZBattlefield, To: state.ZLibrary})
	events.Emit(e.G, e.L, events.Event{Kind: events.Shuffle, Player: player, IDs: append([]state.ObjID(nil), e.G.Zone(state.ZLibrary, player)...), Secret: true})
	capture(e.L.Events[pos:])
	if old == 0 || c.SpellbenchAlias(id) != 0 {
		t.Fatal("shuffle did not retire the revealed copy")
	}
	return e, setup, c, h, id, old
}

func TestPublicKnownLibraryKeepsAnonymousMembershipAfterShuffle(t *testing.T) {
	e, setup, c, h, id, old := shuffledKnownLibrary(t, 1)
	known, err := searchprobe.ProjectKnownCards(h)
	if err != nil {
		t.Fatal(err)
	}
	want := []searchprobe.SpellbenchLibraryMinimum{{Player: 1, Name: "Goblin Piker", Count: 1}}
	if !reflect.DeepEqual(known.SpellbenchAnonymous, want) {
		t.Fatalf("known library counts = %+v, want %+v", known.SpellbenchAnonymous, want)
	}
	for _, library := range known.Libraries {
		for _, member := range library.Members {
			if member.ID == old {
				t.Fatal("retired physical reference remained a placement claim")
			}
		}
	}
	if err := known.Holds(searchprobe.World{Engine: e, Observer: c}); err != nil {
		t.Fatalf("valid knowledge no longer holds in the fixture root: %v", err)
	}
	bad := e.CloneHypothetical(83)
	events.Emit(bad.G, bad.L, events.Event{Kind: events.MoveZone, Obj: id, Player: 1, From: state.ZLibrary, To: state.ZHand})
	if known.Holds(searchprobe.World{Engine: bad, Observer: c}) == nil {
		t.Fatal("a world without the known library member passed")
	}
	// Coalesce the injected moves into one actor boundary. Native replay cannot
	// produce this fixture's artificial prefix, so this tests actual fallback
	// dealing from a supplied hypothetical root, not public reconstruction.
	h.Frames[0].Decision, h.Frames[1].Decision = nil, nil
	h = PublicHistory(h)
	result, err := searchprobe.Sample(setup, h, searchprobe.SampleOptions{Seed: 54321, Attempts: 2, Worlds: 16, MaxSubmits: 30,
		Redeal: &searchprobe.RedealBase{Engine: e, Observer: c}})
	if err != nil || result.Accepted != 0 || result.Redealt != 16 || result.RedealRefused != "" {
		t.Fatalf("anonymous membership did not permit native redeal: %v %+v", err, result)
	}
	for _, world := range result.Worlds {
		if err := known.Holds(world); err != nil {
			t.Fatal(err)
		}
		for _, card := range world.Engine.G.Zone(state.ZHand, 1) {
			if world.Engine.G.Obj(card).Card.Faces[0].Name == "Goblin Piker" {
				t.Fatal("redeal put the unique known library member in the hidden hand")
			}
		}
		if world.Observer.SpellbenchAlias(id) != 0 {
			t.Fatal("redeal restored a retired wire copy link")
		}
	}
}

func TestPublicKnownLibraryConsumesVisibleDrawAndForgetsUnseenDraw(t *testing.T) {
	for _, player := range []state.PlayerID{0, 1} {
		e, _, c, h, id, old := shuffledKnownLibrary(t, player)
		pos := len(e.L.Events)
		events.Emit(e.G, e.L, events.Event{Kind: events.Draw, Obj: id, Player: player, From: state.ZLibrary, To: state.ZHand, Secret: true})
		f, err := c.SpellbenchCapture(e, e.L.Events[pos:])
		if err != nil {
			t.Fatal(err)
		}
		h.Frames = append(h.Frames, f)
		known, err := searchprobe.ProjectKnownCards(h)
		if err != nil || len(known.SpellbenchAnonymous) != 0 {
			t.Fatalf("draw retained an unsupported library claim: %v %+v", err, known)
		}
		if err := known.Holds(searchprobe.World{Engine: e, Observer: c}); err != nil {
			t.Fatal(err)
		}
		if player == 0 {
			if now := c.SpellbenchAlias(id); now == 0 || now == old {
				t.Fatal("actor's draw did not introduce a fresh copy identity")
			}
		} else if c.SpellbenchAlias(id) != 0 {
			t.Fatal("unseen opponent draw introduced a copy identity")
		}
	}
}

func TestWholePublicHistoryIgnoresHiddenDrawAfterShuffle(t *testing.T) {
	a, _, ca, ha, piker, _ := shuffledKnownLibrary(t, 1)
	b, _, cb, hb, _, _ := shuffledKnownLibrary(t, 1)
	var mountain state.ObjID
	for _, id := range b.G.Zone(state.ZLibrary, 1) {
		if b.G.Obj(id).Card.Faces[0].Name == "Mountain" {
			mountain = id
			break
		}
	}
	if mountain == 0 {
		t.Fatal("hidden alternative draw missing")
	}
	for _, branch := range []struct {
		e  *rules.Engine
		c  *searchprobe.Collector
		h  *History
		id state.ObjID
	}{{a, ca, &ha, piker}, {b, cb, &hb, mountain}} {
		pos := len(branch.e.L.Events)
		events.Emit(branch.e.G, branch.e.L, events.Event{Kind: events.Draw, Obj: branch.id, Player: 1, From: state.ZLibrary, To: state.ZHand, Secret: true})
		f, err := branch.c.SpellbenchCapture(branch.e, branch.e.L.Events[pos:])
		if err != nil {
			t.Fatal(err)
		}
		branch.h.Frames = append(branch.h.Frames, f)
	}
	if a.L.Head() == b.L.Head() {
		t.Fatal("fixture did not change the secret draw")
	}
	wa, _ := json.Marshal(ha)
	wb, _ := json.Marshal(hb)
	if string(wa) != string(wb) {
		t.Fatal("the complete history distinguished hidden drawn card names")
	}
	ka, err := searchprobe.ProjectKnownCards(ha)
	if err != nil {
		t.Fatal(err)
	}
	kb, err := searchprobe.ProjectKnownCards(hb)
	if err != nil || !reflect.DeepEqual(ka, kb) {
		t.Fatal("knowledge distinguished hidden drawn card names")
	}
}

func TestPublicCollectorForgetsOpponentPrivateLibraryReorder(t *testing.T) {
	e, _, c, h, id, _ := shuffledKnownLibrary(t, 1)
	f, err := c.SpellbenchCapture(e, []events.Event{{Kind: events.Note, Player: 1, IDs: []state.ObjID{id}}})
	if err != nil {
		t.Fatal(err)
	}
	h.Frames = append(h.Frames, f)
	old := c.SpellbenchAlias(id)
	f, err = c.SpellbenchCapture(e, []events.Event{{Kind: events.LibraryOrder, Player: 1, IDs: append([]state.ObjID(nil), e.G.Zone(state.ZLibrary, 1)...), Secret: true}})
	if err != nil {
		t.Fatal(err)
	}
	h.Frames = append(h.Frames, f)
	if old == 0 || c.SpellbenchAlias(id) != 0 {
		t.Fatal("opponent's private library order preserved a copy link")
	}
	known, err := searchprobe.ProjectKnownCards(h)
	if err != nil || len(known.SpellbenchAnonymous) != 1 || known.SpellbenchAnonymous[0].Count != 1 {
		t.Fatalf("private reorder lost known name multiplicity: %v %+v", err, known)
	}
	if err := known.Holds(searchprobe.World{Engine: e, Observer: c}); err != nil {
		t.Fatal(err)
	}
	if _, err := c.SpellbenchCapture(e, []events.Event{{Kind: events.Note, Player: 1, IDs: []state.ObjID{id}}}); err != nil {
		t.Fatal(err)
	}
	if now := c.SpellbenchAlias(id); now == 0 || now == old {
		t.Fatal("a new public library reveal reused the private order's copy link")
	}
}

func TestPublicCollectorKeepsActorsAnsweredLibraryArrangement(t *testing.T) {
	e, _, c, h, id, _ := shuffledKnownLibrary(t, 0)
	f, err := c.SpellbenchCapture(e, []events.Event{{Kind: events.Note, Player: 0, From: state.ZLibrary, IDs: []state.ObjID{id}, Secret: true}})
	if err != nil {
		t.Fatal(err)
	}
	ref := c.SpellbenchAlias(id)
	action := searchprobe.Action{Decision: decision.KArrange, Kind: "top", Obj: ref}
	f.Decision = &searchprobe.ObservedDecision{Player: 0, Kind: decision.KArrange, Max: 1,
		Options: []searchprobe.ObservedOption{{Action: action}}}
	h.Frames = append(h.Frames, f)
	h.Answers = map[int][]searchprobe.Action{len(h.Frames) - 1: {action}}
	order := []state.ObjID{id}
	for _, other := range e.G.Zone(state.ZLibrary, 0) {
		if other != id {
			order = append(order, other)
		}
	}
	pos := len(e.L.Events)
	events.Emit(e.G, e.L, events.Event{Kind: events.LibraryOrder, Player: 0, IDs: order, Secret: true})
	f, err = c.SpellbenchCapture(e, e.L.Events[pos:])
	if err != nil {
		t.Fatal(err)
	}
	h.Frames = append(h.Frames, f)
	if ref == 0 || c.SpellbenchAlias(id) != ref {
		t.Fatal("the actor's own answered arrangement retired a known copy")
	}
	known, err := searchprobe.ProjectKnownCards(h)
	if err != nil {
		t.Fatal(err)
	}
	positioned := false
	for _, library := range known.Libraries {
		positioned = positioned || library.Player == 0 && len(library.Top) == 1 && library.Top[0].ID == ref
	}
	if !positioned {
		t.Fatalf("the actor's answered top position was forgotten: %+v", known)
	}
	if err := known.Holds(searchprobe.World{Engine: e, Observer: c}); err != nil {
		t.Fatal(err)
	}
}
