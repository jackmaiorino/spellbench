package spellbench.kit.xmage;

import mage.choices.*;
import mage.constants.Outcome;
import spellbench.kit.core.Json;
import spellbench.kit.core.ObsIndex;
import spellbench.models.jack.OriginalCallbackPlayer;
import java.util.*;
import static spellbench.kit.xmage.JackPlayerBootstrapCheck.*;

/** Named callbacks exercise the real inherited Choice implementation and owned replay pause. */
public final class JackNamedChoiceReplayCheck {
    static Choice options(int count,boolean keyed,boolean hashed,boolean duplicate) {
        Choice choice=new ChoiceImpl(true);
        if(keyed) {
            Map<String,String> values=hashed?new HashMap<>():new LinkedHashMap<>();
            for(int i=0;i<count;i++) values.put("key "+i,duplicate?"Same visible label":"Label "+(count-i));
            choice.setKeyChoices(values);
        } else {
            Set<String> values=new LinkedHashSet<>();for(int i=0;i<count;i++) values.add("Option "+i);
            choice.setChoices(values);
        }
        return choice;
    }
    static Map<String,String> actual(Choice choice) {
        Map<String,String> options=new LinkedHashMap<>();
        if(choice.isKeyChoice()) options.putAll(choice.getKeyChoices());
        else for(String value:choice.getChoices()) options.put(value,value);
        return options;
    }
    static Map<String,Object> record(JackDialogReplayCheck.Case test,Choice choice,String kind,boolean prefix) {
        test.player.named=choice;
        Map<String,String> options=actual(choice);List<String> visible=new ArrayList<>(options.keySet());
        if(choice.getKeyChoices() instanceof HashMap && !(choice.getKeyChoices() instanceof LinkedHashMap))
            visible.sort((a,b)->{int c=options.get(a).compareTo(options.get(b));return c!=0?c:a.compareTo(b);});
        Map<String,Object> decision=test.decision("use");List<Object> candidates=new ArrayList<>();
        Object source="choose_cast_method".equals(kind)?new ObsIndex(Json.obj(decision,"observation"))
                .ref(test.world.uuidToId.get(test.ability.getSourceId())):null;
        Json.obj(decision,"context").put("source",source);
        for(int i=visible.size()-1;i>=0;i--) {
            String key=visible.get(i),label=options.get(key);
            Map<String,Object> semantic=Json.map("kind",kind,"source",source);
            if("choose_option".equals(kind)) semantic.putAll(Json.map("purpose","effect_option","option_index",(long)i,
                    "option_count",(long)visible.size(),"option_label",label));
            else if("choose_color".equals(kind)) semantic.putAll(Json.map("purpose","effect","color",label.toLowerCase(Locale.ROOT)));
            else if("choose_name".equals(kind)) semantic.putAll(Json.map("purpose","creature_type","value",label.toLowerCase(Locale.ROOT)));
            else semantic.put("method",key.equals("normal")?"normal":"flashback");
            candidates.add(Json.map("candidate_id",100L+i,"semantic",semantic));
        }
        decision.put("candidates",candidates);Map<String,Object> record=test.record(false);
        if("choose_cast_method".equals(kind)) {
            Json.obj(Json.obj(record,"anchor"),"original_priority_state").put("alternatives",Arrays.asList(
                    Json.map("source",source,"choices",Arrays.asList("alternate"))));
        }
        if(prefix) {
            String picked=new ArrayList<>(options.keySet()).get(Math.min(64,options.size())-1);
            if("choose_cast_method".equals(kind)) picked="alternate";
            int index=visible.indexOf(picked);Map<String,Object> c=Json.obj(candidates.get(visible.size()-1-index));
            Json.obj(record,"replay").put("earlier",Arrays.asList(Json.map("decision",decision,"selection",Json.map(
                    "candidate_id",c.get("candidate_id"),"semantic_echo",Json.copy(c.get("semantic"))))));
        } else record.put("decision",decision);
        return record;
    }
    static Choice type(JackDialogReplayCheck.Case c) {
        Choice choice=new ChoiceCreatureType(c.world.game,null);
        Map<String,String> values=new LinkedHashMap<>();values.put("human-key","Human");values.put("elf-key","Elf");
        choice.setKeyChoices(values);return choice;
    }
    static Choice cost() {
        Choice choice=new ChoiceImpl(true);choice.setMessage("Choose an alternative cost");
        Map<String,String> values=new LinkedHashMap<>();values.put("normal","No alternative cost");values.put("alternate","Flashback alternative cost");
        choice.setKeyChoices(values);return choice;
    }
    public static void main(String[] args) throws Exception {
        for(int count:new int[]{1,2,70}) for(boolean keyed:new boolean[]{false,true}) for(boolean prefix:new boolean[]{false,true}) {
            JackDialogReplayCheck.Case c=new JackDialogReplayCheck.Case();Choice choice=options(count,keyed,false,false);
            Map<String,Object> request=record(c,choice,"choose_option",prefix);
            Map<String,Object> result=JackOriginalBridgeMain.choose(c.world,request);
            String expected=new ArrayList<>(actual(choice).keySet()).get(Math.min(64,count)-1);
            require(expected.equals(keyed?choice.getChoiceKey():choice.getChoice()) && !c.backend.closed,
                    "original named callback reordered keys, selected another slot or closed its owned pause");
            require(c.backend.calls==(prefix?1:count==1?0:1),"named replay consumed an extra original policy draw");
            require(!prefix || Long.valueOf(1).equals(result.get("original_dialog_prefix_replayed")),"named prefix was not replayed");
            c.registry.close();
        }
        for(boolean prefix:new boolean[]{false,true}) for(String kind:new String[]{"choose_color","choose_name","choose_cast_method"}) {
            JackDialogReplayCheck.Case c=new JackDialogReplayCheck.Case();Choice choice;
            if("choose_color".equals(kind)) {choice=new ChoiceColor(true);choice.setChoices(new LinkedHashSet<>(Arrays.asList("Blue","Green")));}
            else if("choose_name".equals(kind)) choice=type(c);else choice=cost();
            JackOriginalBridgeMain.choose(c.world,record(c,choice,kind,prefix));
            require(choice.isChosen() && !c.backend.closed && c.backend.calls==(prefix?1:"choose_cast_method".equals(kind)?0:1),
                    "typed named callback changed its original selection, draw count or owned session");
            c.registry.close();
        }
        for(boolean duplicate:new boolean[]{false,true}) {
            JackDialogReplayCheck.Case c=new JackDialogReplayCheck.Case();Choice choice=options(2,true,!duplicate,duplicate);
            JackOriginalBridgeMain.choose(c.world,record(c,choice,"choose_option",false));
            require(new ArrayList<>(actual(choice).keySet()).get(1).equals(choice.getChoiceKey()),
                    "visible sorting or duplicate labels changed original key order/application");c.registry.close();
        }
        JackDialogReplayCheck.Case implicit=new JackDialogReplayCheck.Case();implicit.player.cost=true;
        Map<String,Object> implicitRecord=record(implicit,options(2,true,false,false),"choose_option",false);
        Map<String,Object> anchor=Json.obj(implicitRecord,"anchor");
        Object implicitSource=new ObsIndex(Json.obj(Json.obj(anchor,"decision"),"observation"))
                .ref(implicit.world.uuidToId.get(implicit.ability.getSourceId()));
        Json.obj(anchor,"original_priority_state").put("alternatives",Arrays.asList(Json.map("source",implicitSource,"choices",Arrays.asList("1"))));
        JackOriginalBridgeMain.choose(implicit.world,implicitRecord);
        require(implicit.backend.calls==1 && !implicit.backend.closed,"recorded alternative cost consumed or replaced the following named callback");
        implicit.registry.close();
        for(String fault:new String[]{"label","index","count","source","id"}) {
            JackDialogReplayCheck.Case c=new JackDialogReplayCheck.Case();Map<String,Object> request=record(c,options(2,true,false,false),"choose_option",false);
            Map<String,Object> decision=Json.obj(request,"decision"),candidate=Json.obj(Json.arr(decision,"candidates").get(0)),semantic=Json.obj(candidate,"semantic");
            if("label".equals(fault)) semantic.put("option_label","foreign");
            if("index".equals(fault)) semantic.put("option_index",0L);
            if("count".equals(fault)) semantic.put("option_count",99L);
            if("source".equals(fault)) semantic.put("source",Json.map("object_id","hidden"));
            if("id".equals(fault)) candidate.put("candidate_id",Json.obj(Json.arr(decision,"candidates").get(1)).get("candidate_id"));
            refused(()->{try {JackOriginalBridgeMain.choose(c.world,request);} catch(Exception failure) {throw new IllegalArgumentException(failure);}});
            require(c.backend.calls==0 && c.backend.closed,"invalid named binding inferred or retained its session");
        }
        JackDialogReplayCheck.Case mint=new JackDialogReplayCheck.Case();
        mint.player.bindOriginalReplay(mint.world.game,(kind,p,g,a,original)->{throw p.pauseOriginalReplay(g,Json.map("owned",true));});
        OriginalCallbackPlayer.ReplayStop foreign;
        try {mint.player.chooseUse(Outcome.Benefit,"mint",null,mint.world.game);throw new AssertionError("pause missing");}
        catch(OriginalCallbackPlayer.ReplayStop stop) {foreign=stop;}
        JackDialogReplayCheck.Case receiver=new JackDialogReplayCheck.Case();
        receiver.player.bindOriginalReplay(receiver.world.game,(kind,p,g,a,original)->{throw foreign;});
        try {receiver.player.choose(Outcome.Benefit,options(2,true,false,false),receiver.world.game);throw new AssertionError("foreign pause accepted");}
        catch(OriginalCallbackPlayer.ReplayStop stop) {require(stop==foreign && receiver.backend.closed && !mint.backend.closed,
                "foreign Choice replay pause bypassed closure or closed another session");}
        mint.registry.close();receiver.registry.close();
        System.out.println("JackNamedChoiceReplayCheck PASS: original key order, visible sorting, duplicate labels, 64-slot cap, forced choices, named prefixes, typed menus, pre-inference refusal and owned pause");
    }
}
