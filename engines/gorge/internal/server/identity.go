package server

import (
	"github.com/adams-shaun/gorge/cards"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/catalog"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/gorgepin"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/wire"
)

const AdapterVersion = "0.1.0"

// DecisionKinds are the 24 kinds the engine emits. distribute is not one:
// combat damage follows the declared engine_order default (Section 7.6).
var DecisionKinds = []string{"pass", "play_land", "cast_spell", "activate_mana_ability", "activate_ability",
	"special_action", "choose_target", "finish_target_selection", "choose_cost_target", "choose_spell_mode",
	"choose_color", "choose_number", "choose_boolean", "choose_name", "select_object", "finish_selection",
	"optional_cost", "optional_cast", "mulligan", "order_pick", "arrange_card", "choose_replacement",
	"declare_attack", "declare_block"}

func engineIdentity(sourceRevision *string) protocol.Engine {
	var ids []string
	for _, d := range catalog.Decks() {
		ids = append(ids, d.DeckID())
	}
	catalogID := wire.DomainID(ids) // the five catalog deck ids, distinct by construction
	return protocol.Engine{Name: "gorge", Version: "gorge-" + gorgepin.GorgeCommit[:12] + "/spellbench-adapter-" + AdapterVersion,
		SourceRevision:   sourceRevision,
		RulesSnapshotID:  "gorge/" + gorgepin.GorgeCommit[:12] + "/ir-" + cards.CompilerFingerprint,
		CardPoolIdentity: "forge-" + gorgepin.ForgeRef[:12] + "/corpus-" + gorgepin.CorpusDigest[:16] + "/catalog-" + catalogID[7:23]}
}

func provenance(e protocol.Engine) protocol.Provenance {
	return protocol.Provenance{EngineName: e.Name, EngineVersion: e.Version, RulesSnapshotID: e.RulesSnapshotID, CardPoolIdentity: e.CardPoolIdentity}
}

// engineOrder is the declared combat damage default (Section 7.6): gorge
// assigns combat damage in engine order (Task 16).
var engineOrder = "engine_order"

func helloOK(id string, e protocol.Engine, flags map[string]bool) protocol.HelloOK {
	var cat []protocol.CatalogDeck
	for _, d := range catalog.Decks() {
		cd := protocol.CatalogDeck{CatalogID: d.CatalogID, Name: d.Name}
		for _, r := range d.Rows {
			cd.Decklist = append(cd.Decklist, protocol.DeckRow{Name: r.Name, Count: uint32(r.Count)})
		}
		cat = append(cat, cd)
	}
	return protocol.HelloOK{ResponseType: "hello_ok", Protocol: protocol.Name, RequestID: id, ProtocolMinor: 0, Engine: e,
		Formats: []string{"pauper-bo1"}, DeckSources: []string{"catalog"}, Catalog: cat,
		RulesSupported: map[string][]string{"mulligan": {"london", "none"}, "starting_player": {"host_assigned"}},
		Observation:    flags, DecisionKinds: DecisionKinds,
		EngineDefaults: map[string]*string{"trigger_order": nil, "replacement_order": nil, "combat_damage_assignment": &engineOrder, "mana_payment": nil},
		Rewind:         false, Fairness: map[string]bool{"noninterference_probe": false},
		Extensions: []protocol.Extension{{Name: "x_gorge_view_v1", NativeIDs: false}}}
}
