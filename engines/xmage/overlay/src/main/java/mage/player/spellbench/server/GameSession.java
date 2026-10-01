package mage.player.spellbench.server;

import mage.cards.Card;
import mage.cards.decks.Deck;
import mage.game.Game;
import mage.game.GameOptions;
import mage.player.cabt.CabtDeckFactory;
import mage.player.cabt.CardResolver;
import mage.player.spellbench.decide.Seats;
import mage.player.spellbench.decide.Exchange;
import mage.player.spellbench.rng.GameRandom;
import mage.players.Player;

import java.io.FileOutputStream;
import java.io.IOException;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

/**
 * One v2 game on XMage (design draft Section 3.2): the X1 stream router installed before any object of the
 * game exists, both seats as {@code decide.SeatPlayer}s whose callbacks pose protocol v2 decisions (task X4), the
 * starting player host-assigned, and the terminal derived from player state, never from XMage's winner string.
 * <p>
 * The game runs on its own thread; {@link Exchange} parks it at each posed decision. The counters ({@code step},
 * {@code decision_count} with groups and rewinds) are the exchange's.
 */
final class GameSession {

    final String gameId;
    private final Seats seats;
    long step;           // the pending decision's binding step = the answered decisions so far
    long decisionCount;  // completed groups that count (Section 8)
    Exchange.Outcome pending;
    Map<String, Object> terminal; // outcome, classification, winner, reason; null while the game runs

    private GameSession(String gameId, Seats seats) {
        this.gameId = gameId;
        this.seats = seats;
    }

    /**
     * Builds the game. Card classes of both decks are initialized under the boot router first, so class
     * initializers never draw from this game's streams (X1); then the game router is installed and every object of
     * the game is created under it, in a fixed order.
     */
    static GameSession create(Requests.Reset reset, List<CabtDeckFactory.Entry> deck0,
                              List<CabtDeckFactory.Entry> deck1, CardResolver resolver) {
        mage.player.spellbench.ManaCostCache.restore(); // the parsed-cost cache of a fresh process (X5)
        GameRandom.installBoot();
        resolver.buildDeck(UUID.nameUUIDFromBytes(new byte[]{0}), deck0);
        resolver.buildDeck(UUID.nameUUIDFromBytes(new byte[]{1}), deck1);
        GameRandom router = GameRandom.install(reset.gameSecret);
        Seats seats = Seats.create();
        addPlayer(seats.game, seats.player(0), resolver.buildDeck(seats.player(0).getId(), deck0));
        addPlayer(seats.game, seats.player(1), resolver.buildDeck(seats.player(1).getId(), deck1));
        seats.game.setGameOptions(new GameOptions());
        router.assignSeat(seats.player(0).getId(), "p0");
        router.assignSeat(seats.player(1).getId(), "p1");
        seats.game.setStartingPlayerId(seats.player(Requests.SEATS.indexOf(reset.rules.startingSeat)).getId());
        seats.connect(reset.gameSecret, EngineProfile.observationFlags(), reset.maxSteps, reset.maxDecisions,
                reset.rules.cardNameDomain, "none".equals(reset.rules.mulligan));
        return new GameSession(reset.gameId, seats);
    }

    private static void addPlayer(Game game, Player player, List<Card> cards) {
        Deck deck = new Deck();
        deck.getCards().addAll(cards);
        game.loadCards(deck.getCards(), player.getId());
        game.addPlayer(player, deck);
    }

    /** A game that failed while being built: already over, halted with {@code cause}. */
    static GameSession halted(String gameId, String cause) {
        GameSession g = new GameSession(gameId, null);
        g.terminal = terminal("halted", "halted", null, "engine_contract_failure:" + cause);
        GameRandom.installBoot();
        return g;
    }

    /** Runs the game to its first decision or its end. */
    void start() {
        Game game = seats.game;
        UUID first = seats.player(0).getId();
        handle(seats.exchange.start(() -> game.start(first)));
    }

    /** Applies a validated candidate of the pending decision and runs to the next decision or the end. */
    void answer(int candidateId) {
        pending = null;
        handle(seats.exchange.answer(candidateId));
    }

    private void handle(Exchange.Outcome outcome) {
        step = seats.exchange.step();
        decisionCount = seats.exchange.decisionCount();
        if (outcome.seatDecision != null) {
            pending = outcome;
            return;
        }
        pending = null;
        terminal = outcome.gameOver ? naturalTerminal() : outcome.terminal;
        seats.exchange.close();
        GameRandom.installBoot();
        report();
    }

    /**
     * Per-game mapping counters for the X4 evidence: stderr, and, when SPELLBENCH_XMAGE_STATS names a directory, one
     * JSON line per game in {@code stats-<process id>.jsonl} there (one file per engine process: concurrent appends
     * to one file can interleave). Engine-side only; never sent to agents.
     */
    private void report() {
        Map<String, Object> line = new LinkedHashMap<>();
        line.put("game_id", gameId);
        line.put("reason", terminal.get("reason"));
        line.put("outcome", terminal.get("outcome"));
        line.put("step_count", step);
        line.put("decision_count", decisionCount);
        Map<String, Object> counts = new LinkedHashMap<>();
        for (Map.Entry<String, Long> e : seats.exchange.stats().snapshot().entrySet()) {
            counts.put(e.getKey(), e.getValue());
        }
        line.put("stats", counts);
        byte[] bytes = StrictJson.canonical(line);
        System.err.println("x4-stats " + new String(bytes, StandardCharsets.UTF_8));
        String dir = System.getenv("SPELLBENCH_XMAGE_STATS");
        if (dir != null && !dir.isEmpty() && new java.io.File(dir).isDirectory()) {
            String pid = java.lang.management.ManagementFactory.getRuntimeMXBean().getName().split("@")[0];
            try (OutputStream out = new FileOutputStream(new java.io.File(dir, "stats-" + pid + ".jsonl"), true)) {
                out.write(bytes);
                out.write('\n');
            } catch (IOException e) {
                System.err.println("xmage-spellbench: cannot append stats: " + e);
            }
        }
    }

    /** Outcome and reason from player state (life, poison, library), never XMage's winner string. */
    private Map<String, Object> naturalTerminal() {
        Game game = seats.game;
        boolean[] lost = new boolean[2];
        String reason = null;
        for (int k = 0; k < 2; k++) {
            Player p = game.getPlayer(seats.player(k).getId());
            String seat = Requests.SEATS.get(k);
            if (p != null && p.hasLost()) {
                lost[k] = true;
                if (reason == null) {
                    if (p.getLife() <= 0) {
                        reason = seat + "_life_zero";
                    } else if (p.getCountersCount(mage.counters.CounterType.POISON) >= 10) {
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
