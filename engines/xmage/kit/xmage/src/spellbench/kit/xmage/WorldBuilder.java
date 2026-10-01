package spellbench.kit.xmage;

import mage.MageObject;
import mage.Mana;
import mage.abilities.Ability;
import mage.abilities.ActivatedAbility;
import mage.abilities.Modes;
import mage.abilities.SpellAbility;
import mage.abilities.TriggeredAbility;
import mage.abilities.common.SimpleStaticAbility;
import mage.abilities.effects.ContinuousEffect;
import mage.abilities.effects.common.InfoEffect;
import mage.cards.Card;
import mage.cards.MeldCard;
import mage.cards.decks.Deck;
import mage.cards.repository.TokenInfo;
import mage.cards.repository.TokenRepository;
import mage.cards.repository.TokenType;
import mage.constants.AbilityType;
import mage.constants.PhaseStep;
import mage.constants.TurnPhase;
import mage.constants.Zone;
import mage.counters.Counter;
import mage.counters.CounterType;
import mage.game.Game;
import mage.game.GameOptions;
import mage.game.GameState;
import mage.game.combat.Combat;
import mage.game.events.ZoneChangeEvent;
import mage.game.mulligan.LondonMulligan;
import mage.game.permanent.Permanent;
import mage.game.permanent.PermanentCard;
import mage.game.permanent.PermanentImpl;
import mage.game.permanent.PermanentMeld;
import mage.game.permanent.PermanentToken;
import mage.game.permanent.token.Token;
import mage.game.stack.Spell;
import mage.game.stack.StackAbility;
import mage.game.stack.StackObject;
import mage.game.turn.Phase;
import mage.game.turn.Step;
import mage.game.turn.Turn;
import mage.game.turn.TurnMod;
import mage.player.cabt.CardResolver;
import mage.player.spellbench.observe.KitBridge;
import mage.players.Player;
import mage.players.PlayerImpl;
import mage.target.Target;
import mage.target.TargetAmount;
import spellbench.kit.core.Json;
import spellbench.kit.core.Sampler;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;

/**
 * Builds a world from the viewer's permitted inputs (design Section 3): the observation of the current decision, the
 * decklists of {@code game_start}, and one sample of the hidden zones. Ports mzbridge's event-free injection
 * (DraftZero, MIT: {@code StateInjector}) to v2 input: init() only, zones filled without events, the turn position
 * set by reflection, triggers, queued events and watcher history cleared. Visible objects take their UUIDs from the
 * id scope of their object id ({@link KitRandom#scopeObject}).
 */
public final class WorldBuilder {

    /** Creates the XMage player of one seat (the decider for the viewer, a puppet for the other seat). */
    public interface PlayerFactory {
        Player create(String seat);
    }

    /** What the world is built for (design Section 5.1). */
    public enum Mode {
        /** the observed window with the viewer holding priority */
        PRIORITY,
        /** the declare attackers step, before attackers are declared */
        ATTACK,
        /** the declare blockers step, attackers declared, before blocks */
        BLOCK,
        /** the observed snapshot, nothing resolved (current dialog) */
        SNAPSHOT,
        /** pregame (mulligan decisions) */
        PREGAME
    }

    public static final class Spec {
        public Map<String, Object> gameStart;
        public Map<String, Object> observation;
        public Sampler.Sample sample;
        public KitRandom random;
        public Mode mode = Mode.PRIORITY;
        public PlayerFactory viewerFactory;
        public PlayerFactory otherFactory;
        public int index;
        /** "first" or "regular" for a combat_damage observation; null: decide from the board */
        public String combatDamageStep;
    }

    static final List<String> SEATS = Arrays.asList("p0", "p1");
    private static final CardResolver RESOLVER = new CardResolver();
    private static volatile List<TokenInfo> tokens;
    private static final Map<String, CounterType> COUNTERS = new HashMap<>();

    private final Spec spec;
    private final World world;
    private final Game game;
    private final Map<String, Object> obs;
    private final Map<String, Map<String, Object>> playersObs = new LinkedHashMap<>();
    private final Ability fake = new SimpleStaticAbility(Zone.OUTSIDE, new InfoEffect("spellbench kit world injection"));
    /** object record -> created card */
    private final Map<Map<String, Object>, Card> cardOf = new HashMap<>();
    private final Map<String, List<Card>> handCards = new HashMap<>();
    private final Map<String, List<Card>> libraryCards = new HashMap<>();

    private WorldBuilder(Spec spec) {
        this.spec = spec;
        this.obs = spec.observation;
        this.game = new KitDuel();
        this.world = new World(game, Json.str(obs, "viewer"), spec.index, spec.random);
        for (Object p : Json.arr(obs, "players")) {
            Map<String, Object> pm = Json.obj(p);
            playersObs.put(Json.str(pm, "seat"), pm);
        }
    }

    public static World build(Spec spec) {
        WorldBuilder b = new WorldBuilder(spec);
        b.run();
        return b.world;
    }

    private void flag(String f) {
        if (!world.flags.contains(f)) {
            world.flags.add(f);
        }
    }

    private Player player(String seat) {
        return game.getPlayer(world.player(seat));
    }

    // =============================================================================================

    private void run() {
        KitRandom random = spec.random;
        world.sample = spec.sample.json();
        world.flags.addAll(spec.sample.flags);

        // ---- 1. players (UUIDs stable across worlds: one id scope per seat) and cards
        KitDuel.KitMatch match;
        random.scopeWorld("game");
        match = new KitDuel.KitMatch();
        for (String seat : SEATS) {
            random.scopeObject("player:" + seat);
            Player p = seat.equals(world.viewer) ? spec.viewerFactory.create(seat) : spec.otherFactory.create(seat);
            created.put(seat, p);
            world.seatPlayer.put(seat, p.getId());
            random.assignSeat(p.getId(), seat);
        }
        Map<String, List<Card>> decks = new LinkedHashMap<>();
        for (String seat : SEATS) {
            decks.put(seat, createCards(seat));
        }
        for (String seat : SEATS) {
            Player p = findCreated(seat);
            Deck deck = new Deck();
            deck.getCards().addAll(decks.get(seat));
            game.loadCards(new LinkedHashSet<>(decks.get(seat)), p.getId());
            game.addPlayer(p, deck);
            match.add(p, deck);
        }
        random.scopeWorld("init");
        GameOptions options = new GameOptions();
        options.testMode = true;
        options.skipInitShuffling = true;
        options.stopOnTurn = 1;
        options.stopAtStep = PhaseStep.UNTAP;
        game.setGameOptions(options);
        String startingSeat = startingSeat();
        game.setStartingPlayerId(world.player(startingSeat));
        game.start(world.player(startingSeat));
        if (game.checkIfGameIsOver()) {
            throw new IllegalStateException("world ended during init()");
        }
        for (String seat : SEATS) {
            Player p = player(seat);
            for (Card c : new ArrayList<>(p.getHand().getCards(game))) {
                p.getHand().remove(c);
            }
            p.getLibrary().clear();
        }

        // ---- 2. zones without events
        random.scopeWorld("inject");
        for (String seat : SEATS) {
            injectZones(seat);
        }
        for (String seat : SEATS) {
            injectBattlefield(seat);
        }
        for (String seat : SEATS) {
            attach(seat);
        }

        // ---- 3. players' public state and the turn position
        String active = Json.str(obs, "active_seat");
        if (active == null) {
            active = startingSeat;
        }
        long turn = Json.num(obs, "turn", 0);
        String phaseStep = Json.str(obs, "phase_step");
        boolean pregame = "pregame".equals(phaseStep) || spec.mode == Mode.PREGAME;
        for (String seat : SEATS) {
            playerState(seat);
        }
        if (!pregame) {
            positionTurn(active, (int) turn, phaseStep, startingSeat);
            combat(active, phaseStep);
            stack();
        }

        // ---- 4. hygiene
        game.getState().getTurnMods().clear();
        if (!pregame && turn == 1 && active.equals(startingSeat) && beforeDraw(phaseStep)) {
            game.getState().getTurnMods().add(new TurnMod(world.player(startingSeat)).withSkipStep(PhaseStep.DRAW));
        }
        if (!Json.arr(obs, "pending_triggers").isEmpty()) {
            flag("approximate:pending_triggers_dropped");
        }
        game.getState().clearTriggeredAbilities();
        ((List<?>) Reflect.get(GameState.class, game.getState(), "simultaneousEvents")).clear();
        game.getState().resetWatchers();
        flag("approximate:watchers_reset");
        game.applyEffects();
        game.getOptions().stopOnTurn = null;
        random.scopeWorld("play");
    }

    private final Map<String, Player> created = new HashMap<>();

    private Player findCreated(String seat) {
        Player p = created.get(seat);
        if (p == null) {
            throw new IllegalStateException("player " + seat + " not created");
        }
        return p;
    }

    private String startingSeat() {
        Map<String, Object> rules = Json.obj(spec.gameStart, "rules");
        String s = rules == null ? null : Json.str(rules, "starting_seat");
        return s == null ? "p0" : s;
    }

    private static boolean beforeDraw(String phaseStep) {
        return "untap".equals(phaseStep) || "upkeep".equals(phaseStep);
    }

    // =============================================================================================
    // cards

    private Card newCard(String name, UUID ownerId) {
        try {
            return RESOLVER.resolve(name).createCard(ownerId);
        } catch (RuntimeException e) {
            throw new IllegalStateException("cannot create card '" + name + "': " + e, e);
        }
    }

    /** Every card a seat owns in this world, each created under its id scope. */
    private List<Card> createCards(String seat) {
        KitRandom random = spec.random;
        UUID owner = world.player(seat);
        List<Card> out = new ArrayList<>();
        Map<String, Object> pm = playersObs.get(seat);
        Sampler.SeatSample ss = spec.sample.seats.get(seat);
        List<Map<String, Object>> records = new ArrayList<>();
        for (Map<String, Object> pmAny : playersObs.values()) {
            for (Object o : Json.arr(pmAny, "battlefield")) {
                records.add(Json.obj(o));
            }
        }
        for (String zone : new String[]{"hand", "graveyard", "exile"}) {
            for (Object o : Json.arr(pm, zone)) {
                records.add(Json.obj(o));
            }
        }
        for (Object o : Json.arr(obs, "stack")) {
            Map<String, Object> e = Json.obj(o);
            if ("spell".equals(Json.str(e, "stack_kind"))) {
                records.add(e);
            }
        }
        if (!Json.arr(pm, "command").isEmpty()) {
            flag("unsupported:command_zone:" + seat);
        }
        for (Map<String, Object> rec : records) {
            if (!seat.equals(Json.str(rec, "owner_seat")) || Json.bool(rec, "token")) {
                continue;
            }
            if (Json.bool(rec, "copy")) {
                flag("approximate:nontoken_copy");
            }
            String name = Json.str(rec, "card_name");
            String id = Json.str(rec, "object_id");
            if (name == null) {
                name = ss.faceDown.get(id);
                flag("approximate:face_down_identity");
                if (name == null) {
                    flag("unsupported:face_down_unsampled");
                    continue;
                }
            }
            random.scopeObject(id);
            Card c = newCard(name, owner);
            cardOf.put(rec, c);
            out.add(c);
        }
        // hidden: the other seat's hand, then the library, top first
        List<Card> hand = new ArrayList<>();
        int hidden = 0;
        for (Sampler.Slot slot : ss.hand) {
            if (slot.name == null) {
                flag("unsupported:hidden_slot_without_name");
                continue;
            }
            if (slot.objectId != null) {
                random.scopeObject(slot.objectId);
            } else {
                random.scopeWorld("hidden:" + seat + ":" + hidden++);
            }
            Card c = newCard(slot.name, owner);
            if (slot.objectId != null) {
                bindCard(slot.objectId, c);
            }
            if (slot.pinned) {
                world.knownHandNames.add(slot.name);
            }
            hand.add(c);
            out.add(c);
        }
        handCards.put(seat, hand);
        List<Card> library = new ArrayList<>();
        for (Sampler.Slot slot : ss.library) {
            if (slot.name == null) {
                flag("unsupported:hidden_slot_without_name");
                continue;
            }
            if (slot.objectId != null) {
                random.scopeObject(slot.objectId);
            } else {
                random.scopeWorld("hidden:" + seat + ":" + hidden++);
            }
            Card c = newCard(slot.name, owner);
            if (slot.objectId != null) {
                bindCard(slot.objectId, c);
            }
            if (slot.pinned) {
                world.pinnedLibrary.add(c.getId());
            }
            library.add(c);
            out.add(c);
        }
        libraryCards.put(seat, library);
        return out;
    }

    private void bindCard(String objectId, Card c) {
        world.bind(objectId, c.getId());
        for (UUID part : partIds(c)) {
            world.alias(part, objectId);
        }
    }

    static List<UUID> partIds(Card c) {
        List<UUID> out = new ArrayList<>();
        if (c instanceof mage.cards.SplitCard) {
            out.add(((mage.cards.SplitCard) c).getLeftHalfCard().getId());
            out.add(((mage.cards.SplitCard) c).getRightHalfCard().getId());
        } else if (c instanceof mage.cards.DoubleFacedCard) {
            out.add(((mage.cards.DoubleFacedCard) c).getLeftHalfCard().getId());
            out.add(((mage.cards.DoubleFacedCard) c).getRightHalfCard().getId());
        } else if (c instanceof mage.cards.CardWithSpellOption) {
            out.add(((mage.cards.CardWithSpellOption) c).getSpellCard().getId());
        }
        out.remove(c.getId());
        return out;
    }

    // =============================================================================================
    // zones

    private void injectZones(String seat) {
        Player p = player(seat);
        Map<String, Object> pm = playersObs.get(seat);
        if (seat.equals(world.viewer)) {
            for (Object o : Json.arr(pm, "hand")) {
                Card c = cardOf.get(Json.obj(o));
                if (c == null) {
                    continue;
                }
                c.setZone(Zone.HAND, game);
                p.getHand().add(c);
                bindCard(Json.str(Json.obj(o), "object_id"), c);
            }
        } else {
            for (Card c : handCards.get(seat)) {
                c.setZone(Zone.HAND, game);
                p.getHand().add(c);
            }
        }
        for (Object o : Json.arr(pm, "graveyard")) {
            Card c = cardOf.get(Json.obj(o));
            if (c == null) {
                continue;
            }
            c.setZone(Zone.GRAVEYARD, game);
            p.getGraveyard().add(c);
            bindCard(Json.str(Json.obj(o), "object_id"), c);
        }
        for (Object o : Json.arr(pm, "exile")) {
            Map<String, Object> rec = Json.obj(o);
            Card c = cardOf.get(rec);
            if (c == null) {
                continue;
            }
            c.setZone(Zone.EXILED, game);
            game.getExile().add(c);
            if (Json.bool(rec, "face_down")) {
                c.setFaceDown(true, game);
            }
            bindCard(Json.str(rec, "object_id"), c);
        }
        for (Card c : libraryCards.get(seat)) {
            c.setZone(Zone.LIBRARY, game);
            p.getLibrary().putOnBottom(c, game);
        }
    }

    private void injectBattlefield(String seat) {
        Player controller = player(seat);
        for (Object o : Json.arr(playersObs.get(seat), "battlefield")) {
            Map<String, Object> rec = Json.obj(o);
            Map<String, Object> pm = Json.obj(rec, "permanent");
            String id = Json.str(rec, "object_id");
            Permanent perm;
            if (Json.bool(rec, "token")) {
                perm = putToken(controller, rec, id);
                if (perm == null) {
                    flag("unsupported:token:" + Json.str(rec, "card_name"));
                    continue;
                }
            } else {
                Card c = cardOf.get(rec);
                if (c == null) {
                    continue;
                }
                spec.random.scopeObject(id + ":permanent");
                putCardOntoBattlefield(c, controller, pm != null && Json.bool(pm, "tapped"));
                perm = game.getPermanent(c.getId());
                if (perm == null) {
                    flag("unsupported:did_not_enter:" + Json.str(rec, "card_name"));
                    continue;
                }
            }
            world.bind(id, perm.getId());
            if (Json.bool(rec, "face_down")) {
                perm.setFaceDown(true, game);
                flag("approximate:face_down_permanent");
            }
            decorate(perm, pm);
        }
    }

    /**
     * mzbridge's {@code putCardOntoBattlefield}: CardUtil.putCardOntoBattlefieldWithEffects without changing the
     * card's owner. No ENTERS_THE_BATTLEFIELD event; "enters with counters / tapped" replacements still apply (the
     * observed counters and tapped state are set afterwards).
     */
    private void putCardOntoBattlefield(Card card, Player controller, boolean tapped) {
        Ability source = fake.copy();
        source.setControllerId(controller.getId());
        source.setSourceId(card.getId());
        Card permCard = mage.util.CardUtil.getDefaultCardSideForBattlefield(game, card);
        permCard.setZone(Zone.BATTLEFIELD, game);
        PermanentCard permanent = permCard instanceof MeldCard ? new PermanentMeld(permCard, controller.getId(), game)
                : new PermanentCard(permCard, controller.getId(), game);
        game.getContinuousEffects().setController(permanent.getId(), controller.getId());
        game.getPermanentsEntering().put(permanent.getId(), permanent);
        permCard.applyEnterWithCounters(permanent, source, game);
        permanent.entersBattlefield(source, game, Zone.OUTSIDE, false);
        game.addPermanent(permanent, game.getState().getNextPermanentOrderNumber());
        game.getPermanentsEntering().remove(permanent.getId());
        permanent.setTapped(tapped);
        for (ContinuousEffect effect : game.getState().getContinuousEffects().getLayeredEffects(game)) {
            Optional<Ability> ability = game.getState().getContinuousEffects().getLayeredEffectAbilities(effect)
                    .stream().findFirst();
            if (ability.isPresent() && permanent.getId().equals(ability.get().getSourceId())) {
                effect.init(ability.get(), game, controller.getId());
            }
        }
    }

    /** A token of a decklist-creatable class, matched on name and characteristics; null when none matches. */
    private Permanent putToken(Player controller, Map<String, Object> rec, String objectId) {
        String name = Json.str(rec, "card_name");
        Map<String, Object> ch = Json.obj(rec, "characteristics");
        spec.random.scopeWorld("token-probe"); // probe instances are cached across worlds: never in an object scope
        Token token = resolveToken(name, ch);
        if (token == null) {
            return null;
        }
        spec.random.scopeObject(objectId);
        Ability src = fake.copy();
        src.setControllerId(controller.getId());
        src.setSourceId(token.getId());
        PermanentToken pm = new PermanentToken(token, controller.getId(), game);
        game.getState().addCard(pm);
        game.getPermanentsEntering().put(pm.getId(), pm);
        pm.updateZoneChangeCounter(game, new ZoneChangeEvent(pm, null, controller.getId(), Zone.OUTSIDE, Zone.BATTLEFIELD));
        game.setScopeRelevant(true);
        pm.entersBattlefield(src, game, Zone.OUTSIDE, false);
        game.setScopeRelevant(false);
        game.addPermanent(pm, game.getState().getNextPermanentOrderNumber());
        pm.setZone(Zone.BATTLEFIELD, game);
        game.getPermanentsEntering().remove(pm.getId());
        return pm;
    }

    private static final Map<String, List<Token>> TOKEN_CACHE = new HashMap<>();

    private Token resolveToken(String name, Map<String, Object> ch) {
        if (name == null) {
            return null;
        }
        List<Token> candidates;
        synchronized (TOKEN_CACHE) {
            candidates = TOKEN_CACHE.get(name);
        }
        if (candidates == null) {
            candidates = new ArrayList<>();
            if (tokens == null) {
                tokens = TokenRepository.instance.getByType(TokenType.TOKEN);
            }
            List<String> classes = new ArrayList<>();
            for (TokenInfo t : tokens) {
                String cls = t.getFullClassFileName();
                if (!classes.contains(cls)) {
                    classes.add(cls);
                }
            }
            Collections.sort(classes);
            for (String cls : classes) {
                try {
                    Token probe = (Token) Class.forName(cls).getConstructor().newInstance();
                    if (name.equals(probe.getName())) {
                        candidates.add(probe);
                    }
                } catch (ReflectiveOperationException | RuntimeException | LinkageError e) {
                    // a token class without a no-argument constructor cannot be a decklist token here
                }
            }
            synchronized (TOKEN_CACHE) {
                TOKEN_CACHE.put(name, candidates);
            }
        }
        for (Token t : candidates) {
            if (ch == null) {
                return t.copy();
            }
            Object pw = ch.get("power");
            Object th = ch.get("toughness");
            boolean ok = (pw == null || ((Number) pw).intValue() == t.getPower().getValue())
                    && (th == null || ((Number) th).intValue() == t.getToughness().getValue());
            if (ok) {
                return t.copy();
            }
        }
        if (!candidates.isEmpty()) {
            flag("approximate:token_characteristics:" + name);
            return candidates.get(0).copy();
        }
        return null;
    }

    private void decorate(Permanent perm, Map<String, Object> pm) {
        if (pm == null) {
            return;
        }
        perm.setTapped(Json.bool(pm, "tapped"));
        // counters: exactly the observed map (design 3.2 changes mzbridge's rule: unlisted types are removed)
        Map<String, Object> want = Json.obj(pm, "counters");
        for (Counter c : new ArrayList<>(perm.getCounters(game).values())) {
            perm.getCounters(game).removeCounter(c.getName(), c.getCount());
        }
        if (want != null) {
            for (Map.Entry<String, Object> e : want.entrySet()) {
                CounterType ct = counterType(e.getKey());
                int n = ((Number) e.getValue()).intValue();
                if (ct == null) {
                    flag("unsupported:counter:" + e.getKey());
                    continue;
                }
                if (n > 0) {
                    perm.getCounters(game).addCounter(ct.createInstance(n));
                }
            }
        }
        Reflect.set(PermanentImpl.class, perm, "damage", (int) Json.num(pm, "damage", 0));
        Reflect.set(PermanentImpl.class, perm, "controlledFromStartOfControllerTurn", !Json.bool(pm, "summoning_sick"));
        if (Json.bool(pm, "phased_out")) {
            Reflect.set(PermanentImpl.class, perm, "phasedIn", false);
        }
    }

    static synchronized CounterType counterType(String v2) {
        if (COUNTERS.isEmpty()) {
            for (CounterType ct : CounterType.values()) {
                String n = KitBridge.counter(ct.getName());
                if (n != null && !COUNTERS.containsKey(n)) {
                    COUNTERS.put(n, ct);
                }
            }
        }
        return COUNTERS.get(v2);
    }

    private void attach(String seat) {
        for (Object o : Json.arr(playersObs.get(seat), "battlefield")) {
            Map<String, Object> rec = Json.obj(o);
            Map<String, Object> pm = Json.obj(rec, "permanent");
            if (pm == null || pm.get("attached_to") == null) {
                continue;
            }
            UUID self = world.idToUuid.get(Json.str(rec, "object_id"));
            UUID host = targetUuid(Json.obj(pm, "attached_to"));
            if (self == null || host == null) {
                flag("approximate:attachment_unresolved");
                continue;
            }
            Ability src = fake.copy();
            src.setControllerId(world.player(seat));
            src.setSourceId(self);
            Permanent hostPerm = game.getPermanent(host);
            boolean ok;
            if (hostPerm != null) {
                ok = hostPerm.addAttachment(self, src, game);
            } else {
                Player hp = game.getPlayer(host);
                ok = hp != null && hp.addAttachment(self, src, game);
            }
            if (!ok) {
                flag("approximate:attachment_refused");
            }
        }
    }

    /** The world UUID of a v2 target reference ({"player": seat} or {"object": ref}), or null. */
    UUID targetUuid(Map<String, Object> t) {
        if (t == null) {
            return null;
        }
        if (t.get("player") != null) {
            return world.player((String) t.get("player"));
        }
        Map<String, Object> ref = Json.obj(t, "object");
        return ref == null ? null : world.idToUuid.get(Json.str(ref, "object_id"));
    }

    // =============================================================================================
    // players and the turn

    private void playerState(String seat) {
        Player p = player(seat);
        Map<String, Object> pm = playersObs.get(seat);
        p.initLife((int) Json.num(pm, "life", 20));
        p.resetLandsPlayed();
        for (int i = 0; i < Json.num(pm, "lands_played_this_turn", 0); i++) {
            p.incrementLandsPlayed();
        }
        Object poison = pm.get("poison");
        if (poison instanceof Number && ((Number) poison).intValue() > 0) {
            p.addCounters(CounterType.POISON.createInstance(((Number) poison).intValue()), p.getId(), fake, game);
        }
        Map<String, Object> pool = Json.obj(pm, "mana_pool");
        if (pool != null) {
            Mana m = new Mana();
            m.setWhite((int) Json.num(pool, "W", 0));
            m.setBlue((int) Json.num(pool, "U", 0));
            m.setBlack((int) Json.num(pool, "B", 0));
            m.setRed((int) Json.num(pool, "R", 0));
            m.setGreen((int) Json.num(pool, "G", 0));
            m.setColorless((int) Json.num(pool, "C", 0));
            if (m.count() > 0) {
                p.getManaPool().addMana(m, game, fake, true);
            }
        }
        // London mulligan bookkeeping (mulligans_taken)
        long taken = Json.num(pm, "mulligans_taken", 0);
        if (game.getMulligan() instanceof LondonMulligan) {
            @SuppressWarnings("unchecked")
            Map<UUID, Integer> start = (Map<UUID, Integer>) Reflect.get(LondonMulligan.class, game.getMulligan(), "startingHandSizes");
            @SuppressWarnings("unchecked")
            Map<UUID, Integer> open = (Map<UUID, Integer>) Reflect.get(LondonMulligan.class, game.getMulligan(), "openingHandSizes");
            start.put(p.getId(), 7);
            open.put(p.getId(), (int) (7 - taken));
        }
    }

    static PhaseStep step(String v2, String combatDamage) {
        switch (v2) {
            case "untap":
                return PhaseStep.UNTAP;
            case "upkeep":
                return PhaseStep.UPKEEP;
            case "draw":
                return PhaseStep.DRAW;
            case "precombat_main":
                return PhaseStep.PRECOMBAT_MAIN;
            case "beginning_of_combat":
                return PhaseStep.BEGIN_COMBAT;
            case "declare_attackers":
                return PhaseStep.DECLARE_ATTACKERS;
            case "declare_blockers":
                return PhaseStep.DECLARE_BLOCKERS;
            case "combat_damage":
                return "first".equals(combatDamage) ? PhaseStep.FIRST_COMBAT_DAMAGE : PhaseStep.COMBAT_DAMAGE;
            case "end_of_combat":
                return PhaseStep.END_COMBAT;
            case "postcombat_main":
                return PhaseStep.POSTCOMBAT_MAIN;
            case "end_step":
                return PhaseStep.END_TURN;
            case "cleanup":
                return PhaseStep.CLEANUP;
            default:
                throw new IllegalArgumentException("phase_step " + v2);
        }
    }

    static TurnPhase phaseOf(PhaseStep s) {
        switch (s) {
            case UNTAP:
            case UPKEEP:
            case DRAW:
                return TurnPhase.BEGINNING;
            case PRECOMBAT_MAIN:
                return TurnPhase.PRECOMBAT_MAIN;
            case BEGIN_COMBAT:
            case DECLARE_ATTACKERS:
            case DECLARE_BLOCKERS:
            case FIRST_COMBAT_DAMAGE:
            case COMBAT_DAMAGE:
            case END_COMBAT:
                return TurnPhase.COMBAT;
            case POSTCOMBAT_MAIN:
                return TurnPhase.POSTCOMBAT_MAIN;
            default:
                return TurnPhase.END;
        }
    }

    private void positionTurn(String active, int turn, String phaseStep, String startingSeat) {
        UUID activeId = world.player(active);
        game.getState().setTurnNum(turn);
        game.getState().setActivePlayerId(activeId);
        game.getState().setPlayerByOrderId(activeId);
        game.getState().getPlayerList().setCurrent(activeId);
        // v2 has one combat_damage step, XMage two: without a first or double striker in combat it is the regular
        // step; with one, the front's own history says which (Section 3.3), else the world is approximate
        String damage = "regular";
        if ("combat_damage".equals(phaseStep) && firstStrikerInCombat()) {
            damage = spec.combatDamageStep;
            if (damage == null) {
                flag("approximate:first_strike_step_unknown");
                damage = "first";
            } else {
                flag("own_history:first_strike_step:" + damage);
            }
        }
        PhaseStep target;
        Step.StepPart part;
        switch (spec.mode) {
            case ATTACK:
                target = PhaseStep.DECLARE_ATTACKERS;
                part = Step.StepPart.PRE;
                break;
            case BLOCK:
                target = PhaseStep.DECLARE_BLOCKERS;
                part = Step.StepPart.PRE;
                break;
            default:
                target = step(phaseStep, damage);
                part = Step.StepPart.PRIORITY;
        }
        TurnPhase phaseType = phaseOf(target);
        Turn t = game.getState().getTurn();
        Phase phase = t.getPhase(phaseType);
        if (phase == null) {
            throw new IllegalStateException("no phase " + phaseType);
        }
        @SuppressWarnings("unchecked")
        List<Step> steps = (List<Step>) Reflect.get(Phase.class, phase, "steps");
        Step step = null;
        for (Step s : steps) {
            if (s.getType() == target) {
                step = s;
            }
        }
        if (step == null) {
            throw new IllegalStateException("step " + target + " not in phase " + phaseType);
        }
        t.setPhase(phase);
        phase.setStep(step);
        Reflect.set(Step.class, step, "stepPart", part);
        Reflect.set(Phase.class, phase, "activePlayerId", activeId);
        for (String seat : SEATS) {
            Player p = player(seat);
            int want = seat.equals(startingSeat) ? (turn + 1) / 2 : turn / 2;
            for (int i = p.getTurns(); i < want; i++) {
                p.becomesActivePlayer();
            }
        }
        String prio = Json.str(obs, "priority_seat");
        if (spec.mode == Mode.PRIORITY) {
            prio = world.viewer;
        }
        game.getState().setPriorityPlayerId(world.player(prio == null ? active : prio));
        List<Object> passed = Json.arr(obs, "passed_seats");
        for (String seat : SEATS) {
            boolean p = spec.mode == Mode.PRIORITY && passed.contains(seat) && !seat.equals(world.viewer);
            Reflect.set(PlayerImpl.class, player(seat), "passed", p);
        }
    }

    private boolean firstStrikerInCombat() {
        for (Map<String, Object> pm : playersObs.values()) {
            for (Object o : Json.arr(pm, "battlefield")) {
                Map<String, Object> rec = Json.obj(o);
                Map<String, Object> perm = Json.obj(rec, "permanent");
                Map<String, Object> ch = Json.obj(rec, "characteristics");
                if (perm == null || ch == null || !(Json.bool(perm, "attacking") || Json.bool(perm, "blocking"))) {
                    continue;
                }
                List<Object> kw = Json.arr(ch, "keywords");
                if (kw.contains("first_strike") || kw.contains("double_strike")) {
                    return true;
                }
            }
        }
        return false;
    }

    private static final List<String> COMBAT_STEPS = Arrays.asList("beginning_of_combat", "declare_attackers",
            "declare_blockers", "combat_damage", "end_of_combat");

    private void combat(String active, String phaseStep) {
        if (!COMBAT_STEPS.contains(phaseStep) && spec.mode != Mode.ATTACK && spec.mode != Mode.BLOCK) {
            return;
        }
        UUID activeId = world.player(active);
        Combat combat = game.getCombat();
        combat.clear();
        combat.setAttacker(activeId);
        combat.setDefenders(game);
        if (spec.mode == Mode.ATTACK) {
            return;
        }
        Map<UUID, Boolean> tapped = new HashMap<>();
        boolean any = false;
        for (Object o : Json.arr(playersObs.get(active), "battlefield")) {
            Map<String, Object> rec = Json.obj(o);
            Map<String, Object> pm = Json.obj(rec, "permanent");
            if (pm == null || !Json.bool(pm, "attacking")) {
                continue;
            }
            UUID atk = world.idToUuid.get(Json.str(rec, "object_id"));
            UUID def = targetUuid(Json.obj(pm, "attack_target"));
            if (atk == null) {
                continue;
            }
            if (def == null) {
                def = world.player(Sampler_other(active));
                flag("approximate:attack_target_left");
            }
            Permanent p = game.getPermanent(atk);
            tapped.put(atk, p.isTapped());
            p.setTapped(false);
            if (!combat.declareAttacker(atk, def, activeId, game)) {
                flag("approximate:attacker_refused");
            }
            any = true;
        }
        if (any) {
            game.getTurn().setDeclareAttackersStepStarted(true);
        }
        boolean blocks = false;
        String defender = Sampler_other(active);
        for (Object o : Json.arr(playersObs.get(defender), "battlefield")) {
            Map<String, Object> rec = Json.obj(o);
            Map<String, Object> pm = Json.obj(rec, "permanent");
            if (pm == null || !Json.bool(pm, "blocking")) {
                continue;
            }
            UUID blk = world.idToUuid.get(Json.str(rec, "object_id"));
            Player dp = player(defender);
            for (Object a : Json.arr(pm, "blocked_attackers")) {
                UUID atk = world.idToUuid.get(Json.str(Json.obj(a), "object_id"));
                if (blk != null && atk != null) {
                    dp.declareBlocker(dp.getId(), blk, atk, game);
                    blocks = true;
                }
            }
            if (Json.arr(pm, "blocked_attackers").isEmpty()) {
                flag("approximate:blocker_without_attackers");
            }
        }
        if (blocks || "combat_damage".equals(phaseStep) || "end_of_combat".equals(phaseStep)) {
            if (blocks) {
                combat.acceptBlockers(game);
            }
            if (!"declare_blockers".equals(phaseStep) || blocks) {
                flag("approximate:blocked_status_from_observation");
            }
        }
        for (Map.Entry<UUID, Boolean> e : tapped.entrySet()) {
            game.getPermanent(e.getKey()).setTapped(e.getValue());
        }
    }

    private static String Sampler_other(String seat) {
        return "p0".equals(seat) ? "p1" : "p0";
    }

    // =============================================================================================
    // the stack (bottom to top)

    private void stack() {
        List<Object> entries = Json.arr(obs, "stack");
        for (Object o : entries) {
            Map<String, Object> e = Json.obj(o);
            String kind = Json.str(e, "stack_kind");
            String id = Json.str(e, "object_id");
            UUID controller = world.player(Json.str(e, "controller_seat"));
            spec.random.scopeObject(id + ":stack");
            if ("spell".equals(kind)) {
                Card c = cardOf.get(e);
                if (c == null) {
                    flag("unsupported:stack_spell_card");
                    placeholder(e, controller);
                    continue;
                }
                Player p = game.getPlayer(controller);
                c.setZone(Zone.HAND, game);
                p.getHand().add(c);
                SpellAbility sa = c.getSpellAbility();
                if (sa == null || c.isLand(game)) {
                    flag("unsupported:stack_spell_not_castable");
                    p.getHand().remove(c);
                    placeholder(e, controller);
                    continue;
                }
                c.cast(game, Zone.HAND, sa, controller);
                Spell spell = game.getStack().getSpell(c.getId());
                if (spell == null) {
                    flag("unsupported:stack_cast_failed");
                    placeholder(e, controller);
                    continue;
                }
                world.bind(id, spell.getId());
                world.alias(c.getId(), id);
                choices(spell.getSpellAbility(), e);
            } else {
                Ability ability = stackAbilitySource(e);
                if (ability == null) {
                    placeholder(e, controller);
                    continue;
                }
                Ability copy = ability.copy();
                copy.newId();
                copy.setControllerId(controller);
                StackAbility sa = new StackAbility(copy, controller);
                game.getStack().push(game, sa);
                world.bind(id, sa.getId());
                choices(copy, e);
            }
        }
    }

    /**
     * The ability a stack entry names: supported only when its source (by reference, or by lineage on its name when
     * the source has left) has exactly one ability of the entry's kind (design Section 3.3, stack ability identity).
     */
    private Ability stackAbilitySource(Map<String, Object> e) {
        boolean triggered = "triggered_ability".equals(Json.str(e, "stack_kind"));
        MageObject source = null;
        Map<String, Object> ref = Json.obj(e, "source");
        if (ref != null) {
            UUID u = world.idToUuid.get(Json.str(ref, "object_id"));
            source = u == null ? null : game.getObject(u);
        }
        if (source == null) {
            // lineage on the name: the source left (Burnished Hart sacrificed itself); a public card of that name
            String name = Json.str(e, "card_name");
            List<MageObject> found = new ArrayList<>();
            for (Map.Entry<String, UUID> m : world.idToUuid.entrySet()) {
                MageObject mo = game.getObject(m.getValue());
                if (mo != null && name != null && name.equals(mo.getName()) && !found.contains(mo)
                        && game.getState().getZone(mo.getId()) != Zone.STACK) {
                    found.add(mo);
                }
            }
            if (found.isEmpty()) {
                Card c = null;
                try {
                    c = RESOLVER.resolve(name).createCard(world.player(Json.str(e, "controller_seat")));
                } catch (RuntimeException ex) {
                    // no such card
                }
                if (c != null) {
                    found.add(c);
                    flag("approximate:stack_source_recreated");
                }
            }
            if (found.size() != 1) {
                flag("approximate:stack_source_ambiguous");
                if (found.isEmpty()) {
                    return null;
                }
            }
            source = found.get(0);
            flag("approximate:stack_source_by_lineage");
        }
        List<Ability> ofKind = new ArrayList<>();
        Iterable<Ability> abilities = source instanceof Permanent ? ((Permanent) source).getAbilities(game)
                : (source instanceof Card ? ((Card) source).getAbilities(game) : source.getAbilities());
        for (Ability a : abilities) {
            if (triggered ? a instanceof TriggeredAbility
                    : (a instanceof ActivatedAbility && a.getAbilityType() == AbilityType.ACTIVATED_NONMANA)) {
                ofKind.add(a);
            }
        }
        if (ofKind.size() != 1) {
            flag("approximate:stack_ability_identity");
            return null;
        }
        return ofKind.get(0);
    }

    /** A stack object the world cannot rebuild: kept for the stack's shape, flagged, never resolved in search. */
    private void placeholder(Map<String, Object> e, UUID controller) {
        Ability info = new SimpleStaticAbility(Zone.ALL, new InfoEffect("spellbench kit placeholder"));
        info.setControllerId(controller);
        info.newId();
        StackAbility sa = new StackAbility(info, controller);
        game.getStack().push(game, sa);
        world.bind(Json.str(e, "object_id"), sa.getId());
        KitContext.horizon.add(sa.getId());
        flag("approximate:stack_placeholder");
    }

    /** Modes, targets, divided amounts and X of a rebuilt stack object, as observed. */
    private void choices(Ability ability, Map<String, Object> e) {
        Modes modes = ability.getModes();
        List<Object> observedModes = Json.arr(e, "modes");
        if (e.get("modes") != null && modes.size() > 1) {
            modes.clearSelectedModes();
            List<mage.abilities.Mode> all = new ArrayList<>(modes.values());
            for (Object m : observedModes) {
                int i = ((Number) m).intValue();
                if (i < all.size()) {
                    modes.addSelectedMode(all.get(i).getId());
                }
            }
        }
        List<Object> targets = Json.arr(e, "targets");
        List<Object> divided = Json.arr(e, "divided");
        int ti = 0;
        int di = 0;
        for (UUID modeId : modes.getSelectedModes()) {
            mage.abilities.Mode mode = modes.get(modeId);
            if (mode == null) {
                continue;
            }
            for (Target t : mode.getTargets()) {
                t.clearChosen();
                int want = Math.max(1, Math.min(t.getMaxNumberOfTargets(), targets.size() - ti));
                for (int k = 0; k < want && ti < targets.size(); k++) {
                    Object to = targets.get(ti++);
                    UUID u = to == null ? null : targetUuid(Json.obj(to));
                    if (u == null) {
                        flag("approximate:stack_target_left");
                        continue;
                    }
                    if (t instanceof TargetAmount && di < divided.size()) {
                        t.addTarget(u, ((Number) divided.get(di++)).intValue(), ability, game, true);
                    } else {
                        t.addTarget(u, ability, game, true);
                    }
                }
            }
        }
        if (ti < targets.size()) {
            flag("approximate:stack_targets_unplaced");
        }
        Object x = e.get("x_value");
        if (x instanceof Number) {
            ability.setCostsTag("X", ((Number) x).intValue());
        }
    }
}
