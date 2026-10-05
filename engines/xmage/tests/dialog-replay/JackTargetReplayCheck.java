package spellbench.kit.xmage;

import mage.constants.Outcome;
import mage.target.Target;
import spellbench.kit.core.Json;
import spellbench.kit.core.ObsIndex;
import java.lang.reflect.Proxy;
import java.util.*;
import static spellbench.kit.xmage.JackPlayerBootstrapCheck.*;

/** Actual original sequential target loop, wire menu binding and prefix replay. */
public final class JackTargetReplayCheck {
    static final class Menu {
        final List<UUID> options,chosen=new ArrayList<>();final int minimum,maximum;
        final Target target;
        Menu(List<UUID> options,int minimum,int maximum) {
            this.options=options;this.minimum=minimum;this.maximum=maximum;
            target=(Target)Proxy.newProxyInstance(Target.class.getClassLoader(),new Class<?>[]{Target.class},(o,m,a)->{
                switch(m.getName()) {
                    case "getMinNumberOfTargets":return minimum;
                    case "getMaxNumberOfTargets":return maximum;
                    case "getTargetName":return "metadata target";
                    case "getTargetController":case "getAbilityController":return null;
                    case "possibleTargets":return new LinkedHashSet<>(options);
                    case "canTarget":return options.contains(a[1]);
                    case "getTargets":return new ArrayList<>(chosen);
                    case "addTarget":chosen.add((UUID)a[0]);return m.getReturnType()==boolean.class?true:null;
                    case "isChosen":return chosen.size()>=minimum;
                    case "isNotTarget":return false;
                    case "getId":return new UUID(0,77);
                    case "toString":return "metadata target";
                    default:throw new AssertionError("unexpected target read: "+m.getName());
                }
            });
        }
    }
    static Map<String,Object> decision(JackDialogReplayCheck.Case c,Menu menu,String family,int selected,
                                        List<UUID> available,boolean stop) {
        Map<String,Object> result=c.decision("use");
        Object source=new ObsIndex(Json.obj(result,"observation")).ref(c.world.uuidToId.get(c.ability.getSourceId()));
        Json.obj(result,"context").put("source",source);
        List<Object> offered=new ArrayList<>();
        List<UUID> order=new ArrayList<>(available);if(stop)order.add(0,null);
        for(int i=order.size()-1;i>=0;i--) {
            UUID id=order.get(i);Map<String,Object> semantic;
            if(id==null) semantic=Json.map("kind","select_object".equals(family)?"finish_selection":"finish_target_selection",
                    "source",source,"selected_count",(long)selected);
            else {
                Object ref=new ObsIndex(Json.obj(result,"observation")).ref(c.world.uuidToId.get(id));
                semantic=Json.map("kind",family,"source",source,"selected_count",(long)selected,
                        "minimum",(long)menu.minimum,"maximum",(long)menu.maximum);
                if("choose_target".equals(family))semantic.put("target",Json.map("object",ref));
                else if("choose_cost_target".equals(family))semantic.put("candidate",ref);
                else semantic.put("choice",Json.map("object",ref));
            }
            if("select_object".equals(family))semantic.put("purpose","cards");
            else if("choose_cost_target".equals(family))semantic.put("cost_kind","discard");
            else semantic.put("slot",0L);
            offered.add(Json.map("candidate_id",100L+i,"semantic",semantic));
        }
        result.put("candidates",offered);return result;
    }
    static Map<String,Object> select(Map<String,Object> decision,int wireIndex) {
        Map<String,Object> candidate=Json.obj(Json.arr(decision,"candidates").get(wireIndex));
        return Json.map("candidate_id",candidate.get("candidate_id"),"semantic_echo",Json.copy(candidate.get("semantic")));
    }
    static Map<String,Object> request(JackDialogReplayCheck.Case c,Menu menu,String family,boolean prefix) {
        c.player.target=menu.target;
        c.player.playable=(mage.abilities.ActivatedAbility)Proxy.newProxyInstance(
                mage.abilities.ActivatedAbility.class.getClassLoader(),new Class<?>[]{mage.abilities.ActivatedAbility.class},(o,m,a)->{
                    if("getControllerId".equals(m.getName()))return c.player.getId();
                    if("copy".equals(m.getName()))return o;
                    try{return m.invoke(c.ability,a);}catch(java.lang.reflect.InvocationTargetException e){throw e.getCause();}
                });
        Map<String,Object> request=c.record(false),current=decision(c,menu,family,0,menu.options,false);
        if(prefix) {
            int original=Math.min(64,menu.options.size())-1;
            Json.obj(request,"replay").put("earlier",Arrays.asList(Json.map("decision",current,
                    "selection",select(current,menu.options.size()-1-original))));
        } else request.put("decision",current);
        return request;
    }
    public static void main(String[] args) throws Exception {
        for(int count:new int[]{1,2,70}) for(boolean prefix:new boolean[]{false,true})
            for(String family:Arrays.asList("choose_target","choose_cost_target","select_object")) {
                JackDialogReplayCheck.Case c=new JackDialogReplayCheck.Case(count,false);
                Menu menu=new Menu(new ArrayList<>(c.player.getHand()),1,1);
                Map<String,Object> result=JackOriginalBridgeMain.choose(c.world,request(c,menu,family,prefix));
                require(!c.backend.closed && c.backend.calls==(prefix?1:count==1?0:1),"target changed policy draws or closed owned pause");
                UUID expected=menu.options.get(Math.min(64,count)-1);
                require(prefix?menu.chosen.equals(Arrays.asList(expected)):menu.chosen.isEmpty(),"target prefix changed original order or mutation");
                require(prefix?Long.valueOf(1).equals(result.get("original_dialog_prefix_replayed")):
                        Long.valueOf(100L+Math.min(64,count)-1).equals(Json.obj(result,"selection").get("candidate_id")),"target wire mapping changed original slots");
                c.registry.close();
            }
        for(boolean same:new boolean[]{false,true}) {
            JackDialogReplayCheck.Case c=new JackDialogReplayCheck.Case(2,same);
            Menu menu=new Menu(new ArrayList<>(c.player.getHand()),1,2);
            Map<String,Object> request=request(c,menu,"choose_target",false),first=Json.obj(request,"decision");
            UUID picked=menu.options.get(0);Map<String,Object> recorded=select(first,1);
            Json.obj(request,"replay").put("earlier",Arrays.asList(Json.map("decision",first,"selection",recorded)));
            request.put("decision",decision(c,menu,"choose_target",1,Arrays.asList(menu.options.get(1)),true));
            Map<String,Object> result=JackOriginalBridgeMain.choose(c.world,request);
            require(menu.chosen.equals(Arrays.asList(picked)) && c.backend.calls==0 && !c.backend.closed,
                    "sequential targets lost prefix, forced same-name return or session");
            require(Long.valueOf(101).equals(Json.obj(result,"selection").get("candidate_id")),"target STOP changed same-name/last-slot policy");
            c.registry.close();
        }
        JackDialogReplayCheck.Case stop=new JackDialogReplayCheck.Case(1,false);
        Menu empty=new Menu(Collections.emptyList(),0,1);
        Map<String,Object> stopRequest=request(stop,empty,"choose_target",false);
        stopRequest.put("decision",decision(stop,empty,"choose_target",0,Collections.emptyList(),true));
        Map<String,Object> stopped=JackOriginalBridgeMain.choose(stop.world,stopRequest);
        require(stop.backend.calls==0 && empty.chosen.isEmpty() && Long.valueOf(100).equals(Json.obj(stopped,"selection").get("candidate_id")),
                "single STOP failed to preserve original direct return");stop.registry.close();
        for(String fault:Arrays.asList("source","count","minimum","id","missing","slot","hidden","prefix-cap","forced")) {
            int count="prefix-cap".equals(fault)?70:2;
            JackDialogReplayCheck.Case c=new JackDialogReplayCheck.Case(count,"forced".equals(fault));
            Menu menu=new Menu(new ArrayList<>(c.player.getHand()),1,1);Map<String,Object> request=request(c,menu,"choose_target",false);
            Map<String,Object> current=Json.obj(request,"decision"),candidate=Json.obj(Json.arr(current,"candidates").get(0));
            Map<String,Object> semantic=Json.obj(candidate,"semantic");
            if("source".equals(fault))semantic.put("source",Json.map("object_id","foreign"));
            if("count".equals(fault))semantic.put("selected_count",1L);
            if("minimum".equals(fault))semantic.put("minimum",0L);
            if("slot".equals(fault))semantic.put("slot",1L);
            if("id".equals(fault))candidate.put("candidate_id",Json.obj(Json.arr(current,"candidates").get(1)).get("candidate_id"));
            if("missing".equals(fault))Json.arr(current,"candidates").remove(0);
            if("hidden".equals(fault))semantic.put("target",Json.map("object",Json.map("object_id","hidden")));
            if("prefix-cap".equals(fault) || "forced".equals(fault)) {
                Json.obj(request,"replay").put("earlier",Arrays.asList(Json.map("decision",current,"selection",select(current,0))));
                request.put("decision",c.decision("x"));
            }
            refused(()->{try {JackOriginalBridgeMain.choose(c.world,request);}catch(Exception e){throw new IllegalArgumentException(e);}});
            require(c.backend.calls==0 && c.backend.closed,"invalid target inferred or kept model session open");
        }
        JackDialogReplayCheck.Case london=new JackDialogReplayCheck.Case();
        london.player.bindOriginalReplay(london.world.game,(k,p,g,a,original)->{throw new IllegalArgumentException("unconnected London");});
        refused(()->london.player.chooseTarget(Outcome.Discard,new mage.target.common.TargetCardInHand(),null,london.world.game));
        require(london.backend.closed && london.backend.calls==0,"target loop bypassed unconnected London guard");
        System.out.println("JackTargetReplayCheck PASS: actual sequential targets, cost/object wire binding, forced/STOP returns, 64-slot cap, prefix mutation, no extra policy draws and pre-inference refusals");
    }
}
