package spellbench.kit.xmage;

import mage.abilities.*;
import mage.abilities.common.SimpleActivatedAbility;
import mage.abilities.costs.mana.GenericManaCost;
import mage.abilities.effects.OneShotEffect;
import mage.constants.*;
import mage.game.Game;
import mage.game.stack.StackAbility;
import mage.util.*;
import spellbench.kit.core.Json;
import spellbench.kit.core.ObsIndex;
import java.lang.reflect.*;
import java.util.*;
import static spellbench.kit.xmage.JackPlayerBootstrapCheck.*;

/** Independent parent oracle and SeatPlayer-shaped wire lifecycle on metadata worlds. */
public final class JackTargetAmountCheck {
    static final class Effect extends OneShotEffect {
        Effect(String rule) {super(Outcome.Benefit);staticText="resolve "+rule;}
        Effect(Effect old) {super(old);}
        @Override public Effect copy() {return new Effect(this);}
        @Override public boolean apply(Game game,Ability source) {throw new AssertionError("metadata effect resolved");}
    }
    static final class Source extends SimpleActivatedAbility {
        Source(String purpose) {
            super(Zone.HAND,new Effect(purpose),new GenericManaCost(0));id=new UUID(0,808);
        }
    }
    static final class Amount extends mage.target.common.TargetAnyTargetAmount {
        final List<UUID> available;final int total;int left,prepared;
        Amount(int total,int min,int max,List<UUID> available) {super(total,min,max);this.total=total;this.available=new ArrayList<>(available);}
        Amount(Amount old) {
            this(old.total,old.getMinNumberOfTargets(),old.getMaxNumberOfTargets(),old.available);
            targets.putAll(old.targets);left=old.left;prepared=old.prepared;
        }
        @Override public Amount copy() {return new Amount(this);}
        @Override public void prepareAmount(Ability source,Game game) {prepared++;left=total;}
        @Override public int getAmountRemaining() {return left;}
        @Override public UUID getAffectedAbilityControllerId(UUID id) {return id;}
        @Override public Set<UUID> possibleTargets(UUID id,Ability source,Game game,Set<UUID> from) {return new LinkedHashSet<>(available);}
        @Override public boolean canTarget(UUID player,UUID id,Ability source,Game game) {return available.contains(id);}
        @Override public boolean isChoiceCompleted(UUID id,Ability source,Game game,mage.cards.Cards from) {return isChosen(game);}
        @Override public boolean isChosen(Game game) {return left==0 && targets.size()>=getMinNumberOfTargets();}
        @Override public void addTarget(UUID id,int amount,Ability source,Game game) {
            require(amount>0 && amount<=left && available.contains(id),"invalid original metadata allocation");targets.put(id,amount);left-=amount;
        }
        @Override public void addTarget(UUID id,Ability source,Game game) {targets.put(id,0);}
        @Override public void setTargetAmount(UUID id,int amount,Ability source,Game game) {
            require(targets.containsKey(id),"wire amount recipient not selected");left-=amount-targets.get(id);targets.put(id,amount);
        }
        void reset() {clearChosen();left=0;prepared=0;}
    }
    static final class Menu {
        final JackDialogReplayCheck.Case c=new JackDialogReplayCheck.Case(1,true);
        final Outcome outcome;final String purpose;final boolean stacked;
        Amount target;Ability source;
        final List<UUID> order=new ArrayList<>();final List<Integer> values=new ArrayList<>();
        final List<Map<String,Object>> decisions=new ArrayList<>(),selections=new ArrayList<>();
        Menu(int total,int min,Outcome outcome,String purpose,boolean stacked) throws Exception {
            this.outcome=outcome;this.purpose=purpose;this.stacked=stacked;
            c.player.initLife(20);c.root.other.initLife(20);
            List<UUID> available=Arrays.asList(c.player.getId(),c.root.other.getId());target=new Amount(total,min,2,available);
            SimpleActivatedAbility ability=new Source(purpose);
            ability.setControllerId(c.player.getId());ability.setSourceId(c.ability.getSourceId());ability.addTarget(target);source=ability;
            if(stacked) {
                StackAbility stack=new StackAbility(ability,c.player.getId());c.root.state.getStack().push(stack);source=stack;
                target=(Amount)stack.getStackAbility().getTargets().get(0);
                mage.player.spellbench.observe.Observation visible=mage.player.spellbench.observe.ObservationBuilder
                        .forSession(c.world.game,new byte[32],JackDialogReplayCheck.flags()).build("p0","p0",Collections.emptyList());
                c.world.bind(Json.str(Json.obj(visible.reference(stack.getId())),"object_id"),stack.getId());
            }
            Amount oracle=new Amount(total,min,2,available);JackAmountReplayCheck.Oracle parent=new JackAmountReplayCheck.Oracle(c.player);
            parent.admitted=(Game)Proxy.newProxyInstance(Game.class.getClassLoader(),new Class<?>[]{Game.class},(o,m,a)->{
                if("getPlayer".equals(m.getName()) && parent.getId().equals(a[0]))return parent;
                try{return m.invoke(c.world.game,a);}catch(InvocationTargetException failure){throw failure.getCause();}
            });
            require(parent.chooseTargetAmount(outcome,oracle,source,parent.admitted),"original allocation oracle failed");
            order.addAll(oracle.getTargets());for(UUID id:order)values.add(oracle.getTargetAmount(id));
            // Independently follow SeatPlayer's target loop, then its amount loop.
            target.prepareAmount(source,c.world.game);int selected=0;
            while(selected<Math.min(2,total)) {
                List<UUID> left=new ArrayList<>(available);left.removeAll(target.getTargets());if(left.isEmpty())break;
                Map<String,Object> d=c.decision("use");Object ref=sourceRef(d);List<Object> candidates=new ArrayList<>();
                for(UUID id:left) {
                    Map<String,Object> sem=Json.map("kind",stacked?"choose_target":"select_object","source",ref,
                            "selected_count",(long)selected,"minimum",(long)Math.min(min,Math.min(2,total)),"maximum",(long)Math.min(2,total));
                    if(stacked) {sem.put("slot",0L);sem.put("target",recipient(id));}else {sem.put("purpose","other");sem.put("choice",recipient(id));}
                    candidates.add(Json.map("candidate_id",100L+available.indexOf(id),"semantic",sem));
                }
                if(selected>=min) {
                    Map<String,Object> sem=Json.map("kind",stacked?"finish_target_selection":"finish_selection","source",ref,"selected_count",(long)selected);
                    if(stacked)sem.put("slot",0L);else sem.put("purpose","other");candidates.add(Json.map("candidate_id",900L,"semantic",sem));
                }
                Collections.reverse(candidates);d.put("candidates",candidates);Json.obj(d,"context").put("source",ref);decisions.add(d);
                UUID picked=selected<order.size()?order.get(selected):null;selections.add(select(d,picked==null?900L:100L+available.indexOf(picked)));
                if(picked==null)break;target.addTarget(picked,source,c.world.game);selected++;
            }
            int assigned=0;
            for(int i=0;i<order.size();i++) {
                int remaining=total-assigned,least=i==order.size()-1?remaining:1,most=remaining-(order.size()-1-i);
                Map<String,Object> d=c.decision("use");Object ref=sourceRef(d);List<Object> candidates=new ArrayList<>();
                for(int value=least;value<=most;value++)candidates.add(Json.map("candidate_id",1000L+value,"semantic",Json.map(
                        "kind","distribute","source",ref,"purpose",purpose,"recipient",recipient(order.get(i)),"amount",(long)value,"remaining",(long)remaining)));
                Collections.reverse(candidates);d.put("candidates",candidates);d.put("group",Json.map("group_id",701L,"substep_index",(long)i,"substep_count",(long)order.size()));
                Json.obj(d,"context").put("source",ref);decisions.add(d);selections.add(select(d,1000L+values.get(i)));
                target.setTargetAmount(order.get(i),values.get(i),source,c.world.game);assigned+=values.get(i);
            }
            decisions.add(c.decision("x"));target.reset();
        }
        Object sourceRef(Map<String,Object> d) {return new ObsIndex(Json.obj(d,"observation")).ref(c.world.uuidToId.get(stacked?source.getId():source.getSourceId()));}
        Object recipient(UUID id) {return Json.map("player",id.equals(c.player.getId())?"p0":"p1");}
        static Map<String,Object> select(Map<String,Object> d,long id) {
            for(Object item:Json.arr(d,"candidates")) {
                Map<String,Object> candidate=Json.obj(item);if(Long.valueOf(id).equals(candidate.get("candidate_id")))
                    return Json.map("candidate_id",id,"semantic_echo",Json.copy(candidate.get("semantic")));
            }throw new AssertionError("oracle selection absent from wire menu");
        }
        Map<String,Object> record(int prefix) {
            Map<String,Object> record=c.record(false);record.put("decision",decisions.get(prefix));List<Object> earlier=new ArrayList<>();
            for(int i=0;i<prefix;i++)earlier.add(Json.map("decision",decisions.get(i),"selection",selections.get(i)));
            Json.obj(record,"replay").put("earlier",earlier);
            c.player.activationWork=()->require(c.player.chooseTargetAmount(outcome,target,source,c.world.game),"replayed original allocation failed");return record;
        }
    }
    public static void main(String[] args) throws Exception {
        List<Object> normalized=new ArrayList<>();int cases=0;
        for(boolean stacked:new boolean[]{false,true})for(int total:new int[]{5,30})for(int min:new int[]{0,1})
            for(String purpose:new String[]{"damage","counters","other"}) {
                Outcome outcome="damage".equals(purpose)?Outcome.Damage:Outcome.Benefit;
                Menu template=new Menu(total,min,outcome,purpose,stacked);int count=template.decisions.size();template.c.registry.close();
                for(int prefix=0;prefix<count;prefix++) {
                    Menu menu=new Menu(total,min,outcome,purpose,stacked);Map<String,Object> result;
                    KitRandom random=JackAmountReplayCheck.random(19);long draws=JackAmountReplayCheck.draws(random);
                    try {result=menu.c.control(menu.record(prefix)).choose();}
                    catch(RuntimeException failure) {
                        throw new AssertionError("case stack="+stacked+" total="+total+" min="+min+" purpose="+purpose
                                +" prefix="+prefix+" actual rule="+menu.source.getRule(),failure);
                    }
                    require(Long.valueOf(prefix).equals(result.get("original_dialog_prefix_replayed")) && !menu.c.backend.closed
                            && menu.c.backend.calls==(prefix==count-1?1:0) && menu.c.backend.copies==0 && menu.target.prepared==1,
                            "divided replay changed preparation, prefix or inference ownership");
                    require(JackAmountReplayCheck.draws(random)==draws,"divided allocation consumed additional engine RNG");
                    if(prefix<count-1)require(Json.canonical(menu.selections.get(prefix)).equals(Json.canonical(result.get("selection"))),"divided replay differs from unchanged parent oracle");
                    normalized.add(Json.map("stacked",stacked,"total",(long)total,"minimum",(long)min,"purpose",purpose,"prefix",(long)prefix,
                            "selection",result.get("selection"),"model_calls",(long)menu.c.backend.calls));menu.c.registry.close();cases++;
                }
            }
        Menu consecutive=new Menu(30,1,Outcome.Damage,"damage",false);
        require(consecutive.order.size()==2,"consecutive oracle did not cover multiple recipients");
        int consecutiveChoices=2*(consecutive.decisions.size()-1);consecutive.c.registry.close();
        for(int prefix=0;prefix<=consecutiveChoices;prefix++) {
            Menu menu=new Menu(30,1,Outcome.Damage,"damage",false);int count=menu.decisions.size()-1;
            Amount second=new Amount(30,1,2,menu.target.available);Source secondSource=new Source("damage");
            secondSource.setControllerId(menu.c.player.getId());secondSource.setSourceId(menu.source.getSourceId());secondSource.addTarget(second);
            Map<String,Object> record=menu.c.record(false);List<Object> earlier=new ArrayList<>();
            for(int i=0;i<=prefix;i++) {
                Map<String,Object> d=i==2*count?menu.decisions.get(count):Json.obj(Json.copy(menu.decisions.get(i%count)));
                if(i>=count && d.get("group")!=null)Json.obj(d,"group").put("group_id",702L);
                if(i==prefix)record.put("decision",d);else earlier.add(Json.map("decision",d,"selection",menu.selections.get(i%count)));
            }
            Json.obj(record,"replay").put("earlier",earlier);
            menu.c.player.activationWork=()->{
                require(menu.c.player.chooseTargetAmount(menu.outcome,menu.target,menu.source,menu.c.world.game),"first divided group failed");
                require(menu.c.player.chooseTargetAmount(menu.outcome,second,secondSource,menu.c.world.game),"second divided group failed");
            };
            Map<String,Object> result=menu.c.control(record).choose();
            require(Long.valueOf(prefix).equals(result.get("original_dialog_prefix_replayed")) && !menu.c.backend.closed
                    && menu.c.backend.calls==(prefix==2*count?1:0) && menu.c.backend.copies==0,
                    "consecutive divided groups lost ownership: prefix="+prefix+" group choices="+count+" replayed="
                            +result.get("original_dialog_prefix_replayed")+" model="+menu.c.backend.calls+" closed="+menu.c.backend.closed);menu.c.registry.close();cases++;
        }
        JackDialogReplayCheck.Case zero=new JackDialogReplayCheck.Case();JackUnconnectedDistributionCheck.Amount empty=new JackUnconnectedDistributionCheck.Amount();
        zero.player.activationWork=()->require(!zero.player.chooseTargetAmount(Outcome.Damage,empty,zero.ability,zero.world.game),"zero amount return changed");
        Map<String,Object> zeroResult=zero.control(zero.record(false)).choose();
        require(empty.prepared==1 && zero.backend.calls==1 && !zero.backend.closed && Long.valueOf(0).equals(zeroResult.get("original_dialog_prefix_replayed")),
                "implicit zero amount swallowed or scored a wire group");zero.registry.close();cases++;
        for(String fault:new String[]{"missing","amount","recipient","group","observation","history","hidden","source","stack-amount","target-bounds"}) {
            Menu menu=new Menu(30,1,Outcome.Damage,"damage","stack-amount".equals(fault));int prefix=2;Map<String,Object> record=menu.record(prefix);
            if("missing".equals(fault))Json.arr(Json.obj(record,"decision"),"candidates").remove(0);
            if("amount".equals(fault))Json.obj(Json.obj(Json.arr(Json.obj(record,"decision"),"candidates").get(0)),"semantic").put("remaining",29L);
            if("recipient".equals(fault))Json.obj(Json.obj(Json.arr(Json.obj(record,"decision"),"candidates").get(0)),"semantic").put("recipient",Json.map("player","p0"));
            if("group".equals(fault))Json.obj(Json.obj(record,"decision"),"group").put("substep_count",3L);
            if("observation".equals(fault))Json.obj(Json.obj(record,"decision"),"observation").put("turn",2L);
            if("hidden".equals(fault))menu.target.available.add(menu.c.root.other.getHand().iterator().next());
            if("source".equals(fault))menu.source.setSourceId(menu.c.root.other.getHand().iterator().next());
            if("stack-amount".equals(fault))Json.obj(Json.arr(Json.obj(Json.obj(record,"decision"),"observation"),"stack").get(0)).put("divided",Arrays.asList(1L,0L));
            if("target-bounds".equals(fault)) {
                Map<String,Object> d=Json.obj(Json.obj(Json.arr(Json.obj(record,"replay"),"earlier").get(0)),"decision");
                Json.obj(Json.obj(Json.arr(d,"candidates").get(0)),"semantic").put("maximum",3L);
            }
            if("history".equals(fault)) {
                Map<String,Object> past=Json.obj(Json.arr(Json.obj(record,"replay"),"earlier").get(0));past.put("selection",Menu.select(Json.obj(past,"decision"),100L));
            }
            refused(()->menu.c.control(record).choose());require(menu.c.backend.calls==0 && menu.c.backend.copies==0 && menu.c.backend.closed,
                    "malformed divided replay scored or retained its session");menu.c.registry.close();cases++;
        }
        System.out.println("JackTargetAmountCheck PASS: "+cases+" metadata cases; unchanged parent allocation, complete public menus and every prefix");
        System.out.println(Json.canonical(normalized));
    }
}
