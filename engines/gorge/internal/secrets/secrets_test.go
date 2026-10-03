package secrets_test

import (
	"encoding/hex"
	"math/rand/v2"
	"testing"

	"github.com/jackmaiorino/spellbench/engines/gorge/internal/secrets"
)

func runSecret() []byte {
	b := make([]byte, 32)
	for i := range b {
		b[i] = byte(i)
	}
	return b
}

func TestHostVectors(t *testing.T) {
	run := runSecret()
	check := func(name, got, want string) {
		t.Helper()
		if got != want {
			t.Errorf("%s = %s, want %s", name, got, want)
		}
	}
	check("commitment", secrets.Commitment(run), "630dcd2966c4336691125448bbb25b4ff412a49c732db2c8abc1b8581bd710dd")
	check("game_secret(0)", hex.EncodeToString(secrets.GameSecret(run, 0)), "7648831b4ae4148770e13149d5ebbe1c4991168413d4b38e49292cfc5538980e")
	check("game_secret(1)", hex.EncodeToString(secrets.GameSecret(run, 1)), "952ea875cce08bf7706f87a89ae6a4e318a1bc4b46d6b506f8bb8505c518238e")
	check("game_id(0)", secrets.GameID(run, 0), "g-f67d7fe78c792984")
	check("game_id(1)", secrets.GameID(run, 1), "g-bb341404cf686511")
	seeds := map[[2]any]uint64{{uint64(0), "p0"}: 8103969398531465, {uint64(0), "p1"}: 1382627979884484,
		{uint64(1), "p0"}: 4616060983342951, {uint64(1), "p1"}: 7705961899067306}
	for k, want := range seeds {
		if got := secrets.AgentSeed(run, k[0].(uint64), k[1].(string)); got != want {
			t.Errorf("agent_seed%v = %d, want %d", k, got, want)
		}
	}
}

func TestEngineVectors(t *testing.T) {
	g, err := secrets.ParseGame("7648831b4ae4148770e13149d5ebbe1c4991168413d4b38e49292cfc5538980e")
	if err != nil {
		t.Fatal(err)
	}
	if g.IDKeyHex() != "842e5229d41477f389ae25e2b8196afb5bfa8c6bd9b95d7bd3703031c88e22e6" {
		t.Fatalf("id_key %s", g.IDKeyHex())
	}
	for msg, want := range map[string]string{
		"p0:card-17:z2":        "o-0a3647243d16bf78",
		"p1:card-17:z2":        "o-e5e4b7ed2a0730e4",
		"p0:card-17:z2:look:0": "o-794a5cb152c9620f",
		"p0:card-17:z2:look:1": "o-e18a35822cc60e1c",
	} {
		if got := g.ObjectID(msg); got != want {
			t.Errorf("object id %q = %s, want %s", msg, got, want)
		}
	}
	seed := g.StreamSeed("p1", "library_shuffle", 0)
	if hex.EncodeToString(seed[:8]) != "8a28fd4db75719b1" {
		t.Fatalf("stream seed %x", seed[:8])
	}
	if _, err := secrets.ParseGame("7648831B4AE4148770E13149D5EBBE1C4991168413D4B38E49292CFC5538980E"); err == nil {
		t.Fatal("uppercase secret accepted")
	}
}

// The spec's vectors cannot pin decimal(i) (indices 0 and 1 read the same in
// every base), the 53-bit mask (bit 53 is clear in all four seeds) or the full
// 32-byte stream key (8 bytes shown). These values were recomputed from the
// Section 5.3 and 11.6 construction text with Python's hmac and hashlib.
func TestConstructionsBeyondTheSpecVectors(t *testing.T) {
	run := runSecret()
	if got := hex.EncodeToString(secrets.GameSecret(run, 10)); got != "665878863cc32544fc66ce7804ed8e7b02f00783183381a08a29a8b3aa468ea6" {
		t.Errorf("game_secret(10) = %s", got)
	}
	if got := secrets.GameID(run, 10); got != "g-e16ded201d7921c3" {
		t.Errorf("game_id(10) = %s", got)
	}
	if got := secrets.AgentSeed(run, 10, "p0"); got != 2080768786345996 {
		t.Errorf("agent_seed(10, p0) = %d", got)
	}
	sec := secrets.GameSecret(run, 0)
	g := secrets.NewGame(sec)
	clear(sec) // NewGame keeps its own copy
	for n, want := range map[uint64]string{
		0:  "8a28fd4db75719b1c4baa10bb426f06330f629bdbe8821c30f02cdf84085fc9e",
		10: "c8224067975e40b3344605f2fcf531bbd7d8f019393909c38e7711791da26af8",
	} {
		seed := g.StreamSeed("p1", "library_shuffle", n)
		if got := hex.EncodeToString(seed[:]); got != want {
			t.Errorf("stream seed %d = %s, want %s", n, got, want)
		}
		key, _ := hex.DecodeString(want)
		ref := rand.New(rand.NewChaCha8([32]byte(key)))
		s := g.Stream("p1", "library_shuffle", n)
		for range 4 {
			if a, b := s.Uint64(), ref.Uint64(); a != b {
				t.Fatalf("stream %d drew %d, ChaCha8 keyed by the seed draws %d", n, a, b)
			}
		}
	}
}

// reset.game_secret is exactly 64 lowercase hex characters (Section 9.2).
func TestParseGameRejectsOtherForms(t *testing.T) {
	const ok = "7648831b4ae4148770e13149d5ebbe1c4991168413d4b38e49292cfc5538980e"
	for _, s := range []string{"", ok[:62], ok[:63], ok + "0", ok + "00", ok[:63] + "g", " " + ok, ok + "\n"} {
		if _, err := secrets.ParseGame(s); err == nil {
			t.Errorf("ParseGame(%q) accepted", s)
		}
	}
}
