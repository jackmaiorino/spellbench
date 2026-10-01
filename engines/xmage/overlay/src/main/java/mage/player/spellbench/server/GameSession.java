package mage.player.spellbench.server;

import mage.game.Game;
import mage.player.cabt.CabtDeckFactory;
import mage.player.cabt.CabtGameSession;
import mage.player.cabt.CardResolver;
import mage.player.spellbench.rng.GameRandom;
import mage.players.Player;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

/**
 * One v2 game on XMage (design draft Section 3.2): the X1 stream router installed before any object of the
 * game exists, both seats as CABT bridge players parked per prompt, the starting player host-assigned, and the
 * terminal derived from player state, never from XMage's winner string.
 * <p>
 * Decisions come from a {@link DecisionMapper} (tasks X3 and X4). Until one exists, the first prompt ends the
 * game {@code halted} with reason {@code engine_contract_failure:decision_mapping_pending} (Section 9.5): the
 * engine never emits a partial decision.
 */
final class GameSession {

    /** Builds the seat decision for a CABT prompt, and applies a chosen candidate (tasks X3, X4). */
    interface DecisionMapper {
        /** The decision to pose, or an engine answer ({@link Posed#engineAnswer}) for an engine-default prompt. */
        Posed pose(CabtGameSession.Event event, Game game, String seat) throws Unrepresentable;

        /** The CABT option indices that realize a candidate of the posed decision. */
        List<Integer> realize(Posed posed, int candidateId) throws Unrepresentable;
    }

    /** A state the mapper cannot represent: the game ends halted (Section 9.5). */
    static final class Unrepresentable extends Exception {
        private static final long serialVersionUID = 1L;
        final String cause;

        Unrepresentable(String cause) {
            super(cause);
            this.cause = cause;
        }
    }

    /**
     * A decision as posed: its seat_decision and each candidate's canonical semantic, for the echo check; or,
     * for a prompt the engine answers itself under a declared default (a keep under {@code mulligan: none}),
     * the CABT option indices it answers with.
     */
    static final class Posed {
        final Map<String, Object> seatDecision;
        final List<String> semantics;
        final List<Integer> engineAnswer;

        Posed(Map<String, Object> seatDecision, List<String> semantics) {
            this.seatDecision = seatDecision;
            this.semantics = semantics;
            this.engineAnswer = null;
        }

        private Posed(List<Integer> engineAnswer) {
            this.seatDecision = null;
            this.semantics = null;
            this.engineAnswer = engineAnswer;
        }

        static Posed engineAnswer(List<Integer> options) {
            return new Posed(options);
        }
    }

    /** The mapper used until X3 and X4 land. */
    static final DecisionMapper PENDING = new DecisionMapper() {
        @Override
        public Posed pose(CabtGameSession.Event event, Game game, String seat) throws Unrepresentable {
            throw new Unrepresentable("decision_mapping_pending");
        }

        @Override
        public List<Integer> realize(Posed posed, int candidateId) throws Unrepresentable {
            throw new Unrepresentable("decision_mapping_pending");
        }
    };

    final String gameId;
    private final DecisionMapper mapper;
    private final CabtGameSession session;
    private final List<UUID> seats = new ArrayList<>();
    private final long maxSteps;
    private final long maxDecisions;
    long step;           // the pending decision's binding step = the answered decisions so far
    long decisionCount;  // completed groups (X4 counts groups; until then one decision is one group)
    Posed pending;
    Map<String, Object> terminal; // outcome, classification, winner, reason; null while the game runs

    private GameSession(String gameId, DecisionMapper mapper, CabtGameSession session, long maxSteps,
                        long maxDecisions) {
        this.gameId = gameId;
        this.mapper = mapper;
        this.session = session;
        this.maxSteps = maxSteps;
        this.maxDecisions = maxDecisions;
    }

    /**
     * Builds the game. Card classes of both decks are initialized under the boot router first, so class
     * initializers never draw from this game's streams (X1); then the game router is installed.
     */
    static GameSession create(Requests.Reset reset, List<CabtDeckFactory.Entry> deck0,
                              List<CabtDeckFactory.Entry> deck1, CardResolver resolver, DecisionMapper mapper) {
        GameRandom.installBoot();
        resolver.buildDeck(UUID.nameUUIDFromBytes(new byte[]{0}), deck0);
        resolver.buildDeck(UUID.nameUUIDFromBytes(new byte[]{1}), deck1);
        GameRandom router = GameRandom.install(reset.gameSecret);
        CabtGameSession.Config config = new CabtGameSession.Config()
                .playerNames("p0", "p1").decisionTimeoutSeconds(600);
        CabtGameSession session = new CabtGameSession(deck0, deck1, config, resolver);
        GameSession g = new GameSession(reset.gameId, mapper, session, reset.maxSteps, reset.maxDecisions);
        g.seats.addAll(session.game().getPlayers().keySet());
        router.assignSeat(g.seats.get(0), "p0");
        router.assignSeat(g.seats.get(1), "p1");
        session.game().setStartingPlayerId(g.seats.get(Requests.SEATS.indexOf(reset.rules.startingSeat)));
        return g;
    }

    /** A game that failed while being built: already over, halted with {@code cause}. */
    static GameSession halted(String gameId, String cause) {
        GameSession g = new GameSession(gameId, PENDING, null, 0, 0);
        g.terminal = terminal("halted", "halted", null, "engine_contract_failure:" + cause);
        GameRandom.installBoot();
        return g;
    }

    /** Runs the game to its first decision or its end. */
    void start() {
        try {
            advance(session.start());
        } catch (RuntimeException e) {
            e.printStackTrace(System.err);
            halt("engine_error");
        }
    }

    /** Applies a validated candidate of the pending decision and runs to the next decision or the end. */
    void answer(int candidateId) {
        Posed posed = pending;
        pending = null;
        step++;
        decisionCount++;
        List<Integer> options;
        try {
            options = mapper.realize(posed, candidateId);
        } catch (Unrepresentable e) {
            halt(e.cause);
            return;
        }
        try {
            advance(session.select(options));
        } catch (RuntimeException e) {
            e.printStackTrace(System.err);
            halt("engine_error");
        }
    }

    private void advance(CabtGameSession.Event event) {
        while (true) {
            switch (event.kind()) {
                case GAME_OVER:
                    end(naturalTerminal());
                    return;
                case GAME_ERROR:
                    halt("engine_error");
                    return;
                default:
                    break;
            }
            if (step >= maxSteps || decisionCount >= maxDecisions) {
                end(terminal("truncated", "truncated", null, step >= maxSteps ? "max_steps" : "max_decisions"));
                return;
            }
            String seat = event.playerName();
            Posed posed;
            try {
                posed = mapper.pose(event, session.game(), seat);
            } catch (Unrepresentable e) {
                halt(e.cause);
                return;
            }
            if (posed.engineAnswer == null) {
                pending = posed;
                return;
            }
            event = session.select(posed.engineAnswer);
        }
    }

    private void halt(String cause) {
        end(terminal("halted", "halted", null, "engine_contract_failure:" + cause));
    }

    private void end(Map<String, Object> t) {
        terminal = t;
        pending = null;
        if (session != null) {
            session.finish();
        }
        GameRandom.installBoot();
    }

    /** Outcome and reason from player state (life, poison, library), never XMage's winner string. */
    private Map<String, Object> naturalTerminal() {
        Game game = session.game();
        boolean[] lost = new boolean[2];
        String reason = null;
        for (int k = 0; k < 2; k++) {
            Player p = game.getPlayer(seats.get(k));
            String seat = Requests.SEATS.get(k);
            if (p != null && p.hasLost()) {
                lost[k] = true;
                if (reason == null) {
                    if (p.getLife() <= 0) {
                        reason = seat + "_life_zero";
                    } else if (p.getCounters().getCount(mage.counters.CounterType.POISON) >= 10) {
                        reason = seat + "_poison";
                    } else if (p.getLibrary().size() == 0) {
                        reason = seat + "_library_empty";
                    } else {
                        reason = seat + "_lost";
                    }
                }
            }
        }
        if (lost[0] && !lost[1]) {
            return terminal("p1_win", "natural", "p1", reason);
        }
        if (lost[1] && !lost[0]) {
            return terminal("p0_win", "natural", "p0", reason);
        }
        if (lost[0]) {
            return terminal("draw", "natural", null, "both_lost");
        }
        return terminal("draw", "natural", null, "game_drawn");
    }

    private static Map<String, Object> terminal(String outcome, String classification, String winner, String reason) {
        Map<String, Object> t = new LinkedHashMap<>();
        t.put("outcome", outcome);
        t.put("classification", classification);
        t.put("winner", winner);
        t.put("reason", reason);
        return t;
    }
}
