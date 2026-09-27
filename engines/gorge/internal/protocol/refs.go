// Package protocol holds the Spellbench v2 wire types this engine emits and reads.
package protocol

import "encoding/json"

const Name = "spellbench/v2"

type ObjectRef struct {
	ObjectID       string  `json:"object_id"`
	CardName       *string `json:"card_name"`
	OwnerSeat      string  `json:"owner_seat"`
	ControllerSeat string  `json:"controller_seat"`
	Zone           string  `json:"zone"`
}

// TargetRef is exactly one of {"player": seat} or {"object": ref}.
type TargetRef struct {
	Player *string
	Object *ObjectRef
}

func PlayerTarget(seat string) TargetRef { return TargetRef{Player: &seat} }
func ObjectTarget(r ObjectRef) TargetRef { return TargetRef{Object: &r} }

func (t TargetRef) MarshalJSON() ([]byte, error) {
	if t.Player != nil {
		return json.Marshal(map[string]string{"player": *t.Player})
	}
	return json.Marshal(map[string]*ObjectRef{"object": t.Object})
}

func (t *TargetRef) UnmarshalJSON(b []byte) error {
	var m struct {
		Player *string    `json:"player"`
		Object *ObjectRef `json:"object"`
	}
	if err := json.Unmarshal(b, &m); err != nil {
		return err
	}
	t.Player, t.Object = m.Player, m.Object
	return nil
}

// OrderItem is order_pick.item: {"object": R} or {"trigger": {...}}.
type OrderItem struct {
	Object  *ObjectRef
	Trigger *TriggerItem
}

type TriggerItem struct {
	Source       *ObjectRef  `json:"source"`
	SourceName   *string     `json:"source_name"`
	AbilityIndex *uint32     `json:"ability_index"`
	EventObjects []ObjectRef `json:"event_objects"`
	Instance     uint32      `json:"instance"`
	Label        *string     `json:"label"`
}

func ObjectItem(r ObjectRef) OrderItem { return OrderItem{Object: &r} }

func (o OrderItem) MarshalJSON() ([]byte, error) {
	if o.Object != nil {
		return json.Marshal(map[string]*ObjectRef{"object": o.Object})
	}
	return json.Marshal(map[string]*TriggerItem{"trigger": o.Trigger})
}
