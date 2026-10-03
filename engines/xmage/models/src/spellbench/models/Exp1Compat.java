package spellbench.models;

import mage.MageObject;
import mage.cards.Card;
import mage.cards.Cards;
import mage.counters.Counter;
import mage.game.Game;
import mage.game.combat.CombatGroup;
import mage.game.permanent.Permanent;
import mage.game.stack.StackObject;
import mage.players.Player;

import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.List;
import java.util.UUID;

/**
 * Fork-only helpers needed by Exp1's encoder on the reviewed base engine.
 * The sorted-card, entity-name and permanent-value rules follow the public
 * DraftZero fork. These decision slices have empty micro-decision history and
 * no activation in progress. Complete dialog equivalence needs history wiring.
 */
public final class Exp1Compat {
    private Exp1Compat() { }

    public static final class History {
        public final List<UUID> targetSequence = Collections.emptyList();
        public final List<String> choiceSequence = Collections.emptyList();
        public final List<Boolean> useSequence = Collections.emptyList();
        public final List<Integer> numSequence = Collections.emptyList();
    }

    public static History history(Player player) { return new History(); }
    public static boolean isActivating(Player player) { return false; }

    public static Card pairedCard(Permanent permanent, Game game) {
        // The original encoder casts a MageObjectReference to Card. Refuse a
        // populated pair rather than silently changing that unqualified case.
        if (permanent.getPairedMOR() != null) {
            throw new IllegalArgumentException("Exp1 decision encoder does not support soulbond pairs");
        }
        return null;
    }

    public static Player opponent(Game game, UUID viewer) {
        if (game.getOpponents(viewer).size() != 1) {
            throw new IllegalArgumentException("Exp1 decision encoder requires two players");
        }
        return game.getPlayer(game.getOpponents(viewer).iterator().next());
    }

    public static List<Card> sortedCards(Cards cards, Game game) {
        List<Card> out = new ArrayList<>();
        for (UUID id : cards) {
            Card card = game.getPermanent(id);
            if (card == null) card = game.getCard(id);
            if (card != null) out.add(card);
        }
        out.sort(Comparator.comparing(Card::getName));
        return out;
    }

    public static String entityName(Game game, UUID id, UUID viewer) {
        if (id == null) return "null";
        if (id.equals(new UUID(0, "stop choosing flag".hashCode()))) return "Stop Choosing";
        MageObject object = game.getObject(id);
        if (object == null) {
            Player player = game.getPlayer(id);
            return player == null ? "null" : player.getId().equals(viewer) ? "PlayerA" : "PlayerB";
        }
        if (object instanceof StackObject && game.getObject(((StackObject) object).getSourceId()) == null) {
            return "null";
        }
        return object.getName();
    }

    public static String permanentValue(Permanent p, Game game, UUID viewer) {
        StringBuilder out = new StringBuilder();
        out.append(p.getControllerId().equals(viewer)).append(p.getName()).append(p.isTapped()).append(p.getDamage());
        out.append(p.getSubtype()).append(p.getSuperType()).append(p.getPower().getValue()).append(p.getToughness().getValue());
        out.append(p.getAbilities(game).getValue());
        List<String> names = new ArrayList<>();
        for (UUID id : p.getAttachments()) names.add(entityName(game, id, viewer));
        Collections.sort(names);
        for (String name : names) out.append(name);
        if (p.isCreature() && p.isAttacking()) {
            out.append("Attacking");
            CombatGroup group = game.getCombat().findGroup(p.getId());
            if (group == null) throw new IllegalArgumentException("attacking permanent lacks its combat group");
            names.clear();
            for (UUID id : group.getBlockers()) names.add(entityName(game, id, viewer));
            Collections.sort(names);
            for (String name : names) out.append(name).append("Blocking");
        }
        List<Counter> counters = new ArrayList<>(p.getCounters(game).values());
        counters.sort(Comparator.comparing(Counter::getName));
        for (Counter counter : counters) out.append(counter.getName()).append(counter.getCount());
        return out.toString();
    }
}
