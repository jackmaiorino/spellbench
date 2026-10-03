package wire_test

import (
	"errors"
	"strings"
	"testing"

	"github.com/jackmaiorino/spellbench/engines/gorge/internal/wire"
)

func nest(n int) string { return strings.Repeat(`{"a":`, n) + `1` + strings.Repeat(`}`, n) }

func TestCheckStrictRejectsWhatSection2Forbids(t *testing.T) {
	bad := map[string]string{
		`{"a":1,"a":2}`:           "duplicate key",
		`{"a":1.0}`:               "fraction",
		`{"a":1e3}`:               "exponent",
		`{"a":9007199254740992}`:  "above 2^53-1",
		`{"a":-9007199254740992}`: "below -(2^53-1)",
		`{"a":"\ud800"}`:          "unpaired high surrogate",
		`{"a":"\udc00"}`:          "unpaired low surrogate",
		`{"a":01}`:                "leading zero",
		nest(65):                  "65 levels",
		"{\"a\":\"\xff\"}":        "invalid UTF-8",
		`{"a":1} x`:               "trailing data",
	}
	for in, why := range bad {
		if err := wire.CheckStrict([]byte(in)); err == nil {
			t.Errorf("%s accepted (%s)", in, why)
		}
	}
	good := []string{
		`{"a":9007199254740991,"b":-9007199254740991,"c":"\ud83d\ude00","d":[{"e":null,"f":true}]}`,
		nest(64),
		" {\"a\":\"Lim-D\u00fbl's Vault\"}\r",
	}
	for _, in := range good {
		if err := wire.CheckStrict([]byte(in)); err != nil {
			t.Errorf("%s rejected: %v", in, err)
		}
	}
}

func TestCheckStrictClassifiesTopLevel(t *testing.T) {
	var se *wire.StrictError
	if err := wire.CheckStrict([]byte(`[1]`)); !errors.As(err, &se) || se.Code != wire.CodeNotObject {
		t.Fatalf("array top level: %v", err)
	}
	if err := wire.CheckStrict([]byte(`{"a":`)); !errors.As(err, &se) || se.Code != wire.CodeMalformedJSON {
		t.Fatalf("truncated object: %v", err)
	}
	if err := wire.CheckStrictAny([]byte(`[{"count":4,"name":"Lightning Bolt"}]`)); err != nil {
		t.Fatalf("CheckStrictAny rejected an array: %v", err)
	}
}
