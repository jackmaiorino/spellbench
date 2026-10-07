package spellbench.kit.xmage;

import mage.cards.Card;
import mage.game.Game;
import mage.game.GameState;
import mage.players.Player;
import spellbench.kit.core.Json;
import spellbench.models.maintainer.OriginalCallbackPlayer;
import spellbench.models.maintainer.OriginalNeuralSelection;

import java.lang.reflect.*;
import java.util.*;
import static spellbench.kit.xmage.MaintainerPlayerBootstrapCheck.*;

/** Actual registry, original copied-player callbacks and branch-local engine watcher copies. */
public final class MaintainerPermittedWorldsCheck {
    static final class Views implements MaintainerPermittedWorlds.Projection {
        final IdentityHashMap<Game,Map<UUID,Map<String,Object>>> records=new IdentityHashMap<>();
        public Map<UUID,Map<String,Object>> view(Game game) {
            if (!records.containsKey(game)) throw new IllegalArgumentException("no viewer projection");
            return records.get(game);
        }
    }
    static final class Scenario {
        final Root root=new Root(); final Backend backend=new Backend(); final Views views=new Views();
        final OriginalCallbackPlayer player;
        final MaintainerPermittedWorlds registry;
        final double[] seconds={10};
        final UUID hand=root.old.getHand().iterator().next();
        final Map<UUID,String> initial=new LinkedHashMap<>();
        Scenario() {
            MaintainerPlayerBootstrap.replaceViewer(root.world,2);
            player=(OriginalCallbackPlayer)root.world.viewerPlayer();
            OriginalNeuralSelection.Session session=new OriginalNeuralSelection.Session(backend,backend.profile(),backend.seed(),()->seconds[0]);
            registry=new MaintainerPermittedWorlds(session);
            Map<UUID,Map<String,Object>> records=new LinkedHashMap<>();
            for (UUID id:player.getHand()) { records.put(id,ref("h","Forest","hand")); initial.put(id,"public-hand"); }
            for (UUID id:player.getGraveyard()) { records.put(id,ref("g","Island","graveyard")); initial.put(id,"public-grave"); }
            views.records.put(root.game,records);
            registry.register(root.world,initial,views);
        }
        Game copy() {
            GameState state=root.state.copy();
            Game game=(Game)Proxy.newProxyInstance(Game.class.getClassLoader(),new Class<?>[]{Game.class},(o,m,a)->{
                switch (m.getName()) {
                    case "getPlayer": return state.getPlayers().get(a[0]);
                    case "getPlayers": return state.getPlayers();
                    case "getState": return state;
                    case "getCard": case "getObject": return root.cards.get(a[0]);
                    case "getPermanent": return null;
                    case "isSimulation": return true;
                    case "getId": return root.game.getId();
                    case "getZone": return state.getZone((UUID)a[0]);
                    default: throw new AssertionError("unexpected admitted-copy read: "+m.getName());
                }
            });
            views.records.put(game,new LinkedHashMap<>(views.records.get(root.game)));
            return game;
        }
    }
    static Map<String,Object> ref(String id,String name,String zone) {
        return Json.map("object_id",id,"card_name",name,"zone",zone,"owner_seat","p0","controller_seat","p0");
    }
    @SuppressWarnings("unchecked") static Map<UUID,String> aliases(OriginalCallbackPlayer player) {
        try {
            Method method=player.getClass().getSuperclass().getDeclaredMethod("originalPriorityRules"); method.setAccessible(true);
            Object rules=method.invoke(player);
            return (Map<UUID,String>)rules.getClass().getMethod("aliases").invoke(rules);
        } catch (ReflectiveOperationException failure) { throw new AssertionError(failure); }
    }
    static void actualProjection() throws Exception {
        Scenario s=new Scenario();
        Card library=s.root.cards.get(s.player.getLibrary().getCardList().get(0));
        Card hidden=new MetadataCard(s.root.other.getId(),"Secret opponent card");
        s.root.cards.put(hidden.getId(),hidden); s.root.other.getHand().add(hidden);
        s.root.state.setZone(hidden.getId(),mage.constants.Zone.HAND);
        Set<UUID> denied=new HashSet<>(Arrays.asList(library.getId(),hidden.getId()));
        mage.game.mulligan.LondonMulligan london=new mage.game.mulligan.LondonMulligan(0);
        Game game=(Game)Proxy.newProxyInstance(Game.class.getClassLoader(),new Class<?>[]{Game.class},(o,m,a)->{
            switch(m.getName()) {
                case "getTurnStepType": return null;
                case "getStartingPlayerId": return s.player.getId();
                case "getMulligan": return london;
                case "getBattlefield": return s.root.state.getBattlefield();
                case "getStack": return s.root.state.getStack();
                case "getExile": return s.root.state.getExile();
                case "getCard": if(denied.contains(a[0])) throw new AssertionError("projection read a hidden card");
                default:
                    try { return m.invoke(s.root.game,a); }
                    catch (InvocationTargetException failure) { throw failure.getCause(); }
            }
        });
        Map<String,Object> flags=new LinkedHashMap<>();
        for (String flag:Arrays.asList("poison","player_counters","designations","player_progress","day_night",
                "passed_seats","pending_triggers","keywords","full_name","exiled_by","stack_text","permanent_details","known_cards"))
            flags.put(flag,false);
        Class<?> type=Class.forName("spellbench.kit.xmage.MaintainerPermittedWorlds$VisibleProjection");
        Constructor<?> constructor=type.getDeclaredConstructor(World.class,Map.class,Map.class); constructor.setAccessible(true);
        MaintainerPermittedWorlds.Projection projection=(MaintainerPermittedWorlds.Projection)constructor.newInstance(s.root.world,flags,s.initial);
        Map<UUID,Map<String,Object>> records=projection.view(game);
        require(records.containsKey(s.hand) && !records.containsKey(library.getId()) && !records.containsKey(hidden.getId()),
                "actual observation projection exposed hidden zones");
        s.root.state.getLookedAt(s.root.other.getId()).add("private other look",hidden);
        records=projection.view(game); require(!records.containsKey(hidden.getId()),"other player's private look entered aliases");
        s.root.state.getLookedAt(s.player.getId()).add("own current look",library); denied.remove(library.getId());
        records=projection.view(game); require(records.containsKey(library.getId()),"own current look missing from projection");
        s.root.state.getRevealed().createRevealed("public reveal").add(hidden); denied.remove(hidden.getId());
        records=projection.view(game); require(records.containsKey(hidden.getId()),"public reveal missing from projection");
        s.root.state.getRevealed().reset(); s.root.state.getLookedAt(s.player.getId()).reset();
        Map<UUID,String> knownRoot=new LinkedHashMap<>(s.initial); knownRoot.put(hidden.getId(),"known-hand");
        KnowledgeWatcher knowledge=KnowledgeWatcher.get(s.root.game); knowledge.pinHand(s.root.other.getId(),hidden.getName());
        projection=(MaintainerPermittedWorlds.Projection)constructor.newInstance(s.root.world,flags,knownRoot);
        records=projection.view(game); require(records.containsKey(hidden.getId()),"initial named opponent-hand reference lost");
        Method left=KnowledgeWatcher.class.getDeclaredMethod("handLeftHidden",UUID.class); left.setAccessible(true);
        left.invoke(knowledge,s.root.other.getId());
        denied.add(hidden.getId());
        records=projection.view(game); require(!records.containsKey(hidden.getId()),"lost name-only hand knowledge retained a physical identity");
        s.registry.close();
    }
    public static void main(String[] args) throws Exception {
        actualProjection();
        Scenario restored=new Scenario();
        GameState bookmark=restored.root.state.copy();
        KnowledgeWatcher before=KnowledgeWatcher.get(restored.root.game);
        Card remembered=restored.root.cards.get(restored.player.getLibrary().getCardList().get(0));
        before.pinLibrary(restored.player.getId(),remembered.getId());
        restored.root.state.restore(bookmark);
        require(restored.root.game.getPlayer(restored.player.getId())==restored.player,
                "actual bookmark restore replaced original player");
        KnowledgeWatcher after=KnowledgeWatcher.get(restored.root.game);
        require(after!=before && !after.knownInLibrary(restored.player.getId(),remembered.getId()),
                "actual bookmark restore retained speculative knowledge");
        require(!restored.player.chooseMulligan(restored.root.game),"restored root lost admission");
        Game restoredChild=restored.copy(); restored.player.admitOriginalSimulation(restored.root.game,restoredChild);
        OriginalCallbackPlayer restoredCopy=(OriginalCallbackPlayer)restoredChild.getPlayer(restored.player.getId());
        restoredChild.getState().restore(restoredChild.getState().copy());
        require(!restoredCopy.chooseMulligan(restoredChild),"restored simulation lost admission");
        restored.registry.close();
        Scenario s=new Scenario();
        require(!s.player.chooseMulligan(s.root.game) && s.backend.features[0]==2,"actual root callback/observed count changed");
        require(aliases(s.player).equals(s.initial),"root public aliases changed");
        Game child=s.copy(); s.player.admitOriginalSimulation(s.root.game,child);
        OriginalCallbackPlayer copied=(OriginalCallbackPlayer)child.getPlayer(s.player.getId());
        require(!copied.chooseMulligan(child) && aliases(copied).equals(s.initial),"actual simulation copy was not bound");
        KnowledgeWatcher parent=KnowledgeWatcher.get(s.root.game),knowledge=KnowledgeWatcher.get(child);
        require(knowledge!=parent && knowledge.decider().equals(parent.decider()),"copied knowledge not independent");
        Card library=s.root.cards.get(s.player.getLibrary().getCardList().get(0));
        knowledge.pinLibrary(s.player.getId(),library.getId());
        require(!parent.knownInLibrary(s.player.getId(),library.getId()),"child knowledge changed parent");
        Card extra=new MetadataCard(s.player.getId(),"Plains"); s.root.cards.put(extra.getId(),extra);
        s.root.state.setZone(extra.getId(),mage.constants.Zone.LIBRARY);
        Game first=s.copy(),second=s.copy();
        s.player.admitOriginalSimulation(s.root.game,first); s.player.admitOriginalSimulation(s.root.game,second);
        s.views.records.get(first).put(library.getId(),ref("library-b","Mountain","library"));
        s.views.records.get(first).put(extra.getId(),ref("library-a","Plains","library"));
        s.views.records.get(second).put(extra.getId(),ref("library-a","Plains","library"));
        s.views.records.get(second).put(library.getId(),ref("library-b","Mountain","library"));
        OriginalCallbackPlayer pFirst=(OriginalCallbackPlayer)first.getPlayer(s.player.getId());
        OriginalCallbackPlayer pSecond=(OriginalCallbackPlayer)second.getPlayer(s.player.getId());
        pFirst.chooseMulligan(first); pSecond.chooseMulligan(second);
        require(aliases(pFirst).get(extra.getId()).compareTo(aliases(pFirst).get(library.getId()))<0
                && aliases(pSecond).get(extra.getId()).compareTo(aliases(pSecond).get(library.getId()))<0,
                "dynamic alias sorting exposed hidden collection iteration order");
        Map<UUID,Map<String,Object>> visible=s.views.records.get(child);
        visible.remove(s.hand); copied.chooseMulligan(child);
        require(!aliases(copied).containsKey(s.hand) && aliases(s.player).containsKey(s.hand),"hidden alias persisted or affected parent");
        visible.put(s.hand,ref("h2","Forest","hand")); copied.chooseMulligan(child);
        String returned=aliases(copied).get(s.hand);
        require(returned!=null && !returned.equals("public-hand"),"hidden/returned entity reused stale alias");
        copied.chooseMulligan(child); require(returned.equals(aliases(copied).get(s.hand)),"unchanged visible alias was reminted");
        visible.put(s.hand,ref("h2","", "hand")); copied.chooseMulligan(child);
        require(!aliases(copied).containsKey(s.hand),"unnamed face-down reference entered model aliases");
        require(!s.backend.closed,"valid refresh closed original session");
        s.registry.retire(s.root.world);
        require(!s.backend.closed,"retiring reconstructed decision closed game-owned inference");
        refused(()->copied.chooseMulligan(child)); require(s.backend.closed,"retired copied callback did not refuse/close");
        s.registry.close(); s.registry.close();

        Scenario duplicate=new Scenario(); Game once=duplicate.copy(); duplicate.player.admitOriginalSimulation(duplicate.root.game,once);
        refused(()->duplicate.player.admitOriginalSimulation(duplicate.root.game,once));
        require(duplicate.backend.closed,"duplicate admission did not close shared session");
        Scenario foreign=new Scenario(); Scenario unrelated=new Scenario(); Game wrong=unrelated.copy();
        refused(()->foreign.player.admitOriginalSimulation(foreign.root.game,wrong));
        require(foreign.backend.closed,"foreign session/world was not refused"); unrelated.registry.close();
        Scenario stale=new Scenario();
        stale.root.state.getPlayers().put(stale.player.getId(),stale.player.copy());
        refused(()->stale.player.chooseMulligan(stale.root.game)); require(stale.backend.closed,"replaced root player remained admitted");
        Scenario malformed=new Scenario(); malformed.views.records.get(malformed.root.game).put(malformed.hand,ref(null,"Forest","hand"));
        refused(()->malformed.player.chooseMulligan(malformed.root.game)); require(malformed.backend.closed,"bad projection did not close inference");
        Scenario cross=new Scenario();
        refused(()->cross.registry.build(null,null,null,null,0)); require(cross.backend.closed,"missing reconstruction inputs did not close session");
        Scenario expired=new Scenario(); expired.seconds[0]=0;
        refused(()->expired.registry.build(null,null,null,null,0));
        require(expired.backend.closed,"expired clock did not refuse and close before reconstruction");
        System.out.println("MaintainerPermittedWorldsCheck PASS: actual root/copy binding, branch knowledge, named alias lifecycle, retirement and failure closure");
    }
}
