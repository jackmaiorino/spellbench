package gorgepin_test

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/adams-shaun/gorge/cards"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/gorgepin"
)

func TestFrozenRegistryBindsActualBytesAndPreservesDefinitions(t *testing.T) {
	c, _ := cards.ParseBytes("fixture", []byte("Name:Mountain\nTypes:Basic Land Mountain\nOracle:\n"))
	r := cards.NewRegistry()
	r.Add(c)
	r.Tokens["fixture"] = c
	path := filepath.Join(t.TempDir(), "sealed.gob.gz")
	if err := r.Save(path); err != nil {
		t.Fatal(err)
	}
	sha, _, err := gorgepin.FileHash(path)
	if err != nil {
		t.Fatal(err)
	}
	loaded, err := gorgepin.OpenInput("absent-development-corpus", path, sha)
	if err != nil {
		t.Fatal(err)
	}
	if _, ok := loaded.Lookup("Mountain"); !ok || len(loaded.Tokens) != 1 {
		t.Fatal("registry definitions changed")
	}
	for _, wrong := range []string{"", "not-a-hash", strings.Repeat("0", 64)} {
		if _, err := gorgepin.OpenFrozenRegistry(path, wrong); err == nil {
			t.Fatal("unbound bytes accepted")
		}
	}
	f, err := os.OpenFile(path, os.O_APPEND|os.O_WRONLY, 0o600)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := f.Write([]byte("changed")); err != nil {
		t.Fatal(err)
	}
	if err := f.Close(); err != nil {
		t.Fatal(err)
	}
	if _, err := gorgepin.OpenInput("absent-development-corpus", path, sha); err == nil {
		t.Fatal("changed input accepted")
	}
	if _, err := gorgepin.OpenInput("", "", sha); err == nil {
		t.Fatal("digest without a file accepted")
	}
}

func TestFreezeRegistryRejectsForgedSourceLabels(t *testing.T) {
	dir := oneCardCorpus(t, gorgepin.ForgeRef, gorgepin.CorpusDigest)
	if _, err := gorgepin.FreezeRegistry(dir, filepath.Join(t.TempDir(), "sealed.gob.gz")); err == nil {
		t.Fatal("matching lock labels substituted for actual source bytes")
	}
}
