// Package secrets implements the HMAC constructions of Spellbench v2
// Sections 5.3 and 11.6. Nothing computed from a game secret reaches an agent.
package secrets

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"fmt"
	"math/rand/v2"
	"regexp"
	"strconv"
)

func mac(key []byte, msg string) []byte {
	h := hmac.New(sha256.New, key)
	h.Write([]byte(msg))
	return h.Sum(nil)
}

func dec(i uint64) string { return strconv.FormatUint(i, 10) }

func Commitment(run []byte) string {
	s := sha256.Sum256(run)
	return hex.EncodeToString(s[:])
}

func GameSecret(run []byte, i uint64) []byte { return mac(run, "spellbench/v2/game:"+dec(i)) }

func GameID(run []byte, i uint64) string {
	return "g-" + hex.EncodeToString(mac(run, "spellbench/v2/game-id:"+dec(i))[:8])
}

func AgentSeed(run []byte, i uint64, seat string) uint64 {
	b := mac(run, "spellbench/v2/agent-seed:"+dec(i)+":"+seat)
	return binary.BigEndian.Uint64(b[:8]) & (1<<53 - 1)
}

// Game holds one game's secret and derived id key. Engine-internal only.
type Game struct {
	secret []byte
	idKey  []byte
}

var hex64 = regexp.MustCompile(`^[0-9a-f]{64}$`)

func ParseGame(s string) (*Game, error) {
	if !hex64.MatchString(s) {
		return nil, fmt.Errorf("game_secret is not 64 lowercase hex characters")
	}
	b, _ := hex.DecodeString(s)
	return NewGame(b), nil
}

func NewGame(secret []byte) *Game {
	return &Game{secret: append([]byte(nil), secret...), idKey: mac(secret, "spellbench/v2/object-id")}
}

func (g *Game) IDKeyHex() string { return hex.EncodeToString(g.idKey) }

// ObjectID is Section 5.3's recommended construction over message M.
func (g *Game) ObjectID(msg string) string { return "o-" + hex.EncodeToString(mac(g.idKey, msg)[:8]) }

// StreamSeed is Section 11.6's recommended stream seed; owner is "p0", "p1" or "shared".
func (g *Game) StreamSeed(owner, purpose string, n uint64) [32]byte {
	var s [32]byte
	copy(s[:], mac(g.secret, fmt.Sprintf("spellbench/v2/rng:%s:%s:%d", owner, purpose, n)))
	return s
}

// Stream is a ChaCha8 generator (256-bit key) for one randomized event.
func (g *Game) Stream(owner, purpose string, n uint64) *rand.Rand {
	return rand.New(rand.NewChaCha8(g.StreamSeed(owner, purpose, n)))
}
