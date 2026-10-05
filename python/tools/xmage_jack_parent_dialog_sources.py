"""Stage original inherited dialogs and amount allocation on a permitted world."""
from __future__ import annotations

import hashlib

from xmage_jack_sources import CALLBACK_SHA256, PARENT_SOURCE_PINS, extract, replace_once

PARENT_DIALOG_VARIANT = (
    "original inherited target scoring, damage allocation, creature-type scan, mode/use/X "
    "fallbacks, queued card targets and ancillary choices; required owned permitted-world "
    "gate; neural callbacks, persistent runtime and native qualification unfinished")


def parent_dialog_source(sources: dict[str, str], callback: str) -> str:
    if (set(sources) != set(PARENT_SOURCE_PINS) or any(
            hashlib.sha256(sources[key].encode()).hexdigest() != digest
            for key, digest in PARENT_SOURCE_PINS.items())):
        raise ValueError("Jack parent dialogs require every pinned April parent source")
    if hashlib.sha256(callback.encode()).hexdigest() != CALLBACK_SHA256:
        raise ValueError("Jack parent dialogs require the pinned April neural callback")
    base = sources["parent_card_source"]
    targets = extract(base, "    @Override\n    public boolean choose(Outcome outcome, Target target, Ability source, Game game) {",
                      "    @Override\n    public boolean priority(Game game) {")
    for old, new in (
            ("public boolean choose(Outcome outcome, Target target, Ability source, Game game)",
             "protected final boolean originalParentTargetChoice(Outcome outcome, Target target, Ability source, Game game)"),
            ("public boolean choose(Outcome outcome, Target target, Ability source, Game game, Map<String, Serializable> options)",
             "protected final boolean originalParentTargetChoice(Outcome outcome, Target target, Ability source, Game game, Map<String, Serializable> options)"),
            ("public boolean chooseTarget(Outcome outcome, Target target, Ability source, Game game)",
             "protected final boolean originalParentTarget(Outcome outcome, Target target, Ability source, Game game)")):
        targets = replace_once(targets, "    @Override\n    " + old, "    " + new)
    targets = replace_once(targets, "return choose(outcome, target, source, game, null);",
                           "return originalParentTargetChoice(outcome, target, source, game, null);")
    targets = targets.replace("PossibleTargetsSelector", "ParentTargetsSelector").replace("PossibleTargetsComparator", "ParentTargetsComparator")
    # Gate each actual entry while retaining all original loop and score decisions.
    targets = replace_once(targets,
                           "private boolean makeChoice(Outcome outcome, Target target, Ability source, Game game, Cards fromCards) {",
                           "private boolean makeChoice(Outcome outcome, Target target, Ability source, Game game, Cards fromCards) {\n        requireOriginalParentWorld(game);")
    # Notify only an active root replay, immediately before the original target mutation.
    begin = targets.index("private boolean makeChoice(Outcome outcome, Target target, Ability source, Game game, Cards fromCards)")
    end = targets.index("    /**\n     * Default choice logic for X or amount values", begin)
    walk = targets[begin:end]
    walk = replace_once(walk, "            target.add(item.getId(), game);\n            if (target.isChoiceCompleted",
        "            originalParentCardPick(item.getId(), possibleTargetsSelector, target, source, game, fromCards, \"good_target\");\n"
        "            target.add(item.getId(), game);\n            if (target.isChoiceCompleted")
    walk = replace_once(walk, "            target.add(item.getId(), game);\n        }\n\n        return target.isChosen",
        "            originalParentCardPick(item.getId(), possibleTargetsSelector, target, source, game, fromCards, \"bad_target\");\n"
        "            target.add(item.getId(), game);\n        }\n\n"
        "        originalParentCardFinish(possibleTargetsSelector, target, source, game, fromCards);\n        return target.isChosen")
    walk = walk.replace("            return false;", "            originalParentCardFinish(null, target, source, game, fromCards);\n            return false;")
    targets = targets[:begin] + walk + targets[end:]
    targets = replace_once(targets, "private int makeChoiceAmount(int min, int max, Game game, Ability source, boolean isManaPay) {",
                           "private int makeChoiceAmount(int min, int max, Game game, Ability source, boolean isManaPay) {\n        requireOriginalParentWorld(game);")
    targets = replace_once(targets, "public boolean chooseTargetAmount(Outcome outcome, TargetAmount target, Ability source, Game game) {",
                           "public final boolean chooseTargetAmount(Outcome outcome, TargetAmount target, Ability source, Game game) {\n        requireOriginalParentWorld(game);")
    creature = extract(base, "    protected boolean chooseCreatureType(Outcome outcome, Choice choice, Game game) {",
                       "    @Override\n    public boolean chooseTarget(Outcome outcome, Cards cards,")
    creature = replace_once(creature,
                            "    protected boolean chooseCreatureType(Outcome outcome, Choice choice, Game game) {",
                            "    @Override protected final boolean originalParentCreatureType(Outcome outcome, Choice choice, Game game) {\n        requireOriginalParentWorld(game);")
    cards = extract(base, "    @Override\n    public boolean chooseTarget(Outcome outcome, Cards cards,",
                    "    @Override\n    public boolean choosePile(")
    cards = replace_once(cards,
                         "    @Override\n    public boolean chooseTarget(Outcome outcome, Cards cards, TargetCard target, Ability source, Game game)",
                         "    private boolean originalBaseTargetCards(Outcome outcome, Cards cards, TargetCard target, Ability source, Game game)")
    cards = replace_once(cards,
                         "    @Override\n    public boolean choose(Outcome outcome, Cards cards, TargetCard target, Ability source, Game game)",
                         "    private boolean originalBaseCards(Outcome outcome, Cards cards, TargetCard target, Ability source, Game game)")
    queued = extract(sources["parent6_source"], "    @Override\n    public boolean chooseTarget(Outcome outcome, Cards cards,",
                     "    private void declareBlockers(")
    for old, new in (("chooseTarget", "originalParentTargetCards"), ("choose", "originalParentCards")):
        queued = replace_once(queued,
                              "    @Override\n    public boolean " + old + "(Outcome outcome, Cards cards, TargetCard target, Ability source, Game game) {",
                              "    protected final boolean " + new + "(Outcome outcome, Cards cards, TargetCard target, Ability source, Game game) {\n        requireOriginalParentWorld(game);")
    queued = replace_once(queued, "super.chooseTarget(outcome, cards, target, source, game)",
                          "originalBaseTargetCards(outcome, cards, target, source, game)")
    queued = replace_once(queued, "super.choose(outcome, cards, target, source, game)",
                          "originalBaseCards(outcome, cards, target, source, game)")
    queued = replace_once(queued, "                target.add(targetId, game);",
        "                originalParentCardPick(targetId, null, target, source, game, cards, \"queued_target\");\n"
        "                target.add(targetId, game);")
    mode = extract(base, "    @Override\n    public Mode chooseMode(",
                   "    @Override\n    public TriggeredAbility chooseTriggeredAbility(")
    mode = replace_once(mode, "    @Override\n    public Mode chooseMode(Modes modes, Ability source, Game game) {",
                         "    protected final Mode originalParentMode(Modes modes, Ability source, Game game) {\n        requireOriginalParentWorld(game);")
    use = extract(base, "    @Override\n    public boolean chooseUse(Outcome outcome, String message, Ability source, Game game) {",
                  "    @Override\n    public boolean choose(Outcome outcome, Choice choice, Game game) {")
    for signature in ("Outcome outcome, String message, Ability source, Game game",
                      "Outcome outcome, String message, String secondMessage, String trueText, String falseText, Ability source, Game game"):
        use = replace_once(use, "    @Override\n    public boolean chooseUse(" + signature + ") {",
                            "    protected final boolean originalParentUse(" + signature + ") {\n        requireOriginalParentWorld(game);")
    announce = extract(base, "    @Override\n    public int announceX(", "    @Override\n    public void abort(")
    announce = replace_once(announce,
                             "    @Override\n    public int announceX(int min, int max, String message, Game game, Ability source, boolean isManaPay)",
                             "    protected final int originalParentAnnounceX(int min, int max, String message, Game game, Ability source, boolean isManaPay)")
    ancillary = extract(base, "    @Override\n    public TriggeredAbility chooseTriggeredAbility(",
                        "    @Override\n    public List<MageObject> getAvailableManaProducers(")
    ancillary += extract(base, "    @Override\n    public boolean choosePile(", "    @Override\n    public void selectAttackers(")
    ancillary += extract(base, "    @Override\n    public int chooseReplacementEffect(", "    @Override\n    public Mode chooseMode(")
    ancillary += extract(base, "    @Override\n    public SpellAbility chooseAbilityForCast(", "    @Override\n    public boolean equals(")
    # The inherited methods keep their signatures and remain actual engine callbacks.
    # getAmount enters the gate through makeChoiceAmount; all others enter here.
    for signature in ("public TriggeredAbility chooseTriggeredAbility(List<TriggeredAbility> abilities, Game game)",
                      "public boolean choosePile(Outcome outcome, String message, List<? extends Card> pile1, List<? extends Card> pile2, Game game)",
                      "public int chooseReplacementEffect(Map<String, String> effectsMap, Map<String, MageObject> objectsMap, Game game)",
                      "public SpellAbility chooseAbilityForCast(Card card, Game game, boolean noMana)"):
        ancillary = replace_once(ancillary, signature + " {", signature + " {\n        requireOriginalParentWorld(game);")
    ancillary = replace_once(ancillary, "int needCount = messages.size();", "requireOriginalParentWorld(game);\n        int needCount = messages.size();")
    return '''package spellbench.models.jack;

import mage.*;
import mage.abilities.*;
import mage.cards.*;
import mage.choices.Choice;
import mage.constants.*;
import mage.game.Game;
import mage.game.permanent.Permanent;
import mage.players.Player;
import mage.players.PlayerImpl;
import mage.target.*;
import mage.util.*;
import java.io.Serializable;
import java.util.*;

/** Original inherited dialogs. All game reads require the owned permitted world. */
public abstract class OriginalParentDialogsPlayer extends OriginalParentManaPlayer {
    public static final String SOURCE_SHA256 = "%s";
    public static final String CALLBACK_SHA256 = "%s";
    public static final String VARIANT = "%s";
    protected List<UUID> targets = new ArrayList<>();
    protected OriginalParentDialogsPlayer(String name, RangeOfInfluence range) { super(name, range); }
    protected OriginalParentDialogsPlayer(mage.player.ai.ComputerPlayer bootstrap) { super(bootstrap); }
    protected OriginalParentDialogsPlayer(OriginalParentDialogsPlayer player) { super(player); targets.addAll(player.targets); }
    @Override public abstract OriginalParentDialogsPlayer copy();
    /** The runtime must reject real hidden state and admit only its reconstructed world/copies. */
    protected abstract void requireOriginalPermittedWorld(Game game);
    private void requireOriginalParentWorld(Game game) {
        if (game == null || game.getPlayer(getId()) != this)
            throw new IllegalArgumentException("original parent dialog needs its owned permitted player");
        requireOriginalPermittedWorld(game);
    }
    protected boolean originalParentCardReplayActive(Game game) { return false; }
    protected void replayOriginalParentCard(Game game,TargetCard target,Ability source,List<UUID> possible,
            UUID selected,int count,int minimum,int maximum,String rule) { }
    private void originalParentCardPick(UUID selected,ParentTargetsSelector selector,Target target,Ability source,
            Game game,Cards cards,String rule) {
        if (cards==null || !originalParentCardReplayActive(game)) return;
        if (!(target instanceof TargetCard)) throw new IllegalArgumentException("actual inherited card target required");
        List<UUID> possible=new ArrayList<>();
        if (selector==null) {
            for(UUID id:target.possibleTargets(target.getAffectedAbilityControllerId(getId()),source,game,cards))
                if (!target.contains(id)) possible.add(id);
        } else for(MageItem item:selector.getAny()) if (!target.contains(item.getId())) possible.add(item.getId());
        if (target.isChosen(game)) possible.add(0,null);
        replayOriginalParentCard(game,(TargetCard)target,source,possible,selected,target.getTargets().size(),
                target.getMinNumberOfTargets(),target.getMaxNumberOfTargets(),rule);
    }
    private void originalParentCardFinish(ParentTargetsSelector selector,Target target,Ability source,Game game,Cards cards) {
        if (cards==null || !originalParentCardReplayActive(game)
                || target.getTargets().size()>=target.getMaxNumberOfTargets() || !target.isChosen(game)) return;
        originalParentCardPick(null,selector,target,source,game,cards,"implicit_finish");
    }
    @Override public final boolean choose(Outcome outcome, Target target, Ability source, Game game, Map<String, Serializable> options) {
        return originalParentTargetChoice(outcome, target, source, game, options);
    }
''' % (PARENT_SOURCE_PINS["parent_card_source"], CALLBACK_SHA256, PARENT_DIALOG_VARIANT) + targets + creature + cards + queued + mode + use + announce + ancillary + "}\n"
