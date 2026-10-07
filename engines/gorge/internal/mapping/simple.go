package mapping

import (
	"fmt"
	"strings"

	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/state"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/observe"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
)

var colors = map[string]string{"white": "white", "blue": "blue", "black": "black", "red": "red", "green": "green"}

var boolPurpose = map[string]string{"search_confirm": "may_ability", "copy_optional": "may_ability",
	"repeat_optional": "may_ability", "search_mayshuffle": "other"}

func init() {
	Register("mulligan/keep", func(env *Env, d *decision.Decision) (Transaction, error) {
		hand := uint32(len(env.G.E.G.Zone(state.ZHand, d.Player)))
		taken := env.Obs.Mulls[d.Player]
		tx, err := SingleChoice(env, d, choice(nil, ""), func(o decision.Option) (protocol.Semantic, bool, error) {
			return protocol.Mulligan(hand, taken, o.Kind == "keep"), true, nil
		})
		if err != nil {
			return nil, err
		}
		st := tx.(*singleTx)
		st.after = func(opt int) {
			if d.Options[opt].Kind == "mulligan" {
				env.Obs.Mulls[d.Player]++
			}
		}
		return st, nil
	})
	Register("trigger_optional/optional", func(env *Env, d *decision.Decision) (Transaction, error) {
		src, err := ResolveSource(env, d)
		if err != nil {
			return nil, err
		}
		return SingleChoice(env, d, choice(src, "optional_trigger"), func(o decision.Option) (protocol.Semantic, bool, error) {
			return protocol.ChooseBoolean(src, "optional_trigger", o.Kind == "yes"), true, nil
		})
	})
	Register("trigger_optional/madness", func(env *Env, d *decision.Decision) (Transaction, error) {
		// optional_cast.card is the exiled card itself. ResolveSource would
		// answer the madness trigger's stack entry, whose source it is.
		r, err := env.Obs.Ref(d.Player, d.Source)
		if err != nil {
			return nil, err
		}
		if r == nil {
			return nil, ErrUnresolvableSource
		}
		card := *r
		return SingleChoice(env, d, choice(&card, ""), func(o decision.Option) (protocol.Semantic, bool, error) {
			return protocol.OptionalCast(card, "madness", o.Kind == "yes"), true, nil
		})
	})
	Register("choose/yesno", func(env *Env, d *decision.Decision) (Transaction, error) {
		src, err := ResolveSource(env, d)
		if err != nil {
			return nil, err
		}
		p := boolPurpose[d.ResumeKind]
		if p == "" {
			p = "other"
		}
		return SingleChoice(env, d, choice(src, p), func(o decision.Option) (protocol.Semantic, bool, error) {
			return protocol.ChooseBoolean(src, p, o.Kind == "yes"), true, nil
		})
	})
	Register("replacement/madness", func(env *Env, d *decision.Decision) (Transaction, error) {
		src, err := ResolveSource(env, d)
		if err != nil {
			return nil, err
		}
		return SingleChoice(env, d, choice(src, "optional_replacement"), func(o decision.Option) (protocol.Semantic, bool, error) {
			return protocol.ChooseBoolean(src, "optional_replacement", o.Kind == "madness_exile"), true, nil
		})
	})
	Register("replacement/order", func(env *Env, d *decision.Decision) (Transaction, error) {
		affected := protocol.PlayerTarget(observe.Seat(d.Player))
		if d.Source != 0 {
			if r, err := env.Obs.Ref(d.Player, d.Source); err != nil {
				return nil, err
			} else if r != nil {
				affected = protocol.ObjectTarget(*r)
			}
		}
		event := "other"
		switch {
		case strings.Contains(d.Prompt, "modify damage"):
			event = "damage"
		case strings.Contains(d.Prompt, "counter"):
			event = "counters"
		case strings.Contains(d.Prompt, "enters with"):
			event = "enter_battlefield"
		}
		n := uint32(len(d.Options))
		return SingleChoice(env, d, choice(nil, ""), func(o decision.Option) (protocol.Semantic, bool, error) {
			rs, err := env.Obs.Ref(d.Player, o.Obj)
			return protocol.ChooseReplacement(affected, event, rs, uint32(o.Index), n), err == nil, err
		})
	})
	Register("choose/color", func(env *Env, d *decision.Decision) (Transaction, error) {
		src, err := ResolveSource(env, d)
		if err != nil {
			return nil, err
		}
		return SingleChoice(env, d, choice(src, "effect"), func(o decision.Option) (protocol.Semantic, bool, error) {
			c, ok := colors[strings.ToLower(strings.TrimSpace(o.Label))]
			if !ok {
				return protocol.Semantic{}, false, fmt.Errorf("%w:color/%q", ErrUnmapped, o.Label)
			}
			return protocol.ChooseColor(src, "effect", c), true, nil
		})
	})
	number := func(purp string) Builder {
		return func(env *Env, d *decision.Decision) (Transaction, error) {
			src, err := ResolveSource(env, d)
			if err != nil {
				return nil, err
			}
			lo, hi := int32(d.Options[0].Amount), int32(d.Options[0].Amount)
			for _, o := range d.Options {
				lo, hi = min(lo, int32(o.Amount)), max(hi, int32(o.Amount))
			}
			return SingleChoice(env, d, choice(src, purp), func(o decision.Option) (protocol.Semantic, bool, error) {
				return protocol.ChooseNumber(src, purp, int32(o.Amount), lo, hi), true, nil
			})
		}
	}
	Register("choose/x", number("x_value"))
	Register("choose/number", number("amount"))
	Register("choose/type", func(env *Env, d *decision.Decision) (Transaction, error) {
		src, err := ResolveSource(env, d)
		if err != nil {
			return nil, err
		}
		return SingleChoice(env, d, choice(src, "card_type"), func(o decision.Option) (protocol.Semantic, bool, error) {
			return protocol.ChooseName(src, "card_type", observe.Normalize(o.Label)), true, nil
		})
	})
	Register("choose/name", func(env *Env, d *decision.Decision) (Transaction, error) {
		src, err := ResolveSource(env, d)
		if err != nil {
			return nil, err
		}
		return SingleChoice(env, d, choice(src, "card_name"), func(o decision.Option) (protocol.Semantic, bool, error) {
			return protocol.ChooseName(src, "card_name", o.Label), env.Domain[o.Label], nil
		})
	})
}
