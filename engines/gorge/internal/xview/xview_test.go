package xview_test

import (
	"bytes"
	"encoding/json"
	"maps"
	"regexp"
	"slices"
	"strconv"
	"testing"

	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/rules"
	"github.com/adams-shaun/gorge/state"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/identity"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/mapping"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/observe"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/testcorpus"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/testgame"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/wire"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/xview"
)

// payloadAt plays bot games (seeds 1 to 20) until pred holds, then builds
// the pose's payload.
func payloadAt(t *testing.T, deck string, pred func(*decision.Decision, *rules.Engine) bool) (xview.Payload, *mapping.Pose) {
	pl, p, _ := payloadAndGame(t, deck, pred)
	return pl, p
}

func payloadAndGame(t *testing.T, deck string, pred func(*decision.Decision, *rules.Engine) bool) (xview.Payload, *mapping.Pose, *rules.Engine) {
	reg := testcorpus.Registry(t)
	for seed := byte(1); seed <= 20; seed++ {
		g := testgame.New(t, reg, deck, deck, seed, "none")
		tr := identity.New(g.E, g.Secret)
		if !testgame.RunUntil(t, g, testgame.Bots(uint64(seed)), func(e *rules.Engine) bool {
			if err := tr.Sync(e); err != nil {
				t.Fatal(err)
			}
			d := e.Pending()
			return d != nil && pred(d, e)
		}, 30000) {
			continue
		}
		env := &mapping.Env{G: g, IDs: tr, Obs: &observe.Projector{E: g.E, IDs: tr}, Slots: map[string]uint32{}}
		tx, err := mapping.Begin(env, g.E.Pending())
		if err != nil {
			t.Fatal(err)
		}
		p, err := tx.Pose()
		if err != nil {
			t.Fatal(err)
		}
		ext, err := xview.New().Extend(env, p, 7)
		if err != nil {
			t.Fatal(err)
		}
		raw := ext["x_gorge_view_v1"]
		if err := wire.CheckStrictAny(raw); err != nil {
			t.Fatalf("payload is not strict JSON: %v", err)
		}
		var pl xview.Payload
		if err := json.Unmarshal(raw, &pl); err != nil {
			t.Fatal(err)
		}
		return pl, p, g.E
	}
	t.Fatalf("no %s game reached the decision", deck)
	return xview.Payload{}, nil, nil
}

func TestPayloadHasNoGlobalCountersOrDigests(t *testing.T) {
	pl, p := payloadAt(t, "Burn", func(d *decision.Decision, e *rules.Engine) bool { return d.Kind == decision.KPriority })
	if pl.Decision.Seq != 7 || pl.NativeIndex != 7 || len(pl.Decision.PaymentActions) != 0 {
		t.Fatalf("seq %d native %d payments %d", pl.Decision.Seq, pl.NativeIndex, len(pl.Decision.PaymentActions))
	}
	if len(pl.Ops) != len(p.Candidates) {
		t.Fatalf("%d ops for %d candidates", len(pl.Ops), len(p.Candidates))
	}
}

func TestSearchOptionsAreSortedAndIDsAreSmall(t *testing.T) {
	pl, _ := payloadAt(t, "Wildfire", func(d *decision.Decision, e *rules.Engine) bool {
		return d.Kind == decision.KChoose && len(d.Options) > 1 && d.Options[0].Kind == "search"
	})
	for i := 1; i < len(pl.Decision.Options); i++ {
		if pl.Decision.Options[i-1].Label > pl.Decision.Options[i].Label {
			t.Fatalf("search options not in name order: %q before %q", pl.Decision.Options[i-1].Label, pl.Decision.Options[i].Label)
		}
		if pl.Decision.Options[i].Index != i {
			t.Fatalf("option %d has index %d", i, pl.Decision.Options[i].Index)
		}
	}
	for _, pv := range pl.View.Players {
		for _, cv := range pv.Battlefield {
			if cv.ID == 0 || cv.ID > 500 {
				t.Fatalf("rekeyed id %d is not a small per-seat integer", cv.ID)
			}
		}
	}
}

// Lembas's gain-life ability stays on the stack after its dies trigger
// shuffles Lembas into the library: the ability's source is hidden, so the
// payload names it 0 instead of failing the game (G2-2).
func TestHiddenStackSourceIsZero(t *testing.T) {
	var ability state.ObjID
	pl, _, e := payloadAndGame(t, "Wildfire", func(d *decision.Decision, e *rules.Engine) bool {
		for _, id := range e.G.Stack {
			if o := e.G.Obj(id); o.Ability != nil && e.G.Obj(o.Source) != nil && e.G.Obj(o.Source).Zone == state.ZLibrary {
				ability = id
				return true
			}
		}
		return false
	})
	i := slices.Index(e.G.Stack, ability)
	if i < 0 || i >= len(pl.View.Stack) || pl.View.Stack[i].Source != 0 {
		t.Fatalf("stack %+v, want entry %d with source 0", pl.View.Stack, i)
	}
}

var kindAndID = regexp.MustCompile(`[a-z_]+:[0-9]+`)

// Block options carry gorge groups named after native ids ("blocker:65"):
// the payload relabels them g0, g1, ... and no string carries a native id
// (G2-3).
func TestGroupsCarryNoNativeIDs(t *testing.T) {
	pl, p, _ := payloadAndGame(t, "Rally", func(d *decision.Decision, e *rules.Engine) bool {
		if d.Kind != decision.KBlockers {
			return false
		}
		for _, o := range d.Options {
			if o.Group != "" {
				return true
			}
		}
		return false
	})
	groups := regexp.MustCompile(`^g[0-9]+$`)
	native, got := p.Native.Options, pl.Decision.Options // blockers are visible: options keep their order
	for i := range native {
		if (native[i].Group == "") != (got[i].Group == "") || (got[i].Group != "" && !groups.MatchString(got[i].Group)) {
			t.Fatalf("option %d group %q became %q", i, native[i].Group, got[i].Group)
		}
		for j := range native {
			if (native[i].Group == native[j].Group) != (got[i].Group == got[j].Group) {
				t.Fatalf("options %d and %d changed group equality", i, j)
			}
		}
	}
	for k := range pl.Decision.GroupLimits {
		if !groups.MatchString(k) {
			t.Fatalf("group limit key %q", k)
		}
	}
	raw, _ := json.Marshal(pl)
	var walk func(any)
	walk = func(v any) {
		switch x := v.(type) {
		case string:
			if kindAndID.MatchString(x) {
				t.Errorf("payload string %q names a native id", x)
			}
		case []any:
			for _, e := range x {
				walk(e)
			}
		case map[string]any:
			for k, e := range x {
				walk(k)
				walk(e)
			}
		}
	}
	var generic any
	json.Unmarshal(raw, &generic)
	walk(generic)
	for _, pv := range pl.View.Players {
		for _, cv := range pv.Battlefield {
			if cv.Token != "#"+strconv.FormatUint(uint64(cv.ID), 10) {
				t.Errorf("card %d token %q", cv.ID, cv.Token)
			}
		}
	}
}

// Fix round 1: the payment drop is pinned on poses that DO carry payment
// data (the review found it asserted only on a payment-free pose).

func TestPaymentActionsAreDroppedFromALivePriorityPose(t *testing.T) {
	pl, p := payloadAt(t, "Burn", func(d *decision.Decision, e *rules.Engine) bool {
		return d.Kind == decision.KPriority && len(d.PaymentActions) > 0
	})
	if len(p.Native.PaymentActions) == 0 {
		t.Fatal("the pose carried no payment actions: the test proves nothing")
	}
	if len(pl.Decision.PaymentActions) != 0 || pl.Decision.PaymentFallback != nil {
		t.Fatalf("payment data survived: %d actions, fallback %+v", len(pl.Decision.PaymentActions), pl.Decision.PaymentFallback)
	}
}

// constructedEnv is a fresh game plus tracker for hand-built poses.
func constructedEnv(t *testing.T) *mapping.Env {
	t.Helper()
	g := testgame.New(t, testcorpus.Registry(t), "Wildfire", "Wildfire", 1, "none")
	tr := identity.New(g.E, g.Secret)
	return &mapping.Env{G: g, IDs: tr, Obs: &observe.Projector{E: g.E, IDs: tr}, Slots: map[string]uint32{}}
}

// The choke point nils the clone's payment fields; the pose keeps its own.
func TestPaymentFieldsAreDroppedFromConstructedPoses(t *testing.T) {
	env := constructedEnv(t)
	pay := []decision.PaymentAction{{ID: "pay:0", Label: "pay"}}
	native := &decision.Decision{Kind: decision.KPriority, Player: 0, Seq: 9,
		PaymentActions: pay, PaymentFallback: &decision.PaymentFallback{PlanID: "plan:0", Reason: "fell back"}}
	follow := &decision.Decision{Kind: decision.KChoose, Player: 0, Seq: 10,
		Options:        []decision.Option{{Index: 0, Kind: "pay"}, {Index: 1, Kind: "done"}},
		PaymentActions: pay, PaymentFallback: &decision.PaymentFallback{PlanID: "plan:1", Reason: "fell back"}}
	p := &mapping.Pose{Seat: 0, Native: native, Followups: map[string]*decision.Decision{"0": follow}}
	ext, err := xview.New().Extend(env, p, 4)
	if err != nil {
		t.Fatal(err)
	}
	var pl xview.Payload
	if err := json.Unmarshal(ext["x_gorge_view_v1"], &pl); err != nil {
		t.Fatal(err)
	}
	if len(pl.Decision.PaymentActions) != 0 || pl.Decision.PaymentFallback != nil {
		t.Fatalf("native payment data survived: %d actions, fallback %+v", len(pl.Decision.PaymentActions), pl.Decision.PaymentFallback)
	}
	fu, ok := pl.Followups["0"]
	if !ok {
		t.Fatalf("follow-up keys %v", maps.Keys(pl.Followups))
	}
	if len(fu.PaymentActions) != 0 || fu.PaymentFallback != nil {
		t.Fatalf("follow-up payment data survived: %d actions, fallback %+v", len(fu.PaymentActions), fu.PaymentFallback)
	}
	if len(native.PaymentActions) == 0 || native.PaymentFallback == nil || len(follow.PaymentActions) == 0 || follow.PaymentFallback == nil {
		t.Fatal("Extend rewrote the pose's own payment fields")
	}
}

// hiddenPair returns two of seat 0's library cards whose name order inverts
// their library positions, so sortHidden's permutation is not the identity.
func hiddenPair(t *testing.T, env *mapping.Env, taken map[state.ObjID]bool) (a, b state.ObjID) {
	t.Helper()
	lib := env.G.E.G.Zone(state.ZLibrary, 0)
	for i := 0; i < len(lib); i++ {
		for j := i + 1; j < len(lib); j++ {
			if taken[lib[i]] || taken[lib[j]] {
				continue
			}
			if env.G.E.G.Obj(lib[i]).Face().Name > env.G.E.G.Obj(lib[j]).Face().Name {
				return lib[i], lib[j]
			}
		}
	}
	t.Fatal("no out-of-order name pair in the library")
	return 0, 0
}

// A pose may be posed again (a retransmission, or T28a's audited sessions
// with Ext wired in): extending it twice must give byte-identical payloads
// and leave the pose's op slices untouched.
func TestReextendingAPoseLeavesItUntouched(t *testing.T) {
	env := constructedEnv(t)
	env.OpenLook(0)
	taken := map[state.ObjID]bool{}
	a, b := hiddenPair(t, env, taken)
	taken[a], taken[b] = true, true
	c, d := hiddenPair(t, env, taken)
	native := &decision.Decision{Kind: decision.KChoose, Player: 0, Seq: 5,
		Options: []decision.Option{{Index: 0, Kind: "search", Obj: a}, {Index: 1, Kind: "search", Obj: b}}}
	follow := &decision.Decision{Kind: decision.KChoose, Player: 0, Seq: 6,
		Options: []decision.Option{{Index: 0, Kind: "search", Obj: c}, {Index: 1, Kind: "search", Obj: d}}}
	p := &mapping.Pose{Seat: 0, Native: native, Followups: map[string]*decision.Decision{"0": follow},
		Candidates: []mapping.Cand{
			{Op: mapping.NativeOp{Op: "choose", Option: 0, Followup: []int{1}}},
			{Op: mapping.NativeOp{Op: "cast", Option: -1, Covers: []int{0, 1}}},
		}}
	before, err := json.Marshal(p.Candidates)
	if err != nil {
		t.Fatal(err)
	}
	x := xview.New()
	ext1, err := x.Extend(env, p, 3)
	if err != nil {
		t.Fatal(err)
	}
	ext2, err := x.Extend(env, p, 3)
	if err != nil {
		t.Fatal(err)
	}
	if raw1, raw2 := ext1["x_gorge_view_v1"], ext2["x_gorge_view_v1"]; !bytes.Equal(raw1, raw2) {
		t.Fatalf("second extension differs:\n%s\n%s", raw1, raw2)
	}
	after, err := json.Marshal(p.Candidates)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(before, after) {
		t.Fatalf("the pose was rewritten:\nbefore %s\nafter  %s", before, after)
	}
	var pl xview.Payload
	if err := json.Unmarshal(ext1["x_gorge_view_v1"], &pl); err != nil {
		t.Fatal(err)
	}
	// Sanity that translation really happened: the swapped names give perm
	// [1,0] on both decisions, so the payload keys the follow-up "1" and the
	// ops carry the renumbered indices.
	if _, ok := pl.Followups["1"]; !ok || len(pl.Followups) != 1 {
		t.Fatalf("follow-up keys %v", maps.Keys(pl.Followups))
	}
	if pl.Ops[0].Option != 1 || !slices.Equal(pl.Ops[0].Followup, []int{0}) {
		t.Fatalf("choose op %+v, want option 1 followup [0]", pl.Ops[0])
	}
	if pl.Ops[1].Option != -1 || !slices.Equal(pl.Ops[1].Covers, []int{1, 0}) {
		t.Fatalf("cast op %+v, want option -1 covers [1 0]", pl.Ops[1])
	}
}
