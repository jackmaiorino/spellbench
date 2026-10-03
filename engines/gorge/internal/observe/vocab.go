package observe

import (
	"fmt"
	"regexp"
	"strings"

	"github.com/adams-shaun/gorge/cards"
	"github.com/adams-shaun/gorge/state"
)

var Flags = map[string]bool{"poison": false, "player_counters": false, "designations": false, "player_progress": false,
	"day_night": false, "passed_seats": false, "pending_triggers": true, "keywords": true, "full_name": false,
	"exiled_by": false, "stack_text": false, "permanent_details": false, "known_cards": false}

func Seat(p state.PlayerID) string { return fmt.Sprintf("p%d", p) }

var steps = [...]string{"untap", "upkeep", "draw", "precombat_main", "beginning_of_combat", "declare_attackers",
	"declare_blockers", "combat_damage", "end_of_combat", "postcombat_main", "end_step", "cleanup"}

func PhaseStep(g *state.Game) string {
	if g.Turn == 0 {
		return "pregame"
	}
	return steps[g.Step]
}

// Normalize is Section 6.10: lowercase, apostrophes removed, spaces and hyphens to "_".
func Normalize(s string) string {
	s = strings.ToLower(strings.TrimSpace(s))
	s = strings.NewReplacer("'", "", "’", "", " ", "_", "-", "_").Replace(s)
	return s
}

var ptCounter = regexp.MustCompile(`^[PM]\d+[PM]\d+$`)

func Counter(kind string) string {
	if u := strings.ToUpper(kind); ptCounter.MatchString(u) {
		return strings.ToLower(u)
	}
	return Normalize(kind)
}

func Colors(letters string) []string {
	out := []string{}
	for _, c := range []struct {
		l    byte
		name string
	}{{'W', "white"}, {'U', "blue"}, {'B', "black"}, {'R', "red"}, {'G', "green"}} {
		if strings.IndexByte(letters, c.l) >= 0 {
			out = append(out, c.name)
		}
	}
	return out
}

// cr702 lists CR 702 keyword names (normalized, no parameters).
var cr702 = map[string]bool{}

func init() {
	for _, k := range strings.Fields(`deathtouch defender double_strike enchant equip first_strike flash flying haste
		hexproof indestructible intimidate landwalk lifelink protection reach shroud trample vigilance ward banding
		rampage cumulative_upkeep flanking phasing buyback shadow cycling echo horsemanship fading kicker flashback
		madness fear morph amplify provoke storm affinity entwine modular sunburst bushido soulshift splice offering
		ninjutsu epic convoke dredge transmute bloodthirst haunt replicate forecast graft recover ripple split_second
		suspend vanishing absorb aura_swap delve fortify frenzy gravestorm poisonous transfigure champion changeling
		evoke hideaway prowl reinforce conspire persist wither retrace devour exalted unearth cascade annihilator
		level_up rebound umbra_armor infect battle_cry living_weapon undying miracle soulbond overload scavenge unleash
		cipher evolve extort fuse bestow tribute dethrone hidden_agenda outlast prowess dash exploit menace renown
		awaken devoid ingest myriad surge skulk emerge escalate melee crew fabricate partner undaunted improvise
		aftermath embalm eternalize afflict ascend assist jump_start mentor afterlife riot spectacle escape companion
		mutate encore boast foretell demonstrate daybound nightbound disturb decayed cleave training compleated
		reconfigure blitz casualty enlist read_ahead ravenous squad prototype living_metal for_mirrodin toxic backup
		bargain craft disguise plot saddle spree gift offspring impending job_select harmonize mobilize station warp`) {
		cr702[k] = true
	}
}

// Keywords maps gorge's derived keyword lines to CR 702 names, deduplicated in order.
func Keywords(lines []string) []string {
	out := []string{}
	seen := map[string]bool{}
	for _, l := range lines {
		k := Normalize(cards.KeywordHead(l))
		switch {
		case strings.HasSuffix(k, "walk") && k != "":
			k = "landwalk"
		case strings.HasSuffix(k, "cycling"):
			k = "cycling"
		case strings.HasPrefix(k, "protection"):
			k = "protection"
		}
		if cr702[k] && !seen[k] {
			seen[k] = true
			out = append(out, k)
		}
	}
	return out
}
