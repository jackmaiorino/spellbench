package catalog_test

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/adams-shaun/gorge/cards"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/catalog"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/testcorpus"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/wire"
)

// Deck ids recomputed independently (Python json.dumps sort_keys, ensure_ascii=False)
// from the mtg-kernel catalog lists with Oracle names; see the plan's evidence.
var wantIDs = map[string]string{
	"Wildfire": "sha256:32d59bef473236ee5861fa4b01932c11fff7ebc7a4fc4b7f189be99d9672e313",
	"Rally":    "sha256:b1b414074a7081c963838b0b82d91b85ce0c46b324feab0a1f542aaabeca73ea",
	"Spy":      "sha256:82b3117c82044353f15f1dc1f32a45614e379f17e6be5b8df267c5e29b59dbb8",
	"Burn":     "sha256:20e44003dba8100a83d84878c55f6736f1cb033ec76596a740cdbeb558b580c9",
	"CawGates": "sha256:84aa6f5edec314009ac290881520c308d581a5e04393f75ddb046c6354c46654",
}

func TestDeckIDsMatchHostComputation(t *testing.T) {
	for _, d := range catalog.Decks() {
		n := 0
		for _, r := range d.Rows {
			n += r.Count
		}
		if n != 60 {
			t.Errorf("%s has %d cards", d.CatalogID, n)
		}
		if d.DeckID() != wantIDs[d.CatalogID] {
			t.Errorf("%s deck_id %s, want %s", d.CatalogID, d.DeckID(), wantIDs[d.CatalogID])
		}
	}
	if got := wire.DomainID(catalog.PoolNames()); got != "sha256:ab186e0272634f91dad9dd7b5765f33b69b3dc91bdfb1f6e43879be6ea49ba5b" {
		t.Errorf("pool domain_id %s", got)
	}
}

func TestEveryCatalogCardResolvesAndIsFullyPlayable(t *testing.T) {
	reg := testcorpus.Registry(t)
	if err := catalog.Preflight(reg); err != nil {
		t.Fatal(err)
	}
	spy, _ := catalog.ByID("Spy")
	cs, err := catalog.Resolve(reg, spy)
	if err != nil || len(cs) != 60 {
		t.Fatalf("Spy resolves to %d cards: %v", len(cs), err)
	}
}

func TestAsciiFoldedNameIsNotSubstituted(t *testing.T) {
	reg := testcorpus.Registry(t)
	bad := catalog.Deck{CatalogID: "X", Rows: []wire.DeckRow{{Name: "Troll of Khazad-dum", Count: 60}}}
	if _, err := catalog.Resolve(reg, bad); err == nil || !strings.Contains(err.Error(), "Troll of Khazad-dum") {
		t.Fatalf("ASCII-folded name resolved: %v", err)
	}
	nfd := catalog.Deck{CatalogID: "Y", Rows: []wire.DeckRow{{Name: "Lo\u0301rien Revealed", Count: 60}}}
	if _, err := catalog.Resolve(reg, nfd); err == nil {
		t.Fatal("NFD-decomposed name resolved")
	}
}

// gorge's Lookup finds each of these (case and punctuation folded, one face of
// a multi-face card, an alias), so each reaches the exact-name check.
func TestNearMissNamesGorgeFindsAreNotSubstituted(t *testing.T) {
	reg := testcorpus.Registry(t)
	for _, name := range []string{"lightning bolt", "KrarkClan Shaman", "Sagu Wildling", "Vector Glider", "Skittering Kitten"} {
		if _, ok := reg.Lookup(name); !ok {
			t.Fatalf("gorge no longer finds %q", name)
		}
		d := catalog.Deck{CatalogID: "Z", Rows: []wire.DeckRow{{Name: name, Count: 60}}}
		if _, err := catalog.Resolve(reg, d); err == nil || !strings.Contains(err.Error(), name) {
			t.Errorf("%q resolved: %v", name, err)
		}
	}
}

// Decks keeps benchmark order and distinct row names, ByID finds exactly the
// named deck, Resolve keeps row order expanded by count (the library order the
// shuffle starts from), and PoolNames is sorted and distinct.
func TestCatalogOrderAndLookupContracts(t *testing.T) {
	reg := testcorpus.Registry(t)
	var ids []string
	for _, d := range catalog.Decks() {
		ids = append(ids, d.CatalogID)
		if got, ok := catalog.ByID(d.CatalogID); !ok || got.CatalogID != d.CatalogID {
			t.Errorf("ByID(%s) gave %q, %v", d.CatalogID, got.CatalogID, ok)
		}
		cs, err := catalog.Resolve(reg, d)
		if err != nil {
			t.Fatal(err)
		}
		seen, i := map[string]bool{}, 0
		for _, r := range d.Rows {
			if seen[r.Name] {
				t.Errorf("%s repeats %s", d.CatalogID, r.Name)
			}
			seen[r.Name] = true
			want, _ := reg.Lookup(r.Name)
			for n := 0; n < r.Count; n++ {
				if i >= len(cs) || cs[i] != want {
					t.Fatalf("%s card %d is not %s", d.CatalogID, i, r.Name)
				}
				i++
			}
		}
		if i != len(cs) {
			t.Errorf("%s resolves to %d cards, rows hold %d", d.CatalogID, len(cs), i)
		}
	}
	if got := strings.Join(ids, " "); got != "Wildfire Rally Spy Burn CawGates" {
		t.Errorf("decks in order %s", got)
	}
	if _, ok := catalog.ByID("Pauper"); ok {
		t.Error("an unknown catalog id was found")
	}
	names := catalog.PoolNames()
	for i := 1; i < len(names); i++ {
		if names[i-1] >= names[i] {
			t.Errorf("pool names %q, %q are not sorted and distinct", names[i-1], names[i])
		}
	}
}

// Preflight fails on a missing catalog card, and on a card that resolves but
// needs a primitive gorge does not implement.
func TestPreflightRefusesMissingAndUnplayableCards(t *testing.T) {
	if err := catalog.Preflight(cards.NewRegistry()); err == nil {
		t.Fatal("an empty registry passed")
	}
	// One synthetic card (authored here, not a Forge file), named for the
	// first row Preflight checks, with a keyword gorge does not implement.
	dir := t.TempDir()
	folder := cards.CorpusDir(dir)
	if err := os.MkdirAll(folder, 0o755); err != nil {
		t.Fatal(err)
	}
	first := catalog.Decks()[0].Rows[0].Name
	script := []byte("Name:" + first + "\nTypes:Land\nK:Spellbench Probe Keyword\nOracle:\n")
	if err := os.WriteFile(filepath.Join(folder, "first.txt"), script, 0o644); err != nil {
		t.Fatal(err)
	}
	reg, err := cards.OpenCorpus(dir)
	if err != nil {
		t.Fatal(err)
	}
	if err := catalog.Preflight(reg); err == nil || !strings.Contains(err.Error(), "kw:Spellbench Probe Keyword") {
		t.Fatalf("an unplayable card passed: %v", err)
	}
}
