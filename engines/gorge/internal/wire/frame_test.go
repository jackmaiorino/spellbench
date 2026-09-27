package wire_test

import (
	"bytes"
	"errors"
	"io"
	"strings"
	"testing"

	"github.com/jackmaiorino/spellbench/engines/gorge/internal/wire"
)

func TestReaderAcceptsEightMiBAndResyncsAfterALongerLine(t *testing.T) {
	exact := `{"p":"` + strings.Repeat("x", wire.MaxLineBytes-8) + `"}`
	over := exact + " "
	in := exact + "\n" + over + "\r\n" + `{"ok":1}` + "\r\n"
	r := wire.NewReader(strings.NewReader(in))
	if line, err := r.ReadLine(); err != nil || len(line) != wire.MaxLineBytes {
		t.Fatalf("8 MiB line: len %d err %v", len(line), err)
	}
	if _, err := r.ReadLine(); !errors.Is(err, wire.ErrLineTooLong) {
		t.Fatalf("longer line: %v", err)
	}
	if line, err := r.ReadLine(); err != nil || string(line) != `{"ok":1}` {
		t.Fatalf("resync: %q %v", line, err)
	}
	if _, err := r.ReadLine(); err != io.EOF {
		t.Fatalf("end: %v", err)
	}
}

// Only the "\n" or "\r\n" terminator is exempt from the bound: a "\r" before
// it is content, so 8 MiB followed by "\r\r\n" is one byte too long.
func TestReaderExemptsOnlyTheTerminatorFromTheBound(t *testing.T) {
	exact := `{"p":"` + strings.Repeat("x", wire.MaxLineBytes-8) + `"}`
	r := wire.NewReader(strings.NewReader(exact + "\r\r\n" + "a\r\r\n"))
	if _, err := r.ReadLine(); !errors.Is(err, wire.ErrLineTooLong) {
		t.Fatalf("8 MiB plus a trailing CR: %v", err)
	}
	if line, err := r.ReadLine(); err != nil || string(line) != "a\r" {
		t.Fatalf("short line: %q %v", line, err)
	}
}

func TestWriteLineIsOneCompactLine(t *testing.T) {
	var b bytes.Buffer
	if err := wire.WriteLine(&b, map[string]any{"a": "<&>", "b": 1}); err != nil {
		t.Fatal(err)
	}
	if b.String() != "{\"a\":\"<&>\",\"b\":1}\n" {
		t.Fatalf("got %q", b.String())
	}
}
