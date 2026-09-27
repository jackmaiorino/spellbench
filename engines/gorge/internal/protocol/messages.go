package protocol

import "encoding/json"

type Candidate struct {
	CandidateID uint32   `json:"candidate_id"`
	Semantic    Semantic `json:"semantic"`
	DisplayText *string  `json:"display_text"`
}

type Group struct {
	GroupID      uint64 `json:"group_id"`
	SubstepIndex uint32 `json:"substep_index"`
	SubstepCount uint32 `json:"substep_count"`
}

type Context struct {
	Kind    string     `json:"kind"`
	Source  *ObjectRef `json:"source"`
	Purpose *string    `json:"purpose"`
	Text    *string    `json:"text"`
	Rewind  bool       `json:"rewind"`
}

type SeatDecision struct {
	ActingSeat  string                     `json:"acting_seat"`
	SeatStep    uint64                     `json:"seat_step"`
	Group       Group                      `json:"group"`
	Context     Context                    `json:"context"`
	Observation Observation                `json:"observation"`
	Candidates  []Candidate                `json:"candidates"`
	Extensions  map[string]json.RawMessage `json:"extensions"`
}

// MarshalJSON writes extensions as an object, {} when there are none, never
// null (Section 9.3).
func (sd SeatDecision) MarshalJSON() ([]byte, error) {
	type plain SeatDecision
	p := plain(sd)
	if p.Extensions == nil {
		p.Extensions = map[string]json.RawMessage{}
	}
	return json.Marshal(p)
}

type Engine struct {
	Name             string  `json:"name"`
	Version          string  `json:"version"`
	SourceRevision   *string `json:"source_revision"`
	RulesSnapshotID  string  `json:"rules_snapshot_id"`
	CardPoolIdentity string  `json:"card_pool_identity"`
}

type Provenance struct {
	EngineName       string `json:"engine_name"`
	EngineVersion    string `json:"engine_version"`
	RulesSnapshotID  string `json:"rules_snapshot_id"`
	CardPoolIdentity string `json:"card_pool_identity"`
}

type CatalogDeck struct {
	CatalogID string    `json:"catalog_id"`
	Name      string    `json:"name"`
	Decklist  []DeckRow `json:"decklist"`
}

type DeckRow struct {
	Name  string `json:"name"`
	Count int    `json:"count"`
}

type Extension struct {
	Name      string `json:"name"`
	NativeIDs bool   `json:"native_ids"`
}

type HelloOK struct {
	ResponseType   string              `json:"response_type"`
	Protocol       string              `json:"protocol"`
	RequestID      string              `json:"request_id"`
	ProtocolMinor  uint64              `json:"protocol_minor"`
	Engine         Engine              `json:"engine"`
	Formats        []string            `json:"formats"`
	DeckSources    []string            `json:"deck_sources"`
	Catalog        []CatalogDeck       `json:"catalog"`
	RulesSupported map[string][]string `json:"rules_supported"`
	Observation    map[string]bool     `json:"observation"`
	DecisionKinds  []string            `json:"decision_kinds"`
	EngineDefaults map[string]*string  `json:"engine_defaults"`
	Rewind         bool                `json:"rewind"`
	Fairness       map[string]bool     `json:"fairness"`
	Extensions     []Extension         `json:"extensions"`
}

type DecisionResponse struct {
	ResponseType string       `json:"response_type"`
	Protocol     string       `json:"protocol"`
	RequestID    string       `json:"request_id"`
	GameID       string       `json:"game_id"`
	Step         uint64       `json:"step"`
	SeatDecision SeatDecision `json:"seat_decision"`
	Provenance   Provenance   `json:"provenance"`
}

type TerminalResponse struct {
	ResponseType   string     `json:"response_type"`
	Protocol       string     `json:"protocol"`
	RequestID      string     `json:"request_id"`
	GameID         string     `json:"game_id"`
	Outcome        string     `json:"outcome"`
	Classification string     `json:"classification"`
	Winner         *string    `json:"winner"`
	Reason         string     `json:"reason"`
	StepCount      uint64     `json:"step_count"`
	DecisionCount  uint64     `json:"decision_count"`
	Provenance     Provenance `json:"provenance"`
}

type ErrorBody struct {
	Code    string `json:"code"`
	Message string `json:"message"`
}

type ErrorResponse struct {
	ResponseType string    `json:"response_type"`
	Protocol     string    `json:"protocol"`
	RequestID    string    `json:"request_id"`
	Error        ErrorBody `json:"error"`
}

type DeckOK struct {
	ResponseType string `json:"response_type"`
	Protocol     string `json:"protocol"`
	RequestID    string `json:"request_id"`
}
