package strategies

import (
	"context"
	"encoding/json"
	"reflect"
	"testing"

	"github.com/adams-shaun/gorge/cards"
	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/events"
	"github.com/adams-shaun/gorge/internal/searchprobe"
	"github.com/adams-shaun/gorge/internal/searchseat"
	"github.com/adams-shaun/gorge/rules"
	"github.com/adams-shaun/gorge/seat"
	"github.com/adams-shaun/gorge/state"
	"github.com/adams-shaun/gorge/view"
)

func fixtureCard(t *testing.T, text string) *cards.Card {
	t.Helper()
	c, ds := cards.ParseBytes("public-search-fixture", []byte(text))
	if len(ds) != 0 {
		t.Fatal(ds)
	}
	c.Link()
	for _, f := range c.Faces {
		f.ApplyIntrinsics()
	}
	return c
}

func fixture(t *testing.T, seed uint64, creatures bool) (*rules.Engine, PublicGame) {
	t.Helper()
	mountain := fixtureCard(t, "Name:Mountain\nTypes:Basic Land Mountain\nOracle:Fixture.\n")
	deck := make([]*cards.Card, 20)
	for i := range deck {
		deck[i] = mountain
	}
	if creatures {
		piker := fixtureCard(t, "Name:Goblin Piker\nManaCost:1 R\nTypes:Creature Goblin Warrior\nPT:2/1\nOracle:Fixture.\n")
		for i := 12; i < len(deck); i++ {
			deck[i] = piker
		}
	}
	setup := PublicGame{Names: []string{"p0", "p1"}, Decks: [][]*cards.Card{deck, deck}, StartingLife: 20}
	e, err := rules.NewHypothetical(rules.Config{Seed: seed, Names: setup.Names, Decks: setup.Decks}, []rules.ChanceDraw{{Bound: 2, Value: 0}})
	if err != nil {
		t.Fatal(err)
	}
	if err := e.AdvanceHypothetical(); err != nil {
		t.Fatal(err)
	}
	return e, setup
}

func TestDriverMatchesNativeFeedAndDeltaDelivery(t *testing.T) {
	e, _ := fixture(t, 17, true)
	driver := NewDriver()
	feeds := [2]*searchseat.Feed{searchseat.NewFeed(0), searchseat.NewFeed(1)}
	bots := [2]*seat.Bot{seat.NewBot(3), seat.NewBot(7)}
	received := [2]History{{Actor: 0}, {Actor: 1}}
	indices := [2]uint64{}
	for n := 0; n < 70 && !e.G.Over; n++ {
		d := e.Pending()
		driver.Observe(e)
		driver.Observe(e) // presenting the same ask cannot capture twice
		for _, f := range feeds {
			if _, ok := f.Observe(e); !ok {
				t.Fatal(f.StopReason())
			}
		}
		indices[d.Player]++
		delta := driver.Delta(d.Player, indices[d.Player], map[uint32]uint32{})
		raw, _ := json.Marshal(delta)
		var wire Delta
		if err := json.Unmarshal(raw, &wire); err != nil {
			t.Fatal(err)
		}
		if err := AppendDelta(&received[d.Player], wire); err != nil {
			t.Fatal(err)
		}
		if !reflect.DeepEqual(received[d.Player], PublicHistory(feeds[d.Player].History())) {
			t.Fatal("transport changed native history or lost the previous answer")
		}
		again := driver.Delta(d.Player, indices[d.Player], map[uint32]uint32{999: 1})
		if !reflect.DeepEqual(delta, again) {
			t.Fatal("repeated pose changed its history delta")
		}
		in, err := bots[d.Player].Decide(context.Background(), view.Project(e.G, e, d.Player, d), *d)
		if err != nil {
			t.Fatal(err)
		}
		if err := driver.RecordAnswer(d, in); err != nil {
			t.Fatal(err)
		}
		if err := feeds[d.Player].RecordAnswer(d, in); err != nil {
			t.Fatal(err)
		}
		for actor, f := range feeds {
			if !reflect.DeepEqual(driver.seats[actor].h, f.History()) {
				t.Fatalf("actor %d capture drifted from native Feed", actor)
			}
		}
		if err := e.SubmitHypothetical(in); err != nil {
			t.Fatal(err)
		}
	}
}

func TestPublicHistoryIgnoresHiddenDealsAndFutureSeed(t *testing.T) {
	a, _ := fixture(t, 17, false)
	b, _ := fixture(t, 83, false)
	if a.L.Head() == b.L.Head() {
		t.Fatal("fixture needs distinct hidden histories")
	}
	da, db := NewDriver(), NewDriver()
	da.Observe(a)
	db.Observe(b)
	for actor := state.PlayerID(0); actor < 2; actor++ {
		wa, _ := json.Marshal(da.Delta(actor, 1, nil))
		wb, _ := json.Marshal(db.Delta(actor, 1, nil))
		if string(wa) != string(wb) {
			t.Fatal("hidden seed or allocation reached public history")
		}
	}
}

func TestSearchDefaultsPreserveShippedConfiguration(t *testing.T) {
	s := NewSearch(1, false)
	if !reflect.DeepEqual(s.opts, searchseat.Defaults()) {
		t.Fatal("search defaults differ from native defaults")
	}
	m := NewSearch(1, true)
	want := searchseat.Defaults()
	want.Kinds["mana"] = true
	if !reflect.DeepEqual(m.opts, want) {
		t.Fatal("mana mode changed another search setting")
	}
}

func TestPublicSearchMatchesNativeChooseWithRekeyedObjects(t *testing.T) {
	for _, kind := range []string{"attackers", "cast", "mana"} {
		t.Run(kind, func(t *testing.T) { publicSearchMatchesNative(t, kind, false) })
	}
}

func TestPublicSearchMatchesNativeChooseAtShippedBudgets(t *testing.T) {
	for _, kind := range []string{"attackers", "cast", "mana"} {
		t.Run(kind, func(t *testing.T) { publicSearchMatchesNative(t, kind, true) })
	}
}

func TestPublicRedealPreservesAcceptedNativeSearchAtShippedBudgets(t *testing.T) {
	for _, kind := range []string{"attackers", "cast", "mana"} {
		t.Run(kind, func(t *testing.T) { publicSearchMatchesNative(t, kind, true, true) })
	}
}

func publicSearchMatchesNative(t *testing.T, kind string, shipped bool, redeal ...bool) {
	e, setup := fixture(t, 17, true)
	driver := NewDriver()
	bots := [2]*seat.Bot{seat.NewBot(3), seat.NewBot(7)}
	for n := 0; n < 160 && !e.G.Over; n++ {
		d := e.Pending()
		driver.Observe(e)
		v := view.Project(e.G, e, d.Player, d)
		v.Round = view.RoundOf(e.G, e.L.Events)
		oracle := seat.NewBot(19)
		base, err := oracle.Decide(context.Background(), v, *d)
		if err != nil {
			t.Fatal(err)
		}
		mana := 0
		for _, o := range d.Options {
			if o.Kind == "activate" && o.Cost == "" {
				mana++
			}
		}
		eligible := kind == "attackers" && d.Kind == decision.KAttackers && len(d.Options) > 0 ||
			kind == "cast" && d.Kind == decision.KPriority && searchseat.CastOptions(d) >= 2 ||
			kind == "mana" && d.Kind == decision.KPriority && searchseat.CastOptions(d) < 2 && mana >= 2 &&
				len(base.Choices) == 1 && d.Options[base.Choices[0]].Kind == "activate"
		if eligible {
			s := NewSearch(19, kind == "mana")
			if len(redeal) > 0 && redeal[0] {
				s = NewRedealSearch(19, kind == "mana")
			}
			if !shipped {
				// Bounded settings are identically configured on both sides.
				s.opts.Worlds, s.opts.Attempts, s.opts.MaxSubmits, s.opts.HorizonTurns = 1, 16, 120, 1
			}
			stream := &driver.seats[d.Player]
			h := PublicHistory(stream.h)
			nativeOptions := s.opts
			nativeOptions.SpellbenchPublicRedeal = false
			want, _, trace := searchseat.Choose(setup, h, stream.c, e, d, base, h.Frames[len(h.Frames)-1], nativeOptions)
			// Move every transport object into a disjoint public namespace.
			rekey := func(id state.ObjID) state.ObjID {
				if id == 0 {
					return 0
				}
				if _, player := id.PlayerRef(); player {
					return id
				}
				return id + 10000
			}
			public := d.CloneValue()
			aliases := map[uint32]uint32{}
			bind := func(id state.ObjID) {
				if ref := stream.c.SpellbenchAlias(id); id != 0 && ref != 0 {
					aliases[uint32(rekey(id))] = ref
				}
			}
			bind(d.Source)
			public.Source = rekey(public.Source)
			for i := range public.Options {
				bind(public.Options[i].Obj)
				bind(public.Options[i].Attacker)
				public.Options[i].Obj = rekey(public.Options[i].Obj)
				public.Options[i].Attacker = rekey(public.Options[i].Attacker)
			}
			for i := range v.Players {
				for _, zone := range [][]view.CardView{v.Players[i].Battlefield, v.Players[i].Hand, v.Players[i].Graveyard, v.Players[i].Exile} {
					for j := range zone {
						zone[j].ID = rekey(zone[j].ID)
					}
				}
			}
			got, gotTrace, err := s.DecideObserved(context.Background(), v, public, setup, h, Delta{Live: true, Aliases: aliases})
			if err != nil || !reflect.DeepEqual(got, want) || !reflect.DeepEqual(gotTrace, trace) {
				t.Fatalf("public/native search mismatch: %v\n%+v %+v\n%+v %+v", err, got, want, gotTrace, trace)
			}
			if gotTrace.Kind != kind || !gotTrace.Covered || gotTrace.Worlds == 0 || gotTrace.Rollouts == 0 {
				t.Fatalf("fixture did not exercise search: %+v", gotTrace)
			}
			if shipped && (gotTrace.Worlds != 8 || gotTrace.Attempts != 64 || gotTrace.Terminal == 0) {
				t.Fatalf("shipped settings did not produce complete rollouts: %+v", gotTrace)
			}
			t.Logf("%s shipped=%v attempts=%d accepted=%d worlds=%d rollouts=%d terminal=%d capped=%d",
				kind, shipped, gotTrace.Attempts, gotTrace.Accepted, gotTrace.Worlds, gotTrace.Rollouts, gotTrace.Terminal, gotTrace.Capped)
			parallel := NewSearch(19, kind == "mana")
			parallel.opts = s.opts
			parallel.opts.Parallelism = 2
			again, parallelTrace, err := parallel.DecideObserved(context.Background(), v, public, setup, h, Delta{Live: true, Aliases: aliases})
			if err != nil || !reflect.DeepEqual(again, got) || !reflect.DeepEqual(parallelTrace, gotTrace) {
				t.Fatal("parallel public sampling or rollout changed the answer")
			}
			return
		}
		in, err := bots[d.Player].Decide(context.Background(), v, *d)
		if err != nil {
			t.Fatal(err)
		}
		if err := driver.RecordAnswer(d, in); err != nil {
			t.Fatal(err)
		}
		if err := e.SubmitHypothetical(in); err != nil {
			t.Fatal(err)
		}
	}
	t.Fatalf("fixture never reached a %s search", kind)
}

func TestSearchDeltaRejectsWrongActorAndMissingFrames(t *testing.T) {
	h := History{Actor: 0}
	for _, d := range []Delta{{Version: 1, Actor: 1}, {Version: 1, Actor: 0, From: 1}} {
		if err := AppendDelta(&h, d); err == nil {
			t.Fatal("invalid history accepted")
		}
	}
}

func TestSearchDeltaRejectsChangedAnswersWithoutMutation(t *testing.T) {
	own := Frame{Board: json.RawMessage(`{}`), Decision: &searchprobe.ObservedDecision{Player: 0, Kind: decision.KPriority}}
	h := History{Actor: 0, Frames: []Frame{own}, Answers: map[int][]Action{0: {{Kind: "pass"}}}}
	before, _ := json.Marshal(h)
	for _, answers := range []map[int][]Action{{0: {{Kind: "different"}}}, {2: {{Kind: "pass"}}}} {
		if err := AppendDelta(&h, Delta{Version: 1, From: 1, Frames: []Frame{own}, Answers: answers}); err == nil {
			t.Fatal("invalid answer delta accepted")
		}
		after, _ := json.Marshal(h)
		if string(before) != string(after) {
			t.Fatal("rejected delta changed stored history")
		}
	}
}

// The type aliases exported by the bridge remain the native sampler types.
var _ searchprobe.History = History{}

func TestPublicHistoryErasesOpponentPrivateAskCounts(t *testing.T) {
	own := Frame{Board: json.RawMessage(`{}`), Decision: &searchprobe.ObservedDecision{Player: 0, Kind: decision.KPriority}}
	plain := History{Actor: 0, Frames: []Frame{own, own}}
	withPrivate := History{Actor: 0, Frames: []Frame{own}}
	for n := 0; n < 19; n++ {
		withPrivate.Frames = append(withPrivate.Frames, Frame{Board: json.RawMessage(`{"private":true}`),
			Events: []searchprobe.ObservedEvent{{Kind: events.DecisionAsk, Player: 1}, {Kind: events.DecisionMade, Player: 1},
				{Kind: events.Note, Player: 1, Secret: true, Text: "private selection"}}})
	}
	withPrivate.Frames = append(withPrivate.Frames, own)
	a, _ := json.Marshal(PublicHistory(plain))
	b, _ := json.Marshal(PublicHistory(withPrivate))
	if string(a) != string(b) {
		t.Fatal("opponent private frame count entered public history")
	}
}

func TestPublicCollectorForgetsBlindShuffleCopyIdentity(t *testing.T) {
	e, _ := fixture(t, 17, false)
	c := searchprobe.NewCollector(0)
	if _, err := c.SpellbenchCapture(e, e.L.Events); err != nil {
		t.Fatal(err)
	}
	id := e.G.Zone(state.ZHand, 0)[0]
	old := c.SpellbenchAlias(id)
	// The net state is the same: move this seen card into its library,
	// shuffle, then draw it. Its physical copy is unknowable after the shuffle.
	ids := append(append([]state.ObjID(nil), e.G.Zone(state.ZLibrary, 0)...), id)
	burst := []events.Event{{Kind: events.MoveZone, Player: 0, Obj: id, From: state.ZHand, To: state.ZLibrary},
		{Kind: events.Shuffle, Player: 0, IDs: ids, Secret: true},
		{Kind: events.Draw, Player: 0, Obj: id, From: state.ZLibrary, To: state.ZHand}}
	if _, err := c.SpellbenchCapture(e, burst); err != nil {
		t.Fatal(err)
	}
	if now := c.SpellbenchAlias(id); old == 0 || now == 0 || now == old {
		t.Fatal("a blind shuffle retained the earlier physical copy identity")
	}
}

func TestPublicCollectorForgetsCardsRevealedEarlierInSameBurst(t *testing.T) {
	e, _ := fixture(t, 17, false)
	c := searchprobe.NewCollector(0)
	if _, err := c.SpellbenchCapture(e, e.L.Events); err != nil {
		t.Fatal(err)
	}
	id := e.G.Zone(state.ZHand, 1)[0]
	f, err := c.SpellbenchCapture(e, []events.Event{
		{Kind: events.Note, Player: 1, IDs: []state.ObjID{id}},
		{Kind: events.Shuffle, Player: 1, IDs: []state.ObjID{id}, Secret: true},
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(f.Events[0].IDs) != 1 || len(f.Identities) != 1 {
		t.Fatal("public reveal was lost")
	}
	old := f.Events[0].IDs[0]
	if c.SpellbenchAlias(id) != 0 {
		t.Fatal("a reveal before a blind shuffle retained its copy link")
	}
	if _, err := c.SpellbenchCapture(e, []events.Event{{Kind: events.Note, Player: 1, IDs: []state.ObjID{id}}}); err != nil {
		t.Fatal(err)
	}
	if now := c.SpellbenchAlias(id); now == 0 || now == old {
		t.Fatal("later reveal reused the retired copy identity")
	}
}

func TestPublicCollectorForgetsHiddenCopiesWhenPlayerIsEffectController(t *testing.T) {
	e, _ := fixture(t, 17, false)
	c := searchprobe.NewCollector(0)
	other := e.G.Zone(state.ZHand, 1)
	if _, err := c.SpellbenchCapture(e, []events.Event{{Kind: events.Note, IDs: []state.ObjID{other[0], other[1]}}}); err != nil {
		t.Fatal(err)
	}
	own := e.G.Zone(state.ZHand, 0)[0]
	before := c.SpellbenchAlias(own)
	if c.SpellbenchAlias(other[0]) == 0 || c.SpellbenchAlias(other[1]) == 0 {
		t.Fatal("reveal did not introduce copies")
	}
	// The actor controls a move between the opponent's hidden zones. The
	// public event identifies no selected card, so all its known copies lose
	// their link. Player is the controller, not the hidden card's owner.
	if _, err := c.SpellbenchCapture(e, []events.Event{{Kind: events.MoveZone, Player: 0, Obj: other[0], From: state.ZHand, To: state.ZLibrary}}); err != nil {
		t.Fatal(err)
	}
	if c.SpellbenchAlias(other[0]) != 0 || c.SpellbenchAlias(other[1]) != 0 {
		t.Fatal("a private selection retained copy identity")
	}
	if c.SpellbenchAlias(own) != before {
		t.Fatal("actor's visible hand lost its identity")
	}
}

func TestPublicSamplerReconstructsDeclaredLondonMulligans(t *testing.T) {
	_, setup := fixture(t, 17, false)
	setup.Mulligans = 7
	e, err := rules.NewHypothetical(rules.Config{Seed: 17, Names: setup.Names, Decks: setup.Decks, Mulligans: 7}, []rules.ChanceDraw{{Bound: 2, Value: 0}})
	if err != nil {
		t.Fatal(err)
	}
	if err := e.AdvanceHypothetical(); err != nil {
		t.Fatal(err)
	}
	driver := NewDriver()
	driver.Observe(e)
	h := PublicHistory(driver.seats[0].h)
	res, err := searchprobe.Sample(setup, h, searchprobe.SampleOptions{Seed: 54321, Attempts: 4, Worlds: 1, MaxSubmits: 30})
	if err != nil || len(res.Worlds) != 1 || res.Worlds[0].Engine.Pending().Kind != decision.KMulligan {
		t.Fatalf("London reconstruction failed: %v %+v", err, res)
	}
}
