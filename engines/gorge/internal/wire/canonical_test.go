package wire_test

import (
	"crypto/sha256"
	"encoding/hex"
	"testing"

	"github.com/jackmaiorino/spellbench/engines/gorge/internal/wire"
)

func TestCanonicalMatchesSpecVector(t *testing.T) {
	in := []byte("{\"b\":\"Chainer's Edict\",\"a\":\"Lim-D\\u00fbl's Vault\",\"c\":\"tab\\there\"}")
	out, err := wire.CanonicalBytes(in)
	if err != nil {
		t.Fatal(err)
	}
	if string(out) != "{\"a\":\"Lim-D\u00fbl's Vault\",\"b\":\"Chainer's Edict\",\"c\":\"tab\\there\"}" {
		t.Fatalf("canonical %s", out)
	}
	sum := sha256.Sum256(out)
	if got := hex.EncodeToString(sum[:]); got != "041575311eb1deb02f63f70361e14159034faf0d2a31e57edf8b4cf037680377" {
		t.Fatalf("sha256 %s", got)
	}
}

func TestDeckAndDomainIDVectors(t *testing.T) {
	id := wire.DeckID([]wire.DeckRow{{Name: "Mountain", Count: 18}, {Name: "Lightning Bolt", Count: 4}})
	if id != "sha256:0df0a001e3c4b74b1061b21e319a645f32fbe3173120e432864e14d6d6f2f5d2" {
		t.Fatalf("deck_id %s", id)
	}
	dom := wire.DomainID([]string{"Mountain", "Lightning Bolt"})
	if dom != "sha256:74f7f4b39eecbed1c039cf4b229fa533069d2cdd8caf3bb6380b832eb40fb697" {
		t.Fatalf("domain_id %s", dom)
	}
}

const specReset = `{"request_type":"reset","protocol":"spellbench/v2","request_id":"h-2","game_id":"g-f67d7fe78c792984","format":"pauper-bo1","seats":[{"seat":"p0","deck":{"deck_id":"sha256:0df0a001e3c4b74b1061b21e319a645f32fbe3173120e432864e14d6d6f2f5d2","catalog_id":"Burn"}},{"seat":"p1","deck":{"deck_id":"sha256:0df0a001e3c4b74b1061b21e319a645f32fbe3173120e432864e14d6d6f2f5d2","catalog_id":"Burn"}}],"rules":{"opponent_decklist":"visible","mulligan":"none","starting_player":"host_assigned","starting_seat":"p0","card_name_domain":{"domain_id":"sha256:74f7f4b39eecbed1c039cf4b229fa533069d2cdd8caf3bb6380b832eb40fb697","names":["Lightning Bolt","Mountain"]},"extensions":[],"probe":false},"game_secret":"7648831b4ae4148770e13149d5ebbe1c4991168413d4b38e49292cfc5538980e","max_decisions":10000,"max_steps":100000}`

func TestGameDigestFirstLinkVector(t *testing.T) {
	msg, err := wire.WithoutRequestID([]byte(specReset))
	if err != nil {
		t.Fatal(err)
	}
	d, err := wire.NewGameDigest(msg)
	if err != nil {
		t.Fatal(err)
	}
	if got := d.String(); got != "sha256:a328e304e4dcacdde5d8abe089c93a8bedd108e9985d3bdab6ede3b8e8f093a3" {
		t.Fatalf("first chain value %s", got)
	}
}

// Sub-project P's Python host pins the same bytes: short escapes, lowercase
// \u00xx, raw DEL and U+2028, and keys in UTF-16 code unit order (U+1F600 is
// D83D DE00, so it sorts before U+FFFD).
func TestCanonicalEscapesAndKeyOrderMatchTheHost(t *testing.T) {
	for _, c := range []struct{ in, want string }{
		{"{\"s\":\"\\u0000\\u0008\\u000c\\n\\r\\t\\u001f\x7f\\u2028\\\"\\\\\"}", "{\"s\":\"\\u0000\\b\\f\\n\\r\\t\\u001f\x7f\U00002028\\\"\\\\\"}"},
		{"{\"\\ufffd\":1,\"\\ud83d\\ude00\":2}", "{\"\U0001F600\":2,\"\U0000FFFD\":1}"},
	} {
		out, err := wire.CanonicalBytes([]byte(c.in))
		if err != nil {
			t.Fatal(err)
		}
		if string(out) != c.want {
			t.Errorf("canonical of %s: %q, want %q", c.in, out, c.want)
		}
	}
}

// A later link is SHA-256(d || canonical(message minus request_id)), whatever
// the message's layout (Section 11.8).
func TestGameDigestChainsCanonicalLinks(t *testing.T) {
	msg, err := wire.WithoutRequestID([]byte(specReset))
	if err != nil {
		t.Fatal(err)
	}
	d, err := wire.NewGameDigest(msg)
	if err != nil {
		t.Fatal(err)
	}
	if err := d.Chain([]byte(`{"step": 0, "response_type": "terminal"}`)); err != nil {
		t.Fatal(err)
	}
	first, err := hex.DecodeString("a328e304e4dcacdde5d8abe089c93a8bedd108e9985d3bdab6ede3b8e8f093a3")
	if err != nil {
		t.Fatal(err)
	}
	want := sha256.Sum256(append(first, `{"response_type":"terminal","step":0}`...))
	if got := d.String(); got != "sha256:"+hex.EncodeToString(want[:]) {
		t.Fatalf("second chain value %s", got)
	}
}
