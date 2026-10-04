package wire

import (
	"bufio"
	"bytes"
	"encoding/json"
	"errors"
	"io"
)

// MaxLineBytes is Section 2's line bound, excluding the terminator.
const MaxLineBytes = 8 << 20

var ErrLineTooLong = errors.New("line exceeds 8 MiB")

type Reader struct{ r *bufio.Reader }

func NewReader(r io.Reader) *Reader { return &Reader{r: bufio.NewReaderSize(r, 64<<10)} }

// ReadLine returns the next line without "\n" or "\r\n". A longer line is
// drained through its newline and reported as ErrLineTooLong, so framing
// resynchronizes on the next line.
func (r *Reader) ReadLine() ([]byte, error) {
	var line []byte
	tooLong := false
	for {
		chunk, err := r.r.ReadSlice('\n')
		if !tooLong {
			line = append(line, chunk...)
			if len(trimTerminator(line)) > MaxLineBytes {
				tooLong, line = true, nil
			}
		}
		switch {
		case errors.Is(err, bufio.ErrBufferFull):
			continue
		case errors.Is(err, io.EOF):
			if tooLong {
				return nil, ErrLineTooLong
			}
			if len(line) == 0 {
				return nil, io.EOF
			}
			return nil, io.ErrUnexpectedEOF
		case err != nil:
			return nil, err
		}
		if tooLong {
			return nil, ErrLineTooLong
		}
		return trimTerminator(line), nil
	}
}

// trimTerminator strips one "\n", then one "\r". Every other byte counts
// toward the bound, so a run of "\r" cannot slip past it.
func trimTerminator(line []byte) []byte {
	return bytes.TrimSuffix(bytes.TrimSuffix(line, []byte("\n")), []byte("\r"))
}

// WriteLine writes v as one compact JSON line (HTML escaping off).
func WriteLine(w io.Writer, v any) error {
	enc := json.NewEncoder(w)
	enc.SetEscapeHTML(false)
	return enc.Encode(v)
}
