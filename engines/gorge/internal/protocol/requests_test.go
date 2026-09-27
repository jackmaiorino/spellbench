package protocol_test

import (
	"reflect"
	"slices"
	"strings"
	"testing"

	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
)

const goodReset = `{"request_type":"reset","protocol":"spellbench/v2","request_id":"h-2","game_id":"g-1","format":"pauper-bo1","seats":[{"seat":"p0","deck":{"deck_id":"sha256:aa","catalog_id":"Burn"}},{"seat":"p1","deck":{"deck_id":"sha256:bb","catalog_id":"Spy"}}],"rules":{"opponent_decklist":"visible","mulligan":"london","starting_player":"host_assigned","starting_seat":"p0","card_name_domain":{"domain_id":"sha256:cc","names":["Lightning Bolt"]},"extensions":["x_gorge_view_v1"],"probe":false},"game_secret":"7648831b4ae4148770e13149d5ebbe1c4991168413d4b38e49292cfc5538980e","max_decisions":10000,"max_steps":100000}`

func TestDecodeReset(t *testing.T) {
	req, perr := protocol.Decode([]byte(goodReset))
	if perr != nil {
		t.Fatal(perr)
	}
	r := req.Reset
	if req.ID != "h-2" || r.GameID != "g-1" || r.Decks[1].CatalogID != "Spy" || r.Rules.Mulligan != "london" ||
		*r.Rules.StartingSeat != "p0" || r.MaxSteps != 100000 || len(r.Rules.Extensions) != 1 {
		t.Fatalf("decoded %+v", req.Reset)
	}
}

// Every other request type, valid. The error cases below edit these lines, so
// an edit that matched nothing would leave a valid line and fail the test.
const (
	goodHello    = `{"request_type":"hello","protocol":"spellbench/v2","request_id":"a","protocol_minor":0}`
	goodStep     = `{"request_type":"step","protocol":"spellbench/v2","request_id":"s","game_id":"g","expected_step":0,"selection":{"candidate_id":0,"semantic_echo":{"kind":"pass"}}}`
	goodValidate = `{"request_type":"validate_deck","protocol":"spellbench/v2","request_id":"v","format":"pauper-bo1","deck":{"catalog_id":"Burn"}}`
	goodProbe    = `{"request_type":"probe_resample","protocol":"spellbench/v2","request_id":"p","game_id":"g","samples":1}`
)

// sub replaces the first from in line with to.
func sub(line, from, to string) string { return strings.Replace(line, from, to, 1) }

// withDecklist gives seat p0 a decklist deck in place of its catalog deck.
func withDecklist(rows string) string {
	return sub(goodReset, `"catalog_id":"Burn"}`, `"decklist":`+rows+`}`)
}

// validateList is a validate_deck request for a decklist deck.
func validateList(rows string) string {
	return sub(goodValidate, `{"catalog_id":"Burn"}`, `{"decklist":`+rows+`}`)
}

func TestDecodeEveryRequestType(t *testing.T) {
	decode := func(line string) protocol.Request {
		t.Helper()
		req, perr := protocol.Decode([]byte(line))
		if perr != nil {
			t.Fatalf("%s: %v", line, perr)
		}
		return req
	}
	if req := decode(goodHello); req.Type != "hello" || req.ID != "a" || req.Hello == nil || req.Hello.ProtocolMinor != 0 {
		t.Errorf("hello: %+v", req)
	}
	if req := decode(goodStep); req.Type != "step" || req.Step == nil || req.Step.GameID != "g" || req.Step.ExpectedStep != 0 ||
		req.Step.CandidateID != 0 || string(req.Step.Echo) != `{"kind":"pass"}` {
		t.Errorf("step: %+v", req.Step)
	}
	if req := decode(goodValidate); req.Type != "validate_deck" || req.ValidateDeck == nil ||
		!reflect.DeepEqual(*req.ValidateDeck, protocol.ValidateDeckReq{Format: "pauper-bo1", Deck: protocol.DeckSpec{CatalogID: "Burn"}}) {
		t.Errorf("validate_deck: %+v", req.ValidateDeck)
	}
	rows := []protocol.DeckRow{{Name: "Mountain", Count: 40}, {Name: "Lightning Bolt", Count: 20}}
	const list = `[{"name":"Mountain","count":40},{"count":20,"name":"Lightning Bolt"}]`
	if req := decode(validateList(list)); req.ValidateDeck == nil || !req.ValidateDeck.Deck.IsDecklist ||
		!reflect.DeepEqual(req.ValidateDeck.Deck.Decklist, rows) {
		t.Errorf("validate_deck decklist: %+v", req.ValidateDeck)
	}
	if req := decode(goodProbe); req.Type != "probe_resample" || req.Probe == nil || *req.Probe != (protocol.ProbeReq{GameID: "g", Samples: 1}) {
		t.Errorf("probe_resample: %+v", req.Probe)
	}
	req := decode(withDecklist(list))
	if d := req.Reset.Decks; !reflect.DeepEqual(d[0], protocol.DeckSpec{DeckID: "sha256:aa", Decklist: rows, IsDecklist: true}) ||
		!reflect.DeepEqual(d[1], protocol.DeckSpec{DeckID: "sha256:bb", CatalogID: "Spy"}) {
		t.Errorf("reset decks: %+v", d)
	}
	p0 := "p0"
	want := protocol.Rules{OpponentDecklist: "visible", Mulligan: "london", StartingPlayer: "host_assigned", StartingSeat: &p0,
		DomainID: "sha256:cc", Names: []string{"Lightning Bolt"}, Extensions: []string{"x_gorge_view_v1"}}
	if !reflect.DeepEqual(req.Reset.Rules, want) || req.Reset.GameSecret != "7648831b4ae4148770e13149d5ebbe1c4991168413d4b38e49292cfc5538980e" ||
		req.Reset.MaxDecisions != 10000 || req.Reset.Format != "pauper-bo1" {
		t.Errorf("reset: %+v", req.Reset)
	}
	for _, line := range []string{
		sub(goodReset, `"probe":false`, `"probe":true`),
		sub(goodReset, `"names":["Lightning Bolt"]`, `"names":[]`),
		sub(goodReset, `"extensions":["x_gorge_view_v1"]`, `"extensions":[]`),
	} {
		r := decode(line).Reset.Rules
		if r.Probe != strings.Contains(line, `"probe":true`) || r.Names == nil || r.Extensions == nil {
			t.Errorf("%s: %+v", line, r)
		}
	}
}

func TestDecodeReadsEscapedStrings(t *testing.T) {
	// A host may escape any character (Section 2 allows any valid JSON layout);
	// decoded names are compared and checked as the strings they denote.
	line := sub(withDecklist(`[{"name":"Troll of Khazad-d\u00fbm","count":4},{"name":"L\u00f3rien Revealed","count":4}]`),
		`"names":["Lightning Bolt"]`, `"names":["Lightning\u0020Bolt","\"Ach! Hans, Run!\""]`)
	req, perr := protocol.Decode([]byte(line))
	if perr != nil {
		t.Fatal(perr)
	}
	rows := []protocol.DeckRow{{Name: "Troll of Khazad-dûm", Count: 4}, {Name: "Lórien Revealed", Count: 4}}
	if !reflect.DeepEqual(req.Reset.Decks[0].Decklist, rows) || !slices.Equal(req.Reset.Rules.Names, []string{"Lightning Bolt", `"Ach! Hans, Run!"`}) {
		t.Fatalf("decoded %+v and %q", req.Reset.Decks[0].Decklist, req.Reset.Rules.Names)
	}
}

func TestDecodeTossWinnerChoosesHasANullStartingSeat(t *testing.T) {
	line := sub(sub(goodReset, `"starting_player":"host_assigned"`, `"starting_player":"toss_winner_chooses"`), `"starting_seat":"p0"`, `"starting_seat":null`)
	req, perr := protocol.Decode([]byte(line))
	if perr != nil || req.Reset.Rules.StartingPlayer != "toss_winner_chooses" || req.Reset.Rules.StartingSeat != nil {
		t.Fatalf("%v %+v", perr, req.Reset)
	}
}

func TestDecodeAcceptsTheIntegerBounds(t *testing.T) {
	// u32 fields reach 2^32-1 (Sections 4.2, 4.4, 9.7, 12.1); counters reach 2^53-1 (Section 4.4).
	cases := []struct {
		line string
		read func(protocol.Request) uint64
		want uint64
	}{
		{sub(goodHello, `"protocol_minor":0`, `"protocol_minor":4294967295`), func(r protocol.Request) uint64 { return r.Hello.ProtocolMinor }, 1<<32 - 1},
		{sub(goodStep, `"candidate_id":0`, `"candidate_id":4294967295`), func(r protocol.Request) uint64 { return r.Step.CandidateID }, 1<<32 - 1},
		{sub(goodStep, `"expected_step":0`, `"expected_step":9007199254740991`), func(r protocol.Request) uint64 { return r.Step.ExpectedStep }, 1<<53 - 1},
		{sub(goodProbe, `"samples":1`, `"samples":4294967295`), func(r protocol.Request) uint64 { return r.Probe.Samples }, 1<<32 - 1},
		{withDecklist(`[{"name":"Mountain","count":4294967295}]`), func(r protocol.Request) uint64 { return uint64(r.Reset.Decks[0].Decklist[0].Count) }, 1<<32 - 1},
		{sub(goodReset, `"max_decisions":10000`, `"max_decisions":9007199254740991`), func(r protocol.Request) uint64 { return r.Reset.MaxDecisions }, 1<<53 - 1},
		{sub(goodReset, `"max_steps":100000`, `"max_steps":0`), func(r protocol.Request) uint64 { return r.Reset.MaxSteps }, 0},
	}
	for _, c := range cases {
		req, perr := protocol.Decode([]byte(c.line))
		if perr != nil {
			t.Errorf("%s: %v", c.line, perr)
		} else if got := c.read(req); got != c.want {
			t.Errorf("%s: decoded %d, want %d", c.line, got, c.want)
		}
	}
}

func TestDecodeAcceptsAnyJSONLayout(t *testing.T) {
	// Insignificant spaces and tabs are valid JSON (Section 2): the strict
	// getters must not depend on the compact layout.
	spaced := strings.NewReplacer(`,"`, " ,\t\"", `":`, "\" :\t ", `[`, "[ ", `]`, " ]", `{`, " { ", `}`, " } ")
	for _, line := range []string{goodReset, withDecklist(`[{"name":"Mountain","count":60}]`), goodHello, goodStep, validateList(`[{"name":"Mountain","count":60}]`), goodProbe} {
		want, perr := protocol.Decode([]byte(line))
		if perr != nil {
			t.Fatalf("%s: %v", line, perr)
		}
		got, perr := protocol.Decode([]byte(spaced.Replace(line)))
		if perr != nil {
			t.Fatalf("%s: %v", spaced.Replace(line), perr)
		}
		got.Line, want.Line = nil, nil
		if got.Step != nil { // the echo stays raw, spaces included
			got.Step.Echo, want.Step.Echo = nil, nil
		}
		if !reflect.DeepEqual(got, want) {
			t.Errorf("%s: decoded %+v, want %+v", spaced.Replace(line), got, want)
		}
	}
}

func TestErrorCodesAreTheClosedTable(t *testing.T) {
	// Section 9.8, in the table's order.
	want := []string{"malformed_json", "malformed_request", "protocol_mismatch", "request_id_reuse_mismatch",
		"step_before_reset", "game_already_active", "game_id_mismatch", "expected_step_mismatch",
		"candidate_id_out_of_range", "semantic_echo_mismatch", "unsupported_format", "unsupported_deck",
		"deck_id_mismatch", "unsupported_rule", "unsupported_request", "probe_refused", "game_already_terminal"}
	got := []string{protocol.CodeMalformedJSON, protocol.CodeMalformedRequest, protocol.CodeProtocolMismatch, protocol.CodeRequestIDReuseMismatch,
		protocol.CodeStepBeforeReset, protocol.CodeGameAlreadyActive, protocol.CodeGameIDMismatch, protocol.CodeExpectedStepMismatch,
		protocol.CodeCandidateIDOutOfRange, protocol.CodeSemanticEchoMismatch, protocol.CodeUnsupportedFormat, protocol.CodeUnsupportedDeck,
		protocol.CodeDeckIDMismatch, protocol.CodeUnsupportedRule, protocol.CodeUnsupportedRequest, protocol.CodeProbeRefused, protocol.CodeGameAlreadyTerminal}
	if !slices.Equal(got, want) {
		t.Fatalf("codes %q, want %q", got, want)
	}
	if e := protocol.Errf(protocol.CodeProbeRefused, "no probe"); e.Code != "probe_refused" || e.Message != "no probe" || e.Error() != "probe_refused: no probe" {
		t.Fatalf("Errf gave %+v (%q)", e, e.Error())
	}
}

func TestDecodeErrorsUseTheClosedTable(t *testing.T) {
	cases := []struct{ line, code, id string }{
		{`{"request_type":"hello"`, protocol.CodeMalformedJSON, ""},
		{`[1]`, protocol.CodeMalformedRequest, ""},
		{`{"request_type":"hello","protocol":"spellbench/v2","request_id":5,"protocol_minor":0}`, protocol.CodeMalformedRequest, ""},
		{`{"request_type":"hello","protocol":"spellbench/v1","request_id":"a","protocol_minor":0}`, protocol.CodeProtocolMismatch, "a"},
		{`{"request_type":"hello","request_id":"a","protocol_minor":0}`, protocol.CodeMalformedRequest, "a"},
		{`{"request_type":"hello","protocol":"spellbench/v2","request_id":"a","protocol_minor":0,"x_extra":1}`, protocol.CodeMalformedRequest, "a"},
		{`{"request_type":"quit","protocol":"spellbench/v2","request_id":"a"}`, protocol.CodeMalformedRequest, "a"},
		{strings.Replace(goodReset, `"p1","deck"`, `"p0","deck"`, 1), protocol.CodeMalformedRequest, "h-2"},
		{strings.Replace(goodReset, `"catalog_id":"Burn"}`, `"catalog_id":"Burn","decklist":[]}`, 1), protocol.CodeMalformedRequest, "h-2"},
		{strings.Replace(goodReset, `"mulligan":"london"`, `"mulligan":"paris"`, 1), protocol.CodeMalformedRequest, "h-2"},
		{strings.Replace(goodReset, `7648831b`, `7648831B`, 1), protocol.CodeMalformedRequest, "h-2"},
		{`{"request_type":"step","protocol":"spellbench/v2","request_id":"s","game_id":"g","expected_step":0,"selection":{"candidate_id":0}}`, protocol.CodeMalformedRequest, "s"},

		// JSON null in each field of each request (G1-4): null is never a
		// string, bool, integer, array or object, and a null protocol is
		// malformed_request, not protocol_mismatch (Section 4.1).
		{sub(goodHello, `"request_id":"a"`, `"request_id":null`), protocol.CodeMalformedRequest, ""},
		{sub(goodHello, `"protocol":"spellbench/v2"`, `"protocol":null`), protocol.CodeMalformedRequest, "a"},
		{sub(goodHello, `"request_type":"hello"`, `"request_type":null`), protocol.CodeMalformedRequest, "a"},
		{sub(goodHello, `"protocol_minor":0`, `"protocol_minor":null`), protocol.CodeMalformedRequest, "a"},
		{sub(goodReset, `"game_id":"g-1"`, `"game_id":null`), protocol.CodeMalformedRequest, "h-2"},
		{sub(goodReset, `"format":"pauper-bo1"`, `"format":null`), protocol.CodeMalformedRequest, "h-2"},
		{sub(goodReset, `"seats":[{"seat":"p0","deck":{"deck_id":"sha256:aa","catalog_id":"Burn"}},{"seat":"p1","deck":{"deck_id":"sha256:bb","catalog_id":"Spy"}}]`, `"seats":null`), protocol.CodeMalformedRequest, "h-2"},
		{sub(goodReset, `{"seat":"p1","deck":{"deck_id":"sha256:bb","catalog_id":"Spy"}}`, `null`), protocol.CodeMalformedRequest, "h-2"},
		{sub(goodReset, `"seat":"p0"`, `"seat":null`), protocol.CodeMalformedRequest, "h-2"},
		{sub(goodReset, `"deck":{"deck_id":"sha256:aa","catalog_id":"Burn"}`, `"deck":null`), protocol.CodeMalformedRequest, "h-2"},
		{sub(goodReset, `"deck_id":"sha256:aa"`, `"deck_id":null`), protocol.CodeMalformedRequest, "h-2"},
		{sub(goodReset, `"catalog_id":"Burn"`, `"catalog_id":null`), protocol.CodeMalformedRequest, "h-2"},
		{withDecklist(`null`), protocol.CodeMalformedRequest, "h-2"},
		{withDecklist(`[null]`), protocol.CodeMalformedRequest, "h-2"},
		{withDecklist(`[{"name":null,"count":60}]`), protocol.CodeMalformedRequest, "h-2"},
		{withDecklist(`[{"name":"Mountain","count":null}]`), protocol.CodeMalformedRequest, "h-2"},
		{sub(goodReset, `"rules":{"opponent_decklist":"visible","mulligan":"london","starting_player":"host_assigned","starting_seat":"p0","card_name_domain":{"domain_id":"sha256:cc","names":["Lightning Bolt"]},"extensions":["x_gorge_view_v1"],"probe":false}`, `"rules":null`), protocol.CodeMalformedRequest, "h-2"},
		{sub(goodReset, `"opponent_decklist":"visible"`, `"opponent_decklist":null`), protocol.CodeMalformedRequest, "h-2"},
		{sub(goodReset, `"mulligan":"london"`, `"mulligan":null`), protocol.CodeMalformedRequest, "h-2"},
		{sub(goodReset, `"starting_player":"host_assigned"`, `"starting_player":null`), protocol.CodeMalformedRequest, "h-2"},
		{sub(goodReset, `"starting_seat":"p0"`, `"starting_seat":null`), protocol.CodeMalformedRequest, "h-2"}, // host_assigned needs a seat
		{sub(goodReset, `"card_name_domain":{"domain_id":"sha256:cc","names":["Lightning Bolt"]}`, `"card_name_domain":null`), protocol.CodeMalformedRequest, "h-2"},
		{sub(goodReset, `"domain_id":"sha256:cc"`, `"domain_id":null`), protocol.CodeMalformedRequest, "h-2"},
		{sub(goodReset, `"names":["Lightning Bolt"]`, `"names":null`), protocol.CodeMalformedRequest, "h-2"},
		{sub(goodReset, `"names":["Lightning Bolt"]`, `"names":["Lightning Bolt",null]`), protocol.CodeMalformedRequest, "h-2"},
		{sub(goodReset, `"extensions":["x_gorge_view_v1"]`, `"extensions":null`), protocol.CodeMalformedRequest, "h-2"},
		{sub(goodReset, `"extensions":["x_gorge_view_v1"]`, `"extensions":[null]`), protocol.CodeMalformedRequest, "h-2"},
		{sub(goodReset, `"probe":false`, `"probe":null`), protocol.CodeMalformedRequest, "h-2"},
		{sub(goodReset, `"game_secret":"7648831b4ae4148770e13149d5ebbe1c4991168413d4b38e49292cfc5538980e"`, `"game_secret":null`), protocol.CodeMalformedRequest, "h-2"},
		{sub(goodReset, `"max_decisions":10000`, `"max_decisions":null`), protocol.CodeMalformedRequest, "h-2"},
		{sub(goodReset, `"max_steps":100000`, `"max_steps":null`), protocol.CodeMalformedRequest, "h-2"},
		{sub(goodStep, `"game_id":"g"`, `"game_id":null`), protocol.CodeMalformedRequest, "s"},
		{sub(goodStep, `"expected_step":0`, `"expected_step":null`), protocol.CodeMalformedRequest, "s"},
		{sub(goodStep, `"selection":{"candidate_id":0,"semantic_echo":{"kind":"pass"}}`, `"selection":null`), protocol.CodeMalformedRequest, "s"},
		{sub(goodStep, `"candidate_id":0`, `"candidate_id":null`), protocol.CodeMalformedRequest, "s"},
		{sub(goodStep, `"semantic_echo":{"kind":"pass"}`, `"semantic_echo":null`), protocol.CodeMalformedRequest, "s"},
		{sub(goodValidate, `"format":"pauper-bo1"`, `"format":null`), protocol.CodeMalformedRequest, "v"},
		{sub(goodValidate, `"deck":{"catalog_id":"Burn"}`, `"deck":null`), protocol.CodeMalformedRequest, "v"},
		{sub(goodValidate, `"catalog_id":"Burn"`, `"catalog_id":null`), protocol.CodeMalformedRequest, "v"},
		{validateList(`null`), protocol.CodeMalformedRequest, "v"},
		{validateList(`[null]`), protocol.CodeMalformedRequest, "v"},
		{validateList(`[{"name":null,"count":60}]`), protocol.CodeMalformedRequest, "v"},
		{validateList(`[{"name":"Mountain","count":null}]`), protocol.CodeMalformedRequest, "v"},
		{sub(goodProbe, `"game_id":"g"`, `"game_id":null`), protocol.CodeMalformedRequest, "p"},
		{sub(goodProbe, `"samples":1`, `"samples":null`), protocol.CodeMalformedRequest, "p"},

		// Other wrong types: a string field takes only a string, a bool field
		// only true or false, an array field only an array of its element type.
		{sub(goodHello, `"protocol":"spellbench/v2"`, `"protocol":5`), protocol.CodeMalformedRequest, "a"},
		{sub(goodHello, `"request_type":"hello"`, `"request_type":["hello"]`), protocol.CodeMalformedRequest, "a"},
		{sub(goodReset, `"game_id":"g-1"`, `"game_id":1`), protocol.CodeMalformedRequest, "h-2"},
		{sub(goodReset, `"format":"pauper-bo1"`, `"format":["pauper-bo1"]`), protocol.CodeMalformedRequest, "h-2"},
		{sub(goodReset, `"deck_id":"sha256:aa"`, `"deck_id":{}`), protocol.CodeMalformedRequest, "h-2"},
		{sub(goodReset, `"catalog_id":"Burn"`, `"catalog_id":true`), protocol.CodeMalformedRequest, "h-2"},
		{sub(goodReset, `"starting_seat":"p0"`, `"starting_seat":0`), protocol.CodeMalformedRequest, "h-2"},
		{sub(goodReset, `"domain_id":"sha256:cc"`, `"domain_id":0`), protocol.CodeMalformedRequest, "h-2"},
		{sub(goodReset, `"names":["Lightning Bolt"]`, `"names":"Lightning Bolt"`), protocol.CodeMalformedRequest, "h-2"},
		{sub(goodReset, `"names":["Lightning Bolt"]`, `"names":[["Lightning Bolt"]]`), protocol.CodeMalformedRequest, "h-2"},
		{sub(goodReset, `"extensions":["x_gorge_view_v1"]`, `"extensions":{"x_gorge_view_v1":true}`), protocol.CodeMalformedRequest, "h-2"},
		{sub(goodReset, `"extensions":["x_gorge_view_v1"]`, `"extensions":[1]`), protocol.CodeMalformedRequest, "h-2"},
		{sub(goodReset, `"probe":false`, `"probe":"false"`), protocol.CodeMalformedRequest, "h-2"},
		{sub(goodReset, `"probe":false`, `"probe":0`), protocol.CodeMalformedRequest, "h-2"},
		{sub(goodReset, `"max_steps":100000`, `"max_steps":"100000"`), protocol.CodeMalformedRequest, "h-2"},
		{sub(goodStep, `"game_id":"g"`, `"game_id":7`), protocol.CodeMalformedRequest, "s"},
		{sub(goodStep, `"semantic_echo":{"kind":"pass"}`, `"semantic_echo":[]`), protocol.CodeMalformedRequest, "s"},
		{sub(goodValidate, `"format":"pauper-bo1"`, `"format":{}`), protocol.CodeMalformedRequest, "v"},
		{sub(goodProbe, `"game_id":"g"`, `"game_id":false`), protocol.CodeMalformedRequest, "p"},

		// Decklist rows are exactly {name, count} (Section 12.1): case-sensitive
		// keys and no others, a nonempty name, a count in [1, 2^32-1], and each
		// name once, in reset and in validate_deck.
		{withDecklist(`[{"name":"Mountain","count":60,"x_note":1}]`), protocol.CodeMalformedRequest, "h-2"},
		{withDecklist(`[{"Name":"Mountain","count":60}]`), protocol.CodeMalformedRequest, "h-2"},
		{withDecklist(`[{"name":"Mountain","Count":60}]`), protocol.CodeMalformedRequest, "h-2"},
		{withDecklist(`[{"name":"Mountain"}]`), protocol.CodeMalformedRequest, "h-2"},
		{withDecklist(`[{"name":"Mountain","count":0}]`), protocol.CodeMalformedRequest, "h-2"},
		{withDecklist(`[{"name":"Mountain","count":-1}]`), protocol.CodeMalformedRequest, "h-2"},
		{withDecklist(`[{"name":"Mountain","count":4294967296}]`), protocol.CodeMalformedRequest, "h-2"},
		{withDecklist(`[{"name":"Mountain","count":"60"}]`), protocol.CodeMalformedRequest, "h-2"},
		{withDecklist(`[{"name":"","count":60}]`), protocol.CodeMalformedRequest, "h-2"},
		{withDecklist(`[{"name":5,"count":60}]`), protocol.CodeMalformedRequest, "h-2"},
		{withDecklist(`[{"name":"Mountain","count":30},{"name":"Mountain","count":30}]`), protocol.CodeMalformedRequest, "h-2"},
		{withDecklist(`["Mountain"]`), protocol.CodeMalformedRequest, "h-2"},
		{withDecklist(`{"Mountain":60}`), protocol.CodeMalformedRequest, "h-2"},
		{withDecklist(`[{"name":"Mountain","count":30},{"name":"Mount\u0061in","count":30}]`), protocol.CodeMalformedRequest, "h-2"},
		{validateList(`[{"name":"Mountain","count":30},{"name":"Mountain","count":30}]`), protocol.CodeMalformedRequest, "v"},
		{validateList(`[{"name":"Mountain","count":60,"x_note":1}]`), protocol.CodeMalformedRequest, "v"},
		{validateList(`[{"Name":"Mountain","count":60}]`), protocol.CodeMalformedRequest, "v"},
		{validateList(`[{"name":"Mountain","count":0}]`), protocol.CodeMalformedRequest, "v"},

		// u32 fields stop at 2^32-1 (Sections 4.2, 4.4 and 9.7). Past 2^53-1, or
		// with a fraction, the line is not strict JSON at all (Section 2).
		{sub(goodHello, `"protocol_minor":0`, `"protocol_minor":4294967296`), protocol.CodeMalformedRequest, "a"},
		{sub(goodHello, `"protocol_minor":0`, `"protocol_minor":-1`), protocol.CodeMalformedRequest, "a"},
		{sub(goodStep, `"candidate_id":0`, `"candidate_id":4294967296`), protocol.CodeMalformedRequest, "s"},
		{sub(goodProbe, `"samples":1`, `"samples":4294967296`), protocol.CodeMalformedRequest, "p"},
		{sub(goodReset, `"max_steps":100000`, `"max_steps":9007199254740992`), protocol.CodeMalformedJSON, ""},
		{sub(goodHello, `"protocol_minor":0`, `"protocol_minor":0.0`), protocol.CodeMalformedJSON, ""},

		// Empty ids and a secret of the wrong length (Sections 4.1, 9.2).
		{sub(goodHello, `"request_id":"a"`, `"request_id":""`), protocol.CodeMalformedRequest, ""},
		{sub(goodReset, `"game_id":"g-1"`, `"game_id":""`), protocol.CodeMalformedRequest, "h-2"},
		{sub(goodReset, `8e49292cfc5538980e"`, `8e49292cfc5538980e0"`), protocol.CodeMalformedRequest, "h-2"},

		// starting_seat is a seat exactly when starting_player is host_assigned (Section 12.2).
		{sub(goodReset, `"starting_seat":"p0"`, `"starting_seat":"p2"`), protocol.CodeMalformedRequest, "h-2"},
		{sub(goodReset, `"starting_player":"host_assigned"`, `"starting_player":"toss_winner_chooses"`), protocol.CodeMalformedRequest, "h-2"},
	}
	for _, c := range cases {
		req, perr := protocol.Decode([]byte(c.line))
		if perr == nil || perr.Code != c.code || req.ID != c.id {
			t.Errorf("%s: got %+v id %q, want %s id %q", c.line, perr, req.ID, c.code, c.id)
		}
		if req.Hello != nil || req.Reset != nil || req.Step != nil || req.ValidateDeck != nil || req.Probe != nil {
			t.Errorf("%s: a failed decode set a request: %+v", c.line, req)
		}
	}
}
