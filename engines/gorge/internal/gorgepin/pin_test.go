package gorgepin_test

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/adams-shaun/gorge/cards"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/gorgepin"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/testcorpus"
)

func TestLinkedGorgeIsThePinnedCompiler(t *testing.T) {
	if cards.CompilerFingerprint != gorgepin.CompilerFingerprint {
		t.Fatalf("linked gorge compiler %s, pinned %s", cards.CompilerFingerprint, gorgepin.CompilerFingerprint)
	}
}

func TestOpenRegistryChecksTheCorpusLock(t *testing.T) {
	reg, err := gorgepin.OpenRegistry(testcorpus.Dir(t))
	if err != nil {
		t.Fatal(err)
	}
	if _, ok := reg.Lookup("Lightning Bolt"); !ok {
		t.Fatal("Lightning Bolt is not in the pinned corpus")
	}
	if _, err := gorgepin.OpenRegistry(t.TempDir()); err == nil {
		t.Fatal("a directory without cards.lock was accepted")
	}
}

// oneCardCorpus writes a corpus of one synthetic card (authored here, not a
// Forge file) whose lock names commit and digest.
func oneCardCorpus(t *testing.T, commit, digest string) string {
	t.Helper()
	dir := t.TempDir()
	if err := cards.WriteLock(dir, &cards.Lock{Commit: commit, Digest: digest}); err != nil {
		t.Fatal(err)
	}
	folder := cards.CorpusDir(dir)
	if err := os.MkdirAll(folder, 0o755); err != nil {
		t.Fatal(err)
	}
	script := []byte("Name:Mountain\nTypes:Basic Land Mountain\nOracle:\n")
	if err := os.WriteFile(filepath.Join(folder, "mountain.txt"), script, 0o644); err != nil {
		t.Fatal(err)
	}
	return dir
}

// An openable corpus is refused when its lock is not the pinned one, so the
// refusal comes from the lock check and not from a missing corpus.
func TestOpenRegistryRefusesAnUnpinnedLock(t *testing.T) {
	if _, err := gorgepin.OpenRegistry(oneCardCorpus(t, gorgepin.ForgeRef, gorgepin.CorpusDigest)); err != nil {
		t.Fatalf("control corpus with the pinned lock: %v", err)
	}
	if _, err := gorgepin.OpenRegistry(oneCardCorpus(t, gorgepin.ForgeRef, "other")); err == nil {
		t.Fatal("a lock with another digest was accepted")
	}
	if _, err := gorgepin.OpenRegistry(oneCardCorpus(t, "other", gorgepin.CorpusDigest)); err == nil {
		t.Fatal("a lock with another commit was accepted")
	}
}
