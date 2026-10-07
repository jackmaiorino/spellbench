package neutral_test

import (
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"

	"github.com/jackmaiorino/spellbench/engines/gorge/internal/catalog"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/neutral"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/testcorpus"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/wire"
)

// kernelDecks reads the pauper-kernel-v2 decklists as mtg-kernel names them.
func kernelDecks(t *testing.T) map[string][]wire.DeckRow {
	t.Helper()
	b, err := os.ReadFile(filepath.Join("..", "..", "..", "xmage", "kit", "register", "pauper-kernel-decks.json"))
	if err != nil {
		t.Fatal(err)
	}
	var decks []struct {
		CatalogID string         `json:"catalog_id"`
		Decklist  []wire.DeckRow `json:"decklist"`
	}
	if err := json.Unmarshal(b, &decks); err != nil {
		t.Fatal(err)
	}
	out := map[string][]wire.DeckRow{}
	for _, d := range decks {
		out[d.CatalogID] = d.Decklist
	}
	return out
}

func TestKernelDecksResolveToGorgeCatalog(t *testing.T) {
	reg := testcorpus.Registry(t)
	kernel := kernelDecks(t)
	if len(kernel) != 8 {
		t.Fatalf("%d kernel decks, want 8", len(kernel))
	}
	gaps := map[string][]string{}
	for id, rows := range kernel {
		d, err := neutral.ResolveDeck(reg, rows)
		if err != nil {
			t.Fatalf("%s: %v", id, err)
		}
		if len(d.Cards) != 60 {
			t.Errorf("%s resolves to %d cards", id, len(d.Cards))
		}
		for _, g := range neutral.Coverage(reg, d) {
			gaps[id] = append(gaps[id], g.Name)
		}
		// A deck gorge plays on its own engine must be the same list once
		// renamed, so its deck_id agrees with the gorge catalog's.
		if cat, ok := catalog.ByID(id); ok {
			if got, want := wire.DeckID(d.Rows), cat.DeckID(); got != want {
				t.Errorf("%s renamed deck_id %s, gorge catalog %s", id, got, want)
			}
		}
	}
	want := map[string][]string{
		"Affinity": {"Black Mage's Rod"},
		"Elves":    {"Avenging Hunter"},
		"Faeries":  {"Saiba Cryptomancer"},
	}
	if !reflect.DeepEqual(gaps, want) {
		t.Errorf("coverage gaps %v, want %v", gaps, want)
	}
}

func TestResolveNamesFacesAndRefusesNearMisses(t *testing.T) {
	reg := testcorpus.Registry(t)
	for _, c := range []struct {
		name, oracle string
		face         int
	}{
		{"Lightning Bolt", "Lightning Bolt", 0},
		{"Troll of Khazad-dum", "Troll of Khazad-dûm", 0},
		{"Troll of Khazad-dûm", "Troll of Khazad-dûm", 0},
		{"Sagu Wildling", "Sagu Wildling // Roost Seek", 0},
		{"Roost Seek", "Sagu Wildling // Roost Seek", 1},
		{"Sagu Wildling // Roost Seek", "Sagu Wildling // Roost Seek", 0},
		{"Vector Glider", "The Modern Age // Vector Glider", 1},
	} {
		ref, err := neutral.Resolve(reg, c.name)
		if err != nil || ref.Oracle != c.oracle || ref.Face != c.face {
			t.Errorf("%q resolves to %q face %d (%v), want %q face %d", c.name, ref.Oracle, ref.Face, err, c.oracle, c.face)
		}
	}
	for _, name := range []string{"lightning bolt", "Lightning Bolt!", "troll of khazad-dum", "Lorien Revealed ", "Roost Seek // Sagu Wildling", "Not A Card"} {
		if ref, err := neutral.Resolve(reg, name); err == nil {
			t.Errorf("%q resolved to %q", name, ref.Oracle)
		}
	}
}

func TestResolveDeckRefusesRowsNamingOneCard(t *testing.T) {
	reg := testcorpus.Registry(t)
	rows := []wire.DeckRow{{Name: "Troll of Khazad-dum", Count: 1}, {Name: "Troll of Khazad-dûm", Count: 1}}
	if _, err := neutral.ResolveDeck(reg, rows); err == nil || !strings.Contains(err.Error(), "both") {
		t.Fatalf("duplicate rows resolved: %v", err)
	}
	if _, err := neutral.ResolveDeck(reg, []wire.DeckRow{{Name: "Mountain", Count: 0}}); err == nil {
		t.Fatal("zero-count row resolved")
	}
}
