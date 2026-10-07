package gorgepin

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"io"
	"os"
	"strings"

	"github.com/adams-shaun/gorge/cards"
)

// OpenInput uses an explicit frozen registry when supplied. A bad frozen
// input never falls back to the development directory or recompiles scripts.
func OpenInput(corpus, registry, wantSHA string) (*cards.Registry, error) {
	if registry != "" {
		return OpenFrozenRegistry(registry, wantSHA)
	}
	if wantSHA != "" {
		return nil, fmt.Errorf("registry-sha256 requires registry")
	}
	return OpenRegistry(corpus)
}

// FileHash returns the bytes actually present, rather than a cache's name or
// cards.lock label. The reference launcher pins regular command-argument files.
func FileHash(path string) (string, int64, error) {
	f, err := os.Open(path)
	if err != nil {
		return "", 0, err
	}
	defer f.Close()
	info, err := f.Stat()
	if err != nil {
		return "", 0, err
	}
	if !info.Mode().IsRegular() {
		return "", 0, fmt.Errorf("registry input is not a regular file")
	}
	h := sha256.New()
	n, err := io.Copy(h, f)
	if err != nil {
		return "", 0, err
	}
	return hex.EncodeToString(h.Sum(nil)), n, nil
}

// OpenFrozenRegistry loads only the exact cache file named in the command.
// It never consults mtimes, cards.lock, sibling caches or the source directory.
// Launchers keep the pinned file immutable and recheck it before every start.
func OpenFrozenRegistry(path, wantSHA string) (*cards.Registry, error) {
	if cards.CompilerFingerprint != CompilerFingerprint {
		return nil, fmt.Errorf("linked gorge compiler is not the pinned compiler")
	}
	want, err := hex.DecodeString(wantSHA)
	if err != nil || len(want) != sha256.Size {
		return nil, fmt.Errorf("registry-sha256 must be a SHA-256 digest")
	}
	wantSHA = strings.ToLower(wantSHA)
	got, _, err := FileHash(path)
	if err != nil {
		return nil, err
	}
	if got != wantSHA {
		return nil, fmt.Errorf("frozen registry SHA-256 mismatch")
	}
	r, err := cards.LoadRegistry(path)
	if err != nil {
		return nil, err
	}
	got, _, err = FileHash(path)
	if err != nil || got != wantSHA {
		return nil, fmt.Errorf("frozen registry changed while loading")
	}
	return r, nil
}

type RegistryReceipt struct {
	Schema             string `json:"schema"`
	GorgeCommit        string `json:"gorge_commit"`
	Compiler           string `json:"compiler_fingerprint"`
	ForgeCommit        string `json:"forge_commit"`
	CardScriptsSHA256  string `json:"card_scripts_sha256"`
	TokenScriptsSHA256 string `json:"token_scripts_sha256"`
	CardScripts        int    `json:"card_scripts"`
	TokenScripts       int    `json:"token_scripts"`
	Cards              int    `json:"cards"`
	Tokens             int    `json:"tokens"`
	Diagnostics        int    `json:"diagnostics"`
	RegistrySHA256     string `json:"registry_sha256"`
	RegistryBytes      int64  `json:"registry_bytes"`
}

// FreezeRegistry recompiles verified sources rather than trusting a possibly
// stale cache. The output is a runtime input containing Forge-derived IR and
// belongs in a registered artifact tree, never in a commit or binary.
func FreezeRegistry(dir, out string) (RegistryReceipt, error) {
	var receipt RegistryReceipt
	if cards.CompilerFingerprint != CompilerFingerprint {
		return receipt, fmt.Errorf("linked gorge compiler is not pinned")
	}
	lock, err := cards.ReadLock(dir)
	if err != nil {
		return receipt, err
	}
	if lock.Commit != ForgeRef || lock.Digest != CorpusDigest {
		return receipt, fmt.Errorf("source corpus lock is not pinned")
	}
	cardHash, cardCount, err := cards.DigestDir(cards.CorpusDir(dir))
	if err != nil {
		return receipt, err
	}
	if cardHash != CorpusDigest {
		return receipt, fmt.Errorf("card script bytes do not match the pinned corpus")
	}
	tokenHash, tokenCount, err := cards.DigestDir(cards.TokensDir(dir))
	if err != nil {
		return receipt, err
	}
	if tokenCount == 0 {
		return receipt, fmt.Errorf("source token scripts are absent")
	}
	if _, err := os.Stat(out); !os.IsNotExist(err) {
		return receipt, fmt.Errorf("frozen registry output must be a new file")
	}
	r, diags, err := cards.CompileDir(cards.CorpusDir(dir))
	if err != nil {
		return receipt, err
	}
	cardAfter, _, err := cards.DigestDir(cards.CorpusDir(dir))
	if err != nil || cardAfter != cardHash {
		return receipt, fmt.Errorf("card scripts changed during compilation")
	}
	tokenAfter, _, err := cards.DigestDir(cards.TokensDir(dir))
	if err != nil || tokenAfter != tokenHash {
		return receipt, fmt.Errorf("token scripts changed during compilation")
	}
	if err := r.Save(out); err != nil {
		return receipt, err
	}
	sha, bytes, err := FileHash(out)
	if err != nil {
		return receipt, err
	}
	receipt = RegistryReceipt{Schema: "spellbench-gorge-registry/v1", GorgeCommit: GorgeCommit, Compiler: CompilerFingerprint,
		ForgeCommit: ForgeRef, CardScriptsSHA256: cardHash, TokenScriptsSHA256: tokenHash,
		CardScripts: cardCount, TokenScripts: tokenCount, Cards: len(r.Cards), Tokens: len(r.Tokens), Diagnostics: len(diags),
		RegistrySHA256: sha, RegistryBytes: bytes}
	return receipt, nil
}
