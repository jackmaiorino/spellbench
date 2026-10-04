"""Resolve the pinned source and a build-only public-collector API overlay."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

PIN = "26257e0eda1779d739a07e835c6500b9c4dabc62"
root = Path(__file__).resolve().parents[1]
source = Path(os.environ["GORGE_SRC"]).resolve()
revision = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
if revision != PIN:
    raise SystemExit(f"gorge at {revision}, pinned {PIN}")
subprocess.run(["git", "-C", str(source), "diff", "--exit-code", "HEAD", "--", "internal/searchprobe", "internal/searchseat", "effects/zone.go"], check=True, stdout=subprocess.DEVNULL)
root.joinpath("go.work").write_text(
    f'go 1.25.8\n\nuse (\n  .\n  ./strategies\n)\n\nreplace github.com/adams-shaun/gorge => "{source.as_posix()}"\n',
    encoding="utf-8",
)
overlay = {
    "Replace": {
        (source / "internal/searchprobe/spellbench_public_collector.go").as_posix():
            (root / "native-overlay/public_collector.go.txt").as_posix(),
        (source / "internal/searchprobe/spellbench_public_history.go").as_posix():
            (root / "native-overlay/public_history.go.txt").as_posix(),
        (source / "internal/searchprobe/spellbench_public_compare.go").as_posix():
            (root / "native-overlay/public_compare.go.txt").as_posix(),
        (source / "internal/searchprobe/spellbench_public_payment.go").as_posix():
            (root / "native-overlay/public_payment.go.txt").as_posix(),
        (source / "internal/searchprobe/spellbench_public_redeal.go").as_posix():
            (root / "native-overlay/public_redeal.go.txt").as_posix(),
        (source / "internal/searchprobe/spellbench_public_basic_search.go").as_posix():
            (root / "native-overlay/public_basic_search.go.txt").as_posix(),
        (source / "internal/searchprobe/spellbench_public_known.go").as_posix():
            (root / "native-overlay/public_known.go.txt").as_posix(),
        (source / "rules/spellbench_public_replay_clone.go").as_posix():
            (root / "native-overlay/public_replay_clone.go.txt").as_posix(),
    }
}

# Keep the pinned proposals, weighting, exclusions, budgets and ordered folds,
# adding actor-only comparison boundaries. Upstream files remain untouched.
sampler = (source / "internal/searchprobe/sample.go").read_text(encoding="utf-8")
patches = [
    ("type PublicGame struct {\n", "type PublicGame struct {\n\tMulligans int\n"),
    ("type History struct {\n", 'type History struct {\n\tActorBoundaries bool `json:",omitempty"`\n'),
    ("type SampleResult struct {\n", 'type SampleResult struct {\n\tPublicReconstruction *SpellbenchReconstruction `json:",omitempty"`\n'),
    ("\t\tworlds, refused := redealWorlds(setup, h, known, opts.Redeal, opts.Worlds, func(i int) [2]uint64 {\n",
     "\t\tbase := opts.Redeal\n"
     "\t\tif base.SpellbenchPublic {\n"
     "\t\t\tvar err error\n"
     "\t\t\tvar work SpellbenchReconstruction\n"
     "\t\t\tbase, work, err = SpellbenchReconstructRedeal(setup, h, opts)\n"
     "\t\t\tresult.PublicReconstruction = &work\n"
     "\t\t\tif err != nil { result.RedealRefused = err.Error(); return result, nil }\n"
     "\t\t}\n"
     "\t\tworlds, refused := redealWorlds(setup, h, known, base, opts.Worlds, func(i int) [2]uint64 {\n"),
    ("cfg := rules.Config{Seed: seed[0], Names: setup.Names, Decks: setup.Decks, Tokens: setup.Tokens, StartingLife: setup.StartingLife}",
     "cfg := rules.Config{Seed: seed[0], Names: setup.Names, Decks: setup.Decks, Tokens: setup.Tokens, StartingLife: setup.StartingLife, Mulligans: setup.Mulligans}"),
    ("\t\t\tgot, err := observer.captureScratch(e, e.L.Events[pos:], opts.ComparePotentialActions)\n",
     "\t\t\tvar got Frame\n\t\t\tvar err error\n"
     "\t\t\tif h.ActorBoundaries {\n"
     "\t\t\t\tvar ok bool\n"
     "\t\t\t\tgot, ok, err = spellbenchActorFrame(e, observer, &pos, &submits, h.Actor, opts, bots, boards, res)\n"
     "\t\t\t\tif err == nil && !ok { accepted = false; break }\n"
     "\t\t\t} else {\n"
     "\t\t\t\tgot, err = observer.captureScratch(e, e.L.Events[pos:], opts.ComparePotentialActions)\n"
     "\t\t\t}\n"),
    ("\t\t\tif !reflect.DeepEqual(got, want) {\n",
     "\t\t\tequal := reflect.DeepEqual(got, want)\n"
     "\t\t\tif h.ActorBoundaries { equal = spellbenchFrameEqual(got, want) }\n"
     "\t\t\tif !equal {\n"),
]
for before, after in patches:
    if sampler.count(before) != 1:
        raise SystemExit("Pinned sampler patch context changed; refusing overlay")
    sampler = sampler.replace(before, after, 1)
generated = root / ".go-overlay"
generated.mkdir(exist_ok=True)
replacement = generated / "sample.go"
replacement.write_text(sampler, encoding="utf-8")
overlay["Replace"][(source / "internal/searchprobe/sample.go").as_posix()] = replacement.as_posix()

# Forge's hidden-origin resolution defaults its decider to the searched
# player. The pinned engine incorrectly defaults library confirmation, look
# and pick to the source controller, exposing an opponent's private choices.
# Explicit Chooser selectors still win; object-valued moves keep their existing
# controller fallback. The original pinned source remains untouched.
zone = (source / "effects/zone.go").read_text(encoding="utf-8")
start = zone.index("func effSearchLibrary(")
end = zone.index("func moveDefinedLibraryObjects(", start)
library = zone[start:end]
if library.count("searchChooser(h, c, sa)") != 3:
    raise SystemExit("Pinned library chooser call sites changed; refusing overlay")
library = library.replace("searchChooser(h, c, sa)", "searchChooser(h, c, sa, owner)")
zone = zone[:start] + library + zone[end:]
before = '''func searchChooser(h Host, c *Ctx, sa *cards.SA) state.PlayerID {
	if spec := strings.TrimSpace(sa.Params["Chooser"]); spec != "" {
		if p, ok := chooserPlayer(h, c, spec); ok {
			return p
		}
	}
	return c.Controller
}'''
after = before.replace("sa *cards.SA)", "sa *cards.SA, fallback ...state.PlayerID)").replace(
    "\treturn c.Controller\n}",
    "\tif len(fallback) != 0 {\n\t\treturn fallback[0]\n\t}\n\treturn c.Controller\n}",
)
if zone.count(before) != 1:
    raise SystemExit("Pinned library chooser fallback changed; refusing overlay")
zone = zone.replace(before, after, 1)
replacement = generated / "zone.go"
replacement.write_text(zone, encoding="utf-8")
overlay["Replace"][(source / "effects/zone.go").as_posix()] = replacement.as_posix()

# Planned payment answers are exclusive selectors with no Choices. Preserve
# them only on the public bridge, using observer IDs and stripped digests;
# Match reissues the exact independently offered hypothetical witness.
# A multi-color mana choice can share source, object and ability. Preserve its
# structured symbol too, so Match can replay the actor's selected color.
action = (source / "internal/searchprobe/action.go").read_text(encoding="utf-8")
for before, after in [
    ("type Action struct {\n", 'type Action struct {\n\tSpellbenchPayment string `json:",omitempty"`\n\tManaSymbol string `json:",omitempty"`\n'),
    ("\tif d.Source != 0 && a.Source == 0 || o.Obj != 0 && a.Obj == 0 || o.Attacker != 0 && a.Attacker == 0 {\n",
     "\tif c.spellbenchChronological { a.ManaSymbol = o.ManaSymbol }\n"
     "\tif d.Source != 0 && a.Source == 0 || o.Obj != 0 && a.Obj == 0 || o.Attacker != 0 && a.Attacker == 0 {\n"),
    ("\tif err := d.Validate(in); err != nil {\n\t\treturn nil, nil, err\n\t}\n",
     "\tif err := d.Validate(in); err != nil {\n\t\treturn nil, nil, err\n\t}\n"
     "\tif c.spellbenchChronological && in.Payment != nil {\n"
     "\t\ta, err := c.spellbenchPaymentAction(d, in.Payment)\n\t\tif err != nil { return nil, nil, err }\n"
     "\t\treturn []Action{a}, nil, nil\n\t}\n"),
    ("\tmatch := func(actions []Action) ([]int, error) {\n",
     "\tif c.spellbenchChronological && len(choices) == 1 && choices[0].SpellbenchPayment != \"\" {\n"
     "\t\tif len(rest) != 0 { return decision.Intent{}, fmt.Errorf(\"payment answer has an arranged rest\") }\n"
     "\t\treturn c.spellbenchMatchPayment(d, choices[0])\n\t}\n"
     "\tmatch := func(actions []Action) ([]int, error) {\n"),
]:
    if action.count(before) != 1:
        raise SystemExit("Pinned payment action context changed; refusing overlay")
    action = action.replace(before, after, 1)
replacement = generated / "action.go"
replacement.write_text(action, encoding="utf-8")
overlay["Replace"][(source / "internal/searchprobe/action.go").as_posix()] = replacement.as_posix()

# The two pinned London sites move the asking player's own hand. A redacted
# opponent card does not make the actor's unrelated library order uncertain.
# Other blind moves retain the native conservative invalidation of all cursors.
epochs = (source / "internal/searchprobe/epochs.go").read_text(encoding="utf-8")
before = "\t\t\t\towner, known := owners[ev.Obj]\n"
after = before + (
    "\t\t\t\tif h.ActorBoundaries && !known && ev.Obj == 0 && ev.From == state.ZHand && ev.To == state.ZLibrary && (ev.Text == \"mulligan\" || ev.Text == \"bottomed\") {\n"
    "\t\t\t\t\towner, known = ev.Player, true\n\t\t\t\t}\n"
)
if epochs.count(before) != 1:
    raise SystemExit("Pinned London library-owner context changed; refusing overlay")
epochs = epochs.replace(before, after, 1)
replacement = generated / "epochs.go"
replacement.write_text(epochs, encoding="utf-8")
overlay["Replace"][(source / "internal/searchprobe/epochs.go").as_posix()] = replacement.as_posix()

# Opaque observer IDs never get reused after the bridge forgets knowledge.
# The ordinary native collector has no forgotten IDs, so its result is intact.
observation = (source / "internal/searchprobe/observation.go").read_text(encoding="utf-8")
observer_patches = [
    ("type Collector struct {\n", "type Collector struct {\n\tspellbenchZones map[state.ObjID]state.Zone\n\tspellbenchSources map[state.ObjID]uint32\n\tspellbenchChronological bool\n"),
    ("\tout := NewCollector(c.actor)\n", "\tout := NewCollector(c.actor)\n\tout.spellbenchChronological = c.spellbenchChronological\n\tif c.spellbenchZones != nil {\n\t\tout.spellbenchZones = map[state.ObjID]state.Zone{}\n\t\tfor id, zone := range c.spellbenchZones { out.spellbenchZones[id] = zone }\n\t}\n\tif c.spellbenchSources != nil {\n\t\tout.spellbenchSources = map[state.ObjID]uint32{}\n\t\tfor id, ref := range c.spellbenchSources { out.spellbenchSources[id] = ref }\n\t}\n"),
    ("ref := uint32(len(c.known) + 1)", "ref := uint32(len(c.byRef))"),
]
for before, after in observer_patches:
    if observation.count(before) != 1:
        raise SystemExit("Pinned observer patch context changed; refusing overlay")
    observation = observation.replace(before, after, 1)
# Public event identities are allocated and retired in event order, before
# the final board. Otherwise a reveal before a shuffle in the same burst can
# acquire a binding after the shuffle's retirement pass and leak that copy.
intro_start = observation.index("\t// Introduce only cards explicitly displayed")
intro_end = observation.index("\tredacted := c.redacted[:0]", intro_start)
introduce_board = observation[intro_start:intro_end]
public_introduce_board = introduce_board.replace(
    "\tfor _, s := range v.Stack {\n\t\tc.introduce(e, s.ID)\n",
    "\tfor i := range v.Stack {\n\t\ts := &v.Stack[i]\n\t\tc.introduce(e, s.ID)\n\t\tc.spellbenchStackSource(e, s)\n",
)
if public_introduce_board == introduce_board:
    raise SystemExit("Pinned stack-source collector context changed; refusing overlay")
observation = observation[:intro_start] + "\tif !c.spellbenchChronological {\n" + introduce_board + "\t}\n" + observation[intro_end:]
chronological_patches = [
    ("\tv := view.Project(e.G, chars, c.actor, e.Pending())\n",
     "\tv := view.Project(e.G, chars, c.actor, e.Pending())\n\tif c.spellbenchChronological { c.spellbenchPublicView(e, &v) }\n"),
    ("\tc.introduced = nil\n", "\tc.introduced = nil\n\tvar publicEvents []ObservedEvent\n"),
    ("\tfor _, raw := range burst {\n", "\tfor _, raw := range burst {\n\t\tif c.spellbenchChronological { c.spellbenchForget(e, []events.Event{raw}) }\n"),
    ("\t\tredacted = append(redacted, ev)\n", "\t\tif c.spellbenchChronological { publicEvents = append(publicEvents, c.spellbenchObservedEvent(ev)) } else { redacted = append(redacted, ev) }\n"),
    ("\tframe := Frame{Identities: append([]Identity(nil), c.introduced...)}\n",
     "\tframe := Frame{Identities: append([]Identity(nil), c.introduced...)}\n"
     "\tif c.spellbenchChronological {\n" + public_introduce_board +
     "\t\tframe.Identities = append([]Identity(nil), c.introduced...)\n\t\tframe.Events = publicEvents\n\t}\n"),
]
for before, after in chronological_patches:
    if observation.count(before) != 1:
        raise SystemExit("Pinned chronological collector context changed; refusing overlay")
    observation = observation.replace(before, after, 1)
replacement = generated / "observation.go"
replacement.write_text(observation, encoding="utf-8")
overlay["Replace"][(source / "internal/searchprobe/observation.go").as_posix()] = replacement.as_posix()

# A public root is constructed lazily only when native rejection sampling
# starves. The native redeal implementation still derives, pins and deals its
# pool, and the ordinary search configuration never invokes this seam.
for relative, patches in [
    ("internal/searchprobe/redeal.go", [
        ("type RedealBase struct {\n", "type RedealBase struct {\n\tSpellbenchPublic bool\n"),
        ("string(now.Board) != string(last.Board)",
         "!spellbenchBoardEqual(now.Board, last.Board, h.ActorBoundaries)"),
        ("string(frame.Board) != string(now.Board)",
         "!spellbenchBoardEqual(frame.Board, now.Board, h.ActorBoundaries)"),
        ("\t\tfor _, id := range append(append([]state.ObjID(nil), plan.hand...), lib...) {\n",
         "\t\textra, reason := known.spellbenchAnonymousPins(e, p, pinLib)\n"
         "\t\tif reason != \"\" { return nil, reason }\n"
         "\t\tfor _, id := range extra { pinLib[id] = true; plan.loose = append(plan.loose, id); take(p, e.G.Obj(id).Card.Faces[0].Name) }\n"
         "\t\textraHand, reason := known.spellbenchAnonymousHandPins(e, p, plan.pinHand)\n"
         "\t\tif reason != \"\" { return nil, reason }\n"
         "\t\tfor _, id := range extraHand { plan.pinHand[id] = true; take(p, e.G.Obj(id).Card.Faces[0].Name) }\n"
         "\t\tfor _, id := range append(append([]state.ObjID(nil), plan.hand...), lib...) {\n"),
    ]),
    ("internal/searchprobe/known.go", [
        ("type KnownCards struct {\n", 'type KnownCards struct {\n\tSpellbenchAnonymous []SpellbenchLibraryMinimum `json:",omitempty"`\n\tSpellbenchAnonymousHands []SpellbenchHandMinimum `json:",omitempty"`\n'),
        ("type KnownCardTracker struct {\n", "type KnownCardTracker struct {\n\tspellbenchPublic bool\n\tspellbenchMinimum map[state.PlayerID]map[string]int\n\tspellbenchHandMinimum map[state.PlayerID]map[string]int\n"),
        ("\tt := NewKnownCardTracker(h.Actor)\n", "\tt := NewKnownCardTracker(h.Actor)\n\tt.spellbenchPublic = h.ActorBoundaries\n"),
        ("func (k KnownCards) Count() int {\n\tn := 0\n", "func (k KnownCards) Count() int {\n\tn := k.spellbenchExtraAnonymousCount()\n"),
        ("\tfor _, ev := range frame.Events {\n\t\tt.event(ev)\n", "\tfor _, ev := range frame.Events {\n\t\tif t.spellbenchPublic { t.spellbenchKnowledgeEvent(ev) }\n\t\tt.event(ev)\n"),
        ("func (t *KnownCardTracker) clearZone(z knownLoc) {\n", "func (t *KnownCardTracker) clearZone(z knownLoc) {\n\tif z.zone == state.ZLibrary { delete(t.spellbenchMinimum, z.player) }\n\tif z.zone == state.ZHand { delete(t.spellbenchHandMinimum, z.player) }\n"),
        ("\tout := KnownCards{Actor: t.actor}\n", "\tout := KnownCards{Actor: t.actor}\n\tif t.spellbenchPublic { out.SpellbenchAnonymous = t.spellbenchMinimumClaims(); out.SpellbenchAnonymousHands = t.spellbenchHandMinimumClaims() }\n"),
        ("func (k KnownCards) holds(e *rules.Engine, c *Collector) error {\n", "func (k KnownCards) holds(e *rules.Engine, c *Collector) error {\n\tif err := k.spellbenchAnonymousHolds(e); err != nil { return err }\n"),
    ]),
    ("internal/searchseat/searchseat.go", [
        ("type Options struct {\n", "type Options struct {\n\tSpellbenchPublicRedeal bool\n"),
        ("type Trace struct {\n", 'type Trace struct {\n\tPublicReconstruction *searchprobe.SpellbenchReconstruction `json:",omitempty"`\n\tRedealt int `json:",omitempty"`\n\tRedealRefused string `json:",omitempty"`\n'),
        ("\treturn &searchprobe.RedealBase{Engine: e, Observer: collector}\n",
         "\tif opts.SpellbenchPublicRedeal { return &searchprobe.RedealBase{SpellbenchPublic: true} }\n"
         "\treturn &searchprobe.RedealBase{Engine: e, Observer: collector}\n"),
        ("func recordSample(tr *Trace, sr searchprobe.SampleResult) {\n",
         "func recordSample(tr *Trace, sr searchprobe.SampleResult) {\n"
         "\ttr.Redealt, tr.RedealRefused, tr.PublicReconstruction = sr.Redealt, sr.RedealRefused, sr.PublicReconstruction\n"),
    ]),
]:
    contents = (source / relative).read_text(encoding="utf-8")
    for before, after in patches:
        if contents.count(before) != 1:
            raise SystemExit(f"Pinned {relative} patch context changed; refusing overlay")
        contents = contents.replace(before, after, 1)
    replacement = generated / Path(relative).name
    replacement.write_text(contents, encoding="utf-8")
    overlay["Replace"][(source / relative).as_posix()] = replacement.as_posix()
root.joinpath("go-overlay.json").write_text(json.dumps(overlay, indent=2) + "\n", encoding="utf-8")
print(f"Pinned gorge {revision}; read-only source {source}; public API overlay configured")
