// Package catalog holds the engine's catalog decks: the five Spellbench Pauper
// lists gorge plays fully, with Oracle names in NFC ("A // B" for multi-face).
package catalog

import (
	"fmt"
	"sort"
	"strings"
	"unicode/utf8"

	"github.com/adams-shaun/gorge/cards"
	"github.com/adams-shaun/gorge/effects"
	// rules registers its non-API primitives with effects.Supported; without
	// this import coverage checks undercount (see gorge cmd/forgec).
	_ "github.com/adams-shaun/gorge/rules"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/wire"
)

// Deck is one catalog deck: its catalog_id, display name and decklist rows.
type Deck struct {
	CatalogID, Name string
	Rows            []wire.DeckRow
}

// DeckID is the deck's Section 4.3 deck_id.
func (d Deck) DeckID() string { return wire.DeckID(d.Rows) }

var decks = []Deck{
	{CatalogID: "Wildfire", Name: "Wildfire", Rows: []wire.DeckRow{
		{Name: "Twisted Landscape", Count: 4}, {Name: "Fanatical Offering", Count: 4}, {Name: "Ichor Wellspring", Count: 3}, {Name: "Blood Fountain", Count: 1},
		{Name: "Drossforge Bridge", Count: 4}, {Name: "Slagwoods Bridge", Count: 4}, {Name: "Writhing Chrysalis", Count: 4}, {Name: "Nyxborn Hydra", Count: 1},
		{Name: "Vault of Whispers", Count: 1}, {Name: "Cleansing Wildfire", Count: 4}, {Name: "Lembas", Count: 3}, {Name: "Makeshift Munitions", Count: 1},
		{Name: "Cast Down", Count: 4}, {Name: "Nihil Spellbomb", Count: 4}, {Name: "Swamp", Count: 3}, {Name: "Mountain", Count: 2}, {Name: "Forest", Count: 2},
		{Name: "Refurbished Familiar", Count: 4}, {Name: "Krark-Clan Shaman", Count: 3}, {Name: "Eviscerator's Insight", Count: 1}, {Name: "Toxin Analysis", Count: 2},
		{Name: "Pulse of Murasa", Count: 1},
	}},
	{CatalogID: "Rally", Name: "Rally", Rows: []wire.DeckRow{
		{Name: "Clockwork Percussionist", Count: 4}, {Name: "Voldaren Epicure", Count: 4}, {Name: "Goblin Bushwhacker", Count: 4},
		{Name: "Goblin Tomb Raider", Count: 4}, {Name: "Burning-Tree Emissary", Count: 4}, {Name: "Galvanic Blast", Count: 4},
		{Name: "Experimental Synthesizer", Count: 3}, {Name: "Lightning Bolt", Count: 4}, {Name: "Reckless Impulse", Count: 4},
		{Name: "Rally at the Hornburg", Count: 4}, {Name: "Great Furnace", Count: 4}, {Name: "Mountain", Count: 14}, {Name: "Chain Lightning", Count: 2},
		{Name: "End the Festivities", Count: 1},
	}},
	{CatalogID: "Spy", Name: "Spy", Rows: []wire.DeckRow{
		{Name: "Mesmeric Fiend", Count: 2}, {Name: "Overgrown Battlement", Count: 4}, {Name: "Saruli Caretaker", Count: 4}, {Name: "Gatecreeper Vine", Count: 3},
		{Name: "Sagu Wildling // Roost Seek", Count: 4}, {Name: "Generous Ent", Count: 4}, {Name: "Lead the Stampede", Count: 4}, {Name: "Winding Way", Count: 4},
		{Name: "Land Grant", Count: 4}, {Name: "Balustrade Spy", Count: 4}, {Name: "Lotleth Giant", Count: 2}, {Name: "Dread Return", Count: 2}, {Name: "Swamp", Count: 1},
		{Name: "Forest", Count: 3}, {Name: "Wall of Roots", Count: 3}, {Name: "Masked Vandal", Count: 3}, {Name: "Quirion Ranger", Count: 2},
		{Name: "Troll of Khazad-dûm", Count: 1}, {Name: "Lotus Petal", Count: 2}, {Name: "Tinder Wall", Count: 2}, {Name: "Elves of Deep Shadow", Count: 2},
	}},
	{CatalogID: "Burn", Name: "Burn", Rows: []wire.DeckRow{
		{Name: "Sneaky Snacker", Count: 4}, {Name: "Faithless Looting", Count: 2}, {Name: "Highway Robbery", Count: 4}, {Name: "Masked Meower", Count: 4},
		{Name: "Lightning Bolt", Count: 4}, {Name: "Mountain", Count: 18}, {Name: "Grab the Prize", Count: 4}, {Name: "Fireblast", Count: 4}, {Name: "Guttersnipe", Count: 4},
		{Name: "Fiery Temper", Count: 4}, {Name: "Voldaren Epicure", Count: 4}, {Name: "Lava Dart", Count: 4},
	}},
	{CatalogID: "CawGates", Name: "CawGates", Rows: []wire.DeckRow{
		{Name: "Island", Count: 4}, {Name: "Citadel Gate", Count: 4}, {Name: "Counterspell", Count: 4}, {Name: "Heap Gate", Count: 2}, {Name: "Idyllic Beachfront", Count: 1},
		{Name: "Brainstorm", Count: 3}, {Name: "Journey to Nowhere", Count: 4}, {Name: "Lórien Revealed", Count: 3}, {Name: "Outlaw Medic", Count: 2},
		{Name: "Basilisk Gate", Count: 4}, {Name: "Sacred Cat", Count: 4}, {Name: "Sea Gate", Count: 4}, {Name: "Azorius Guildgate", Count: 2},
		{Name: "The Modern Age // Vector Glider", Count: 4}, {Name: "Thraben Charm", Count: 2}, {Name: "Prismatic Strands", Count: 4},
		{Name: "Squadron Hawk", Count: 4}, {Name: "Spell Pierce", Count: 2}, {Name: "Preordain", Count: 2}, {Name: "Guardian of the Guildpact", Count: 1},
	}},
}

// Decks returns the catalog in benchmark order. The slice and its rows are
// shared: callers must not modify them.
func Decks() []Deck { return decks }

// ByID returns the catalog deck whose catalog_id is id.
func ByID(id string) (Deck, bool) {
	for _, d := range decks {
		if d.CatalogID == id {
			return d, true
		}
	}
	return Deck{}, false
}

// lookup resolves an Oracle name exactly. gorge's Lookup folds case and
// whitespace, drops punctuation and combining marks, reads only the front face
// of "A // B", and also finds a card by one face or an alias, so the card it
// finds must carry exactly this name: its faces joined with " // ".
func lookup(reg *cards.Registry, name string) (*cards.Card, error) {
	if !utf8.ValidString(name) {
		return nil, fmt.Errorf("card %q is not UTF-8", name)
	}
	c, ok := reg.Lookup(name)
	if !ok {
		return nil, fmt.Errorf("card %q is not in the corpus", name)
	}
	var faces []string
	for _, f := range c.Faces {
		faces = append(faces, f.Name)
	}
	full := faces[0]
	if len(faces) > 1 {
		full = strings.Join(faces, " // ")
	}
	if full != name {
		return nil, fmt.Errorf("card %q is %q in the corpus", name, full)
	}
	return c, nil
}

// Resolve returns d's cards in row order, each row repeated count times. A
// name that is not exactly a corpus card's Oracle name is an error, never a
// substitution.
func Resolve(reg *cards.Registry, d Deck) ([]*cards.Card, error) {
	var out []*cards.Card
	for _, r := range d.Rows {
		c, err := lookup(reg, r.Name)
		if err != nil {
			return nil, fmt.Errorf("deck %s: %w", d.CatalogID, err)
		}
		for i := 0; i < r.Count; i++ {
			out = append(out, c)
		}
	}
	return out, nil
}

// Preflight proves every catalog card resolves and is fully playable
// (every primitive its script names is implemented). It does not prove that
// the engine can offer every decision these cards raise (Section 9.2 makes
// such a deck unsupported_deck): the plan's decision-shape census (census5)
// and the Task 28 qualification prove decision-kind coverage.
func Preflight(reg *cards.Registry) error {
	sup := effects.Supported()
	for _, d := range decks {
		for _, r := range d.Rows {
			c, err := lookup(reg, r.Name)
			if err != nil {
				return fmt.Errorf("deck %s: %w", d.CatalogID, err)
			}
			if miss := reg.Unsupported(c, sup); len(miss) > 0 {
				return fmt.Errorf("deck %s: %s needs %v", d.CatalogID, r.Name, miss)
			}
		}
	}
	return nil
}

// PoolNames returns every catalog card name once, sorted in code point order.
func PoolNames() []string {
	set := map[string]bool{}
	for _, d := range decks {
		for _, r := range d.Rows {
			set[r.Name] = true
		}
	}
	var out []string
	for n := range set {
		out = append(out, n)
	}
	sort.Strings(out)
	return out
}
