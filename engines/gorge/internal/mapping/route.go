package mapping

import (
	"sort"
	"strings"

	"github.com/adams-shaun/gorge/decision"
)

func optKinds(d *decision.Decision) (set map[string]bool, sorted string) {
	set = map[string]bool{}
	var ks []string
	for _, o := range d.Options {
		if !set[o.Kind] {
			set[o.Kind] = true
			ks = append(ks, o.Kind)
		}
	}
	sort.Strings(ks)
	return set, strings.Join(ks, ",")
}

func Route(d *decision.Decision) string {
	k, sorted := optKinds(d)
	switch d.Kind {
	case decision.KPriority:
		return "priority"
	case decision.KAttackers:
		return "attackers"
	case decision.KBlockers:
		return "blockers"
	case decision.KTarget:
		return "target"
	case decision.KTriggerOrder:
		return "trigger_order"
	case decision.KModes:
		for _, o := range d.Options {
			if o.Mode == decision.ModeUnlessPay || o.Mode == decision.ModeUnlessDecline {
				return "modes/unless"
			}
		}
		if k["discard"] {
			return "modes/discard"
		}
		return "modes/mode"
	case decision.KMulligan:
		if k["bottom"] {
			return "mulligan/bottom"
		}
		return "mulligan/keep"
	case decision.KTriggerOptional:
		if d.ResumeKind == "madness" {
			return "trigger_optional/madness"
		}
		return "trigger_optional/optional"
	case decision.KReplacement:
		if k["madness_exile"] || k["madness_graveyard"] {
			return "replacement/madness"
		}
		if k["replacement"] {
			return "replacement/order"
		}
	case decision.KArrange:
		if len(d.Options) > 0 {
			return "arrange/" + d.Options[0].Kind
		}
	case decision.KChoose:
		switch {
		case k["activate"] || (k["done"] && len(k) == 1):
			return "choose/mana_window"
		case k["trigger_cost_pay"] || k["trigger_cost_decline"]:
			return "choose/trigger_cost"
		case k["sacrifice"] || k["tapcost"] || k["returncost"] || k["exile_cost"] || k["exile"] || (k["discard"] && d.Source != 0):
			return "choose/cost"
		case k["discard"]:
			return "choose/cleanup_discard"
		case k["yes"] || k["no"]:
			return "choose/yesno"
		case k["graveyard"] && k["top"]:
			return "choose/explore"
		}
		for _, o := range d.Options {
			if strings.HasPrefix(o.Kind, "pay_") {
				return "choose/pay_pip"
			}
		}
		if len(k) == 1 {
			for _, c := range []string{"search", "hand_move", "dig", "untap", "keep", "x", "number", "color", "type", "name", "division", "mana"} {
				if k[c] {
					return "choose/" + c
				}
			}
		}
	}
	return "unmapped:" + string(d.Kind) + "/" + sorted
}
