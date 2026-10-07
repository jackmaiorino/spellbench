package spellbench.kit.xmage;

import mage.constants.Outcome;
import spellbench.kit.core.Json;
import java.util.*;
import static spellbench.kit.xmage.MaintainerPlayerBootstrapCheck.*;

/** Original pass/callback bodies with a scripted metadata resume, no native event loop. */
public final class MaintainerResolutionReplayCheck {
    static Map<String,Object> record(MaintainerDialogReplayCheck.Case c,boolean prefix,boolean already,boolean priority) {
        MaintainerReplayOpponent other=new MaintainerReplayOpponent(c.root.other);
        c.root.state.getPlayers().put(other.getId(),other);
        if(already)other.pass(c.world.game);
        Map<String,Object> record=c.record(prefix),anchor=Json.obj(record,"anchor"),root=Json.obj(anchor,"decision");
        root.put("seat_step",0L);
        List<Object> choices=new ArrayList<>(Json.arr(root,"candidates"));
        Map<String,Object> pass=Json.map("candidate_id",99L,"semantic",Json.map("kind","pass"));choices.add(0,pass);root.put("candidates",choices);
        anchor.put("selection",Json.map("candidate_id",99L,"semantic_echo",Json.copy(pass.get("semantic"))));
        Json.obj(root,"observation").put("stack",Collections.singletonList(Json.map("metadata_scripted_stack",true)));
        Json.obj(root,"observation").put("passed_seats",already?Collections.singletonList("p1"):Collections.emptyList());
        Json.obj(record,"replay").put("priority_passes",already?Collections.emptyList():Collections.singletonList("p1"));
        List<Object> earlier=Json.arr(Json.obj(record,"replay"),"earlier");
        if(prefix)Json.obj(Json.obj(earlier.get(0)),"decision").put("seat_step",1L);
        if(priority) {
            Map<String,Object> current=Json.obj(Json.copy(root));Json.obj(current,"observation").put("stack",Collections.emptyList());
            record.put("decision",current);
        }
        Json.obj(record,"decision").put("seat_step",prefix?2L:1L);
        c.resumeWork=()->{
            require(c.player.isPassed(),"saved original pass was not applied before resume");
            if(!already) {other.priority(c.world.game);require(other.isPassed(),"recorded opponent pass was not applied");}
            if(prefix)require(c.player.chooseUse(Outcome.Benefit,"earlier",null,c.world.game),"recorded resolution prefix changed");
            if(priority)c.player.priority(c.world.game);else c.player.announceX(0,3,"current",c.world.game,null,false);
        };
        return record;
    }
    public static void main(String[] args) {
        List<Object> normalized=new ArrayList<>();
        for(boolean prefix:new boolean[]{false,true})for(boolean already:new boolean[]{false,true})for(boolean priority:new boolean[]{false,true}) {
            MaintainerDialogReplayCheck.Case c=new MaintainerDialogReplayCheck.Case();Map<String,Object> record=record(c,prefix,already,priority);
            Map<String,Object> result=c.control(record).choose();
            require(Boolean.TRUE.equals(result.get("original_resolution_path")) && Boolean.FALSE.equals(result.get("original_activation_path")),"resolution substituted an activation");
            require(Long.valueOf(already?0:1).equals(result.get("original_priority_passes_replayed")),"recorded public passes were skipped or added");
            require(Long.valueOf(prefix?1:0).equals(result.get("original_dialog_prefix_replayed")),"resolution prefix did not complete");
            require(c.backend.calls==1 && c.backend.copies==0 && c.player.entered==0 && c.resumes==1,"resolution changed model/copy draws or bypassed resume");
            require(Long.valueOf(priority?1:23).equals(Json.obj(result,"selection").get("candidate_id")),"original callback or priority selection changed");
            require(!c.backend.closed,"owned successful pause closed inference");
            if(priority)require(Boolean.TRUE.equals(result.get("original_priority_continuation")),"next priority did not dispatch the original policy");
            normalized.add(Json.map("prefix",prefix,"other_already_passed",already,"priority",priority,"passes_replayed",result.get("original_priority_passes_replayed"),"model_calls",(long)c.backend.calls,"candidate_id",Json.obj(result,"selection").get("candidate_id")));c.registry.close();
        }
        for(String fault:new String[]{"missing-pass","extra-priority","viewer-before-pass","opponent-choice","opponent-trigger","opponent-ring","ended","phase","empty-stack","own-already-passed"}) {
            MaintainerDialogReplayCheck.Case c=new MaintainerDialogReplayCheck.Case();boolean already="extra-priority".equals(fault);
            Map<String,Object> record=record(c,false,already,false);Map<String,Object> root=Json.obj(Json.obj(record,"anchor"),"decision");
            MaintainerReplayOpponent other=(MaintainerReplayOpponent)c.world.game.getPlayer(c.root.other.getId());
            if("missing-pass".equals(fault))Json.obj(record,"replay").put("priority_passes",Collections.emptyList());
            if("extra-priority".equals(fault))c.resumeWork=()->other.priority(c.world.game);
            if("viewer-before-pass".equals(fault))c.resumeWork=()->c.player.priority(c.world.game);
            if("opponent-choice".equals(fault))c.resumeWork=()->other.chooseUse(Outcome.Benefit,"unrecorded",null,c.world.game);
            if("opponent-trigger".equals(fault))c.resumeWork=()->other.chooseTriggeredAbility(Collections.emptyList(),c.world.game);
            if("opponent-ring".equals(fault))c.resumeWork=()->other.chooseRingBearer(c.world.game);
            if("ended".equals(fault))c.resumeWork=()->{};
            if("phase".equals(fault))Json.obj(Json.obj(record,"decision"),"observation").put("phase_step","postcombat_main");
            if("empty-stack".equals(fault))Json.obj(root,"observation").put("stack",Collections.emptyList());
            if("own-already-passed".equals(fault))Json.obj(root,"observation").put("passed_seats",Collections.singletonList("p0"));
            refused(()->c.control(record).choose());require(c.backend.closed && c.backend.calls==0 && c.backend.copies==0,"unrecorded resolution advanced inference or retained its session");
        }
        System.out.println(Json.canonical(normalized));
        System.out.println("MaintainerResolutionReplayCheck PASS: actual saved/public passes, resolving X, recorded binary prefix, next original priority, owned pause and pre-inference refusal; scripted metadata resume, native stack legality/event loop unqualified");
    }
}
