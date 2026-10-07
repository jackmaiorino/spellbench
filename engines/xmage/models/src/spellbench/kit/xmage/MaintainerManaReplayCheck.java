package spellbench.kit.xmage;

import mage.abilities.costs.mana.ManaCost;
import mage.abilities.costs.mana.ManaCostsImpl;
import mage.choices.ChoiceColor;
import mage.constants.Outcome;
import mage.constants.RangeOfInfluence;
import mage.player.ai.ComputerPlayer;

import java.lang.reflect.Field;
import java.util.Map;
import java.util.UUID;

/** Public engine delegation preserves actual pending costs; no private maintainer source. */
public final class MaintainerManaReplayCheck {
    private MaintainerManaReplayCheck() { }
    @SuppressWarnings("unchecked")
    public static void main(String[] args) throws Exception {
        Field pending = ComputerPlayer.class.getDeclaredField("lastUnpaidMana");
        pending.setAccessible(true);
        ComputerPlayer player = new ComputerPlayer("original mana delegation", RangeOfInfluence.ALL);
        Map<UUID, ManaCost> costs = (Map<UUID, ManaCost>) pending.get(player);
        String[] symbols = {"W", "R", "G", "U", "B", "C"};
        String[] colors = {"White", "Red", "Green", "Blue", "Black", "Colorless"};
        for (int i = 0; i < symbols.length; i++) {
            costs.clear();
            // Keep a preceding nested payment with a different required color.
            costs.put(new UUID(0, 1), new ManaCostsImpl<ManaCost>("{G}").get(0));
            costs.put(new UUID(0, 2), new ManaCostsImpl<ManaCost>("{" + symbols[i] + "}").get(0));
            ChoiceColor baseline = new ChoiceColor(true), delegated = new ChoiceColor(true);
            baseline.getChoices().add("Colorless"); delegated.getChoices().add("Colorless");
            if (!player.choose(Outcome.PutManaInPool, baseline, null)
                    || !MaintainerManaReplay.engineColor(player, Outcome.PutManaInPool, delegated, null)
                    || !colors[i].equals(baseline.getChoice()) || !baseline.getChoice().equals(delegated.getChoice())
                    || costs.size() != 2) {
                throw new IllegalStateException("original pending mana/color delegation changed for " + symbols[i]);
            }
        }
        System.out.println("Original engine pending-cost delegation: six colors and ordered nested payments pass; private rules unexecuted");
    }
}
