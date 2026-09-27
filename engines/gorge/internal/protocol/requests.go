package protocol

import (
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"regexp"
	"slices"
	"strconv"

	"github.com/jackmaiorino/spellbench/engines/gorge/internal/wire"
)

type HelloReq struct{ ProtocolMinor uint64 }

type DeckSpec struct {
	DeckID     string
	CatalogID  string
	Decklist   []DeckRow
	IsDecklist bool
}

type Rules struct {
	OpponentDecklist, Mulligan, StartingPlayer string
	StartingSeat                               *string
	DomainID                                   string
	Names                                      []string
	Extensions                                 []string
	Probe                                      bool
}

type ResetReq struct {
	GameID, Format         string
	Decks                  [2]DeckSpec
	Rules                  Rules
	GameSecret             string
	MaxDecisions, MaxSteps uint64
}

type StepReq struct {
	GameID       string
	ExpectedStep uint64
	CandidateID  uint64
	Echo         json.RawMessage
}

type ValidateDeckReq struct {
	Format string
	Deck   DeckSpec
}

type ProbeReq struct {
	GameID  string
	Samples uint64
}

type Request struct {
	Type, ID     string
	Line         []byte
	Hello        *HelloReq
	Reset        *ResetReq
	Step         *StepReq
	ValidateDeck *ValidateDeckReq
	Probe        *ProbeReq
}

type obj map[string]json.RawMessage

func exact(o obj, fields ...string) error {
	if len(o) != len(fields) {
		return fmt.Errorf("want fields %v", fields)
	}
	for _, f := range fields {
		if _, ok := o[f]; !ok {
			return fmt.Errorf("missing %s", f)
		}
	}
	return nil
}

// The readers check a raw value's type before decoding it: json.Unmarshal of
// null into a string, bool or slice is a silent no-op, and null is none of them.

// asString reads raw as a JSON string.
func asString(raw json.RawMessage) (s string, ok bool) {
	ok = len(raw) > 0 && raw[0] == '"' && json.Unmarshal(raw, &s) == nil
	return s, ok
}

func getStr(o obj, k string) (string, error) {
	if s, ok := asString(o[k]); ok {
		return s, nil
	}
	return "", fmt.Errorf("%s is not a string", k)
}

// getBool reads a field that is exactly true or false.
func getBool(o obj, k string) (bool, error) {
	switch string(o[k]) {
	case "true":
		return true, nil
	case "false":
		return false, nil
	}
	return false, fmt.Errorf("%s is not true or false", k)
}

// asArray reads raw as a JSON array, leaving its elements raw.
func asArray(raw json.RawMessage) (elems []json.RawMessage, ok bool) {
	ok = len(raw) > 0 && raw[0] == '[' && json.Unmarshal(raw, &elems) == nil
	return elems, ok
}

// getStrings reads an array field whose elements are all strings.
func getStrings(o obj, k string) ([]string, error) {
	elems, ok := asArray(o[k])
	if !ok {
		return nil, fmt.Errorf("%s is not an array", k)
	}
	out := make([]string, len(elems))
	for i, e := range elems {
		if out[i], ok = asString(e); !ok {
			return nil, fmt.Errorf("%s[%d] is not a string", k, i)
		}
	}
	return out, nil
}

// getU64 accepts only an integer literal (json.Number would also take "5").
// -0 is 0: Section 2 forbids only fractions and exponents, and CheckStrict has
// already refused every other signed spelling of zero ("-00" has a leading zero).
func getU64(o obj, k string) (uint64, error) {
	raw := o[k]
	if string(raw) == "-0" {
		return 0, nil
	}
	if len(raw) == 0 || raw[0] < '0' || raw[0] > '9' {
		return 0, fmt.Errorf("%s is not a non-negative integer", k)
	}
	v, err := strconv.ParseUint(string(raw), 10, 64)
	if err != nil {
		return 0, fmt.Errorf("%s is not a non-negative integer", k)
	}
	return v, nil
}

// getU32 is getU64 bounded to a u32 (Section 4.4).
func getU32(o obj, k string) (uint64, error) {
	v, err := getU64(o, k)
	if err != nil || v > math.MaxUint32 {
		return 0, fmt.Errorf("%s is not a u32", k)
	}
	return v, nil
}

func getObj(raw json.RawMessage) (obj, error) {
	var o obj
	if err := json.Unmarshal(raw, &o); err != nil || o == nil {
		return nil, fmt.Errorf("not an object")
	}
	return o, nil
}

var (
	hex64 = regexp.MustCompile(`^[0-9a-f]{64}$`)
	// deckIDForm is Section 4.3's deck_id: "sha256:" and 64 lowercase hex digits.
	deckIDForm = regexp.MustCompile(`^sha256:[0-9a-f]{64}$`)
	// extensionName is an x_ key (Section 14).
	extensionName = regexp.MustCompile(`^x_[a-z0-9_]+$`)
)

// firstRepeat returns the index of the first value that repeats an earlier
// one, or -1 when all are distinct.
func firstRepeat(vals []string) int {
	seen := make(map[string]bool, len(vals))
	for i, v := range vals {
		if seen[v] {
			return i
		}
		seen[v] = true
	}
	return -1
}

// Decode parses one request line strictly. On error, Request.ID holds the
// request_id when it could be read, else "", and no per-type request is set.
func Decode(line []byte) (Request, *Error) {
	req := Request{Line: line}
	if err := wire.CheckStrict(line); err != nil {
		var se *wire.StrictError
		if errors.As(err, &se) && se.Code == wire.CodeNotObject {
			return req, Errf(CodeMalformedRequest, se.Msg)
		}
		return req, Errf(CodeMalformedJSON, err.Error())
	}
	o, err := getObj(line) // cannot fail after CheckStrict; checked all the same
	if err != nil {
		return req, Errf(CodeMalformedRequest, "the request is not a JSON object")
	}
	if id, err := getStr(o, "request_id"); err == nil && id != "" {
		req.ID = id
	} else {
		return req, Errf(CodeMalformedRequest, "request_id is not a nonempty string")
	}
	ps, err := getStr(o, "protocol")
	if err != nil {
		return req, Errf(CodeMalformedRequest, "protocol is missing or not a string")
	}
	if ps != Name {
		return req, Errf(CodeProtocolMismatch, "protocol "+ps)
	}
	rt, err := getStr(o, "request_type")
	if err != nil {
		return req, Errf(CodeMalformedRequest, err.Error())
	}
	req.Type = rt
	var derr error
	switch rt {
	case "hello":
		derr = decodeHello(o, &req)
	case "reset":
		derr = decodeReset(o, &req)
	case "step":
		derr = decodeStep(o, &req)
	case "validate_deck":
		derr = decodeValidateDeck(o, &req)
	case "probe_resample":
		derr = decodeProbe(o, &req)
	default:
		derr = fmt.Errorf("unknown request_type %q", rt)
	}
	if derr != nil {
		return req, Errf(CodeMalformedRequest, derr.Error())
	}
	return req, nil
}

func decodeHello(o obj, req *Request) error {
	if err := exact(o, "request_type", "protocol", "request_id", "protocol_minor"); err != nil {
		return err
	}
	m, err := getU32(o, "protocol_minor")
	if err != nil {
		return err
	}
	req.Hello = &HelloReq{ProtocolMinor: m}
	return nil
}

// decodeDecklist reads Section 12.1's rows: at least one, each exactly
// {name, count}, with a nonempty name and a count in [1, 2^32-1], and no name
// twice.
func decodeDecklist(raw json.RawMessage) ([]DeckRow, error) {
	elems, ok := asArray(raw)
	if !ok || len(elems) == 0 {
		return nil, errors.New("decklist is not a nonempty array")
	}
	rows := make([]DeckRow, len(elems))
	seen := make(map[string]bool, len(elems))
	for i, e := range elems {
		row, err := getObj(e)
		if err != nil || exact(row, "name", "count") != nil {
			return nil, fmt.Errorf("decklist[%d] is not exactly {name, count}", i)
		}
		name, err := getStr(row, "name")
		if err != nil || name == "" {
			return nil, fmt.Errorf("decklist[%d].name is not a nonempty string", i)
		}
		count, err := getU32(row, "count")
		if err != nil || count == 0 {
			return nil, fmt.Errorf("decklist[%d].count is not in [1, 2^32-1]", i)
		}
		if seen[name] {
			return nil, fmt.Errorf("decklist names %q twice", name)
		}
		seen[name] = true
		rows[i] = DeckRow{Name: name, Count: uint32(count)}
	}
	return rows, nil
}

func decodeDeck(raw json.RawMessage) (DeckSpec, error) {
	d, err := getObj(raw)
	if err != nil {
		return DeckSpec{}, err
	}
	var s DeckSpec
	if s.DeckID, err = getStr(d, "deck_id"); err != nil || !deckIDForm.MatchString(s.DeckID) {
		return s, errors.New(`deck_id is not "sha256:" and 64 lowercase hex digits`)
	}
	switch {
	case exact(d, "deck_id", "catalog_id") == nil:
		s.CatalogID, err = getStr(d, "catalog_id")
	case exact(d, "deck_id", "decklist") == nil:
		s.IsDecklist = true
		s.Decklist, err = decodeDecklist(d["decklist"])
	default:
		err = errors.New("deck must be {deck_id, catalog_id} or {deck_id, decklist}")
	}
	return s, err
}

func oneOf(v string, vals ...string) error {
	if !slices.Contains(vals, v) {
		return fmt.Errorf("%q not in %v", v, vals)
	}
	return nil
}

func decodeRules(raw json.RawMessage) (Rules, error) {
	var r Rules
	o, err := getObj(raw)
	if err != nil {
		return r, err
	}
	if err := exact(o, "opponent_decklist", "mulligan", "starting_player", "starting_seat", "card_name_domain", "extensions", "probe"); err != nil {
		return r, err
	}
	if r.OpponentDecklist, err = getStr(o, "opponent_decklist"); err != nil || oneOf(r.OpponentDecklist, "visible", "hidden") != nil {
		return r, errors.New("opponent_decklist")
	}
	if r.Mulligan, err = getStr(o, "mulligan"); err != nil || oneOf(r.Mulligan, "london", "none") != nil {
		return r, errors.New("mulligan")
	}
	if r.StartingPlayer, err = getStr(o, "starting_player"); err != nil || oneOf(r.StartingPlayer, "host_assigned", "toss_winner_chooses") != nil {
		return r, errors.New("starting_player")
	}
	// Nullable: json.Unmarshal leaves the pointer nil for null and rejects
	// every other non-string.
	if err := json.Unmarshal(o["starting_seat"], &r.StartingSeat); err != nil ||
		(r.StartingSeat != nil && oneOf(*r.StartingSeat, "p0", "p1") != nil) ||
		(r.StartingPlayer == "host_assigned") != (r.StartingSeat != nil) {
		return r, errors.New("starting_seat")
	}
	dom, err := getObj(o["card_name_domain"])
	if err != nil || exact(dom, "domain_id", "names") != nil {
		return r, errors.New("card_name_domain")
	}
	if r.DomainID, err = getStr(dom, "domain_id"); err != nil {
		return r, err
	}
	if r.Names, err = getStrings(dom, "names"); err != nil {
		return r, err
	}
	if i := slices.Index(r.Names, ""); i >= 0 {
		return r, fmt.Errorf("card_name_domain.names[%d] is empty", i)
	}
	if i := firstRepeat(r.Names); i >= 0 {
		return r, fmt.Errorf("card_name_domain.names[%d] repeats %q", i, r.Names[i])
	}
	if r.Extensions, err = getStrings(o, "extensions"); err != nil {
		return r, err
	}
	for i, x := range r.Extensions {
		if !extensionName.MatchString(x) {
			return r, fmt.Errorf("extensions[%d] %q is not an x_[a-z0-9_]+ name", i, x)
		}
	}
	if i := firstRepeat(r.Extensions); i >= 0 {
		return r, fmt.Errorf("extensions[%d] repeats %q", i, r.Extensions[i])
	}
	if r.Probe, err = getBool(o, "probe"); err != nil {
		return r, err
	}
	return r, nil
}

// errGameID answers a missing, mistyped or empty game_id: reset, step and
// probe_resample each name a game.
var errGameID = errors.New("game_id is not a nonempty string")

func decodeReset(o obj, req *Request) error {
	if err := exact(o, "request_type", "protocol", "request_id", "game_id", "format", "seats", "rules", "game_secret", "max_decisions", "max_steps"); err != nil {
		return err
	}
	r := &ResetReq{}
	var err error
	if r.GameID, err = getStr(o, "game_id"); err != nil || r.GameID == "" {
		return errGameID
	}
	if r.Format, err = getStr(o, "format"); err != nil {
		return err
	}
	var seats []json.RawMessage
	if json.Unmarshal(o["seats"], &seats) != nil || len(seats) != 2 {
		return errors.New("seats must list p0 then p1")
	}
	for i, raw := range seats {
		s, err := getObj(raw)
		if err != nil || exact(s, "seat", "deck") != nil {
			return errors.New("seat entry shape")
		}
		if name, _ := getStr(s, "seat"); name != fmt.Sprintf("p%d", i) {
			return errors.New("seats must list p0 then p1")
		}
		if r.Decks[i], err = decodeDeck(s["deck"]); err != nil {
			return err
		}
	}
	if r.Rules, err = decodeRules(o["rules"]); err != nil {
		return err
	}
	if r.GameSecret, err = getStr(o, "game_secret"); err != nil || !hex64.MatchString(r.GameSecret) {
		return errors.New("game_secret must be 64 lowercase hex characters")
	}
	if r.MaxDecisions, err = getU64(o, "max_decisions"); err != nil {
		return err
	}
	if r.MaxSteps, err = getU64(o, "max_steps"); err != nil {
		return err
	}
	req.Reset = r
	return nil
}

func decodeStep(o obj, req *Request) error {
	if err := exact(o, "request_type", "protocol", "request_id", "game_id", "expected_step", "selection"); err != nil {
		return err
	}
	s := &StepReq{}
	var err error
	if s.GameID, err = getStr(o, "game_id"); err != nil || s.GameID == "" {
		return errGameID
	}
	if s.ExpectedStep, err = getU64(o, "expected_step"); err != nil {
		return err
	}
	sel, err := getObj(o["selection"])
	if err != nil || exact(sel, "candidate_id", "semantic_echo") != nil {
		return errors.New("selection must be {candidate_id, semantic_echo}")
	}
	if s.CandidateID, err = getU32(sel, "candidate_id"); err != nil {
		return err
	}
	if _, err := getObj(sel["semantic_echo"]); err != nil {
		return errors.New("semantic_echo is not an object")
	}
	s.Echo = sel["semantic_echo"]
	req.Step = s
	return nil
}

func decodeValidateDeck(o obj, req *Request) error {
	if err := exact(o, "request_type", "protocol", "request_id", "format", "deck"); err != nil {
		return err
	}
	v := &ValidateDeckReq{}
	var err error
	if v.Format, err = getStr(o, "format"); err != nil {
		return err
	}
	d, err := getObj(o["deck"])
	if err != nil {
		return err
	}
	switch {
	case exact(d, "catalog_id") == nil:
		v.Deck.CatalogID, err = getStr(d, "catalog_id")
	case exact(d, "decklist") == nil:
		v.Deck.IsDecklist = true
		v.Deck.Decklist, err = decodeDecklist(d["decklist"])
	default:
		err = errors.New("deck must be {catalog_id} or {decklist}")
	}
	if err != nil {
		return err
	}
	req.ValidateDeck = v
	return nil
}

func decodeProbe(o obj, req *Request) error {
	if err := exact(o, "request_type", "protocol", "request_id", "game_id", "samples"); err != nil {
		return err
	}
	p := &ProbeReq{}
	var err error
	if p.GameID, err = getStr(o, "game_id"); err != nil || p.GameID == "" {
		return errGameID
	}
	if p.Samples, err = getU32(o, "samples"); err != nil {
		return err
	}
	req.Probe = p
	return nil
}
