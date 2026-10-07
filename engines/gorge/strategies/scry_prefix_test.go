package strategies

import (
	"testing"

	"github.com/adams-shaun/gorge/internal/searchprobe"
)

func TestPublicScryPrefixDoesNotSpendLookCountsTwice(t *testing.T) {
	var prefix searchprobe.SpellbenchScryPrefix
	for range 7 {
		prefix.Draw()
	}
	prefix.Scry(2, 1)
	prefix.Draw()
	if got := prefix.Through(); got != 9 {
		t.Fatalf("one kept card must stay within original prefix 9, got %d", got)
	}
	prefix.Scry(2, 0)
	if got := prefix.Through(); got != 11 {
		t.Fatalf("next look can touch original prefix 11, got %d", got)
	}
}

// Enumerate hidden keep/bottom partitions and orderings, including looking
// at fewer cards than the public maximum. Every subsequently drawn original
// rank must fit the bound. Repeated scries may inspect bottomed cards again.
func TestPublicScryPrefixBoundsEveryHiddenOrdering(t *testing.T) {
	checked := 0
	var walk func([]int, searchprobe.SpellbenchScryPrefix, int)
	walk = func(library []int, prefix searchprobe.SpellbenchScryPrefix, depth int) {
		if len(library) == 0 || depth == 0 {
			return
		}
		drawn := prefix
		drawn.Draw()
		checked++
		if library[0] > drawn.Through() {
			t.Fatalf("rank %d exceeds public bound %d, library=%v", library[0], drawn.Through(), library)
		}
		walk(library[1:], drawn, depth-1)
		for maximum := 1; maximum <= 3; maximum++ {
			for look := 1; look <= min(maximum, len(library)); look++ {
				window := append([]int(nil), library[:look]...)
				var permute func(int)
				permute = func(at int) {
					if at != look {
						for i := at; i < look; i++ {
							window[at], window[i] = window[i], window[at]
							permute(at + 1)
							window[at], window[i] = window[i], window[at]
						}
						return
					}
					for bottom := 0; bottom <= look; bottom++ {
						kept := look - bottom
						next := append([]int(nil), window[:kept]...)
						next = append(next, library[look:]...)
						next = append(next, window[kept:]...)
						public := prefix
						public.Scry(maximum, bottom)
						walk(next, public, depth-1)
					}
				}
				permute(0)
			}
		}
	}
	walk([]int{1, 2, 3, 4, 5}, searchprobe.SpellbenchScryPrefix{}, 4)
	if checked < 1000 {
		t.Fatalf("insufficient hidden paths: %d", checked)
	}
	t.Logf("checked %d possible public draw bounds", checked)
}
