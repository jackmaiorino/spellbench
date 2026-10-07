// Package neutral lets gorge's policies play a protocol v2 game hosted by
// another engine (mtg-kernel on pauper-kernel-v2). It reads only what the
// seat may read, the observation and candidates, and rebuilds gorge's view
// and decision from them; gorge's own registry supplies printed card facts.
package neutral

import (
	"fmt"
	"strings"
	"unicode/utf8"

	"github.com/adams-shaun/gorge/cards"
	"github.com/adams-shaun/gorge/effects"
	// rules registers its non-API primitives with effects.Supported; without
	// this import Coverage would report them missing.
	_ "github.com/adams-shaun/gorge/rules"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/wire"
)

// asciiNames maps the names another engine spells without diacritics to
// gorge's Oracle names. mtg-kernel's Pauper lists come from XMage, which
// writes "Troll of Khazad-dum"; gorge's registry keeps the Oracle spelling,
// and its lookup keeps precomposed letters, so these never fold together.
// The table is explicit on purpose: a fuzzy fold could silently substitute
// a different card.
var asciiNames = map[string]string{
	"Lorien Revealed":     "Lórien Revealed",
	"Troll of Khazad-dum": "Troll of Khazad-dûm",
}

// Ref is one engine name resolved to a gorge card: the card, the face the
// name is printed on, and the card's full Oracle name ("A // B" for a
// multi-face card).
type Ref struct {
	Card   *cards.Card
	Face   int
	Oracle string
}

// FullName is c's Oracle name: its faces joined with " // ".
func FullName(c *cards.Card) string {
	names := make([]string, len(c.Faces))
	for i, f := range c.Faces {
		names[i] = f.Name
	}
	return strings.Join(names, " // ")
}

// Resolve finds the card another engine calls name. The name must be
// exactly a card's full Oracle name, exactly one of its face names, or an
// entry of the ASCII table; gorge's case and punctuation folding is never
// accepted on its own, so a near miss is an error, not a substitution.
func Resolve(reg *cards.Registry, name string) (Ref, error) {
	if !utf8.ValidString(name) {
		return Ref{}, fmt.Errorf("card %q is not UTF-8", name)
	}
	want := name
	if oracle, ok := asciiNames[name]; ok {
		want = oracle
	}
	// Lookup indexes every face name and an "A // B" name by its front
	// face, then folds case and punctuation; the checks below undo the fold.
	c, ok := reg.Lookup(want)
	if !ok {
		return Ref{}, fmt.Errorf("card %q is not in the gorge registry", name)
	}
	full := FullName(c)
	if full == want {
		return Ref{Card: c, Oracle: full}, nil
	}
	for i, f := range c.Faces {
		if f.Name == want {
			return Ref{Card: c, Face: i, Oracle: full}, nil
		}
	}
	return Ref{}, fmt.Errorf("card %q is %q in the gorge registry", name, full)
}

// Deck is a decklist resolved to gorge: rows renamed to Oracle names in the
// source order, and the cards each row stands for.
type Deck struct {
	Rows  []wire.DeckRow
	Cards []*cards.Card
}

// ResolveDeck resolves every row of a decklist another engine sent. Two
// rows that name one card are an error: the list would not mean what it
// says to gorge.
func ResolveDeck(reg *cards.Registry, rows []wire.DeckRow) (Deck, error) {
	var d Deck
	seen := map[*cards.Card]string{}
	for _, r := range rows {
		if r.Count <= 0 {
			return Deck{}, fmt.Errorf("card %q has count %d", r.Name, r.Count)
		}
		ref, err := Resolve(reg, r.Name)
		if err != nil {
			return Deck{}, err
		}
		if prev, dup := seen[ref.Card]; dup {
			return Deck{}, fmt.Errorf("rows %q and %q are both %q", prev, r.Name, ref.Oracle)
		}
		seen[ref.Card] = r.Name
		d.Rows = append(d.Rows, wire.DeckRow{Name: ref.Oracle, Count: r.Count})
		for i := 0; i < r.Count; i++ {
			d.Cards = append(d.Cards, ref.Card)
		}
	}
	return d, nil
}

// Gap is a card gorge cannot play fully: the primitives its script names
// that gorge does not implement.
type Gap struct {
	Name    string
	Missing []string
}

// Coverage lists the cards of a resolved deck that gorge cannot play
// fully, once each in row order. An empty result means every card's
// script is implemented; it does not prove every decision these cards
// raise translates.
func Coverage(reg *cards.Registry, d Deck) []Gap {
	sup := effects.Supported()
	seen := map[*cards.Card]bool{}
	var gaps []Gap
	for _, c := range d.Cards {
		if seen[c] {
			continue
		}
		seen[c] = true
		if miss := reg.Unsupported(c, sup); len(miss) > 0 {
			gaps = append(gaps, Gap{Name: FullName(c), Missing: miss})
		}
	}
	return gaps
}
