package protocol

const (
	CodeMalformedJSON          = "malformed_json"
	CodeMalformedRequest       = "malformed_request"
	CodeProtocolMismatch       = "protocol_mismatch"
	CodeRequestIDReuseMismatch = "request_id_reuse_mismatch"
	CodeStepBeforeReset        = "step_before_reset"
	CodeGameAlreadyActive      = "game_already_active"
	CodeGameIDMismatch         = "game_id_mismatch"
	CodeExpectedStepMismatch   = "expected_step_mismatch"
	CodeCandidateIDOutOfRange  = "candidate_id_out_of_range"
	CodeSemanticEchoMismatch   = "semantic_echo_mismatch"
	CodeUnsupportedFormat      = "unsupported_format"
	CodeUnsupportedDeck        = "unsupported_deck"
	CodeDeckIDMismatch         = "deck_id_mismatch"
	CodeUnsupportedRule        = "unsupported_rule"
	CodeUnsupportedRequest     = "unsupported_request"
	CodeProbeRefused           = "probe_refused"
	CodeGameAlreadyTerminal    = "game_already_terminal"
)

type Error struct{ Code, Message string }

func (e *Error) Error() string { return e.Code + ": " + e.Message }

func Errf(code, msg string) *Error { return &Error{Code: code, Message: msg} }
