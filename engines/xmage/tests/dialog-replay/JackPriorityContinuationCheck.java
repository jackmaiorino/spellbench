package spellbench.kit.xmage;

import mage.abilities.ActivatedAbility;
import spellbench.kit.core.Json;
import java.lang.reflect.*;
import java.util.*;
import static spellbench.kit.xmage.JackPlayerBootstrapCheck.*;

/** Actual original act completion and stack-dependent pass on metadata worlds. */
public final class JackPriorityContinuationCheck {
    static Map<String,Object> record(JackDialogReplayCheck.Case c,int prefix,boolean stack,boolean phasePass) {
        c.player.completeActivation=true;c.player.prefix=prefix>0;c.player.completionX=prefix>1;
        c.player.playable=(ActivatedAbility)Proxy.newProxyInstance(ActivatedAbility.class.getClassLoader(),new Class<?>[]{ActivatedAbility.class},(o,m,a)->{
            if("isUsesStack".equals(m.getName()))return stack;
            if("copy".equals(m.getName()))return o;
            if("equals".equals(m.getName()))return o==a[0];
            if("hashCode".equals(m.getName()))return System.identityHashCode(o);
            try{return m.invoke(c.ability,a);}catch(InvocationTargetException failure){throw failure.getCause();}
        });
        Map<String,Object> record=c.record(prefix>0),anchor=Json.obj(record,"anchor"),root=Json.obj(anchor,"decision");
        root.put("seat_step",0L);anchor.put("priority_pass_after_activation",phasePass);
        List<Object> earlier=Json.arr(Json.obj(record,"replay"),"earlier");
        if(prefix>1) {
            Map<String,Object> x=c.decision("x"),candidate=Json.obj(Json.arr(x,"candidates").get(1));
            earlier.add(Json.map("decision",x,"selection",Json.map("candidate_id",candidate.get("candidate_id"),"semantic_echo",Json.copy(candidate.get("semantic")))));
        }
        for(int i=0;i<earlier.size();i++)Json.obj(Json.obj(earlier.get(i)),"decision").put("seat_step",(long)i+1);
        Map<String,Object> current=Json.obj(Json.copy(root));current.put("seat_step",(long)prefix+1);
        List<Object> candidates=new ArrayList<>(Json.arr(current,"candidates"));
        candidates.add(0,Json.map("candidate_id",99L,"semantic",Json.map("kind","pass")));current.put("candidates",candidates);
        record.put("decision",current);return record;
    }
    public static void main(String[] args) throws Exception {
        List<Object> rows=new ArrayList<>();
        for(int prefix:new int[]{0,1,2})for(boolean stack:new boolean[]{false,true})for(boolean phasePass:new boolean[]{false,true}) {
            JackDialogReplayCheck.Case c=new JackDialogReplayCheck.Case();Map<String,Object> record=record(c,prefix,stack,phasePass);
            require(JackOriginalBridgeMain.reconstructionDecision(record)==Json.obj(Json.obj(record,"anchor"),"decision"),"continuation resampled from current priority");
            Map<String,Object> result=JackOriginalBridgeMain.choose(c.world,record);boolean pass=stack||phasePass;
            require(Boolean.TRUE.equals(result.get("original_priority_continuation")) && Boolean.TRUE.equals(result.get("original_activation_path")),"actual continuation was skipped");
            require(Boolean.valueOf(stack).equals(result.get("original_activation_pass_deferred")),"original act stack-dependent pass was lost");
            require(Long.valueOf(prefix).equals(result.get("original_dialog_prefix_replayed")),"original callback prefix was not completed");
            require(Long.valueOf(pass?99:1).equals(Json.obj(result,"selection").get("candidate_id")),"original pass or fresh dispatch changed its wire action");
            require(c.backend.calls==(pass?0:1) && c.backend.copies==0 && c.player.entered==1,"continuation added replay draws or skipped original activation");
            require(c.player.isPassed()==pass,"deferred pass did not become the actual original pass");
            require(c.player.activationAbility()==null && c.player.excludedManaSource()==null && c.player.reservedTapSources().isEmpty(),"original completion skipped activation cleanup");
            require(!c.backend.closed,"successful continuation closed the owned session");
            rows.add(Json.map("prefix",(long)prefix,"stack_pass",stack,"phase_pass",phasePass,"candidate_id",Json.obj(result,"selection").get("candidate_id"),"model_calls",(long)c.backend.calls,"copy_draws",(long)c.backend.copies));c.registry.close();
        }
        for(String fault:new String[]{"unrecorded","observation","unoffered-pass","phase"}) {
            JackDialogReplayCheck.Case c=new JackDialogReplayCheck.Case();Map<String,Object> record=record(c,0,true,false);
            if("unrecorded".equals(fault))c.player.prefix=true;
            if("observation".equals(fault))Json.obj(Json.arr(Json.obj(Json.obj(record,"decision"),"observation"),"players").get(0)).put("life",19L);
            if("unoffered-pass".equals(fault))Json.arr(Json.obj(record,"decision"),"candidates").remove(0);
            if("phase".equals(fault))Json.obj(Json.obj(record,"decision"),"observation").put("phase_step","postcombat_main");
            refused(()->new JackDialogReplay(c.world,record).choose());
            require(c.backend.closed && c.backend.calls==0 && c.backend.copies==0,"failed continuation advanced the model or kept its session");
        }
        System.out.println(Json.canonical(rows));System.out.println("JackPriorityContinuationCheck PASS: actual act cleanup, stack/phase passes, complete binary/X prefixes, zero replay draws, fresh original dispatch and refusal; metadata activation only");
    }
}
