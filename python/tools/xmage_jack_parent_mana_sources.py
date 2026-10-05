"""Stage the pinned April parent payment policy without substituting engine AI."""
from __future__ import annotations

import hashlib
import re

from xmage_jack_sources import PARENT_SOURCE_PINS, extract, replace_once

PARENT_MANA_PINS = {key: PARENT_SOURCE_PINS[key] for key in
                    ("parent_card_source", "parent6_source", "parent7_source")}
PARENT_MANA_PINS["parent_choice_source"] = "a483f89ab8c749fbd9639111bdf816365b8a5b803a0f73672487aff51cc4cc4c"
PARENT_MANA_VARIANT = (
    "original April parent payment order, producer scores, as-though/conditional tests, "
    "phyrexian guard, special action, queued parent answers and unpaid-color hint; engine producer primitive "
    "through original activation reservations; strategic callbacks and native games unfinished")


def parent_mana_source(sources: dict[str, str]) -> str:
    if (set(sources) != set(PARENT_MANA_PINS) or any(
            hashlib.sha256(sources[key].encode()).hexdigest() != digest
            for key, digest in PARENT_MANA_PINS.items())):
        raise ValueError("Jack parent mana requires all pinned April parent and choice sources")
    # Both intermediate parents inherit these methods. Refuse a changed inheritance path.
    for key in ("parent6_source", "parent7_source"):
        if re.search(r"(?:public|protected|private)\s+[^;{}]*\b(?:playMana|playManaHandling|"
                     r"getAvailableManaProducers)\s*\(", sources[key]):
            raise ValueError("Jack parent mana inheritance has a callback override")
    base = sources["parent_card_source"]
    payment = extract(base, "    @Override\n    public boolean playMana(Ability ability, ManaCost unpaid, String promptText, Game game) {",
                      "    @Override\n    public int announceX(")
    payment = replace_once(payment, "public boolean playMana(Ability ability, ManaCost unpaid, String promptText, Game game)",
                           "protected boolean originalParentPlayMana(Ability ability, ManaCost unpaid, String promptText, Game game)")
    choice = extract(base, "    @Override\n    public boolean choose(Outcome outcome, Choice choice, Game game) {",
                     "    protected boolean chooseCreatureType(")
    choice = replace_once(choice, "    @Override\n    public boolean choose(Outcome outcome, Choice choice, Game game)",
                          "    private boolean originalBaseChoice(Outcome outcome, Choice choice, Game game)")
    choice = replace_once(choice, "chooseCreatureType(outcome, choice, game)",
                          "originalParentCreatureType(outcome, choice, game)")
    queued_choice = extract(sources["parent6_source"],
                            "    @Override\n    public boolean choose(Outcome outcome, Choice choice, Game game) {",
                            "    @Override\n    public boolean chooseTarget(Outcome outcome, Cards cards,")
    queued_choice = replace_once(queued_choice,
                                 "    @Override\n    public boolean choose(Outcome outcome, Choice choice, Game game)",
                                 "    protected final boolean originalParentChoice(Outcome outcome, Choice choice, Game game)")
    queued_choice = replace_once(queued_choice, "super.choose(outcome, choice, game)",
                                 "originalBaseChoice(outcome, choice, game)")
    queued_choice = replace_once(queued_choice, "choice.setChoiceByAnswers(choices, true)",
                                 "setChoiceByAnswers(choice, choices, true)")
    answer = extract(sources["parent_choice_source"],
                     "    @Override\n    public boolean setChoiceByAnswers(List<String> answers, boolean removeSelectAnswerFromList) {",
                     "    @Override\n    public void setSpecial(")
    answer = replace_once(answer,
                          "    @Override\n    public boolean setChoiceByAnswers(List<String> answers, boolean removeSelectAnswerFromList)",
                          "    private static boolean setChoiceByAnswers(Choice choice, List<String> answers, boolean removeSelectAnswerFromList)")
    answer = answer.replace("this.", "choice.")
    return '''package spellbench.models.jack;

import mage.*;
import mage.abilities.*;
import mage.abilities.costs.mana.*;
import mage.abilities.mana.ActivatedManaAbilityImpl;
import mage.abilities.mana.ManaOptions;
import mage.choices.Choice;
import mage.constants.*;
import mage.game.Game;
import mage.players.ManaPoolItem;
import mage.util.CardUtil;
import mage.util.ManaUtil;
import java.util.*;
import java.util.Map.Entry;

/** Original inherited payment policy. Does not assert complete neural callbacks. */
public abstract class OriginalParentManaPlayer extends OriginalActivationPlayer {
    public static final String SOURCE_SHA256 = "%s";
    public static final String PARENT6_SHA256 = "%s";
    public static final String PARENT7_SHA256 = "%s";
    public static final String CHOICE_SHA256 = "%s";
    public static final String VARIANT = "%s";
    private final transient Map<UUID, ManaCost> lastUnpaidMana = new LinkedHashMap<>();
    private transient boolean alreadyTryingToPayPhyrexian;
    protected List<String> choices = new ArrayList<>();
    protected OriginalParentManaPlayer(String name, RangeOfInfluence range) { super(name, range); }
    protected OriginalParentManaPlayer(mage.player.ai.ComputerPlayer bootstrap) { super(bootstrap); }
    protected OriginalParentManaPlayer(OriginalParentManaPlayer player) { super(player); choices.addAll(player.choices); }
    @Override public abstract OriginalParentManaPlayer copy();
    protected abstract boolean originalParentCreatureType(Outcome outcome, Choice choice, Game game);
    @Override protected List<MageObject> originalParentManaProducers(Game game) {
        return engineParentManaProducers(game);
    }
''' % (PARENT_MANA_PINS["parent_card_source"], PARENT_MANA_PINS["parent6_source"],
       PARENT_MANA_PINS["parent7_source"], PARENT_MANA_PINS["parent_choice_source"], PARENT_MANA_VARIANT) + payment + choice + queued_choice + answer + "}\n"
