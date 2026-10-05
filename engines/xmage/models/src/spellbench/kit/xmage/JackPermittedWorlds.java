package spellbench.kit.xmage;

import mage.cards.Card;
import mage.cards.Cards;
import mage.constants.WatcherScope;
import mage.constants.Zone;
import mage.game.*;
import mage.game.command.CommandObject;
import mage.game.events.GameEvent;
import mage.game.permanent.Permanent;
import mage.game.stack.StackObject;
import mage.player.spellbench.observe.*;
import mage.players.Player;
import mage.watchers.Watcher;
import spellbench.kit.core.Json;
import spellbench.kit.core.Sampler;

import java.lang.reflect.*;
import java.util.*;

/** Game-owned admission for roots built from permitted inputs and their actual engine copies. */
public final class JackPermittedWorlds implements AutoCloseable {
    interface Projection { Map<UUID,Map<String,Object>> view(Game game) throws Exception; }
    private static final class Lineage extends Watcher {
        final UUID token, viewer;
        Lineage(UUID token, UUID viewer) { super(WatcherScope.GAME); this.token=token; this.viewer=viewer; }
        Lineage(Lineage parent) { super(parent); token=parent.token; viewer=parent.viewer; }
        @SuppressWarnings("unchecked") @Override public <T extends Watcher> T copy() { return (T)new Lineage(this); }
        @Override public void watch(GameEvent event, Game game) { }
    }
    private static final class Entry {
        final Game game; final Player player; final Lineage lineage; final Projection projection;
        final Map<UUID,String> aliases=new LinkedHashMap<>(), signatures=new HashMap<>();
        final Set<String> minted=new HashSet<>();
        long next; boolean binding;
        Entry(Game game,Player player,Lineage lineage,Projection projection) {
            this.game=game; this.player=player; this.lineage=lineage; this.projection=projection;
        }
    }
    private final Object session;
    private final Class<?> playerClass,sessionClass,admissionClass;
    private final Method sessionOf,bind,close,remaining;
    private final IdentityHashMap<Game,Entry> entries=new IdentityHashMap<>();
    private boolean closed;

    public JackPermittedWorlds(Object session) {
        try {
            playerClass=Class.forName("spellbench.models.jack.OriginalCallbackPlayer");
            sessionClass=Class.forName("spellbench.models.jack.OriginalNeuralSelection$Session");
            admissionClass=Class.forName("spellbench.models.jack.OriginalNeuralSelection$Admission");
            if (!sessionClass.isInstance(session)) throw new IllegalArgumentException("original game-owned session required");
            this.session=session;
            sessionOf=playerClass.getSuperclass().getDeclaredMethod("originalNeuralSession"); sessionOf.setAccessible(true);
            bind=playerClass.getMethod("bindOriginalWorld",Game.class,Map.class,sessionClass,admissionClass);
            close=sessionClass.getMethod("close");
            remaining=sessionClass.getDeclaredMethod("remaining"); remaining.setAccessible(true);
        } catch (ReflectiveOperationException failure) { throw new IllegalArgumentException("original admission interfaces unavailable",failure); }
    }

    /** Sampling and bootstrap are owned here; no public API admits an externally supplied Game. */
    public synchronized World build(Map<String,Object> start,Map<String,Object> decision,
            KitRandom random,WorldBuilder.Mode mode,int index) {
        return build(start,decision,null,random,mode,index);
    }
    public synchronized World buildReplay(Map<String,Object> start,Map<String,Object> decision,Map<String,Object> record,
            KitRandom random,WorldBuilder.Mode mode,int index) {
        return build(start,decision,record,random,mode,index);
    }
    private World build(Map<String,Object> start,Map<String,Object> decision,Map<String,Object> record,
            KitRandom random,WorldBuilder.Mode mode,int index) {
        requireOpen();
        try {
            if (start==null || decision==null || random==null || mode==null) throw new IllegalArgumentException("permitted reconstruction inputs required");
            Map<String,Object> copy=Json.obj(Json.copy(decision)),obs=Json.obj(copy,"observation");
            WorldBuilder.Spec spec=new WorldBuilder.Spec();
            spec.gameStart=start; spec.observation=obs; spec.random=random; spec.mode=mode; spec.index=index;
            spec.history=Json.obj(copy,"x_history");
            Map<String,Object> sampling=record==null?obs:JackReplayKnowledge.samplingObservation(copy,record);
            List<String> repairs=WorldBuilder.restoreVisibleNames(obs,spec.history);
            if(sampling!=obs)WorldBuilder.restoreVisibleNames(sampling,spec.history);
            spec.sample=Sampler.sample(start,sampling,random.stream("sampler"));
            if(record!=null)for(String flag:spec.sample.flags)if(flag.startsWith("approximate:public_exceeds_list:"+Json.str(obs,"viewer"))
                    || flag.startsWith("approximate:known_library_exceeds_count"))throw new IllegalArgumentException("conditioned library facts conflict with the permitted pool: "+flag);
            World world=JackPlayerBootstrap.build(spec);
            world.flags.addAll(repairs);
            Map<UUID,String> initial=JackWorldAliases.namedAliases(world,copy);
            register(world,initial,new VisibleProjection(world,RoundTrip.flagsFrom(copy),initial));
            return world;
        } catch (Throwable failure) { throw failed(failure); }
    }

    // The package-private path supports metadata checks. Live callers must reconstruct above.
    synchronized void register(World world,Map<UUID,String> initial,Projection projection) {
        requireOpen();
        try {
            if (world==null || world.game==null || world.game.isSimulation() || initial==null || projection==null
                    || entries.containsKey(world.game) || !playerClass.isInstance(world.viewerPlayer()))
                throw new IllegalArgumentException("one reconstructed original root required");
            for (String flag:world.flags) if (flag.startsWith("unsupported:") || flag.startsWith("horizon:"))
                throw new IllegalArgumentException("original reconstructed world unsupported: "+flag);
            Player player=world.viewerPlayer();
            if (call(sessionOf,player)!=null || KnowledgeWatcher.get(world.game)!=null
                    || world.game.getState().getWatcher(Lineage.class)!=null)
                throw new IllegalArgumentException("fresh unbound reconstruction required");
            KnowledgeWatcher knowledge=KnowledgeWatcher.install(world.game,player.getId());
            for (Map.Entry<String,UUID> object:world.idToUuid.entrySet()) {
                UUID id=object.getValue();if(!initial.containsKey(id))continue;
                Card card=world.game.getCard(id);
                if (card!=null && world.game.getState().getZone(id)==Zone.LIBRARY)
                    knowledge.pinLibrary(card.getOwnerId(),id);
            }
            UUID other=world.player("p0".equals(world.viewer)?"p1":"p0");
            for (String name:world.knownHandNames) knowledge.pinHand(other,name);
            Lineage lineage=new Lineage(UUID.randomUUID(),player.getId()); world.game.getState().addWatcher(lineage);
            Entry entry=new Entry(world.game,player,lineage,projection); entry.binding=true;
            entry.aliases.putAll(initial); entry.minted.addAll(initial.values());
            if (entry.minted.size()!=initial.size() || initial.containsKey(null) || entry.minted.contains(null) || entry.minted.contains(""))
                throw new IllegalArgumentException("unique named root aliases required");
            entries.put(world.game,entry);
            refresh(entry,true);
            call(bind,player,world.game,new LinkedHashMap<>(entry.aliases),session,admission(entry));
            entry.binding=false; owned(world.game,player);
        } catch (Throwable failure) { throw failed(failure); }
    }

    private Object admission(Entry entry) {
        return Proxy.newProxyInstance(admissionClass.getClassLoader(),new Class<?>[]{admissionClass},(proxy,method,args)->{
            if (method.getDeclaringClass()==Object.class) {
                if (method.getName().equals("equals")) return proxy==args[0];
                if (method.getName().equals("hashCode")) return System.identityHashCode(proxy);
                return "Jack permitted-world admission";
            }
            synchronized (JackPermittedWorlds.this) {
                try {
                    if (method.getName().equals("require")) { requireEntry(entry,(Game)args[0],(Player)args[1]); return null; }
                    if (method.getName().equals("aliases")) {
                        requireEntry(entry,(Game)args[0],(Player)args[1]); refresh(entry,false);
                        return Collections.unmodifiableMap(new LinkedHashMap<>(entry.aliases));
                    }
                    if (method.getName().equals("copy")) {
                        requireEntry(entry,(Game)args[0],entry.player);
                        Game child=(Game)args[1]; Player player=(Player)args[2];
                        if (child==null || child==entry.game || !child.isSimulation() || entries.containsKey(child)
                                || !entry.game.getId().equals(child.getId()) || !playerClass.isInstance(player)
                                || player==entry.player || !entry.player.getId().equals(player.getId())
                                || child.getPlayer(player.getId())!=player || call(sessionOf,player)!=session)
                            throw new IllegalArgumentException("actual original simulation copy required");
                        Lineage lineage=child.getState().getWatcher(Lineage.class);
                        KnowledgeWatcher knowledge=KnowledgeWatcher.get(child),source=KnowledgeWatcher.get(entry.game);
                        if (lineage==null || lineage==entry.game.getState().getWatcher(Lineage.class)
                                || !entry.lineage.token.equals(lineage.token)
                                || !player.getId().equals(lineage.viewer) || knowledge==null || knowledge==source
                                || !player.getId().equals(knowledge.decider()))
                            throw new IllegalArgumentException("simulation lost branch-local permitted lineage/knowledge");
                        Entry copied=new Entry(child,player,lineage,entry.projection);
                        copied.aliases.putAll(entry.aliases); copied.signatures.putAll(entry.signatures);
                        copied.minted.addAll(entry.minted); copied.next=entry.next;
                        entries.put(child,copied); return admission(copied);
                    }
                    throw new IllegalArgumentException("unknown original admission operation");
                } catch (Throwable failure) { throw failed(failure); }
            }
        });
    }

    private Entry owned(Game game,Player player) {
        requireOpen(); Entry entry=entries.get(game);
        KnowledgeWatcher knowledge=game==null?null:KnowledgeWatcher.get(game);
        Lineage lineage=game==null?null:game.getState().getWatcher(Lineage.class);
        if (entry==null || entry.player!=player || game.getPlayer(player.getId())!=player
                // GameState.restore retains the player and replaces watchers with saved copies.
                || lineage==null || !entry.lineage.token.equals(lineage.token)
                || !player.getId().equals(lineage.viewer)
                || knowledge==null || !player.getId().equals(knowledge.decider())
                || (!entry.binding && call(sessionOf,player)!=session))
            throw new IllegalArgumentException("world/player is outside original registry");
        return entry;
    }
    private void requireEntry(Entry expected,Game game,Player player) {
        if (owned(game,player)!=expected) throw new IllegalArgumentException("admission belongs to another world");
    }
    private void refresh(Entry entry,boolean root) throws Exception {
        Map<UUID,Map<String,Object>> visible=entry.projection.view(entry.game);
        Map<UUID,String> aliases=new LinkedHashMap<>(),signatures=new HashMap<>();
        Set<String> references=new HashSet<>();
        for (Map.Entry<UUID,Map<String,Object>> item:visible.entrySet()) {
            UUID id=item.getKey(); Map<String,Object> ref=item.getValue();
            String name=Json.str(ref,"card_name"),reference=Json.str(ref,"object_id");
            if (id==null || name==null || name.isEmpty()) continue;
            if (reference==null || reference.isEmpty()) throw new IllegalArgumentException("named projection lacks reference");
            if (!references.add(reference)) continue; // stack/card or multipart aliases name one entity
            Map<String,Object> fingerprint=new LinkedHashMap<>(ref); fingerprint.remove("object_id");
            Card card=entry.game.getCard(id);
            fingerprint.put("zone_change_counter",card==null?-1L:(long)card.getZoneChangeCounter(entry.game));
            String signature=Json.canonical(fingerprint),alias=entry.aliases.get(id);
            if (root && alias==null) throw new IllegalArgumentException("named root entity lacks its supplied alias");
            if (!root && (alias==null || !signature.equals(entry.signatures.get(id)))) {
                // The opaque viewer reference sorts first. Birth order must not encode library order.
                do { alias=reference+"-jack-visible-"+(entry.next++); } while (!entry.minted.add(alias));
            }
            aliases.put(id,alias); signatures.put(id,signature);
        }
        if (root && !aliases.equals(entry.aliases)) throw new IllegalArgumentException("root aliases include an unnamed/absent entity");
        entry.aliases.clear(); entry.aliases.putAll(aliases); entry.signatures.clear(); entry.signatures.putAll(signatures);
    }
    /** Release a reconstructed decision and all its copies, keeping the game's inference session. */
    public synchronized void retire(World world) {
        try {
            Entry entry=owned(world.game,world.viewerPlayer()); UUID token=entry.lineage.token;
            entries.values().removeIf(item->token.equals(item.lineage.token));
        } catch (Throwable failure) { throw failed(failure); }
    }
    private void requireOpen() {
        if (closed) throw new IllegalArgumentException("original world registry closed");
        try { call(remaining,session); } catch (Throwable failure) { throw failed(failure); }
    }
    private static Object call(Method method,Object owner,Object...args) {
        try { return method.invoke(owner,args); }
        catch (InvocationTargetException failure) {
            Throwable cause=failure.getCause(); if (cause instanceof RuntimeException) throw (RuntimeException)cause;
            if (cause instanceof Error) throw (Error)cause; throw new IllegalArgumentException("original admission call failed",cause);
        } catch (ReflectiveOperationException failure) { throw new IllegalArgumentException("original admission call unavailable",failure); }
    }
    private RuntimeException failed(Throwable failure) {
        try { close(); } catch (Throwable closing) { if (closing!=failure) failure.addSuppressed(closing); }
        if (failure instanceof Error) throw (Error)failure;
        return failure instanceof RuntimeException?(RuntimeException)failure:new IllegalArgumentException("permitted projection failed",failure);
    }
    @Override public synchronized void close() { if (!closed) { closed=true; entries.clear(); call(close,session); } }

    private static final class VisibleProjection implements Projection {
        final String viewer; final UUID p0,p1; final Map<String,Object> flags;
        final Map<UUID,String> initialHands=new LinkedHashMap<>();
        final Map<UUID,Integer> handIncarnations=new HashMap<>();
        final Map<String,Integer> handCounts=new HashMap<>();
        VisibleProjection(World world,Map<String,Object> flags,Map<UUID,String> initial) {
            viewer=world.viewer; p0=world.player("p0"); p1=world.player("p1"); this.flags=new LinkedHashMap<>(flags);
            for (UUID id:initial.keySet()) {
                Card card=world.game.getCard(id);
                if (card!=null && !card.getOwnerId().equals(world.player(viewer)) && world.game.getState().getZone(id)==Zone.HAND) {
                    initialHands.put(id,card.getName()); handIncarnations.put(id,card.getZoneChangeCounter(world.game));
                    handCounts.merge(card.getName(),1,Integer::sum);
                }
            }
        }
        public Map<UUID,Map<String,Object>> view(Game game) throws Exception {
            KnowledgeWatcher knowledge=KnowledgeWatcher.get(game);
            if (knowledge==null || !game.getPlayer("p0".equals(viewer)?p0:p1).getId().equals(knowledge.decider()))
                throw new IllegalArgumentException("viewer knowledge unavailable");
            List<Look> looks=new ArrayList<>();
            for (UUID seat:Arrays.asList(p0,p1)) for (UUID id:knowledge.libKnown(seat))
                if (game.getState().getZone(id)==Zone.LIBRARY) looks.add(Look.searching(id));
            // Name-only hand knowledge cannot identify which duplicate left hidden.
            // Drop the root references when its full known count no longer survives.
            for (Map.Entry<UUID,String> item:initialHands.entrySet()) {
                UUID other="p0".equals(viewer)?p1:p0;
                if (knowledge.knownHandCount(other,item.getValue())<handCounts.get(item.getValue())
                        || game.getState().getZone(item.getKey())!=Zone.HAND) continue;
                Card card=game.getCard(item.getKey());
                if (card!=null && card.getZoneChangeCounter(game)==handIncarnations.get(item.getKey()))
                    looks.add(new Look(item.getKey(),"looked_at",null,null));
            }
            // Only the viewer's own engine look windows and public reveals, never the other player's looks.
            for (Cards cards:game.getState().getLookedAt(knowledge.decider()).values())
                for (UUID id:cards) currentLook(game,id,false,looks);
            for (Cards cards:game.getState().getRevealed().values())
                for (UUID id:cards) currentLook(game,id,true,looks);
            Observation observation=new ObservationBuilder(game,new mage.player.spellbench.ids.ObjectIds(new byte[32]),flags,p0,p1)
                    .build(viewer,null,looks);
            List<UUID> objects=new ArrayList<>();
            for (StackObject object:game.getStack()) objects.add(object.getId());
            for (CommandObject object:game.getState().getCommand()) objects.add(object.getId());
            for (UUID seat:Arrays.asList(p0,p1)) {
                Player player=game.getPlayer(seat);
                for (Permanent object:game.getBattlefield().getAllActivePermanents(seat)) objects.add(object.getId());
                if (seat.equals(knowledge.decider())) objects.addAll(player.getHand());
                objects.addAll(player.getGraveyard()); objects.addAll(knowledge.libKnown(seat));
            }
            for (Look look:looks) objects.add(look.cardId);
            for (ExileZone zone:game.getExile().getExileZones()) objects.addAll(zone);
            Map<UUID,Map<String,Object>> result=new LinkedHashMap<>();
            for (UUID id:objects) {
                Map<String,Object> ref=observation.reference(id);
                if (ref!=null) result.put(id,ref);
            }
            return result;
        }
        private static void currentLook(Game game,UUID id,boolean revealed,List<Look> out) {
            Zone zone=game.getState().getZone(id);
            if (zone==Zone.LIBRARY) out.add(Look.searching(id));
            else if (zone==Zone.HAND) out.add(new Look(id,revealed?"revealed":"looked_at",null,null));
        }
    }
}
