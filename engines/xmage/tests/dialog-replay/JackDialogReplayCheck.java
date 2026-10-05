package spellbench.kit.xmage;

import mage.MageObject;
import mage.abilities.ActivatedAbility;
import mage.constants.Outcome;
import mage.game.Game;
import spellbench.kit.core.Json;
import spellbench.models.jack.OriginalCallbackPlayer;
import spellbench.models.jack.OriginalNeuralSelection;
import java.lang.reflect.*;
import java.util.*;
import static spellbench.kit.xmage.JackPlayerBootstrapCheck.*;

/** Actual original act/callback path and replay ownership on metadata worlds. */
public final class JackDialogReplayCheck {
    static final class Backend implements OriginalNeuralSelection.Model {
        int calls;boolean closed;
        public String callbackSourceSha256() {return OriginalCallbackPlayer.SOURCE_SHA256;}
        public String profile() {return OriginalNeuralSelection.GREEDY;}
        public long seed() {return 27;}
        public OriginalNeuralSelection.Prediction score(OriginalNeuralSelection.Request r,double seconds) {
            calls++;float[] probabilities=new float[64];probabilities[r.count-1]=1;
            return new OriginalNeuralSelection.Prediction(probabilities,0);
        }
        public void close() {closed=true;}
    }
    static final class Viewer extends OriginalCallbackPlayer {
        boolean prefix;int entered;boolean earlier;
        Viewer(mage.player.ai.ComputerPlayer old) {super(old,2);}
        Viewer(Viewer old) {super(old);prefix=old.prefix;}
        @Override public Viewer copy() {return new Viewer(this);}
        @Override protected List<MageObject> engineParentManaProducers(Game game) {return Collections.emptyList();}
        @Override protected boolean activateOriginalAbility(ActivatedAbility ability,Game game) {
            entered++;
            if(prefix) earlier=chooseUse(Outcome.Benefit,"earlier",null,game);
            announceX(0,3,"current",game,null,false);return true;
        }
    }
    static final class Case {
        final Root root=new Root();final Viewer player=new Viewer(root.old);final Backend backend=new Backend();
        final World world;final JackPermittedWorlds registry;final ActivatedAbility ability;
        final Set<UUID> hidden=new HashSet<>();
        int compares;
        Case() {
            root.state.getPlayers().put(player.getId(),player);
            hidden.addAll(player.getLibrary().getCardList());
            mage.cards.Card secret=new MetadataCard(root.other.getId(),"Secret opponent card");
            root.cards.put(secret.getId(),secret);root.other.getHand().add(secret);hidden.add(secret.getId());
            Game game=(Game)Proxy.newProxyInstance(Game.class.getClassLoader(),new Class<?>[]{Game.class},(o,m,a)->{
                switch(m.getName()) {
                    case "getTurnStepType":return mage.constants.PhaseStep.PRECOMBAT_MAIN;
                    case "getTurnNum":return 1;
                    case "getPhase":return null;
                    case "getStartingLife":return 20;
                    case "getBattlefield":return root.state.getBattlefield();
                    case "getStack":return root.state.getStack();
                    case "getExile":return root.state.getExile();
                    case "getOpponents":return Collections.singleton(root.other.getId());
                    case "getActivePlayerId":return player.getId();
                    case "getRangeOfInfluence":return mage.constants.RangeOfInfluence.ALL;
                    case "getMulligan":return new mage.game.mulligan.LondonMulligan(0);
                    case "createSimulationForPlayableCalc":return simulation((Game)o);
                    case "getCard":case "getObject":
                        if(hidden.contains(a[0])) throw new AssertionError("dialog projection/encoder read a hidden card");
                        return root.cards.get(a[0]);
                    default:
                        try{return m.invoke(root.game,a);} catch(InvocationTargetException failure) {throw failure.getCause();}
                }
            });
            world=new World(game,"p0",0,null);world.seatPlayer.put("p0",player.getId());world.seatPlayer.put("p1",root.other.getId());
            Map<UUID,String> aliases=new LinkedHashMap<>();
            for(UUID id:player.getHand()) {aliases.put(id,"hand");world.bind("hand",id);}
            for(UUID id:player.getGraveyard()) {aliases.put(id,"grave");world.bind("grave",id);}
            registry=new JackPermittedWorlds(new OriginalNeuralSelection.Session(backend,backend.profile(),backend.seed(),()->10));
            registry.register(world,aliases,g->{
                Map<UUID,Map<String,Object>> rows=new LinkedHashMap<>();
                for(Map.Entry<UUID,String> e:aliases.entrySet()) rows.put(e.getKey(),Json.map("object_id",e.getValue(),"card_name",root.cards.get(e.getKey()).getName()));
                return rows;
            });
            ability=JackRootDecisionCheck.land(player.getHand().iterator().next(),0);
        }
        Game simulation(Game parent) {
            mage.game.GameState state=parent.getState().copy();
            return (Game)Proxy.newProxyInstance(Game.class.getClassLoader(),new Class<?>[]{Game.class},(o,m,a)->{
                switch(m.getName()) {
                    case "getState":return state;
                    case "getPlayer":return state.getPlayers().get(a[0]);
                    case "getPlayers":return state.getPlayers();
                    case "isSimulation":return true;
                    case "createSimulationForPlayableCalc":return simulation((Game)o);
                    default:
                        try{return m.invoke(parent,a);} catch(InvocationTargetException failure) {throw failure.getCause();}
                }
            });
        }
        Map<String,Object> decision(String kind) {
            List<Object> offered=new ArrayList<>();
            if("x".equals(kind)) for(long x=3;x>=0;x--) offered.add(Json.map("candidate_id",20L+x,
                    "semantic",Json.map("kind","choose_number","source",null,"purpose","x_value","minimum",0L,"maximum",3L,"value",x)));
            else for(boolean value:new boolean[]{false,true}) offered.add(Json.map("candidate_id",value?7L:8L,
                    "semantic",Json.map("kind","choose_boolean","source",null,"value",value)));
            Map<String,Object> flags=new LinkedHashMap<>();
            for(String flag:Arrays.asList("poison","player_counters","designations","player_progress","day_night",
                    "passed_seats","pending_triggers","keywords","full_name","exiled_by","stack_text","permanent_details","known_cards")) flags.put(flag,false);
            try {
                return Json.map("acting_seat","p0","context",Json.map("kind","choice","source",null),
                        "observation",RoundTrip.project(world,flags,"p0",Collections.emptyList()),"x_observation_flags",flags,"candidates",offered);
            } catch(Exception failure) {throw new AssertionError(failure);}
        }
        Map<String,Object> record(boolean prefix) {
            Map<String,Object> root=decision("use");Json.obj(root,"context").put("kind","priority");
            root.put("candidates",Arrays.asList(Json.map("candidate_id",1L,"semantic",Json.map("kind","play_land","source",Json.map("object_id","hand"),"face","primary"))));
            Map<String,Object> selected=Json.map("candidate_id",1L,"semantic_echo",Json.copy(Json.obj(Json.obj(Json.arr(root,"candidates").get(0)),"semantic")));
            List<Object> earlier=new ArrayList<>();
            if(prefix) earlier.add(Json.map("decision",decision("use"),"selection",Json.map("candidate_id",7L,"semantic_echo",
                    Json.copy(Json.obj(Json.obj(Json.arr(decision("use"),"candidates").get(1)),"semantic")))));
            return Json.map("game_start",Json.map("seat","p0","agent_seed",27L),"decision",decision("x"),
                    "anchor",Json.map("decision",root,"selection",selected,"priority_pass_after_activation",false),
                    "replay",Json.map("earlier",earlier,"priority_passes",Collections.emptyList()));
        }
        JackDialogReplay control(Map<String,Object> record) {
            return new JackDialogReplay(world,record,(w,d)->{require(w==world,"projection used another world");compares++;});
        }
    }
    public static void main(String[] args) throws Exception {
        Case known=new Case();UUID library=known.player.getLibrary().getCardList().get(0);known.hidden.remove(library);
        mage.cards.Card named=new MetadataCard(known.player.getId(),"Forest");known.root.cards.put(named.getId(),named);
        known.player.getLibrary().putOnTop(named,known.world.game);
        Class<?> stateType=Class.forName("spellbench.models.jack.StateSequenceBuilder");
        Method encode=stateType.getMethod("buildBaseState",Game.class,mage.constants.TurnPhase.class,int.class,UUID.class,Map.class);
        Map<UUID,String> allowed=new LinkedHashMap<>();allowed.put(library,"z-known");allowed.put(named.getId(),"a-known");
        Object state=encode.invoke(null,known.world.game,null,256,known.player.getId(),allowed);
        @SuppressWarnings("unchecked") Map<UUID,Integer> tokens=(Map<UUID,Integer>)state.getClass().getField("uuidToTokenIndex").get(state);
        require(tokens.containsKey(library) && tokens.containsKey(named.getId()) && tokens.get(named.getId())<tokens.get(library),
                "explicitly named library tokens were dropped or reordered by hidden library order");
        known.registry.close();
        Case live=new Case();JackDialogReplay replay=live.control(live.record(false));replay.bind();
        Map<String,Object> result=replay.activate(live.ability);
        require(Long.valueOf(23).equals(Json.obj(result,"selection").get("candidate_id")) && live.backend.calls==1
                && live.player.entered==1 && !live.backend.closed,"actual original activation/X pause changed policy or closed session");
        live.registry.close();
        Case prefix=new Case();prefix.player.prefix=true;replay=prefix.control(prefix.record(true));replay.bind();
        result=replay.activate(prefix.ability);
        require(prefix.player.earlier && prefix.backend.calls==1 && Long.valueOf(1).equals(result.get("original_dialog_prefix_replayed"))
                && prefix.compares==2 && !prefix.backend.closed,"recorded binary prefix consumed inference or lost observation comparison");
        Viewer copied=prefix.player.copy();require(copied!=prefix.player,"actual player copy was not independent");
        Field bridge=OriginalCallbackPlayer.class.getDeclaredField("replay");bridge.setAccessible(true);
        require(bridge.get(copied)==null && bridge.get(prefix.player)!=null,"simulation copy retained root replay bridge");
        prefix.registry.close();
        Case wrong=new Case();Map<String,Object> record=wrong.record(false);
        Json.obj(Json.obj(Json.arr(Json.obj(record,"decision"),"candidates").get(0)),"semantic").put("source",Json.map("object_id","foreign"));
        replay=wrong.control(record);replay.bind();JackDialogReplay bad=replay;
        refused(()->bad.activate(wrong.ability));require(wrong.backend.closed && wrong.backend.calls==0,"bad binding inferred or left session open");
        Case unsupported=new Case();replay=unsupported.control(unsupported.record(false));replay.bind();
        refused(()->unsupported.player.chooseMulligan(unsupported.world.game));require(unsupported.backend.closed,"unconnected replay family ran its policy");
        Case foreign=new Case();Map<String,Object> badSeed=foreign.record(false);Json.obj(badSeed,"game_start").put("agent_seed",1L);
        refused(()->foreign.control(badSeed));require(foreign.backend.closed,"foreign constructor seed left the game-owned model open");
        System.out.println("JackDialogReplayCheck PASS: original activation, current X, recorded binary prefix, no repeated inference, copy isolation and failure closure");
    }
}
