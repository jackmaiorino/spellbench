package observe

import (
	"testing"

	"github.com/adams-shaun/gorge/state"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/testcorpus"
)

// Vector Glider, the back face of The Modern Age, has the front face's mana
// value (CR 712.8e); X counts only on the stack (CR 202.3e).
func TestManaValueOfBackFacesAndX(t *testing.T) {
	reg := testcorpus.Registry(t)
	age, ok1 := reg.Lookup("The Modern Age")
	hydra, ok2 := reg.Lookup("Nyxborn Hydra")
	if !ok1 || !ok2 {
		t.Fatal("corpus lacks The Modern Age or Nyxborn Hydra")
	}
	for _, c := range []struct {
		what string
		o    state.Object
		want uint32
	}{
		{"The Modern Age", state.Object{Card: age, Zone: state.ZBattlefield}, 2},
		{"Vector Glider", state.Object{Card: age, FaceIdx: 1, Zone: state.ZBattlefield}, 2},
		{"Nyxborn Hydra in hand", state.Object{Card: hydra, Zone: state.ZHand, X: 3}, 1},
		{"Nyxborn Hydra on the stack with X 3", state.Object{Card: hydra, Zone: state.ZStack, X: 3}, 4},
	} {
		if got := manaValue(&c.o); got != c.want {
			t.Errorf("%s: mana value %d, want %d", c.what, got, c.want)
		}
	}
}
