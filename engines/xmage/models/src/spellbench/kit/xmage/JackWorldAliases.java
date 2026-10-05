package spellbench.kit.xmage;

import mage.abilities.Ability;
import mage.abilities.Mode;
import mage.abilities.Modes;
import mage.abilities.mana.ManaOptions;
import mage.constants.TurnPhase;
import mage.game.Game;
import mage.players.Player;
import mage.cards.Card;
import mage.game.ExileZone;
import mage.game.command.CommandObject;
import mage.game.permanent.Permanent;
import mage.game.stack.StackObject;
import mage.player.spellbench.observe.Look;
import mage.player.spellbench.observe.Observation;
import mage.player.spellbench.observe.ObservationBuilder;
import spellbench.kit.core.Json;
import spellbench.kit.core.ObsIndex;
import spellbench.kit.core.ObsCompare;
import spellbench.kit.core.Seeds;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;

/** Existing verified root alias projection, shared by codecs and the admitted player. */
final class JackWorldAliases {
    private JackWorldAliases() { }
    static Map<UUID, String> namedAliases(World world, Map<String, Object> decision) throws Exception {
        Map<String, Object> obs = Json.obj(decision, "observation");
        ObsIndex index = new ObsIndex(obs);
        List<Look> looks = new ArrayList<>();
        for (Object item : Json.arr(obs, "known")) {
            Map<String, Object> known = Json.obj(item);
            UUID id = world.idToUuid.get(Json.str(known, "object_id"));
            String how = Json.str(known, "how");
            if (id == null || !("looked_at".equals(how) || "revealed".equals(how) || "searching".equals(how))) continue;
            Number top = (Number) known.get("position_from_top"), bottom = (Number) known.get("position_from_bottom");
            looks.add(new Look(id, how, top == null ? null : top.intValue(), bottom == null ? null : bottom.intValue()));
        }
        Observation visible = ObservationBuilder.forSession(world.game, new byte[32], RoundTrip.flagsFrom(decision))
                .build(world.viewer, Json.str(obs, "priority_seat"), looks);
        Map<String, Object> projected = Json.obj(Json.copy(visible.json()));
        if (!ObsCompare.diff(obs, projected, 8).isEmpty()) {
            throw new IllegalArgumentException("mode aliases differ from the verified current observation");
        }
        Map<String, String> aliases = ObsCompare.alignIds(projected, obs);
        List<UUID> objects = new ArrayList<>();
        // A spell and its underlying card share a reference. Keep the stack
        // entity first, matching the original base-state entity list.
        for (StackObject object : world.game.getStack()) objects.add(object.getId());
        for (CommandObject object : world.game.getState().getCommand()) objects.add(object.getId());
        for (Player player : world.game.getPlayers().values()) {
            for (Permanent object : world.game.getBattlefield().getAllActivePermanents(player.getId())) objects.add(object.getId());
            for (Card card : player.getHand().getCards(world.game)) objects.add(card.getId());
            for (Card card : player.getGraveyard().getCards(world.game)) objects.add(card.getId());
            for (Card card : player.getLibrary().getCards(world.game)) objects.add(card.getId());
        }
        for (ExileZone zone : world.game.getExile().getExileZones()) {
            for (Card card : zone.getCards(world.game)) objects.add(card.getId());
        }
        Map<UUID, String> result = new LinkedHashMap<>();
        Set<String> used = new HashSet<>();
        for (UUID id : objects) {
            Map<String, Object> ref = visible.reference(id);
            if (ref == null || Json.str(ref, "card_name") == null || Json.str(ref, "card_name").isEmpty()) continue;
            String alias = aliases.get(Json.str(ref, "object_id"));
            if (alias == null) throw new IllegalArgumentException("named replay entity has no public alias");
            ref.put("object_id", alias);
            if (!Json.canonical(ref).equals(Json.canonical(index.ref(alias)))) {
                throw new IllegalArgumentException("named replay reference differs from the permitted source");
            }
            if (used.add(alias)) result.put(id, alias);
        }
        for (String alias : index.ids()) {
            String name = Json.str(index.ref(alias), "card_name");
            if (name != null && !name.isEmpty() && !used.contains(alias)) {
                throw new IllegalArgumentException("named permitted entity is absent from the replay map");
            }
        }
        return result;
    }
}
