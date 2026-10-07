package spellbench.kit.xmage;

import mage.constants.PhaseStep;
import spellbench.kit.core.Json;
import java.util.*;
import static spellbench.kit.xmage.MaintainerPlayerBootstrapCheck.*;

/** Actual projection and original dispatch, with scripted metadata phase resume. */
public final class MaintainerPhaseAdvanceCheck {
    static Map<String,Object> record(MaintainerDialogReplayCheck.Case c,PhaseStep before,PhaseStep after,boolean already) throws Exception {
        MaintainerReplayOpponent other=new MaintainerReplayOpponent(c.root.other);c.root.state.getPlayers().put(other.getId(),other);
        c.step=before;if(already)other.pass(c.world.game);
        Map<String,Object> r=c.record(false),anchor=Json.obj(r,"anchor"),root=Json.obj(anchor,"decision"),flags=MaintainerDialogReplayCheck.flags();flags.put("passed_seats",true);
        root.put("seat_step",0L);root.put("x_observation_flags",flags);
        root.put("observation",RoundTrip.project(c.world,flags,"p0",Collections.emptyList()));
        List<Object> choices=new ArrayList<>(Json.arr(root,"candidates"));choices.add(Json.map("candidate_id",99L,"semantic",Json.map("kind","pass")));root.put("candidates",choices);
        anchor.put("selection",Json.map("candidate_id",99L,"semantic_echo",Json.map("kind","pass")));
        Json.obj(r,"replay").put("priority_passes",already?Collections.emptyList():Collections.singletonList("p1"));
        other.resetPassed();c.step=after;Map<String,Object> current=Json.obj(Json.copy(root));current.put("seat_step",1L);
        current.put("observation",RoundTrip.project(c.world,flags,"p0",Collections.emptyList()));r.put("decision",current);
        c.step=before;if(already)other.pass(c.world.game);
        c.resumeWork=()->{
            require(c.player.isPassed(),"original anchor pass did not execute");
            if(!already)other.priority(c.world.game);
            require(other.isPassed(),"public opponent pass did not execute");
            c.player.resetPassed();other.resetPassed();c.step=after;c.player.priority(c.world.game);
        };
        return r;
    }
    public static void main(String[] args) throws Exception {
        List<Object> rows=new ArrayList<>();
        PhaseStep[][] transitions={{PhaseStep.PRECOMBAT_MAIN,PhaseStep.BEGIN_COMBAT},{PhaseStep.POSTCOMBAT_MAIN,PhaseStep.END_TURN},
                {PhaseStep.UPKEEP,PhaseStep.DRAW},{PhaseStep.END_COMBAT,PhaseStep.POSTCOMBAT_MAIN}};
        for(PhaseStep[] pair:transitions)for(boolean already:new boolean[]{false,true}) {
            MaintainerDialogReplayCheck.Case c=new MaintainerDialogReplayCheck.Case();Map<String,Object> r=record(c,pair[0],pair[1],already);
            Map<String,Object> result=new MaintainerDialogReplay(c.world,r).choose();
            require(Boolean.TRUE.equals(result.get("original_phase_advance_path")) && Boolean.TRUE.equals(result.get("original_priority_continuation")),"phase path or original dispatch lost");
            require(c.resumes==1 && c.player.entered==0 && c.backend.copies==0 && !c.backend.closed,"phase resume substituted activation or leaked session");
            require(Long.valueOf(already?0:1).equals(result.get("original_priority_passes_replayed")),"phase pass sequence changed");
            rows.add(Json.map("before",pair[0].name(),"after",pair[1].name(),"already",already,"model_calls",(long)c.backend.calls,
                    "candidate_id",Json.obj(result,"selection").get("candidate_id")));c.registry.close();
        }
        for(String fault:Arrays.asList("actual-phase","missing-pass","opponent-choice","ended","turn","active","rewind","prefix")) {
            MaintainerDialogReplayCheck.Case c=new MaintainerDialogReplayCheck.Case();Map<String,Object> r=record(c,PhaseStep.PRECOMBAT_MAIN,PhaseStep.BEGIN_COMBAT,false);
            Map<String,Object> current=Json.obj(r,"decision"),obs=Json.obj(current,"observation");
            MaintainerReplayOpponent other=(MaintainerReplayOpponent)c.world.game.getPlayer(c.root.other.getId());
            if("actual-phase".equals(fault))c.resumeWork=()->{other.priority(c.world.game);c.player.resetPassed();other.resetPassed();c.player.priority(c.world.game);};
            if("missing-pass".equals(fault))Json.obj(r,"replay").put("priority_passes",Collections.emptyList());
            if("opponent-choice".equals(fault))c.resumeWork=()->other.chooseUse(mage.constants.Outcome.Benefit,"unrecorded",null,c.world.game);
            if("ended".equals(fault))c.resumeWork=()->{};
            if("turn".equals(fault))obs.put("turn",Json.num(obs,"turn",0)+1);
            if("active".equals(fault))obs.put("active_seat","p1");
            if("rewind".equals(fault))obs.put("phase_step","upkeep");
            if("prefix".equals(fault))Json.obj(r,"replay").put("earlier",Collections.singletonList(Json.map("decision",current,"selection",Json.obj(Json.obj(r,"anchor"),"selection"))));
            refused(()->new MaintainerDialogReplay(c.world,r).choose());require(c.backend.closed && c.backend.calls==0 && c.backend.copies==0,"invalid phase advanced inference or retained session");
        }
        System.out.println(Json.canonical(rows));
        System.out.println("MaintainerPhaseAdvanceCheck PASS: original empty-stack passes, real projection before next-phase original dispatch, exact public pass order and pre-inference refusals; scripted metadata resume, native event loop unqualified");
    }
}
