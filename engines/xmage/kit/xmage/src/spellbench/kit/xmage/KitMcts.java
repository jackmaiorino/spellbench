package spellbench.kit.xmage;

import mage.abilities.Ability;
import mage.constants.RangeOfInfluence;
import mage.game.Game;
import mage.player.ai.ComputerPlayerMCTS;
import mage.player.ai.MCTSNode;
import mage.player.ai.MCTSPlayer;
import mage.player.ai.score.GameStateEvaluator2;
import spellbench.kit.core.Json;
import spellbench.kit.core.ObsIndex;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * H3's bot (design Section 5.3): the vendored upstream MCTS plugin with the kit diff (re-deal hook with branch-local
 * knowledge, completed-iteration budget, single thread, payload witness, root statistics, horizon), deciding on one
 * world. Upstream quirks are preserved (integer division in UCT, anything but a win is a loss, random high values
 * for unvisited children).
 */
public class KitMcts extends ComputerPlayerMCTS {

    private static final long serialVersionUID = 1L;

    public transient boolean setup = true;
    private transient World world;
    private transient List<Map<String, Object>> stats = new ArrayList<>();
    private transient ObsIndex obs;

    public KitMcts(String name, int skill) {
        super(name, RangeOfInfluence.ALL, skill);
    }

    protected KitMcts(final KitMcts p) {
        super(p);
        this.setup = p.setup;
        this.world = p.world;
    }

    @Override
    public KitMcts copy() {
        return new KitMcts(this);
    }

    public void attach(World w, ObsIndex obs) {
        this.world = w;
        this.obs = obs;
        this.setup = false;
    }

    @Override
    public boolean chooseMulligan(Game game) {
        return setup ? false : super.chooseMulligan(game);
    }

    @Override
    protected void kitRootStats(MCTSNode root) {
        stats = new ArrayList<>();
        if (root == null) {
            return;
        }
        int i = 0;
        for (MCTSNode child : root.kitChildren()) {
            Ability a = child.getAction();
            Map<String, Object> sem = a == null ? null : Mapping.prioritySemantic(world, world.game, a, obs);
            Map<String, Object> st = Json.map("index", (long) i++, "semantic", sem, "visits", (long) child.getVisits(),
                    "wins", (long) child.kitWins(), "payload", child.kitPayload(), "truncated", child.kitIsTruncated());
            if (a == null && child.getCombat() != null) {
                st.put("combat", combatPairs(child.getCombat()));
            }
            stats.add(st);
        }
    }

    /** A combat's pairs through the world's id map: attacker and defender, or blocker and attacker. */
    List<Object> combatPairs(mage.game.combat.Combat combat) {
        List<Object> pairs = new ArrayList<>();
        for (mage.game.combat.CombatGroup g : combat.getGroups()) {
            for (java.util.UUID at : g.getAttackers()) {
                if (g.getBlockers().isEmpty()) {
                    pairs.add(Json.map("attacker", world.uuidToId.get(at), "defender", Mapping.targetRef(world, g.getDefenderId())));
                }
                for (java.util.UUID b : g.getBlockers()) {
                    pairs.add(Json.map("blocker", world.uuidToId.get(b), "attacker", world.uuidToId.get(at)));
                }
            }
        }
        return pairs;
    }

    /**
     * Upstream dispatch for combat (A1 result review, change 6): {@code ComputerPlayerMCTS.selectAttackers} or
     * {@code selectBlockers} on the world, which search with MCTS and declare the best child's combat; root
     * statistics per child (visits, wins, the child's combat).
     */
    public Map<String, Object> decideCombat(World w, ObsIndex index, boolean attack) {
        Game game = w.game;
        attach(w, index);
        KitContext.world = w;
        KitContext.baseline = GameStateEvaluator2.evaluate(playerId, game).getTotalScore();
        if (attack) {
            selectAttackers(game, playerId);
        } else {
            selectBlockers(null, game, playerId);
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("root_stats", stats);
        return out;
    }

    /** The search on the world: root statistics per child, and the upstream best child's action and payload. */
    public Map<String, Object> decidePriority(World w, ObsIndex index) {
        Game game = w.game;
        attach(w, index);
        KitContext.world = w;
        KitContext.baseline = GameStateEvaluator2.evaluate(playerId, game).getTotalScore();
        game.getState().setPriorityPlayerId(playerId);
        game.firePriorityEvent(playerId);
        getNextAction(game, MCTSPlayer.NextAction.PRIORITY);
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("root_stats", stats);
        Ability best = root == null ? null : root.getAction();
        out.put("semantic", best == null ? Json.map("kind", "pass") : Mapping.prioritySemantic(w, game, best, index));
        out.put("executed_payload", root == null ? null : root.kitPayload());
        return out;
    }
}
