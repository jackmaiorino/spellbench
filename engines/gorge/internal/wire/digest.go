package wire

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
)

// WithoutRequestID removes the top-level request_id before digesting (Section 11.8).
func WithoutRequestID(msg []byte) ([]byte, error) {
	dec := json.NewDecoder(bytes.NewReader(msg))
	dec.UseNumber()
	var m map[string]any
	if err := dec.Decode(&m); err != nil {
		return nil, err
	}
	delete(m, "request_id")
	return Canonical(m)
}

// GameDigest is the Section 11.8 chain.
type GameDigest struct{ d [32]byte }

func NewGameDigest(resetMinusID []byte) (*GameDigest, error) {
	c, err := CanonicalBytes(resetMinusID)
	if err != nil {
		return nil, err
	}
	h := sha256.New()
	h.Write([]byte("spellbench/v2/game-digest"))
	h.Write(c)
	g := &GameDigest{}
	copy(g.d[:], h.Sum(nil))
	return g, nil
}

func (g *GameDigest) Chain(msgMinusID []byte) error {
	c, err := CanonicalBytes(msgMinusID)
	if err != nil {
		return err
	}
	h := sha256.New()
	h.Write(g.d[:])
	h.Write(c)
	copy(g.d[:], h.Sum(nil))
	return nil
}

func (g *GameDigest) String() string { return "sha256:" + hex.EncodeToString(g.d[:]) }
