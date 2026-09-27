// Package wire holds the transport rules of Spellbench v2 Section 2 and the
// canonical JSON of Section 4.3.
package wire

import (
	"fmt"
	"strconv"
	"strings"
	"unicode/utf16"
	"unicode/utf8"
)

const (
	MaxDepth          = 64
	MaxInt            = int64(1)<<53 - 1
	CodeMalformedJSON = "malformed_json"
	CodeNotObject     = "malformed_request"
)

// StrictError carries the v2 error code a receiver answers with.
type StrictError struct{ Code, Msg string }

func (e *StrictError) Error() string { return e.Code + ": " + e.Msg }

func bad(format string, a ...any) error {
	return &StrictError{Code: CodeMalformedJSON, Msg: fmt.Sprintf(format, a...)}
}

// CheckStrict validates one request line: strict JSON whose top level is an object.
func CheckStrict(b []byte) error {
	if err := CheckStrictAny(b); err != nil {
		return err
	}
	p := &parser{b: b}
	p.ws()
	if p.b[p.i] != '{' {
		return &StrictError{Code: CodeNotObject, Msg: "top-level value is not an object"}
	}
	return nil
}

// CheckStrictAny validates strict JSON with any top-level value.
func CheckStrictAny(b []byte) error {
	if !utf8.Valid(b) {
		return bad("invalid UTF-8")
	}
	p := &parser{b: b}
	if err := p.value(0); err != nil {
		return err
	}
	p.ws()
	if p.i != len(p.b) {
		return bad("trailing data at byte %d", p.i)
	}
	return nil
}

type parser struct {
	b []byte
	i int
}

func (p *parser) ws() {
	for p.i < len(p.b) && strings.IndexByte(" \t\n\r", p.b[p.i]) >= 0 {
		p.i++
	}
}

func (p *parser) lit(s string) bool {
	if strings.HasPrefix(string(p.b[p.i:min(len(p.b), p.i+len(s))]), s) {
		p.i += len(s)
		return true
	}
	return false
}

func (p *parser) value(depth int) error {
	p.ws()
	if p.i >= len(p.b) {
		return bad("unexpected end of input")
	}
	switch c := p.b[p.i]; {
	case c == '{':
		return p.object(depth + 1)
	case c == '[':
		return p.array(depth + 1)
	case c == '"':
		_, err := p.str()
		return err
	case c == '-' || (c >= '0' && c <= '9'):
		return p.number()
	case p.lit("true"), p.lit("false"), p.lit("null"):
		return nil
	default:
		return bad("unexpected byte %q at %d", c, p.i)
	}
}

func (p *parser) object(depth int) error {
	if depth > MaxDepth {
		return bad("nesting deeper than %d levels", MaxDepth)
	}
	p.i++
	seen := map[string]bool{}
	p.ws()
	if p.i < len(p.b) && p.b[p.i] == '}' {
		p.i++
		return nil
	}
	for {
		p.ws()
		if p.i >= len(p.b) || p.b[p.i] != '"' {
			return bad("expected a key at %d", p.i)
		}
		k, err := p.str()
		if err != nil {
			return err
		}
		if seen[k] {
			return bad("duplicate key %q", k)
		}
		seen[k] = true
		p.ws()
		if p.i >= len(p.b) || p.b[p.i] != ':' {
			return bad("expected ':' at %d", p.i)
		}
		p.i++
		if err := p.value(depth); err != nil {
			return err
		}
		p.ws()
		if p.i >= len(p.b) {
			return bad("unterminated object")
		}
		switch p.b[p.i] {
		case ',':
			p.i++
		case '}':
			p.i++
			return nil
		default:
			return bad("expected ',' or '}' at %d", p.i)
		}
	}
}

func (p *parser) array(depth int) error {
	if depth > MaxDepth {
		return bad("nesting deeper than %d levels", MaxDepth)
	}
	p.i++
	p.ws()
	if p.i < len(p.b) && p.b[p.i] == ']' {
		p.i++
		return nil
	}
	for {
		if err := p.value(depth); err != nil {
			return err
		}
		p.ws()
		if p.i >= len(p.b) {
			return bad("unterminated array")
		}
		switch p.b[p.i] {
		case ',':
			p.i++
		case ']':
			p.i++
			return nil
		default:
			return bad("expected ',' or ']' at %d", p.i)
		}
	}
}

func (p *parser) hex4() (rune, error) {
	if p.i+4 > len(p.b) {
		return 0, bad("short \\u escape")
	}
	v, err := strconv.ParseUint(string(p.b[p.i:p.i+4]), 16, 32)
	if err != nil {
		return 0, bad("bad \\u escape")
	}
	p.i += 4
	return rune(v), nil
}

// str parses a string and returns its decoded value (for duplicate-key checks).
func (p *parser) str() (string, error) {
	p.i++
	var sb strings.Builder
	for p.i < len(p.b) {
		c := p.b[p.i]
		switch {
		case c == '"':
			p.i++
			return sb.String(), nil
		case c < 0x20:
			return "", bad("control character in string")
		case c == '\\':
			if p.i+1 >= len(p.b) {
				return "", bad("unterminated escape")
			}
			e := p.b[p.i+1]
			p.i += 2
			switch e {
			case '"', '\\', '/':
				sb.WriteByte(e)
			case 'b':
				sb.WriteByte('\b')
			case 'f':
				sb.WriteByte('\f')
			case 'n':
				sb.WriteByte('\n')
			case 'r':
				sb.WriteByte('\r')
			case 't':
				sb.WriteByte('\t')
			case 'u':
				r, err := p.hex4()
				if err != nil {
					return "", err
				}
				if utf16.IsSurrogate(r) {
					if r >= 0xDC00 || p.i+2 > len(p.b) || p.b[p.i] != '\\' || p.b[p.i+1] != 'u' {
						return "", bad("unpaired surrogate escape")
					}
					p.i += 2
					r2, err := p.hex4()
					if err != nil {
						return "", err
					}
					if r2 < 0xDC00 || r2 > 0xDFFF {
						return "", bad("unpaired surrogate escape")
					}
					r = utf16.DecodeRune(r, r2)
				}
				sb.WriteRune(r)
			default:
				return "", bad("bad escape \\%c", e)
			}
		default:
			sb.WriteByte(c)
			p.i++
		}
	}
	return "", bad("unterminated string")
}

func (p *parser) number() error {
	start := p.i
	if p.b[p.i] == '-' {
		p.i++
	}
	if p.i >= len(p.b) || p.b[p.i] < '0' || p.b[p.i] > '9' {
		return bad("bad number at %d", start)
	}
	if p.b[p.i] == '0' && p.i+1 < len(p.b) && p.b[p.i+1] >= '0' && p.b[p.i+1] <= '9' {
		return bad("leading zero at %d", start)
	}
	for p.i < len(p.b) && p.b[p.i] >= '0' && p.b[p.i] <= '9' {
		p.i++
	}
	if p.i < len(p.b) && strings.IndexByte(".eE", p.b[p.i]) >= 0 {
		return bad("number with a fraction or an exponent at %d", start)
	}
	n, err := strconv.ParseInt(string(p.b[start:p.i]), 10, 64)
	if err != nil || n > MaxInt || n < -MaxInt {
		return bad("integer outside |x| <= 2^53-1 at %d", start)
	}
	return nil
}
