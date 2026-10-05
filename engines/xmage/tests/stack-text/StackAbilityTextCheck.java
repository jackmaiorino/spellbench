package spellbench.kit.xmage;

import mage.abilities.Ability;
import mage.abilities.TriggeredAbility;
import mage.abilities.common.EntersBattlefieldTriggeredAbility;
import mage.cards.CardSetInfo;
import mage.cards.k.KioraTheRisingTide;
import mage.constants.Rarity;
import mage.game.stack.StackAbility;
import mage.player.spellbench.observe.StackAbilityText;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.UUID;

/** Kiora's actual two triggers must remain distinct, including after stack copying. No game or database. */
public final class StackAbilityTextCheck {
    private static void require(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }

    public static void main(String[] args) {
        require(StackAbilityText.class.getProtectionDomain().getCodeSource().getLocation().equals(
                WorldBuilder.class.getProtectionDomain().getCodeSource().getLocation()),
                "model kit must carry its renderer instead of requiring a newer engine jar");
        KitRandom.installBoot();
        UUID owner = UUID.nameUUIDFromBytes(new byte[]{4});
        KioraTheRisingTide card = new KioraTheRisingTide(owner,
                new CardSetInfo("Kiora, the Rising Tide", "FDN", "45", Rarity.RARE));
        List<Ability> triggers = new ArrayList<>();
        Ability enter = null;
        for (Ability ability : card.getAbilities()) {
            if (ability instanceof TriggeredAbility) triggers.add(ability);
            if (ability instanceof EntersBattlefieldTriggeredAbility) enter = ability;
        }
        require(triggers.size() == 2 && enter != null, "Kiora trigger fixture changed");
        StackAbility stack = new StackAbility(enter.copy(), owner);
        String publicText = StackAbilityText.of(stack.getStackAbility());
        require(publicText != null && publicText.contains("discard"), "wrong public stack rule");
        List<Ability> match = WorldBuilder.stackAbilitiesWithText(triggers, publicText);
        require(match.size() == 1 && match.get(0) == enter, "discard trigger was not uniquely identified");
        require(WorldBuilder.stackAbilitiesWithText(triggers, null).size() == 2,
                "missing text guessed an ambiguous trigger");
        require(WorldBuilder.stackAbilitiesWithText(triggers, "unknown public rule").isEmpty(),
                "unmatched text guessed a trigger");
        require(WorldBuilder.stackAbilitiesWithText(Arrays.asList(enter, enter.copy()), publicText).size() == 2,
                "duplicate text lost its ambiguity");
        System.out.println("Kiora public stack identity: PASS");
    }
}
