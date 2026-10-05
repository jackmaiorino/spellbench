package spellbench.kit.xmage;

import mage.cards.*;
import mage.constants.*;
import mage.game.*;
import mage.players.Player;
import spellbench.kit.core.Json;
import spellbench.models.jack.OriginalCallbackPlayer;
import spellbench.models.jack.OriginalNeuralSelection;

import java.lang.reflect.Proxy;
import java.util.*;

/** Checks actual private constructors and player-state transfer without a card database or native game. */
public final class JackPlayerBootstrapCheck {
    static void require(boolean ok, String message) { if (!ok) throw new AssertionError(message); }
    static void refused(Runnable work) {
        try { work.run(); } catch (IllegalArgumentException expected) { return; }
        throw new AssertionError("invalid bootstrap accepted");
    }
    static final class MetadataCard extends CardImpl {
        MetadataCard(UUID owner, String name) {
            super(owner, new CardSetInfo(name, "META", "1", Rarity.COMMON), new CardType[]{CardType.LAND}, "");
        }
        MetadataCard(MetadataCard card) { super(card); }
        @Override public MetadataCard copy() { return new MetadataCard(this); }
    }
    static final class Root {
        final KitMad old = new KitMad("p0", 10);
        final Puppet other = new Puppet("p1");
        final GameState state = new GameState();
        final Map<UUID, Card> cards = new HashMap<>();
        boolean simulation;
        final Game game = (Game) Proxy.newProxyInstance(Game.class.getClassLoader(), new Class<?>[]{Game.class}, (o,m,a) -> {
            switch (m.getName()) {
                case "getPlayer": return state.getPlayers().get(a[0]);
                case "getPlayers": return state.getPlayers();
                case "getState": return state;
                case "getCard": case "getObject": return cards.get(a[0]);
                case "getPermanent": return null;
                case "isSimulation": return simulation;
                case "getId": return new UUID(0, 41);
                case "getZone": return state.getZone((UUID) a[0]);
                case "setZone": state.setZone((UUID) a[0], (Zone) a[1]); return null;
                default: throw new AssertionError("unexpected bootstrap read: " + m.getName());
            }
        });
        final World world = new World(game, "p0", 0, null);
        Root() {
            state.getPlayers().addPlayer(old); state.getPlayers().addPlayer(other);
            world.seatPlayer.put("p0", old.getId()); world.seatPlayer.put("p1", other.getId());
            Card hand = new MetadataCard(old.getId(), "Forest"); cards.put(hand.getId(), hand); old.getHand().add(hand);
            Card grave = new MetadataCard(old.getId(), "Island"); cards.put(grave.getId(), grave); old.getGraveyard().add(grave);
            Card library = new MetadataCard(old.getId(), "Mountain"); cards.put(library.getId(), library);
            old.getLibrary().putOnTop(library, game);
            old.initLife(13); old.incrementLandsPlayed();
        }
    }
    static final class Backend implements OriginalNeuralSelection.Model {
        int calls; float[] features; boolean closed;
        public String callbackSourceSha256() { return OriginalCallbackPlayer.SOURCE_SHA256; }
        public String profile() { return OriginalNeuralSelection.GREEDY; }
        public long seed() { return 27; }
        public OriginalNeuralSelection.Prediction score(OriginalNeuralSelection.Request r, double seconds) {
            throw new AssertionError("bootstrap entered policy inference");
        }
        public OriginalNeuralSelection.MulliganPrediction mulligan(float[] f, double seconds) {
            calls++; features=f; return new OriginalNeuralSelection.MulliganPrediction("keep-mull-q", 1, 1);
        }
        public void close() { closed=true; }
    }
    public static void main(String[] args) {
        WorldBuilder.Spec supplied = new WorldBuilder.Spec(); supplied.observation = Json.map("viewer", "p0");
        supplied.viewerFactory = seat -> new KitMad(seat, 10);
        refused(() -> JackPlayerBootstrap.build(supplied));
        Map<String,Object> observed = Json.map("players", Arrays.asList(Json.map("seat", "p0", "mulligans_taken", 3L)));
        require(JackPlayerBootstrap.observedMulligans(observed, "p0") == 3, "observed count changed");
        observed = Json.map("players", Arrays.asList(Json.map("seat", "p0", "mulligans_taken", 3)));
        require(JackPlayerBootstrap.observedMulligans(observed, "p0") == 3, "engine integer count refused");
        for (Object bad : new Object[]{-1L, 8L, 3.0, "3", null, Boolean.TRUE}) {
            Map<String,Object> input = Json.map("players", Arrays.asList(Json.map("seat", "p0", "mulligans_taken", bad)));
            refused(() -> JackPlayerBootstrap.observedMulligans(input, "p0"));
        }
        refused(() -> JackPlayerBootstrap.observedMulligans(Json.map("players", Arrays.asList()), "p0"));
        Map<String,Object> duplicate = Json.map("players", Arrays.asList(Json.map("seat", "p0", "mulligans_taken", 1L),
                Json.map("seat", "p0", "mulligans_taken", 1L)));
        refused(() -> JackPlayerBootstrap.observedMulligans(duplicate, "p0"));
        Root root = new Root();
        Set<UUID> hand = new LinkedHashSet<>(root.old.getHand());
        Set<UUID> grave = new LinkedHashSet<>(root.old.getGraveyard());
        List<UUID> library = new ArrayList<>(root.old.getLibrary().getCardList());
        JackPlayerBootstrap.replaceViewer(root.world, 3);
        require(root.world.viewerPlayer().getClass() == OriginalCallbackPlayer.class, "setup policy remained installed");
        OriginalCallbackPlayer player = (OriginalCallbackPlayer) root.world.viewerPlayer();
        require(player.getId().equals(root.old.getId()) && player.getLife() == 13 && player.getLandsPlayed() == 1,
                "initialized identity/life/land state changed");
        require(player.getHand().equals(hand) && player.getGraveyard().equals(grave), "initialized zones changed");
        require(player.getLibrary().getCardList().equals(library), "initialized library changed");
        require(player.getManaPool() != root.old.getManaPool(), "mutable mana pool shared with setup player");
        root.old.getHand().clear(); root.old.getGraveyard().clear(); root.old.getLibrary().clear(); root.old.initLife(20);
        require(player.getHand().equals(hand) && player.getGraveyard().equals(grave) && player.getLife() == 13,
                "bootstrap retains mutable setup player state");
        require(player.getLibrary().getCardList().equals(library), "bootstrap retains mutable setup library");
        refused(() -> player.chooseMulligan(root.game));
        Backend backend = new Backend();
        OriginalNeuralSelection.Session session = new OriginalNeuralSelection.Session(backend, backend.profile(), backend.seed(), () -> 10);
        player.bindOriginalWorld(root.game, Collections.emptyMap(), session, (game, owner) -> {
            if (game != root.game || owner != player) throw new IllegalArgumentException("foreign world");
        });
        require(!player.chooseMulligan(root.game) && backend.calls == 1 && backend.features[0] == 3,
                "observed mulligan count was reset during conversion");
        OriginalCallbackPlayer copied = player.copy();
        require(copied.getId().equals(player.getId()) && copied.getHand().equals(player.getHand()), "policy copy state changed");
        refused(() -> copied.chooseMulligan(root.game));
        require(backend.closed, "unadmitted copy did not close its shared session");
        refused(() -> JackPlayerBootstrap.replaceViewer(root.world, 3));
        Root attached = new Root(); attached.old.attach(attached.world);
        refused(() -> JackPlayerBootstrap.replaceViewer(attached.world, 0));
        Root simulated = new Root(); simulated.simulation = true;
        refused(() -> JackPlayerBootstrap.replaceViewer(simulated.world, 0));
        Root valid = new Root();
        refused(() -> new OriginalCallbackPlayer(valid.old, -1));
        refused(() -> new OriginalCallbackPlayer(valid.old, 8));
        refused(() -> new OriginalCallbackPlayer((mage.player.ai.ComputerPlayer) null, 0));
        refused(() -> new OriginalCallbackPlayer(player, 0));
        System.out.println("JackPlayerBootstrapCheck PASS: actual state conversion, admission refusal, observed mulligan count and copy isolation");
    }
}
