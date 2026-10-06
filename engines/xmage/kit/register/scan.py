"""Builds the kit's state-qualified mechanics register (design 3.4; A1 result review, change 3) for the cards of the
pool's decklists plus the fixture cards, by a conservative static scan of the pinned XMage sources:

- triggered abilities: a card whose triggers' resolution may read an event object or a captured value is
  ``event_data`` (the kit flags its triggers approximate and never resolves them in search); else ``event_free``.
  Read evidence: the card's own source or a class it references reads effect or game values (``getValue(..)``), or
  a trigger is built to set its target pointer from the event (``SetTargetPointer.X`` other than NONE, or a
  trigger class with a boolean ``setTargetPointer`` constructed with ``true``).
- activated abilities: ``captured_value`` when the card or a class it references reads values or paid costs
  (``getValue(..)``, cost tags, sacrificed or tapped objects); else ``plain``.
- optional and alternative costs (kicker, flashback, gift...): the paid state is not observable, so spells of such
  cards on the stack are flagged approximate (search horizon).
- emblems: the emblem classes a card creates; rebuildable when the card creates exactly one with a no-argument
  constructor.
- tokens: the token classes a card creates (the kit resolves tokens by name at run time; the Java pool audit checks
  each one resolves).
- unsupported: restricted mana (``ConditionalMana``, "Spend this mana only"), control of another player.

Each deck's admission for kit entries follows: excluded when one of its cards has an unsupported status.

    python scan.py --xmage XMAGE_SRC --catalog catalog.json [--catalog more.json ...] [--extra NAME ...]
        [--keep-extensions register.json] --out register.json

Several catalogs may be given (the XMage engine's FDN/Standard catalog and the pauper-kernel decks); their deck ids
must be distinct. ``--keep-extensions`` carries the reviewed ``source_extensions`` rows of an existing register over
unchanged.
"""

import argparse
import json
import os
import re
import sys

READS = re.compile(r"\bgetValue\(\s*[^)\s]")
COST_READS = re.compile(r"getCostsTag|getSourceCostsTag|SacrificeCost\w*Value|SacrificedPermanent|TapTargetCost.*getTarget"
                        r"|getCosts\(\)\.get|ExileFromGraveCost.*getExiled|DiscardCost.*getCards")
SET_POINTER = re.compile(r"SetTargetPointer\.(PERMANENT|CARD|PLAYER|SPELL|ATTACHED_TO_CONTROLLER|ATTACHED_TO_OPPONENT)")
NEW_CLASS = re.compile(r"new\s+([A-Z]\w+)\s*[(<]")
STATIC_REF = re.compile(r"\b([A-Z]\w+)\.(instance|MANY|ONE|TWICE|NONE_\w*|[A-Z_]{3,})\b")
OPTIONAL_COSTS = ["KickerAbility", "MultikickerAbility", "OptionalAdditionalCost", "BuybackAbility", "EntwineAbility",
                  "ReplicateAbility", "SquadAbility", "OffspringAbility", "GiftAbility", "BargainAbility",
                  "CasualtyAbility", "BlitzAbility", "EvokeAbility", "DashAbility", "FlashbackAbility", "EscapeAbility",
                  "DisturbAbility", "MiracleAbility", "ProwlAbility", "SpectacleAbility", "SurgeAbility",
                  "MadnessAbility", "ForetellAbility", "PlotAbility", "WarpAbility", "AlternativeCostSourceAbility",
                  "CleaveAbility", "EmergeAbility", "BestowAbility", "ImpendAbility", "MayhemAbility",
                  "HarmonizeAbility", "SneakAbility", "WebSlingingAbility", "EvidenceAbility", "CollectEvidence"]
RESTRICTED_MANA = re.compile(r"ConditionalMana|ConditionalAnyColorManaAbility|ConditionalColoredManaAbility"
                             r"|ConditionalColorlessManaAbility|Spend this mana only")
CONTROL_PLAYER = re.compile(r"ControlTargetPlayer|GainControlTargetPlayer|takeControlUnderPlayer")


def index_classes(root):
    out = {}
    for d, _, files in os.walk(root):
        for f in files:
            if f.endswith(".java"):
                out.setdefault(f[:-5], os.path.join(d, f))
    return out


def card_classes(sets_dir):
    pat = re.compile(r'SetCardInfo\("([^"]+)",[^;]*?(mage\.cards\.[a-z0-9]+\.[A-Za-z0-9_]+)\.class')
    out = {}
    for f in os.listdir(sets_dir):
        if not f.endswith(".java"):
            continue
        text = open(os.path.join(sets_dir, f), encoding="utf-8", errors="replace").read()
        for name, cls in pat.findall(text):
            out.setdefault(name, cls)
    return out


def read(path):
    return open(path, encoding="utf-8", errors="replace").read()


def strip_comments(text):
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


def card_is_land(text):
    """Read the card constructor's types, retaining the conservative fallback.

    A spell's effects may mention LAND in a filter without making it a land.
    Unrecognized constructors keep the previous source-wide classification.
    """
    constructor = re.search(r"\bsuper\s*\([^,()]*,[^,()]*,\s*new\s+CardType\s*\[\s*\]\s*\{([^}]*)\}", text)
    types = constructor.group(1) if constructor else text
    return re.search(r"\bCardType\.LAND\b", types) is not None


def referenced(text, lib):
    names = set(NEW_CLASS.findall(text)) | {m[0] for m in STATIC_REF.findall(text)}
    return sorted(n for n in names if n in lib)


def class_reads(name, lib, cache, depth=0):
    """(reads values, reads costs, superclass chain) for a library class, one superclass level deep."""
    if name in cache:
        return cache[name]
    cache[name] = (False, False)
    src = strip_comments(read(lib[name]))
    r = bool(READS.search(src))
    c = bool(COST_READS.search(src))
    m = re.search(r"class\s+%s\b[^{]*?\bextends\s+([A-Z]\w+)" % re.escape(name), src)
    if m and depth < 2 and m.group(1) in lib and not m.group(1).endswith("Impl"):
        pr, pc = class_reads(m.group(1), lib, cache, depth + 1)
        r, c = r or pr, c or pc
    cache[name] = (r, c)
    return cache[name]


def boolean_pointer_true(text, lib):
    """A trigger class with a boolean setTargetPointer field constructed with a literal true."""
    for m in re.finditer(r"new\s+([A-Z]\w*TriggeredAbility)\s*\(", text):
        cls = m.group(1)
        if cls not in lib:
            continue
        if not re.search(r"boolean\s+setTargetPointer", read(lib[cls])):
            continue
        depth, i = 1, m.end()
        while i < len(text) and depth:
            depth += {"(": 1, ")": -1}.get(text[i], 0)
            i += 1
        if re.search(r",\s*true\s*\)$", text[m.end() - 1:i]):
            return True
    return False


def scan_card(name, cls, sets_root, lib, cache):
    rel = cls.replace(".", "/") + ".java"
    path = os.path.join(sets_root, rel)
    if not os.path.exists(path):
        path = os.path.join(main_root, rel)
    if not os.path.exists(path):
        return {"status": "unsupported", "why": ["source not found"]}
    raw = read(path)
    text = strip_comments(raw)
    refs = referenced(text, lib)
    triggers = set(re.findall(r"new\s+([A-Z]\w*TriggeredAbility)\s*\(", text)) \
        | set(re.findall(r"class\s+\w+\s+extends\s+(\w*TriggeredAbility\w*)", text))
    for r in refs:  # keyword triggers (prowess, valiant...): library classes that extend a triggered ability
        if r.endswith("Ability") and re.search(r"class\s+%s\b[^{]*\bextends\s+\w*TriggeredAbility" % re.escape(r),
                                               read(lib[r])):
            triggers.add(r)
    triggers = sorted(triggers)
    reads_values = bool(READS.search(text))
    reads_costs = bool(COST_READS.search(text))
    readers = []
    for r in refs:
        rv, rc = class_reads(r, lib, cache)
        if rv or rc:
            readers.append(r)
        reads_values |= rv
        reads_costs |= rc
    pointer = bool(SET_POINTER.search(text)) or boolean_pointer_true(text, lib)
    entry = {"class": cls}
    why_approx = []
    why_unsupported = []
    if triggers:
        event = reads_values or pointer
        entry["triggers"] = "event_data" if event else "event_free"
        entry["trigger_classes"] = triggers
        if event:
            why_approx.append("triggers read event data or captured values" + (" (target pointer from the event)" if pointer else ""))
    activated = bool(re.search(r"new\s+(Simple)?ActivatedAbility\(|new\s+\w*LoyaltyAbility\(|extends\s+ActivatedAbilityImpl", text))
    if activated:
        entry["activated"] = "captured_value" if (reads_values or reads_costs) else "plain"
        if reads_values or reads_costs:
            why_approx.append("activated abilities read captured values or paid costs")
    if readers:
        entry["reading_classes"] = readers
    opt = sorted(o for o in OPTIONAL_COSTS if re.search(r"\b%s\b" % o, text))
    if opt:
        entry["optional_costs"] = opt
        why_approx.append("optional or alternative costs: " + ", ".join(opt))
    emblems = sorted(set(re.findall(r"new\s+([A-Z]\w*Emblem)\s*\(", text)))
    if emblems:
        rebuild = []
        for e in emblems:
            if e not in lib:
                continue
            src = read(lib[e])
            noarg = re.search(r"public\s+%s\s*\(\s*\)" % re.escape(e), src) is not None
            rebuild.append({"class": qualified(lib[e]), "no_arg": noarg})
        entry["emblems"] = rebuild
        if len(rebuild) != 1 or not rebuild[0]["no_arg"]:
            why_unsupported.append("emblem not rebuildable")
    non_stack = []
    if card_is_land(text) and re.search(r"AsEntersBattlefieldAbility|EntersBattlefieldEffect\(new\s+Choose", text):
        non_stack.append("land play asks a choice as it enters")
    if re.search(r"\b(MorphAbility|DisguiseAbility|ManifestDreadEffect|CloakEffect)\b", text):
        non_stack.append("turning face up pays costs with choices")
    if non_stack:
        entry["non_stack_choices"] = non_stack
        why_approx.append("non-stack action asks a choice (the kit declines that action, review change 4)")
    tokens = sorted(set(re.findall(r"new\s+([A-Z]\w*Token)\s*\(", text)))
    # CreatureToken describes what a permanent becomes ("becomes a creature"), not a created token
    tokens = [t for t in tokens if t != "CreatureToken"]
    if tokens:
        entry["tokens"] = tokens
    if RESTRICTED_MANA.search(raw):
        why_unsupported.append("restricted mana")
    if CONTROL_PLAYER.search(text):
        why_unsupported.append("control of another player")
    entry["status"] = "unsupported" if why_unsupported else ("approximate" if why_approx else "supported")
    if why_unsupported or why_approx:
        entry["why"] = why_unsupported + why_approx
    return entry


main_root = ""


def qualified(path):
    p = path.replace("\\", "/")
    for marker in ("/src/main/java/", "/Mage.Sets/src/"):
        if marker in p:
            return p.split(marker, 1)[1][:-5].replace("/", ".")
    return os.path.basename(path)[:-5]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--xmage", required=True)
    ap.add_argument("--catalog", required=True, action="append")
    ap.add_argument("--extra", nargs="*", default=[])
    ap.add_argument("--keep-extensions")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    global main_root
    main_root = os.path.join(a.xmage, "Mage", "src", "main", "java")
    lib = index_classes(main_root)
    sets_root = os.path.join(a.xmage, "Mage.Sets", "src")
    for d, _, files in os.walk(os.path.join(sets_root, "mage", "game", "permanent", "token")):
        for f in files:
            if f.endswith(".java"):
                lib.setdefault(f[:-5], os.path.join(d, f))
    classes = card_classes(os.path.join(sets_root, "mage", "sets"))
    names = set(a.extra)
    decks = {}
    for path in a.catalog:
        for d in json.load(open(path, encoding="utf-8")):
            if d["catalog_id"] in decks:
                sys.exit("duplicate deck id %s" % d["catalog_id"])
            decks[d["catalog_id"]] = sorted({r["name"] for r in d["decklist"]})
            names.update(decks[d["catalog_id"]])
    cache = {}
    cards = {}
    for n in sorted(names):
        cls = classes.get(n) or classes.get(n.split(" // ")[0])
        cards[n] = scan_card(n, cls, sets_root, lib, cache) if cls else {"status": "unsupported", "why": ["no XMage card"]}
    admission = {}
    for deck, ns in sorted(decks.items()):
        bad = [n for n in ns if cards[n]["status"] == "unsupported"]
        approx = [n for n in ns if cards[n]["status"] == "approximate"]
        admission[deck] = {"admitted": not bad, "unsupported_cards": bad, "approximate_cards": approx}
    out = {"schema": "spellbench-kit-register/v1",
           "source": "kit/register/scan.py (static scan of the pinned XMage sources; conservative)",
           "rows": {
               "triggered abilities": "supported: a source with exactly one triggered ability whose resolution reads no "
                                      "event object or captured value (cards[].triggers == event_free); otherwise "
                                      "approximate with the search horizon",
               "activated abilities": "supported unless they read captured values or paid costs (cards[].activated)",
               "optional and alternative costs": "approximate with the search horizon for such spells on the stack",
               "stack targets": "a stack object whose observed targets cannot all be placed is approximate with the "
                                "search horizon",
               "pending triggers": "a world with dropped pending triggers is not searched at priority",
               "emblems": "rebuilt when the source card creates exactly one emblem class with a no-argument "
                          "constructor; else unsupported",
               "tokens": "rebuilt by name through the token repository; a token that does not resolve is unsupported",
               "restricted mana, control of another player": "unsupported"},
           "cards": cards, "admission": admission}
    if a.keep_extensions:
        kept = json.load(open(a.keep_extensions, encoding="utf-8"))
        extensions = kept.get("source_extensions", {})
        for name in extensions:
            cards[name] = kept["cards"][name]
        if extensions:
            out["source_extensions"] = extensions
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, indent=1, sort_keys=True)
        f.write("\n")
    status = {}
    for c in cards.values():
        status[c["status"]] = status.get(c["status"], 0) + 1
    print(json.dumps({"cards": len(cards), "status": status,
                      "decks_admitted": sum(1 for v in admission.values() if v["admitted"]),
                      "decks": len(admission)}))


if __name__ == "__main__":
    main()
