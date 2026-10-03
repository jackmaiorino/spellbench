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
subprocess.run(["git", "-C", str(source), "diff", "--exit-code", "HEAD", "--", "internal/searchprobe", "internal/searchseat"], check=True, stdout=subprocess.DEVNULL)
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
    }
}

# Keep the pinned proposals, weighting, exclusions, budgets and ordered folds,
# adding actor-only comparison boundaries. Upstream files remain untouched.
sampler = (source / "internal/searchprobe/sample.go").read_text(encoding="utf-8")
patches = [
    ("type PublicGame struct {\n", "type PublicGame struct {\n\tMulligans int\n"),
    ("type History struct {\n", 'type History struct {\n\tActorBoundaries bool `json:",omitempty"`\n'),
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

# Opaque observer IDs never get reused after the bridge forgets knowledge.
# The ordinary native collector has no forgotten IDs, so its result is intact.
observation = (source / "internal/searchprobe/observation.go").read_text(encoding="utf-8")
observer_patches = [
    ("type Collector struct {\n", "type Collector struct {\n\tspellbenchZones map[state.ObjID]state.Zone\n"),
    ("\tout := NewCollector(c.actor)\n", "\tout := NewCollector(c.actor)\n\tif c.spellbenchZones != nil {\n\t\tout.spellbenchZones = map[state.ObjID]state.Zone{}\n\t\tfor id, zone := range c.spellbenchZones { out.spellbenchZones[id] = zone }\n\t}\n"),
    ("ref := uint32(len(c.known) + 1)", "ref := uint32(len(c.byRef))"),
]
for before, after in observer_patches:
    if observation.count(before) != 1:
        raise SystemExit("Pinned observer patch context changed; refusing overlay")
    observation = observation.replace(before, after, 1)
replacement = generated / "observation.go"
replacement.write_text(observation, encoding="utf-8")
overlay["Replace"][(source / "internal/searchprobe/observation.go").as_posix()] = replacement.as_posix()
root.joinpath("go-overlay.json").write_text(json.dumps(overlay, indent=2) + "\n", encoding="utf-8")
print(f"Pinned gorge {revision}; read-only source {source}; public API overlay configured")
