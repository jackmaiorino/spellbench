package spellbench.kit.xmage;

import mage.MageObject;
import mage.abilities.ActivatedAbility;
import mage.abilities.Ability;
import mage.abilities.Mode;
import mage.abilities.Modes;
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
    static Map<String,Object> flags() {
        Map<String,Object> flags=new LinkedHashMap<>();
        for(String flag:Arrays.asList("poison","player_counters","designations","player_progress","day_night",
                "passed_seats","pending_triggers","keywords","full_name","exiled_by","stack_text","permanent_details","known_cards")) flags.put(flag,false);
        return flags;
    }
    static final class Backend implements OriginalNeuralSelection.Model {
        int calls,copies;boolean closed,chooseFirst,wholeRank;final List<String> heads=new ArrayList<>();
        final List<Integer> ranks=new ArrayList<>();
        public String callbackSourceSha256() {return OriginalCallbackPlayer.SOURCE_SHA256;}
        public String profile() {return OriginalNeuralSelection.GREEDY;}
        public long seed() {return 27;}
        public OriginalNeuralSelection.Prediction score(OriginalNeuralSelection.Request r,double seconds) {
            calls++;heads.add(r.head);float[] probabilities=new float[64];probabilities[chooseFirst?0:r.count-1]=1;
            if(wholeRank) {
                require("card_select".equals(r.head) && r.minimum==r.count && r.maximum==r.count,"London lost full-hand ranking bounds");
                ranks.add(r.count);
                for(int i=0;i<r.count;i++)probabilities[i]=(r.count-i)/(float)(r.count*(r.count+1)/2);
            }
            return new OriginalNeuralSelection.Prediction(probabilities,0);
        }
        public void close() {closed=true;}
        public int physicalCopy(int count,double seconds) {copies++;return count-1;}
    }
    static final class Viewer extends OriginalCallbackPlayer {
        boolean prefix,cost,mode,modePrefix,completeActivation,completionX;int entered;boolean earlier;ActivatedAbility playable;
        Modes modes;Ability modeSource;Mode earlierMode;
        mage.choices.Choice named;boolean namedResult;
        mage.target.Target target;boolean targetResult;
        mage.cards.Cards cards;mage.target.TargetCard cardTarget;boolean parentCards,cardResult;
        Outcome cardOutcome=Outcome.Benefit;
        boolean londonMetadata;final List<UUID> bottomed=new ArrayList<>();
        @Override public boolean putCardsOnBottomOfLibrary(mage.cards.Cards cards,Game game,Ability source,boolean anyOrder) {
            if(!londonMetadata)return super.putCardsOnBottomOfLibrary(cards,game,source,anyOrder);
            for(UUID id:cards) {require(getHand().contains(id),"metadata London moved an absent card");getHand().remove(id);bottomed.add(id);}
            return true;
        }
        void queueCard(UUID id) {targets.add(id);}
        Viewer(mage.player.ai.ComputerPlayer old) {super(old,2);}
        Viewer(Viewer old) {super(old);prefix=old.prefix;}
        @Override public Viewer copy() {return new Viewer(this);}
        @Override public List<ActivatedAbility> getPlayable(Game game,boolean hidden) {return Collections.singletonList(playable);}
        @Override protected List<MageObject> engineParentManaProducers(Game game) {return Collections.emptyList();}
        @Override protected boolean activateOriginalAbility(ActivatedAbility ability,Game game) {
            entered++;
            if(cost) {
                mage.choices.ChoiceImpl choice=new mage.choices.ChoiceImpl(true);
                choice.getKeyChoices().put("0","normal cost");choice.getKeyChoices().put("1","alternative cost");
                require(choose(Outcome.Benefit,choice,game) && "1".equals(choice.getChoiceKey()),
                        "original activation lost its recorded validated alternative cost or selected source");
            }
            if(prefix) earlier=chooseUse(Outcome.Benefit,"earlier",null,game);
            if(mode || modePrefix) earlierMode=chooseMode(modes,modeSource,game);
            if(named!=null) namedResult=choose(Outcome.Benefit,named,game);
            if(target!=null) targetResult=chooseTarget(Outcome.Benefit,target,playable,game);
            if(cards!=null) cardResult=parentCards?choose(cardOutcome,cards,cardTarget,playable,game)
                    :chooseTarget(cardOutcome,cards,cardTarget,playable,game);
            if(!completeActivation || completionX)announceX(0,3,"current",game,null,false);return true;
        }
    }
    static final class StableCard extends mage.cards.CardImpl {
        StableCard(UUID owner,String name,int index) {
            super(owner,new mage.cards.CardSetInfo(name,"META","1",mage.constants.Rarity.COMMON),
                    new mage.constants.CardType[]{mage.constants.CardType.LAND},"");
            objectId=new UUID(0,900+index);
            for(Ability ability:getAbilities())ability.setSourceId(objectId);
        }
        StableCard(StableCard old) {super(old);}
        @Override public StableCard copy() {return new StableCard(this);}
    }
    static final class Case {
        final Root root=new Root();final Viewer player=new Viewer(root.old);final Backend backend=new Backend();
        final World world;final JackPermittedWorlds registry;final ActivatedAbility ability;
        final Set<UUID> hidden=new HashSet<>();
        final mage.game.mulligan.LondonMulligan mulligan=new mage.game.mulligan.LondonMulligan(0);
        int compares;boolean pregame;
        Runnable resumeWork;int resumes;
        Case() {
            this(0,false);
        }
        Case(int handSize,boolean sameName) {
            root.state.getPlayers().put(player.getId(),player);
            if(handSize>0)player.getHand().clear();
            for(int i=0;i<handSize;i++) {
                mage.cards.Card card=new StableCard(player.getId(),sameName || i%2==0?"Forest":"Island",i);
                root.cards.put(card.getId(),card);player.getHand().add(card);
            }
            hidden.addAll(player.getLibrary().getCardList());
            mage.cards.Card secret=new MetadataCard(root.other.getId(),"Secret opponent card");
            root.cards.put(secret.getId(),secret);root.other.getHand().add(secret);hidden.add(secret.getId());
            Game game=(Game)Proxy.newProxyInstance(Game.class.getClassLoader(),new Class<?>[]{Game.class},(o,m,a)->{
                switch(m.getName()) {
                    case "getTurnStepType":return pregame?null:mage.constants.PhaseStep.PRECOMBAT_MAIN;
                    case "getTurnNum":return 1;
                    case "getPhase":return null;
                    case "getStartingLife":return 20;
                    case "getBattlefield":return root.state.getBattlefield();
                    case "getStack":return root.state.getStack();
                    case "getExile":return root.state.getExile();
                    case "getOpponents":return Collections.singleton(root.other.getId());
                    case "getActivePlayerId":return player.getId();
                    case "getStartingPlayerId":return player.getId();
                    case "getRangeOfInfluence":return mage.constants.RangeOfInfluence.ALL;
                    case "getMulligan":return mulligan;
                    case "firePriorityEvent":return null;
                    case "resumeTimer":case "pauseTimer":case "pause":return null;
                    case "resume":resumes++;if(resumeWork!=null)resumeWork.run();return null;
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
            try {
                mage.player.spellbench.observe.Observation visible=mage.player.spellbench.observe.ObservationBuilder
                        .forSession(game,new byte[32],flags()).build("p0","p0",Collections.emptyList());
                Set<UUID> publicIds=new LinkedHashSet<>(player.getHand());publicIds.addAll(player.getGraveyard());
                for(UUID id:publicIds) {
                    String alias=Json.str(Json.obj(visible.reference(id)),"object_id");
                    aliases.put(id,alias);world.bind(alias,id);
                }
            } catch(Exception failure) {throw new AssertionError(failure);}
            registry=new JackPermittedWorlds(new OriginalNeuralSelection.Session(backend,backend.profile(),backend.seed(),()->10));
            registry.register(world,aliases,g->{
                Map<UUID,Map<String,Object>> rows=new LinkedHashMap<>();
                for(Map.Entry<UUID,String> e:aliases.entrySet()) rows.put(e.getKey(),Json.map("object_id",e.getValue(),"card_name",root.cards.get(e.getKey()).getName()));
                return rows;
            });
            ability=JackRootDecisionCheck.land(player.getHand().iterator().next(),0);
            player.playable=ability;
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
            Map<String,Object> flags=flags();
            try {
                return Json.map("acting_seat","p0","context",Json.map("kind","choice","source",null),
                        "observation",RoundTrip.project(world,flags,"p0",Collections.emptyList()),"x_observation_flags",flags,"candidates",offered);
            } catch(Exception failure) {throw new AssertionError(failure);}
        }
        Map<String,Object> record(boolean prefix) {
            Map<String,Object> root=decision("use");Json.obj(root,"context").put("kind","priority");
            root.put("candidates",Arrays.asList(Json.map("candidate_id",1L,"semantic",Json.map("kind","play_land","source",
                    new spellbench.kit.core.ObsIndex(Json.obj(root,"observation")).ref(world.uuidToId.get(ability.getSourceId())),"face",0L))));
            Map<String,Object> selected=Json.map("candidate_id",1L,"semantic_echo",Json.copy(Json.obj(Json.obj(Json.arr(root,"candidates").get(0)),"semantic")));
            List<Object> targets=new ArrayList<>();spellbench.kit.core.ObsIndex index=new spellbench.kit.core.ObsIndex(Json.obj(root,"observation"));
            for(UUID id:player.queuedOriginalTargets(world.game))targets.add(index.ref(world.uuidToId.get(id)));
            List<Object> earlier=new ArrayList<>();
            if(prefix) earlier.add(Json.map("decision",decision("use"),"selection",Json.map("candidate_id",7L,"semantic_echo",
                    Json.copy(Json.obj(Json.obj(Json.arr(decision("use"),"candidates").get(1)),"semantic")))));
            return Json.map("game_start",Json.map("seat","p0","agent_seed",27L),"decision",decision("x"),
                    "anchor",Json.map("decision",root,"selection",selected,"priority_pass_after_activation",false,
                            "original_priority_state",Json.map("alternatives",Collections.emptyList(),"targets",targets)),
                    "replay",Json.map("earlier",earlier,"priority_passes",Collections.emptyList()));
        }
        JackDialogReplay control(Map<String,Object> record) {
            return new JackDialogReplay(world,record,(w,d)->{require(w==world,"projection used another world");compares++;});
        }
        Map<String,Object> modeDecision(int count) {
            List<Mode> available=new ArrayList<>();
            for(int i=0;i<count;i++) available.add(new Mode(new mage.abilities.effects.common.InfoEffect("mode "+i)));
            player.modes=new Modes() {
                @Override public List<Mode> getAvailableModes(Ability source,Game game) {return new ArrayList<>(available);}
            };
            player.modes.clear();
            player.modes.setMinModes(count==0?0:1);player.modes.setMaxModes(1);
            for(Mode mode:available) player.modes.addMode(mode);
            player.modes.clearSelectedModes();
            player.modeSource=(Ability)Proxy.newProxyInstance(Ability.class.getClassLoader(),new Class<?>[]{Ability.class},(o,m,a)->{
                if("getControllerId".equals(m.getName())) return player.getId();
                try{return m.invoke(ability,a);} catch(InvocationTargetException failure) {throw failure.getCause();}
            });
            Map<String,Object> decision=decision("use");
            Object source=new spellbench.kit.core.ObsIndex(Json.obj(decision,"observation")).ref(world.uuidToId.get(ability.getSourceId()));
            Json.obj(decision,"context").put("source",source);
            List<Object> offered=new ArrayList<>();
            for(int i=count-1;i>=0;i--) offered.add(Json.map("candidate_id",100L+i,"semantic",Json.map(
                    "kind","choose_spell_mode","source",source,"mode_index",(long)i,"mode_count",(long)count,
                    "selected_count",0L,"minimum",1L,"maximum",1L)));
            if(count==0) offered.add(Json.map("candidate_id",900L,"semantic",Json.map(
                    "kind","finish_selection","source",source,"purpose","modes","selected_count",0L)));
            decision.put("candidates",offered);return decision;
        }
        Map<String,Object> modeRecord(int count,boolean prefix) {
            Map<String,Object> record=record(false),modeDecision=modeDecision(count);
            if(prefix) {
                Map<String,Object> chosen=Json.obj(Json.arr(modeDecision,"candidates").get(count==0?0:Math.max(0,count-64)));
                Json.obj(record,"replay").put("earlier",Arrays.asList(Json.map("decision",modeDecision,"selection",Json.map(
                        "candidate_id",chosen.get("candidate_id"),"semantic_echo",Json.copy(chosen.get("semantic"))))));
                player.modePrefix=true;
            } else {record.put("decision",modeDecision);player.mode=true;}
            return record;
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
        Case production=new Case();production.player.cost=true;Map<String,Object> nativeRecord=production.record(false);
        Map<String,Object> anchor=Json.obj(nativeRecord,"anchor"),rootDecision=Json.obj(anchor,"decision");
        Method getter=OriginalCallbackPlayer.class.getSuperclass().getDeclaredMethod("originalPriorityRules");getter.setAccessible(true);
        Object rules=getter.invoke(production.player);Field alternatives=rules.getClass().getDeclaredField("validAlternativeCosts");alternatives.setAccessible(true);
        @SuppressWarnings("unchecked") Map<UUID,Set<String>> validated=(Map<UUID,Set<String>>)alternatives.get(rules);
        validated.put(production.ability.getSourceId(),Collections.singleton("1"));
        Map<String,Object> recorded=JackPriorityState.capture(production.world,rootDecision,rules);validated.clear();
        anchor.put("original_priority_state",recorded);
        require(JackOriginalBridgeMain.reconstructionDecision(nativeRecord)==rootDecision,"production callback reconstructed the current callback instead of its anchor");
        Map<String,Object> bridged=JackOriginalBridgeMain.choose(production.world,nativeRecord);
        require(Long.valueOf(23).equals(Json.obj(bridged,"selection").get("candidate_id")) && production.backend.calls==1
                && production.player.entered==1 && !production.backend.closed,"production bridge changed the original activation or inference stream");
        production.registry.close();
        Case missing=new Case();Map<String,Object> missingRecord=missing.record(false);Json.obj(missingRecord,"anchor").remove("original_priority_state");
        refused(()->{try {JackOriginalBridgeMain.choose(missing.world,missingRecord);} catch(Exception failure) {throw new IllegalArgumentException(failure);}});
        require(missing.backend.closed && missing.backend.calls==0,"missing original priority state inferred or retained the model");
        Case aliased=new Case();Map<String,Object> aliasedRecord=aliased.record(false);
        Map<String,Object> badState=Json.obj(Json.obj(aliasedRecord,"anchor"),"original_priority_state");
        badState.put("alternatives",Arrays.asList(Json.map("source",Json.map("object_id","foreign"),"choices",Arrays.asList("1"))));
        refused(()->{try {JackOriginalBridgeMain.choose(aliased.world,aliasedRecord);} catch(Exception failure) {throw new IllegalArgumentException(failure);}});
        require(aliased.backend.closed && aliased.backend.calls==0,"foreign original priority state inferred or retained the model");
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
        for(int count:new int[]{0,1,2,70}) {
            Case modes=new Case();Map<String,Object> modeRecord=modes.modeRecord(count,false);
            Map<String,Object> modeResult=JackOriginalBridgeMain.choose(modes.world,modeRecord);
            require(Long.valueOf(count==0?900:100+Math.min(count,64)-1).equals(Json.obj(modeResult,"selection").get("candidate_id"))
                    && modes.backend.calls==(count<2?0:1) && !modes.backend.closed,
                    "original mode replay changed forced handling, order, 64-slot cap or draw count");
            modes.registry.close();
            Case recordedMode=new Case();modeRecord=recordedMode.modeRecord(count,true);
            modeResult=JackOriginalBridgeMain.choose(recordedMode.world,modeRecord);
            require(recordedMode.backend.calls==1 && Long.valueOf(1).equals(modeResult.get("original_dialog_prefix_replayed"))
                    && (count==0?recordedMode.player.earlierMode==null:
                        recordedMode.player.earlierMode==new ArrayList<>(recordedMode.player.modes.values()).get(Math.min(count,64)-1))
                    && !recordedMode.backend.closed,"recorded mode prefix consumed another draw or applied a different mode");
            recordedMode.registry.close();
        }
        Case wrongMode=new Case();Map<String,Object> wrongModeRecord=wrongMode.modeRecord(2,false);
        Json.obj(Json.obj(Json.arr(Json.obj(wrongModeRecord,"decision"),"candidates").get(0)),"semantic").put("mode_index",99L);
        refused(()->{try {JackOriginalBridgeMain.choose(wrongMode.world,wrongModeRecord);} catch(Exception failure) {throw new IllegalArgumentException(failure);}});
        require(wrongMode.backend.calls==0 && wrongMode.backend.closed,"invalid mode entered original inference or retained its model");
        Case wrong=new Case();Map<String,Object> record=wrong.record(false);
        Json.obj(Json.obj(Json.arr(Json.obj(record,"decision"),"candidates").get(0)),"semantic").put("source",Json.map("object_id","foreign"));
        replay=wrong.control(record);replay.bind();JackDialogReplay bad=replay;
        refused(()->bad.activate(wrong.ability));require(wrong.backend.closed && wrong.backend.calls==0,"bad binding inferred or left session open");
        Case unsupported=new Case();replay=unsupported.control(unsupported.record(false));replay.bind();
        refused(()->unsupported.player.chooseMulligan(unsupported.world.game));require(unsupported.backend.closed,"unconnected replay family ran its policy");
        Case foreign=new Case();Map<String,Object> badSeed=foreign.record(false);Json.obj(badSeed,"game_start").put("agent_seed",1L);
        refused(()->foreign.control(badSeed));require(foreign.backend.closed,"foreign constructor seed left the game-owned model open");
        System.out.println("JackDialogReplayCheck PASS: production dispatch, original activation, X, binary and mode prefixes, forced modes, 64-slot cap, copy isolation and failure closure");
    }
}
