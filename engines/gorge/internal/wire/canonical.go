package wire

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"sort"
	"strconv"
	"unicode/utf16"
)

// CanonicalBytes re-serializes strict JSON per RFC 8785 for integer-only data.
func CanonicalBytes(raw []byte) ([]byte, error) {
	if err := CheckStrictAny(raw); err != nil {
		return nil, err
	}
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.UseNumber()
	var v any
	if err := dec.Decode(&v); err != nil {
		return nil, err
	}
	var buf bytes.Buffer
	if err := writeCanon(&buf, v); err != nil {
		return nil, err
	}
	return buf.Bytes(), nil
}

// Canonical marshals v (HTML escaping off) and canonicalizes the result.
func Canonical(v any) ([]byte, error) {
	var b bytes.Buffer
	enc := json.NewEncoder(&b)
	enc.SetEscapeHTML(false)
	if err := enc.Encode(v); err != nil {
		return nil, err
	}
	return CanonicalBytes(bytes.TrimSuffix(b.Bytes(), []byte("\n")))
}

func utf16Less(a, b string) bool {
	x, y := utf16.Encode([]rune(a)), utf16.Encode([]rune(b))
	for i := 0; i < len(x) && i < len(y); i++ {
		if x[i] != y[i] {
			return x[i] < y[i]
		}
	}
	return len(x) < len(y)
}

func writeCanon(buf *bytes.Buffer, v any) error {
	switch t := v.(type) {
	case nil:
		buf.WriteString("null")
	case bool:
		buf.WriteString(strconv.FormatBool(t))
	case json.Number:
		n, err := strconv.ParseInt(string(t), 10, 64)
		if err != nil {
			return fmt.Errorf("non-integer number %s", t)
		}
		buf.WriteString(strconv.FormatInt(n, 10))
	case string:
		writeString(buf, t)
	case []any:
		buf.WriteByte('[')
		for i, e := range t {
			if i > 0 {
				buf.WriteByte(',')
			}
			if err := writeCanon(buf, e); err != nil {
				return err
			}
		}
		buf.WriteByte(']')
	case map[string]any:
		keys := make([]string, 0, len(t))
		for k := range t {
			keys = append(keys, k)
		}
		sort.Slice(keys, func(i, j int) bool { return utf16Less(keys[i], keys[j]) })
		buf.WriteByte('{')
		for i, k := range keys {
			if i > 0 {
				buf.WriteByte(',')
			}
			writeString(buf, k)
			buf.WriteByte(':')
			if err := writeCanon(buf, t[k]); err != nil {
				return err
			}
		}
		buf.WriteByte('}')
	default:
		return fmt.Errorf("unexpected JSON value %T", v)
	}
	return nil
}

func writeString(buf *bytes.Buffer, s string) {
	buf.WriteByte('"')
	for _, r := range s {
		switch r {
		case '"':
			buf.WriteString(`\"`)
		case '\\':
			buf.WriteString(`\\`)
		case '\b':
			buf.WriteString(`\b`)
		case '\f':
			buf.WriteString(`\f`)
		case '\n':
			buf.WriteString(`\n`)
		case '\r':
			buf.WriteString(`\r`)
		case '\t':
			buf.WriteString(`\t`)
		default:
			if r < 0x20 {
				fmt.Fprintf(buf, `\u%04x`, r)
			} else {
				buf.WriteRune(r)
			}
		}
	}
	buf.WriteByte('"')
}

// DeckRow is one decklist row.
type DeckRow struct {
	Name  string `json:"name"`
	Count int    `json:"count"`
}

func sha(b []byte) string {
	s := sha256.Sum256(b)
	return "sha256:" + hex.EncodeToString(s[:])
}

// DeckID is Section 4.3's deck_id: rows sorted by name in code point order
// (UTF-8 byte order equals code point order), canonical, SHA-256.
func DeckID(rows []DeckRow) string {
	s := append([]DeckRow(nil), rows...)
	sort.Slice(s, func(i, j int) bool { return s[i].Name < s[j].Name })
	var buf bytes.Buffer
	buf.WriteByte('[')
	for i, r := range s {
		if i > 0 {
			buf.WriteByte(',')
		}
		buf.WriteString(`{"count":` + strconv.Itoa(r.Count) + `,"name":`)
		writeString(&buf, r.Name)
		buf.WriteByte('}')
	}
	buf.WriteByte(']')
	return sha(buf.Bytes())
}

// DomainID is card_name_domain.domain_id: the names sorted, canonical, SHA-256.
func DomainID(names []string) string {
	s := append([]string(nil), names...)
	sort.Strings(s)
	var buf bytes.Buffer
	buf.WriteByte('[')
	for i, n := range s {
		if i > 0 {
			buf.WriteByte(',')
		}
		writeString(&buf, n)
	}
	buf.WriteByte(']')
	return sha(buf.Bytes())
}
