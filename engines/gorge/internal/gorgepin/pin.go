// Package gorgepin pins the gorge build and the Forge corpus this adapter was
// qualified against. A different build or corpus is a different engine identity.
package gorgepin

import (
	"fmt"

	"github.com/adams-shaun/gorge/cards"
	// rules registers its non-API primitives with effects.Supported; without
	// this import coverage checks undercount (see gorge cmd/forgec).
	_ "github.com/adams-shaun/gorge/rules"
)

const (
	GorgeCommit         = "26257e0eda1779d739a07e835c6500b9c4dabc62"
	CompilerFingerprint = "4e081d8104fbe09256edb9fa696ce6f7"
	ForgeRef            = "95f04e8a04c8925fa97cb226fc3341cabcc90a53"
	CorpusDigest        = "377204728a927366bab4cc40bf89a64544bd5bf464d66d261e58e1a71b69bf5f"
)

// OpenRegistry opens dir's compiled corpus after checking that the linked gorge
// compiler and the fetched corpus are the pinned ones.
func OpenRegistry(dir string) (*cards.Registry, error) {
	if cards.CompilerFingerprint != CompilerFingerprint {
		return nil, fmt.Errorf("gorge compiler %s is not the pinned %s", cards.CompilerFingerprint, CompilerFingerprint)
	}
	lock, err := cards.ReadLock(dir)
	if err != nil {
		return nil, fmt.Errorf("corpus lock in %s: %w", dir, err)
	}
	if lock.Commit != ForgeRef || lock.Digest != CorpusDigest {
		return nil, fmt.Errorf("corpus %s/%s is not the pinned %s/%s", lock.Commit, lock.Digest, ForgeRef, CorpusDigest)
	}
	return cards.OpenCorpus(dir)
}
