package spellbench.kit.xmage;

import mage.constants.PhaseStep;
import mage.constants.Outcome;
import spellbench.kit.core.Json;
import java.util.*;
import static spellbench.kit.xmage.JackPlayerBootstrapCheck.*;

/** Real projection and original callback execution after scripted metadata phase transitions. */
public final class JackPhaseCallbackCheck {
    static Map<String,Object> record(JackDialogReplayCheck.Case c,PhaseStep before,PhaseStep after,boolean already,int count,boolean priority) throws Exception {
        Map<String,Object> r=JackPhaseAdvanceCheck.record(c,before,after,already);
        List<Object> earlier=new ArrayList<>();
        for(int i=0;i<count;i++) {
            c.step=after;
            Map<String,Object> d=c.decision("use");d.put("seat_step",(long)i+1);
            earlier.add(Json.map("decision",d,"selection",Json.map("candidate_id",7L,"semantic_echo",Json.copy(Json.obj(Json.obj(Json.arr(d,"candidates").get(1)),"semantic")))));
        }
        c.step=after;
        Map<String,Object> current=priority?Json.obj(r,"decision"):c.decision("use");current.put("seat_step",(long)count+1);
        r.put("decision",current);Json.obj(r,"replay").put("earlier",earlier);
        c.step=before;JackReplayOpponent other=(JackReplayOpponent)c.world.game.getPlayer(c.root.other.getId());
        c.resumeWork=()->{
            require(c.player.isPassed(),"saved phase anchor pass did not execute");
            if(!already)other.priority(c.world.game);
            require(other.isPassed(),"recorded other-seat pass did not execute");
            c.player.resetPassed();other.resetPassed();
            for(int i=0;i<count;i++) {
                c.step=after;
                require(c.player.chooseUse(Outcome.Benefit,"recorded phase callback",null,c.world.game),"recorded callback answer changed");
            }
            c.step=after;
            if(priority)c.player.priority(c.world.game);else c.player.chooseUse(Outcome.Benefit,"current phase callback",null,c.world.game);
        };
        return r;
    }
    public static void main(String[] args) throws Exception {
        List<Object> rows=new ArrayList<>();
        PhaseStep[][] transitions={{PhaseStep.UPKEEP,PhaseStep.DRAW},{PhaseStep.PRECOMBAT_MAIN,PhaseStep.BEGIN_COMBAT},
                {PhaseStep.END_COMBAT,PhaseStep.POSTCOMBAT_MAIN},{PhaseStep.POSTCOMBAT_MAIN,PhaseStep.END_TURN}};
        for(PhaseStep[] pair:transitions)for(boolean already:new boolean[]{false,true})for(int count=0;count<=2;count++)for(boolean priority:new boolean[]{false,true}) {
            JackDialogReplayCheck.Case c=new JackDialogReplayCheck.Case();Map<String,Object> r=record(c,pair[0],pair[1],already,count,priority);
            Map<String,Object> result=new JackDialogReplay(c.world,r).choose();
            require(Boolean.TRUE.equals(result.get("original_phase_advance_path")) && Boolean.TRUE.equals(result.get("original_resolution_path")) && Boolean.FALSE.equals(result.get("original_activation_path")),"phase callback lost original resolution receipt");
            require(Long.valueOf(count).equals(result.get("original_dialog_prefix_replayed")) && Long.valueOf(already?0:1).equals(result.get("original_priority_passes_replayed")),"recorded phase choices or public passes were skipped");
            require(c.resumes==1 && c.player.entered==0 && c.backend.copies==0 && !c.backend.closed,"phase callback substituted activation/copy or closed owned session");
            if(!priority)require(c.backend.calls==1,"recorded phase callbacks consumed additional policy draws");
            rows.add(Json.map("before",pair[0].name(),"after",pair[1].name(),"already",already,"prefix",(long)count,"priority",priority,"model_calls",(long)c.backend.calls,"candidate_id",Json.obj(result,"selection").get("candidate_id")));c.registry.close();
        }
        for(String fault:Arrays.asList("turn","active","reverse","overshoot","actual-phase","missing-pass","viewer-priority","opponent-choice")) {
            JackDialogReplayCheck.Case c=new JackDialogReplayCheck.Case();Map<String,Object> r=record(c,PhaseStep.UPKEEP,PhaseStep.PRECOMBAT_MAIN,false,2,false);
            Map<String,Object> first=Json.obj(Json.obj(Json.arr(Json.obj(r,"replay"),"earlier").get(0)),"decision"),last=Json.obj(Json.obj(Json.arr(Json.obj(r,"replay"),"earlier").get(1)),"decision");
            if("turn".equals(fault))Json.obj(first,"observation").put("turn",2L);
            if("active".equals(fault))Json.obj(first,"observation").put("active_seat","p1");
            if("reverse".equals(fault)){Json.obj(first,"observation").put("phase_step","draw");Json.obj(last,"observation").put("phase_step","upkeep");}
            if("overshoot".equals(fault))Json.obj(first,"observation").put("phase_step","end_step");
            if("missing-pass".equals(fault))Json.obj(r,"replay").put("priority_passes",Collections.emptyList());
            JackReplayOpponent other=(JackReplayOpponent)c.world.game.getPlayer(c.root.other.getId());
            if("actual-phase".equals(fault))c.resumeWork=()->{other.priority(c.world.game);c.player.resetPassed();other.resetPassed();c.step=PhaseStep.END_TURN;c.player.chooseUse(Outcome.Benefit,"changed",null,c.world.game);};
            if("viewer-priority".equals(fault))c.resumeWork=()->{other.priority(c.world.game);c.player.resetPassed();other.resetPassed();c.player.priority(c.world.game);};
            if("opponent-choice".equals(fault))c.resumeWork=()->other.chooseUse(Outcome.Benefit,"unrecorded",null,c.world.game);
            refused(()->new JackDialogReplay(c.world,r).choose());require(c.backend.calls==0 && c.backend.copies==0 && c.backend.closed,"invalid phase callback scored or retained its session");
        }
        System.out.println(Json.canonical(rows));
        System.out.println("JackPhaseCallbackCheck PASS: actual projection before current callback/priority, ordered phase prefixes, original dispatch with zero past policy/copy draws, exact public passes and transition/refusal checks; scripted metadata resume, native event loop unqualified");
    }
}
