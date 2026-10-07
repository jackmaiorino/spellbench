package observe_test

import (
	"reflect"
	"testing"

	"github.com/jackmaiorino/spellbench/engines/gorge/internal/observe"
)

func TestVocabularyNormalization(t *testing.T) {
	for in, want := range map[string]string{"Time Lord": "time_lord", "Urza's": "urzas", "First Strike": "first_strike", "Human": "human"} {
		if got := observe.Normalize(in); got != want {
			t.Errorf("Normalize(%q) = %q, want %q", in, got, want)
		}
	}
	for in, want := range map[string]string{"P1P1": "p1p1", "M0M1": "m0m1", "CHARGE": "charge", "Lore": "lore"} {
		if got := observe.Counter(in); got != want {
			t.Errorf("Counter(%q) = %q, want %q", in, got, want)
		}
	}
	if got := observe.Colors("RWG"); !reflect.DeepEqual(got, []string{"white", "red", "green"}) {
		t.Errorf("Colors = %v", got)
	}
	got := observe.Keywords([]string{"Flying", "Flashback:1 R", "Forestwalk", "Protection from red", "CARDNAME can't block.", "Flying"})
	if !reflect.DeepEqual(got, []string{"flying", "flashback", "landwalk", "protection"}) {
		t.Errorf("Keywords = %v", got)
	}
}
