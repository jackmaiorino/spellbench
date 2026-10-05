package spellbench.kit.xmage;

import mage.abilities.*;
import mage.cards.*;
import mage.constants.*;
import mage.filter.FilterCard;
import mage.game.Game;
import mage.target.TargetCard;
import mage.target.common.TargetCardInHand;
import spellbench.kit.core.Json;
import spellbench.kit.core.ObsIndex;
import java.lang.reflect.*;
import java.util.*;
import static spellbench.kit.xmage.JackPlayerBootstrapCheck.*;

/** Actual original neural groups and inherited sorting on named metadata cards. */
public final class JackCardReplayCheck {
    static final class PlainTarget extends TargetCard {
        final List<UUID> options;
        PlainTarget(List<UUID> options,int min,int max) {super(min,max,Zone.HAND,new FilterCard());this.options=options;}
        @Override public Set<UUID> possibleTargets(UUID player,Ability source,Game game,Set<UUID> supplied) {
            Set<UUID> result=new LinkedHashSet<>(options);result.removeAll(getTargets());if(supplied!=null)result.retainAll(supplied);return result;
        }
        @Override public boolean canTarget(UUID player,UUID id,Ability source,Game game) {return options.contains(id);}
        @Override public void add(UUID id,Game game) {targets.put(id,0);chosen=true;}
        @Override public void addTarget(UUID id,Ability source,Game game) {add(id,game);}
        @Override public boolean isChoiceCompleted(UUID player,Ability source,Game game,Cards cards) {
            return !targets.isEmpty() && (targets.size()>=getMaxNumberOfTargets() || possibleTargets(player,source,game,cards).isEmpty());
        }
    }
    static final class HandTarget extends TargetCardInHand {
        final List<UUID> options;
        HandTarget(List<UUID> options,int min,int max) {super(min,max,new FilterCard());this.options=options;}
        @Override public Set<UUID> possibleTargets(UUID player,Ability source,Game game,Set<UUID> supplied) {
            Set<UUID> result=new LinkedHashSet<>(options);result.removeAll(getTargets());if(supplied!=null)result.retainAll(supplied);return result;
        }
        @Override public boolean canTarget(UUID player,UUID id,Ability source,Game game) {return options.contains(id);}
        @Override public void add(UUID id,Game game) {targets.put(id,0);chosen=true;}
        @Override public void addTarget(UUID id,Ability source,Game game) {add(id,game);}
        @Override public boolean isChoiceCompleted(UUID player,Ability source,Game game,Cards cards) {
            return !targets.isEmpty() && (targets.size()>=getMaxNumberOfTargets() || possibleTargets(player,source,game,cards).isEmpty());
        }
    }
    static Map<String,Object> decision(JackDialogReplayCheck.Case c,TargetCard target,List<UUID> possible,int count,boolean stop) {
        Map<String,Object> decision=c.decision("use");
        Map<String,Object> source=new ObsIndex(Json.obj(decision,"observation")).ref(c.world.uuidToId.get(c.ability.getSourceId()));
        Json.obj(decision,"context").put("source",source);List<Object> offered=new ArrayList<>();
        List<UUID> order=new ArrayList<>(possible);if(stop)order.add(0,null);
        for(int i=order.size()-1;i>=0;i--) {
            UUID id=order.get(i);Map<String,Object> semantic=Json.map("kind",id==null?"finish_selection":"select_object",
                    "source",source,"purpose","cards","selected_count",(long)count);
            if(id!=null)semantic.putAll(Json.map("choice",Json.map("object",new ObsIndex(Json.obj(decision,"observation"))
                    .ref(c.world.uuidToId.get(id))),"minimum",(long)target.getMinNumberOfTargets(),"maximum",(long)target.getMaxNumberOfTargets()));
            offered.add(Json.map("candidate_id",100L+i,"semantic",semantic));
        }
        decision.put("candidates",offered);return decision;
    }
    static Map<String,Object> selected(Map<String,Object> decision,UUID id,JackDialogReplayCheck.Case c) {
        for(Object item:Json.arr(decision,"candidates")) {
            Map<String,Object> candidate=Json.obj(item),semantic=Json.obj(candidate,"semantic");
            if(id==null?"finish_selection".equals(semantic.get("kind")):c.world.uuidToId.get(id).equals(
                    Json.str(Json.obj(Json.obj(semantic,"choice"),"object"),"object_id")))
                return Json.map("candidate_id",candidate.get("candidate_id"),"semantic_echo",Json.copy(semantic));
        }
        throw new AssertionError("metadata card missing from wire menu");
    }
    static Map<String,Object> request(JackDialogReplayCheck.Case c,TargetCard target,List<UUID> supplied,boolean parent,Outcome outcome) {
        c.player.cards=new CardsImpl(supplied);c.player.cardTarget=target;c.player.parentCards=parent;c.player.cardOutcome=outcome;
        c.player.playable=(ActivatedAbility)Proxy.newProxyInstance(ActivatedAbility.class.getClassLoader(),new Class<?>[]{ActivatedAbility.class},(o,m,a)->{
            if("getControllerId".equals(m.getName()))return c.player.getId();if("copy".equals(m.getName()))return o;
            try{return m.invoke(c.ability,a);}catch(InvocationTargetException failure){throw failure.getCause();}
        });
        Map<String,Object> record=c.record(false);record.put("decision",decision(c,target,supplied,0,target.getMinNumberOfTargets()==0));return record;
    }
    static List<List<UUID>> groups(JackDialogReplayCheck.Case c,List<UUID> options,boolean dedup) {
        Map<String,List<UUID>> grouped=new LinkedHashMap<>();
        for(UUID id:options)grouped.computeIfAbsent(dedup?c.root.cards.get(id).getName():id.toString(),key->new ArrayList<>()).add(id);
        return new ArrayList<>(grouped.values());
    }
    public static void main(String[] args) throws Exception {
        List<Object> primary=new ArrayList<>();
        for(int count:new int[]{1,2,70})for(boolean dedup:new boolean[]{false,true})for(boolean prefix:new boolean[]{false,true}) {
            JackDialogReplayCheck.Case c=new JackDialogReplayCheck.Case(count,count==70 && dedup);
            List<UUID> options=new ArrayList<>(c.player.getHand());TargetCard target=dedup?new HandTarget(options,1,1):new PlainTarget(options,1,1);
            Map<String,Object> record=request(c,target,options,false,Outcome.Benefit),menu=Json.obj(record,"decision");
            List<List<UUID>> groups=groups(c,options,dedup);List<UUID> group=groups.get(Math.min(64,groups.size())-1);
            UUID chosen=group.get(group.size()-1);
            if(prefix) {
                Json.obj(record,"replay").put("earlier",Arrays.asList(Json.map("decision",menu,"selection",selected(menu,chosen,c))));
                record.put("decision",c.decision("x"));
            }
            Map<String,Object> result=JackOriginalBridgeMain.choose(c.world,record);
            require(c.backend.calls==(prefix?1:groups.size()==1?0:1) && c.backend.copies==(prefix?0:group.size()==1?0:1)
                    && !c.backend.closed,"card replay repeated a model/copy draw or closed its owned pause");
            require(prefix?target.getTargets().equals(Arrays.asList(chosen)):target.getTargets().isEmpty(),"card prefix changed physical selection or mutation");
            if(!prefix)require(Json.canonical(Json.obj(result,"selection")).equals(Json.canonical(selected(menu,chosen,c))),"card group mapped to another physical wire ID");
            require(prefix?c.backend.heads.equals(Arrays.asList("action")):groups.size()==1?c.backend.heads.isEmpty():c.backend.heads.equals(Arrays.asList("card_select")),
                    "card replay changed the trained head");
            primary.add(Json.map("count",(long)count,"dedup",dedup,"prefix",prefix,"candidate_id",Json.obj(result,"selection").get("candidate_id"),
                    "model_calls",(long)c.backend.calls,"copy_draws",(long)c.backend.copies));c.registry.close();
        }
        for(Outcome outcome:new Outcome[]{Outcome.Benefit,Outcome.Detriment})for(boolean prefix:new boolean[]{false,true}) {
            JackDialogReplayCheck.Case c=new JackDialogReplayCheck.Case(2,false);List<UUID> options=new ArrayList<>(c.player.getHand());
            HandTarget target=new HandTarget(options,1,1);Map<String,Object> record=request(c,target,options,true,outcome),menu=Json.obj(record,"decision");
            UUID chosen=options.get(outcome==Outcome.Benefit?1:0);
            if(prefix) {Json.obj(record,"replay").put("earlier",Arrays.asList(Json.map("decision",menu,"selection",selected(menu,chosen,c))));record.put("decision",c.decision("x"));}
            Map<String,Object> result=JackOriginalBridgeMain.choose(c.world,record);
            require(c.backend.calls==(prefix?1:0) && c.backend.copies==0 && !c.backend.closed,"inherited card policy consumed model or copy RNG");
            require(prefix?target.getTargets().equals(Arrays.asList(chosen)):Json.canonical(Json.obj(result,"selection")).equals(Json.canonical(selected(menu,chosen,c))),
                    "inherited card sorting or target.add changed");
            primary.add(Json.map("parent",true,"good",outcome==Outcome.Benefit,"prefix",prefix,"candidate_id",Json.obj(result,"selection").get("candidate_id")));c.registry.close();
        }
        for(boolean queued:new boolean[]{false,true}) {
            JackDialogReplayCheck.Case c=new JackDialogReplayCheck.Case(2,false);List<UUID> options=new ArrayList<>(c.player.getHand());
            if(queued)c.player.queueCard(options.get(1));
            HandTarget target=new HandTarget(options,queued?1:0,2);Map<String,Object> record=request(c,target,options,true,Outcome.Detriment);
            Map<String,Object> result=JackOriginalBridgeMain.choose(c.world,record);
            require(c.backend.calls==0 && c.backend.copies==0 && !c.backend.closed,"parent completion/queue changed draw ownership");
            require(Json.canonical(Json.obj(result,"selection")).equals(Json.canonical(selected(Json.obj(record,"decision"),queued?options.get(1):null,c))),
                    "parent completion or queued target was replaced");c.registry.close();
        }
        JackDialogReplayCheck.Case sequential=new JackDialogReplayCheck.Case(3,true);
        List<UUID> repeated=new ArrayList<>(sequential.player.getHand());HandTarget repeatedTarget=new HandTarget(repeated,1,2);
        Map<String,Object> chain=request(sequential,repeatedTarget,repeated,false,Outcome.Benefit),first=Json.obj(chain,"decision");
        Json.obj(chain,"replay").put("earlier",Arrays.asList(Json.map("decision",first,"selection",selected(first,repeated.get(2),sequential))));
        chain.put("decision",decision(sequential,repeatedTarget,repeated.subList(0,2),1,true));
        Map<String,Object> chained=JackOriginalBridgeMain.choose(sequential.world,chain);
        require(repeatedTarget.getTargets().equals(Arrays.asList(repeated.get(2))) && sequential.backend.calls==1 && sequential.backend.copies==1
                && Json.canonical(Json.obj(chained,"selection")).equals(Json.canonical(selected(Json.obj(chain,"decision"),repeated.get(1),sequential))),
                "sequential group replay changed representative, previous physical copy or current stream draws");
        primary.add(Json.map("sequential_group",true,"candidate_id",Json.obj(chained,"selection").get("candidate_id"),"model_calls",1L,"copy_draws",1L));
        sequential.registry.close();
        JackDialogReplayCheck.Case neuralStop=new JackDialogReplayCheck.Case(2,false);neuralStop.backend.chooseFirst=true;
        List<UUID> stopCards=new ArrayList<>(neuralStop.player.getHand());HandTarget stopTarget=new HandTarget(stopCards,0,1);
        Map<String,Object> stopRequest=request(neuralStop,stopTarget,stopCards,false,Outcome.Benefit);
        Map<String,Object> stopResult=JackOriginalBridgeMain.choose(neuralStop.world,stopRequest);
        require(neuralStop.backend.calls==1 && neuralStop.backend.copies==0 && stopTarget.getTargets().isEmpty()
                && Json.canonical(Json.obj(stopResult,"selection")).equals(Json.canonical(selected(Json.obj(stopRequest,"decision"),null,neuralStop))),
                "neural STOP drew a physical copy or mutated a card");neuralStop.registry.close();
        JackDialogReplayCheck.Case parentFinish=new JackDialogReplayCheck.Case(2,false);
        List<UUID> finishCards=new ArrayList<>(parentFinish.player.getHand());HandTarget finishTarget=new HandTarget(finishCards,1,2);
        Map<String,Object> finishRequest=request(parentFinish,finishTarget,finishCards,true,Outcome.Detriment),finishFirst=Json.obj(finishRequest,"decision");
        Json.obj(finishRequest,"replay").put("earlier",Arrays.asList(Json.map("decision",finishFirst,"selection",selected(finishFirst,finishCards.get(0),parentFinish))));
        finishRequest.put("decision",decision(parentFinish,finishTarget,finishCards.subList(1,2),1,true));
        Map<String,Object> finished=JackOriginalBridgeMain.choose(parentFinish.world,finishRequest);
        require(finishTarget.getTargets().equals(Arrays.asList(finishCards.get(0))) && parentFinish.backend.calls==0 && parentFinish.backend.copies==0
                && Json.canonical(Json.obj(finished,"selection")).equals(Json.canonical(selected(Json.obj(finishRequest,"decision"),null,parentFinish))),
                "inherited bad-target prefix did not complete at its original minimum");parentFinish.registry.close();
        for(String fault:Arrays.asList("source","id","hidden","range","missing","prefix-cap","parent-prefix")) {
            JackDialogReplayCheck.Case c=new JackDialogReplayCheck.Case("prefix-cap".equals(fault)?70:2,false);
            List<UUID> options=new ArrayList<>(c.player.getHand());TargetCard target=new PlainTarget(options,1,1);
            boolean parent="parent-prefix".equals(fault);Map<String,Object> record=request(c,target,options,parent,Outcome.Benefit),menu=Json.obj(record,"decision");
            Map<String,Object> candidate=Json.obj(Json.arr(menu,"candidates").get(0)),semantic=Json.obj(candidate,"semantic");
            if("source".equals(fault))semantic.put("source",Json.map("object_id","foreign"));
            if("id".equals(fault))candidate.put("candidate_id",Json.obj(Json.arr(menu,"candidates").get(1)).get("candidate_id"));
            if("hidden".equals(fault))semantic.put("choice",Json.map("object",Json.map("object_id","hidden")));
            if("range".equals(fault))semantic.put("minimum",0L);
            if("missing".equals(fault))Json.arr(menu,"candidates").remove(0);
            if("prefix-cap".equals(fault)||parent) {
                UUID bad=parent?options.get(0):options.get(69);
                Json.obj(record,"replay").put("earlier",Arrays.asList(Json.map("decision",menu,"selection",selected(menu,bad,c))));record.put("decision",c.decision("x"));
            }
            refused(()->{try{JackOriginalBridgeMain.choose(c.world,record);}catch(Exception failure){throw new IllegalArgumentException(failure);}});
            require(c.backend.calls==0 && c.backend.copies==0 && c.backend.closed,"invalid card binding drew or retained session");
        }
        System.out.println(Json.canonical(primary));
        System.out.println("JackCardReplayCheck PASS: original groups, card_select head, physical copies, inherited sorting/queue/finish, exact prefixes and pre-inference refusal");
    }
}
