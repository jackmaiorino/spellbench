package spellbench.kit.xmage;

import mage.abilities.Ability;
import mage.cards.*;
import mage.constants.*;
import mage.game.Game;
import mage.game.combat.CombatGroup;
import mage.game.permanent.*;
import spellbench.kit.core.Json;
import spellbench.kit.core.ObsIndex;
import spellbench.models.maintainer.OriginalCallbackPlayer;
import spellbench.models.maintainer.OriginalNeuralSelection;
import java.lang.reflect.*;
import java.util.*;
import static spellbench.kit.xmage.MaintainerPlayerBootstrapCheck.*;

/** Actual original combat loops, with explicit metadata legality and declarations. */
public final class MaintainerCombatPlanCheck {
    static final class Body extends CardImpl {
        Body(UUID owner,int i) {
            super(owner,new CardSetInfo(i%2==0?"Forest":"Island","META","1",Rarity.COMMON),new CardType[]{CardType.CREATURE},"");
            objectId=new UUID(0,2000+i);power=new mage.MageInt(i+1);toughness=new mage.MageInt(3);
        }
        Body(Body old) {super(old);}
        @Override public Body copy() {return new Body(this);}
    }
    static final class Creature extends PermanentCard {
        boolean eligible=true;
        Creature(Card card,UUID owner,Game game) {super(card,owner,game);objectId=card.getId();}
        @Override public boolean canAttack(UUID target,Game game) {return eligible;}
        @Override public boolean canBlock(UUID target,Game game) {return eligible;}
    }
    static final class Backend implements OriginalNeuralSelection.Model {
        boolean closed,doneFirst;int calls;
        final List<Object> rounds=new ArrayList<>();
        public String callbackSourceSha256() {return OriginalCallbackPlayer.SOURCE_SHA256;}
        public String profile() {return OriginalNeuralSelection.GREEDY;}
        public long seed() {return 27;}
        public OriginalNeuralSelection.Prediction score(OriginalNeuralSelection.Request r,double seconds) {
            calls++;require("attack".equals(r.head)||"block".equals(r.head),"combat changed its trained head");
            rounds.add(Json.map("head",r.head,"count",(long)r.count,"minimum",(long)r.minimum,"maximum",(long)r.maximum));
            float[] p=new float[64];
            for(int i=0;i<r.count;i++)p[i]=(doneFirst && i==r.count-1?100:r.count-i)/100f;
            return new OriginalNeuralSelection.Prediction(p,0);
        }
        public void close() {closed=true;}
    }
    static final class Viewer extends OriginalCallbackPlayer {
        boolean nested;final List<Permanent> blockers=new ArrayList<>();final List<Object> declared=new ArrayList<>();
        Viewer(mage.player.ai.ComputerPlayer old) {super(old,0);}
        Viewer(Viewer old) {super(old);}
        @Override public Viewer copy() {return new Viewer(this);}
        @Override public List<Permanent> getAvailableBlockers(Game game) {return new ArrayList<>(blockers);}
        @Override public void declareAttacker(UUID id,UUID defender,Game game,boolean late) {
            if(nested)chooseUse(Outcome.Benefit,"nested combat cost",null,game);
            CombatGroup group=new CombatGroup(defender,game.getPermanent(defender)!=null,game.getPlayer(defender)!=null?defender:game.getPermanent(defender).getControllerId());
            group.getAttackers().add(id);game.getCombat().getGroups().add(group);declared.add(id);
        }
        @Override public void declareBlocker(UUID player,UUID id,UUID attacker,Game game) {
            game.getCombat().findGroup(attacker).getBlockers().add(id);declared.add(attacker);
        }
    }
    static final class Case {
        final Root root=new Root();final Viewer player=new Viewer(root.old);final Backend backend=new Backend();
        final World world;final MaintainerPermittedWorlds registry;final Map<UUID,String> aliases=new LinkedHashMap<>();
        final Set<UUID> hidden=new HashSet<>();
        final mage.game.combat.Combat combat=new mage.game.combat.Combat() {
            final Set<UUID> ordered=new LinkedHashSet<>();
            @Override public Set<UUID> getDefenders() {return ordered;}
        };
        final List<Creature> own=new ArrayList<>(),other=new ArrayList<>();final boolean attack;
        Case(boolean attack,int count,boolean multiDefender) throws Exception {
            this.attack=attack;root.state.getPlayers().put(player.getId(),player);
            hidden.addAll(player.getLibrary().getCardList());
            Card secret=new MetadataCard(root.other.getId(),"Secret opponent card");root.cards.put(secret.getId(),secret);root.other.getHand().add(secret);hidden.add(secret.getId());
            Game game=(Game)Proxy.newProxyInstance(Game.class.getClassLoader(),new Class<?>[]{Game.class},(o,m,a)->{
                switch(m.getName()) {
                    case "getTurnStepType":return attack?PhaseStep.DECLARE_ATTACKERS:PhaseStep.DECLARE_BLOCKERS;
                    case "getTurnNum":return 1;
                    case "getPhase":return null;
                    case "getStartingLife":return 20;
                    case "getBattlefield":return root.state.getBattlefield();
                    case "getCombat":return combat;
                    case "getPlayerList":return root.state.getPlayerList();
                    case "getPermanent":return root.state.getBattlefield().getPermanent((UUID)a[0]);
                    case "getObject":
                        if(hidden.contains(a[0]))throw new AssertionError("combat read a hidden card");
                        Permanent permanent=root.state.getBattlefield().getPermanent((UUID)a[0]);
                        return permanent==null?root.cards.get(a[0]):permanent;
                    case "getCard":
                        if(hidden.contains(a[0]))throw new AssertionError("combat read a hidden card");
                        return root.cards.get(a[0]);
                    case "getStack":return root.state.getStack();
                    case "getExile":return root.state.getExile();
                    case "getOpponents":return Collections.singleton(root.other.getId());
                    case "getActivePlayerId":return attack?player.getId():root.other.getId();
                    case "getRangeOfInfluence":return RangeOfInfluence.ALL;
                    case "getMulligan":return new mage.game.mulligan.LondonMulligan(0);
                    default:try{return m.invoke(root.game,a);}catch(InvocationTargetException failure){throw failure.getCause();}
                }
            });
            for(int i=0;i<count;i++)own.add(add(player.getId(),i,game));
            for(int i=0;i<(attack?multiDefender?1:0:2);i++)other.add(add(root.other.getId(),100+i,game));
            combat.getDefenders().add(attack?root.other.getId():player.getId());
            if(attack && multiDefender)combat.getDefenders().add(other.get(0).getId());
            if(!attack) {
                player.blockers.addAll(own);
                for(Creature p:other) {
                    p.setAttacking(new mage.MageObjectReference(player.getId()));
                    CombatGroup group=new CombatGroup(player.getId(),false,player.getId());group.getAttackers().add(p.getId());combat.getGroups().add(group);
                }
            }
            world=new World(game,"p0",0,null);world.seatPlayer.put("p0",player.getId());world.seatPlayer.put("p1",root.other.getId());
            mage.player.spellbench.observe.Observation visible=mage.player.spellbench.observe.ObservationBuilder.forSession(game,new byte[32],MaintainerDialogReplayCheck.flags()).build("p0","p0",Collections.emptyList());
            Set<UUID> publicIds=new LinkedHashSet<>(player.getHand());publicIds.addAll(player.getGraveyard());
            for(Permanent p:root.state.getBattlefield().getAllActivePermanents())publicIds.add(p.getId());
            for(UUID id:publicIds) {String alias=Json.str(Json.obj(visible.reference(id)),"object_id");aliases.put(id,alias);world.bind(alias,id);}
            registry=new MaintainerPermittedWorlds(new OriginalNeuralSelection.Session(backend,backend.profile(),backend.seed(),()->10));
            registry.register(world,aliases,g->{Map<UUID,Map<String,Object>> rows=new LinkedHashMap<>();
                for(Map.Entry<UUID,String> entry:aliases.entrySet())rows.put(entry.getKey(),Json.map("object_id",entry.getValue(),"card_name",root.cards.get(entry.getKey()).getName()));return rows;});
        }
        Creature add(UUID owner,int i,Game game) {
            Body card=new Body(owner,i);root.cards.put(card.getId(),card);Creature p=new Creature(card,owner,game);
            root.state.getBattlefield().addPermanent(p);root.state.setZone(p.getId(),Zone.BATTLEFIELD);return p;
        }
        Map<String,Object> decision() throws Exception {
            Map<String,Object> obs=RoundTrip.project(world,MaintainerDialogReplayCheck.flags(),"p0",Collections.emptyList());ObsIndex index=new ObsIndex(obs);
            Map<String,Object> creature=index.ref(aliases.get(own.get(0).getId()));List<Object> menu=new ArrayList<>();
            String name=attack?"attacker":"blocker",ref=attack?"defender":"attacker",kind=attack?"declare_attack":"declare_block";
            menu.add(Json.map("candidate_id",10L,"semantic",Json.map("kind",kind,name,creature,ref,null)));
            if(attack) {
                menu.add(Json.map("candidate_id",11L,"semantic",Json.map("kind",kind,name,creature,ref,Json.map("player","p1"))));
                if(!other.isEmpty())menu.add(Json.map("candidate_id",12L,"semantic",Json.map("kind",kind,name,creature,ref,Json.map("object",index.ref(aliases.get(other.get(0).getId()))))));
            } else for(int i=0;i<other.size();i++)menu.add(Json.map("candidate_id",11L+i,"semantic",Json.map("kind",kind,name,creature,ref,index.ref(aliases.get(other.get(i).getId())))));
            long slots=0;
            for(Creature p:own)slots+=attack?1:p.getMaxBlocks()==0?other.size():Math.min(other.size(),p.getMaxBlocks());
            return Json.map("acting_seat","p0","seat_step",0L,"context",Json.map("kind","choice","rewind",false),"observation",obs,
                    "group",Json.map("group_id",88L,"substep_index",0L,"substep_count",slots),"x_observation_flags",MaintainerDialogReplayCheck.flags(),"candidates",menu);
        }
    }
    public static void main(String[] args) throws Exception {
        List<Object> rows=new ArrayList<>();
        for(boolean attack:new boolean[]{true,false})for(boolean done:new boolean[]{false,true}) {
            Case c=new Case(attack,2,attack);c.backend.doneFirst=done;Map<String,Object> d=c.decision();
            Map<String,Object> result=MaintainerOriginalBridgeMain.choose(c.world,Json.map("game_start",Json.map("seat","p0","agent_seed",27L),"decision",d));
            require(Boolean.TRUE.equals(result.get("original_combat_path")),"original combat callback was not reached");
            require(Json.arr(result,"combat_slots").equals(Arrays.asList(c.aliases.get(c.own.get(0).getId()),c.aliases.get(c.own.get(1).getId()))),"engine slot order changed");
            require(Json.arr(result,"pairs").size()==(done?0:2),"DONE or original creature declarations changed");
            require(c.backend.calls==(attack&&!done?3:attack?1:done?2:1),"original defender or shrinking blocker draw count changed");
            require(Long.valueOf(done?10:attack?11:12).equals(Json.obj(result,"selection").get("candidate_id")),"original first combat assignment mapped to another wire choice");
            if(!attack&&!done)require(c.player.declared.equals(Arrays.asList(c.other.get(1).getId(),c.other.get(1).getId())),"blockers did not follow descending attacker power/removal");
            rows.add(Json.map("attack",attack,"done_first",done,"candidate_id",Json.obj(result,"selection").get("candidate_id"),"pairs",(long)Json.arr(result,"pairs").size(),"rounds",c.backend.rounds));c.registry.close();
        }
        for(int max:new int[]{2,0})for(boolean done:new boolean[]{false,true}) {
            Case c=new Case(false,2,false);c.own.get(0).setMaxBlocks(max);c.backend.doneFirst=done;
            Map<String,Object> result=MaintainerRootDecision.choose(c.world,Json.map("seat","p0","agent_seed",27L),c.decision());
            require(Json.arr(result,"combat_slots").equals(Arrays.asList(c.aliases.get(c.own.get(0).getId()),c.aliases.get(c.own.get(0).getId()),c.aliases.get(c.own.get(1).getId()))),"additional/unlimited block slot schedule changed");
            require(Json.arr(result,"pairs").size()==(done?0:2) && c.backend.calls==(done?2:1),"extra engine slots changed the original policy or draw count");
            rows.add(Json.map("block_max",(long)max,"done_first",done,"slots",(long)Json.arr(result,"combat_slots").size(),"pairs",(long)Json.arr(result,"pairs").size(),"rounds",c.backend.rounds));c.registry.close();
        }
        for(String fault:new String[]{"source","hidden","duplicate","group","slot-count","first-slot","nested"}) {
            Case c=new Case(true,2,false);Map<String,Object> d=c.decision();
            if("source".equals(fault))Json.obj(Json.obj(Json.arr(d,"candidates").get(0)),"semantic").put("attacker",Json.map("object_id","unknown"));
            if("hidden".equals(fault))Json.obj(Json.obj(Json.arr(d,"candidates").get(1)),"semantic").put("defender",Json.map("object",Json.map("object_id","hidden")));
            if("duplicate".equals(fault))Json.arr(d,"candidates").add(Json.copy(Json.arr(d,"candidates").get(0)));
            if("group".equals(fault))Json.obj(d,"group").put("substep_index",1L);
            if("slot-count".equals(fault))Json.obj(d,"group").put("substep_count",3L);
            if("first-slot".equals(fault)) {
                Map<String,Object> ref=new ObsIndex(Json.obj(d,"observation")).ref(c.aliases.get(c.own.get(1).getId()));
                for(Object item:Json.arr(d,"candidates"))Json.obj(Json.obj(item),"semantic").put("attacker",ref);
            }
            c.player.nested="nested".equals(fault);
            refused(()->MaintainerRootDecision.choose(c.world,Json.map("seat","p0","agent_seed",27L),d));
            require(c.backend.closed && c.backend.calls==("nested".equals(fault)?1:0),"malformed/nested combat advanced the model or left it open");
        }
        System.out.println(Json.canonical(rows));System.out.println("MaintainerCombatPlanCheck PASS: actual original attack/defender/block loops, DONE, descending threats, blocker removal, exact engine slots including additional/unlimited blocks, wire binding and failure closure; metadata legality/declarations only");
    }
}
