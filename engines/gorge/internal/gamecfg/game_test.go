package gamecfg_test

import (
	"context"
	"encoding/binary"
	"errors"
	"slices"
	"testing"

	"github.com/adams-shaun/gorge/cards"
	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/seat"
	"github.com/adams-shaun/gorge/state"
	"github.com/adams-shaun/gorge/view"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/catalog"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/gamecfg"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/secrets"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/testcorpus"
)

func deck(t *testing.T, reg *cards.Registry, id string) []*cards.Card {
	d, _ := catalog.ByID(id)
	cs, err := catalog.Resolve(reg, d)
	if err != nil {
		t.Fatal(err)
	}
	return cs
}

func secret(b byte) *secrets.Game {
	s := make([]byte, 32)
	s[0] = b
	return secrets.NewGame(s)
}

func playOut(t *testing.T, g *gamecfg.Game) string {
	bots := [2]seat.Seat{seat.NewBot(1), seat.NewBot(2)}
	for n := 0; !g.E.G.Over && g.E.Pending() != nil && n < 50000; n++ {
		d := g.E.Pending()
		in, _ := bots[d.Player].Decide(context.Background(), view.Project(g.E.G, g.E, d.Player, d), *d)
		if err := g.Submit(in); err != nil {
			t.Fatalf("intent %d: %v", n, err)
		}
	}
	return g.E.L.Head()
}

func TestStartingSeatIsForcedAndGamesAreDeterministic(t *testing.T) {
	reg := testcorpus.Registry(t)
	burn := deck(t, reg, "Burn")
	for _, start := range []state.PlayerID{0, 1} {
		a, err := gamecfg.New(reg, secret(7), [2][]*cards.Card{burn, burn}, gamecfg.Rules{Mulligan: "london", StartingSeat: start})
		if err != nil {
			t.Fatal(err)
		}
		if a.E.G.StartingPlayer != start {
			t.Fatalf("starting player %d, want %d", a.E.G.StartingPlayer, start)
		}
		b, _ := gamecfg.New(reg, secret(7), [2][]*cards.Card{burn, burn}, gamecfg.Rules{Mulligan: "london", StartingSeat: start})
		if playOut(t, a) != playOut(t, b) {
			t.Fatal("same secret and answers gave different chain heads")
		}
	}
}

func TestSeatOneLibraryIsIndependentOfSeatZero(t *testing.T) {
	reg := testcorpus.Registry(t)
	spy, burn := deck(t, reg, "Spy"), deck(t, reg, "Burn")
	a, _ := gamecfg.New(reg, secret(9), [2][]*cards.Card{spy, burn}, gamecfg.Rules{Mulligan: "none"})
	b, _ := gamecfg.New(reg, secret(9), [2][]*cards.Card{burn, burn}, gamecfg.Rules{Mulligan: "none"})
	names := func(g *gamecfg.Game) (out []string) {
		for _, z := range []state.Zone{state.ZHand, state.ZLibrary} {
			for _, id := range g.E.G.Zone(z, 1) {
				out = append(out, g.E.G.Obj(id).Card.Faces[0].Name)
			}
		}
		return out
	}
	na, nb := names(a), names(b)
	for i := range na {
		if na[i] != nb[i] {
			t.Fatalf("seat 1 card %d differs (%s vs %s) when only seat 0's deck changed", i, na[i], nb[i])
		}
	}
}

func TestUnplannedRandomnessIsDetected(t *testing.T) {
	reg := testcorpus.Registry(t)
	burn := deck(t, reg, "Burn")
	g, _ := gamecfg.New(reg, secret(3), [2][]*cards.Card{burn, burn}, gamecfg.Rules{Mulligan: "none"})
	g.E.Rand(6) // an engine draw no planner supplied, as a Rand-using card would make
	if err := g.CheckRandomness(); !errors.Is(err, gamecfg.ErrUnplannedRandomness) {
		t.Fatalf("got %v", err)
	}
}

// fisherYates recomputes a Section 11.6 library shuffle from the spec alone:
// Fisher-Yates over in, driven by the stream of
// "spellbench/v2/rng:<owner>:library_shuffle:<n>".
func fisherYates(sec *secrets.Game, owner string, n uint64, in []state.ObjID) []state.ObjID {
	out := slices.Clone(in)
	r := sec.Stream(owner, "library_shuffle", n)
	for i := len(out) - 1; i > 0; i-- {
		j := r.IntN(i + 1)
		out[i], out[j] = out[j], out[i]
	}
	return out
}

// dealt is p's hand then library. A draw moves the library's top (index 0)
// to the end of the hand, so right after a shuffle and a fresh seven this is
// the shuffled order.
func dealt(g *gamecfg.Game, p state.PlayerID) []state.ObjID {
	return append(slices.Clone(g.E.G.Zone(state.ZHand, p)), g.E.G.Zone(state.ZLibrary, p)...)
}

// intent answers p's pending decision with its option of this kind.
func intent(t *testing.T, g *gamecfg.Game, p state.PlayerID, kind string) decision.Intent {
	t.Helper()
	d := g.E.Pending()
	if d == nil || d.Player != p {
		t.Fatalf("no pending decision for p%d", p)
	}
	for i, o := range d.Options {
		if o.Kind == kind {
			return decision.Intent{Seq: d.Seq, Player: p, Choices: []int{i}}
		}
	}
	t.Fatalf("p%d has no %q option", p, kind)
	return decision.Intent{}
}

// Both opening libraries, recomputed from the secret without the planner:
// gorge numbers objects from 1, seat by seat in deck order, and shuffles each
// library from that order. A swapped seat, ordinal or purpose fails here, and
// so does a gorge seed not taken from the shared stream.
func TestOpeningLibrariesFollowTheSecretStreams(t *testing.T) {
	reg := testcorpus.Registry(t)
	decks := [2][]*cards.Card{deck(t, reg, "Spy"), deck(t, reg, "Burn")}
	sec := secret(5)
	g, err := gamecfg.New(reg, sec, decks, gamecfg.Rules{Mulligan: "none"})
	if err != nil {
		t.Fatal(err)
	}
	next := state.ObjID(1)
	for p, owner := range []string{"p0", "p1"} {
		in := make([]state.ObjID, len(decks[p]))
		for i, c := range decks[p] {
			if o := g.E.G.Obj(next); o == nil || o.Card != c {
				t.Fatalf("object %d is not %s's deck card %d", next, owner, i)
			}
			in[i] = next
			next++
		}
		if got, want := dealt(g, state.PlayerID(p)), fisherYates(sec, owner, 0, in); !slices.Equal(got, want) {
			t.Fatalf("%s opening order\n got %v\nwant %v", owner, got, want)
		}
	}
	seed := sec.StreamSeed("shared", "gorge_seed", 0)
	if want := binary.BigEndian.Uint64(seed[:8]); g.E.L.Seed != want {
		t.Fatalf("gorge seed %d, want %d", g.E.L.Seed, want)
	}
}

// A London mulligan is the seat's second shuffle: ordinal 1 of its own
// stream, over its library with the hand moved to the end. gorge redraws when
// the declaration pass ends, so p1 answers first.
func TestMulliganShuffleUsesTheSeatsNextOrdinal(t *testing.T) {
	reg := testcorpus.Registry(t)
	burn := deck(t, reg, "Burn")
	sec := secret(5)
	g, err := gamecfg.New(reg, sec, [2][]*cards.Card{burn, burn}, gamecfg.Rules{Mulligan: "london"})
	if err != nil {
		t.Fatal(err)
	}
	in := append(slices.Clone(g.E.G.Zone(state.ZLibrary, 0)), g.E.G.Zone(state.ZHand, 0)...)
	if err := g.Submit(intent(t, g, 0, "mulligan")); err != nil {
		t.Fatal(err)
	}
	if err := g.Submit(intent(t, g, 1, "keep")); err != nil {
		t.Fatal(err)
	}
	if d := g.E.Pending(); d == nil || d.Kind != decision.KMulligan || d.Player != 0 {
		t.Fatal("p0 is not deciding on its redrawn hand")
	}
	if got, want := dealt(g, 0), fisherYates(sec, "p0", 1, in); !slices.Equal(got, want) {
		t.Fatalf("p0 order after the mulligan\n got %v\nwant %v", got, want)
	}
}

// Submit checks the invariant after every intent.
func TestSubmitReportsUnplannedRandomness(t *testing.T) {
	reg := testcorpus.Registry(t)
	burn := deck(t, reg, "Burn")
	g, _ := gamecfg.New(reg, secret(3), [2][]*cards.Card{burn, burn}, gamecfg.Rules{Mulligan: "london"})
	in := intent(t, g, 0, "keep")
	g.E.Rand(6)
	if err := g.Submit(in); !errors.Is(err, gamecfg.ErrUnplannedRandomness) {
		t.Fatalf("got %v", err)
	}
}

// Probe answers on a clone: an option the engine did not offer is an error,
// and a legal answer moves only the clone, to where the real submit arrives.
func TestProbeLeavesTheRealEngineUntouched(t *testing.T) {
	reg := testcorpus.Registry(t)
	burn := deck(t, reg, "Burn")
	g, _ := gamecfg.New(reg, secret(3), [2][]*cards.Card{burn, burn}, gamecfg.Rules{Mulligan: "london"})
	in := intent(t, g, 0, "mulligan")
	head, draws := g.E.L.Head(), g.E.RNGDraws()
	if _, err := g.Probe(decision.Intent{Seq: in.Seq, Player: 0, Choices: []int{2}}); err == nil {
		t.Fatal("probe accepted an option the engine did not offer")
	}
	c, err := g.Probe(in)
	if err != nil {
		t.Fatal(err)
	}
	if g.E.L.Head() != head || g.E.RNGDraws() != draws || g.E.Pending().Seq != in.Seq {
		t.Fatal("probing moved the real engine")
	}
	if err := g.Submit(in); err != nil {
		t.Fatal(err)
	}
	if g.E.L.Head() == head || c.L.Head() != g.E.L.Head() {
		t.Fatal("the probe's clone is not where the real submit arrives")
	}
}
