package spellbench.kit.xmage;

import mage.MageObject;
import mage.abilities.ActivatedAbility;
import mage.abilities.Modes;
import mage.abilities.costs.CostsImpl;
import mage.abilities.costs.mana.ManaCostsImpl;
import mage.cards.Card;
import mage.constants.*;
import mage.game.Game;
import mage.target.Targets;
import spellbench.kit.core.Json;
import spellbench.kit.core.ObsIndex;
import spellbench.models.maintainer.OriginalCallbackPlayer;
import spellbench.models.maintainer.OriginalNeuralSelection;
import java.lang.reflect.*;
import java.util.*;
import static spellbench.kit.xmage.MaintainerPlayerBootstrapCheck.*;

/** Actual original root dispatch, exact wire binding and refusal, metadata only. */
public final class MaintainerRootDecisionCheck {
    static final class Viewer extends OriginalCallbackPlayer {
        final List<ActivatedAbility> playable=new ArrayList<>();
        Viewer(mage.player.ai.ComputerPlayer old) {super(old,2);}
        Viewer(Viewer old) {super(old);}
        @Override public Viewer copy() {return new Viewer(this);}
        @Override public List<ActivatedAbility> getPlayable(Game game,boolean hidden) {return new ArrayList<>(playable);}
        @Override protected List<MageObject> engineParentManaProducers(Game game) {return Collections.emptyList();}
    }
    static final class RootBackend implements OriginalNeuralSelection.Model {
        int calls,policyCalls; float[] features; boolean closed;
        public String callbackSourceSha256() {return OriginalCallbackPlayer.SOURCE_SHA256;}
        public String profile() {return OriginalNeuralSelection.GREEDY;}
        public long seed() {return 27;}
        public OriginalNeuralSelection.Prediction score(OriginalNeuralSelection.Request r,double seconds) {
            require(r.count==64 && r.minimum==1 && r.maximum==1 && "action".equals(r.head),"original priority prefix or bounds changed");
            for(int valid:r.candidateMask()) require(valid==1,"original 64-slot prefix changed");
            policyCalls++;float[] probabilities=new float[64];probabilities[63]=1;
            return new OriginalNeuralSelection.Prediction(probabilities,0);
        }
        public OriginalNeuralSelection.MulliganPrediction mulligan(float[] f,double seconds) {
            calls++;features=f;return new OriginalNeuralSelection.MulliganPrediction("keep-mull-q",1,1);
        }
        public void close() {closed=true;}
    }
    static ActivatedAbility land(UUID source,int index) {
        return (ActivatedAbility)Proxy.newProxyInstance(ActivatedAbility.class.getClassLoader(),new Class<?>[]{ActivatedAbility.class},(o,m,a)->{
            switch(m.getName()) {
                case "getSourceId":return source;
                case "getId":case "getOriginalId":return new UUID(0,index+100);
                case "getAbilityType":return AbilityType.PLAY_LAND;
                case "isUsesStack":return false;
                case "toString":case "getRule":return "metadata land "+index;
                case "getSourceObject":case "getControllerId":return null;
                case "getTargets":return new Targets();
                case "getCosts":return new CostsImpl<>();
                case "getManaCostsToPay":return new ManaCostsImpl<>();
                case "getModes":return new Modes();
                case "canActivate":return ActivatedAbility.ActivationStatus.withoutApprovingObject(true);
                case "copy":return o;
                case "hashCode":return System.identityHashCode(o);
                case "equals":return o==a[0];
                default:throw new AssertionError("unexpected root ability read: "+m.getName());
            }
        });
    }
    static final class Case {
        final Root root=new Root(); final RootBackend backend=new RootBackend();
        final Viewer player=new Viewer(root.old); final World world;
        final MaintainerPermittedWorlds registry;
        final Map<UUID,String> aliases=new LinkedHashMap<>();
        PhaseStep step=PhaseStep.PRECOMBAT_MAIN; int events;
        Case() {this(0);}
        Case(int lands) {
            root.state.getPlayers().put(player.getId(),player);
            for(int i=0;i<lands;i++) {
                Card card=new MetadataCard(player.getId(),"Forest");root.cards.put(card.getId(),card);
                player.getHand().add(card);player.playable.add(land(card.getId(),i));
            }
            Game game=(Game)Proxy.newProxyInstance(Game.class.getClassLoader(),new Class<?>[]{Game.class},(o,m,a)->{
                switch(m.getName()) {
                    case "getTurnStepType":return step;
                    case "getTurnNum":return 1;
                    case "getPhase":return null;
                    case "getActivePlayerId":return player.getId();
                    case "getStartingLife":return 20;
                    case "getBattlefield":return root.state.getBattlefield();
                    case "getStack":return root.state.getStack();
                    case "getExile":return root.state.getExile();
                    case "getRangeOfInfluence":return RangeOfInfluence.ALL;
                    case "getOpponents":return Collections.singleton(root.other.getId());
                    case "inCheckPlayableState":return false;
                    case "firePriorityEvent":events++;return null;
                    default:
                        try{return m.invoke(root.game,a);} catch(InvocationTargetException failure){throw failure.getCause();}
                }
            });
            world=new World(game,"p0",0,null);world.seatPlayer.put("p0",player.getId());world.seatPlayer.put("p1",root.other.getId());
            int index=0;
            for(UUID id:player.getHand()) {String alias="hand-"+index++;aliases.put(id,alias);world.bind(alias,id);}
            for(UUID id:player.getGraveyard()) aliases.put(id,"grave");
            OriginalNeuralSelection.Session shared=new OriginalNeuralSelection.Session(backend,backend.profile(),backend.seed(),()->10);
            registry=new MaintainerPermittedWorlds(shared);
            registry.register(world,aliases,g->{
                Map<UUID,Map<String,Object>> records=new LinkedHashMap<>();
                for(Map.Entry<UUID,String> entry:aliases.entrySet()) records.put(entry.getKey(),Json.map(
                        "object_id",entry.getValue(),"card_name",root.cards.get(entry.getKey()).getName()));
                return records;
            });
        }
        Map<String,Object> start() {return Json.map("seat","p0","agent_seed",backend.seed());}
        Map<String,Object> decision(boolean mulligan) {
            List<Object> hand=new ArrayList<>();for(UUID id:player.getHand()) hand.add(Json.map("object_id",aliases.get(id),"card_name",root.cards.get(id).getName()));
            Map<String,Object> own=Json.map("seat","p0","mulligans_taken",2L,"hand_count",(long)hand.size(),"hand",hand,
                    "battlefield",new ArrayList<>(),"graveyard",new ArrayList<>(),"exile",new ArrayList<>(),"command",new ArrayList<>());
            Map<String,Object> observation=Json.map("viewer","p0","phase_step",mulligan?"pregame":"precombat_main",
                    "players",Arrays.asList(own),"known",new ArrayList<>(),"stack",new ArrayList<>());
            List<Object> offered=new ArrayList<>();
            if(mulligan) for(boolean keep:new boolean[]{true,false}) offered.add(Json.map("candidate_id",keep?7L:8L,
                    "semantic",Json.map("kind","mulligan","keep",keep,"mulligans_taken",2L,"hand_size",1L)));
            else {
                offered.add(Json.map("candidate_id",19L,"semantic",Json.map("kind","pass")));
                for(int i=0;i<player.playable.size();i++) offered.add(Json.map("candidate_id",100L+i,
                        "semantic",Mapping.prioritySemantic(world,world.game,player.playable.get(i),new ObsIndex(observation))));
                Collections.reverse(offered);
            }
            return Json.map("acting_seat","p0","context",Json.map("kind",mulligan?"pregame":"priority"),
                    "observation",observation,"candidates",offered);
        }
    }
    public static void main(String[] args) {
        Case mull=new Case();Map<String,Object> picked=MaintainerRootDecision.choose(mull.world,mull.start(),mull.decision(true));
        require(Long.valueOf(7).equals(Json.obj(picked,"selection").get("candidate_id")) && mull.backend.calls==1
                && mull.backend.features[0]==2,"actual original mulligan was not bound to its observed count and choice");
        require(MaintainerPriorityBinding.hash(mull.decision(true)).equals(picked.get("decision_sha256")),"mulligan decision binding changed");
        mull.registry.close();
        Case pass=new Case();
        for(PhaseStep step:new PhaseStep[]{PhaseStep.UPKEEP,PhaseStep.PRECOMBAT_MAIN,PhaseStep.DECLARE_ATTACKERS,
                PhaseStep.DECLARE_BLOCKERS,PhaseStep.POSTCOMBAT_MAIN,PhaseStep.END_TURN}) {
            pass.step=step;picked=MaintainerRootDecision.choose(pass.world,pass.start(),pass.decision(false));
            require(Long.valueOf(19).equals(Json.obj(picked,"selection").get("candidate_id")) && pass.backend.calls==0,
                    "original pass-only shortcut inferred or changed choice");
            require(Boolean.FALSE.equals(picked.get("priority_pass_after_activation")),"pass selection retained a phantom activation");
        }
        require(pass.events==6,"original priority dispatch events changed");pass.registry.close();
        for(PhaseStep step:new PhaseStep[]{PhaseStep.PRECOMBAT_MAIN,PhaseStep.DECLARE_ATTACKERS,PhaseStep.DECLARE_BLOCKERS}) {
            Case active=new Case(70);active.step=step;
            picked=MaintainerRootDecision.choose(active.world,active.start(),active.decision(false));
            require(Long.valueOf(162).equals(Json.obj(picked,"selection").get("candidate_id")) && active.backend.policyCalls==1,
                    "original neural first-64 slot was reordered or mapped incorrectly");
            require(Boolean.TRUE.equals(picked.get("priority_dispatch_result")),"original activation dispatch result changed");
            require(Boolean.valueOf(step!=PhaseStep.PRECOMBAT_MAIN).equals(picked.get("priority_pass_after_activation")),
                    "original combat pass-after-activation was lost");
            active.registry.close();
        }
        Case wrong=new Case();Map<String,Object> changed=wrong.decision(true);
        Json.obj(Json.obj(Json.arr(changed,"candidates").get(0)),"semantic").put("mulligans_taken",1L);
        refused(()->MaintainerRootDecision.choose(wrong.world,wrong.start(),changed));require(wrong.backend.closed && wrong.backend.calls==0,"bad counter did not refuse/close before inference");
        Case seed=new Case();Map<String,Object> start=seed.start();start.put("agent_seed",1L);
        refused(()->MaintainerRootDecision.choose(seed.world,start,seed.decision(true)));require(seed.backend.closed,"foreign seed remained open");
        Case invalid=new Case();Map<String,Object> malformed=invalid.decision(false);
        Json.arr(malformed,"candidates").add(Json.copy(Json.arr(malformed,"candidates").get(0)));
        refused(()->MaintainerRootDecision.choose(invalid.world,invalid.start(),malformed));require(invalid.backend.closed,"ambiguous priority did not close");
        Case callback=new Case();Map<String,Object> unsupported=callback.decision(false);
        Json.obj(unsupported,"context").put("kind","choice");
        refused(()->MaintainerRootDecision.choose(callback.world,callback.start(),unsupported));require(callback.backend.closed,"unconnected callback silently substituted a choice");
        Case constructor=new Case();refused(()->MaintainerRootDecision.choose(constructor.world,null,constructor.decision(true)));
        require(constructor.backend.closed,"invalid root construction did not close the owned session");
        System.out.println("MaintainerRootDecisionCheck PASS: actual original mulligan/priority roots, exact choices, pass shortcuts and failure closure");
    }
}
