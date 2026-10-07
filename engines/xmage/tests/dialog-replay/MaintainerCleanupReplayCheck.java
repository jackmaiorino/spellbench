package spellbench.kit.xmage;

import mage.abilities.Ability;
import mage.constants.Outcome;
import mage.constants.PhaseStep;
import mage.game.Game;
import mage.target.common.TargetDiscard;
import spellbench.kit.core.Json;
import spellbench.kit.core.ObsIndex;
import java.util.*;
import static spellbench.kit.xmage.MaintainerPlayerBootstrapCheck.*;

/** Original cleanup target loop with scripted metadata resume and target mutations. */
public final class MaintainerCleanupReplayCheck {
    static final class Discard extends TargetDiscard {
        final List<UUID> hand;
        Discard(UUID player,int count,List<UUID> hand) {super(count,mage.filter.StaticFilters.FILTER_CARD,player);this.hand=hand;}
        @Override public Set<UUID> possibleTargets(UUID player,Ability source,Game game) {return new LinkedHashSet<>(hand);}
        @Override public boolean canTarget(UUID player,UUID id,Ability source,Game game) {return hand.contains(id);}
        @Override public void addTarget(UUID id,Ability source,Game game) {targets.put(id,0);}
    }
    static Map<String,Object> menu(MaintainerDialogReplayCheck.Case c,int count,int selected,List<UUID> picked) {
        Map<String,Object> d=c.decision("use"),obs=Json.obj(d,"observation");
        Json.obj(d,"x_observation_flags").put("passed_seats",true);
        obs.put("phase_step","cleanup");obs.put("passed_seats",Arrays.asList("p0","p1"));obs.put("priority_seat",null);
        d.put("seat_step",(long)selected+1);d.put("context",Json.map("kind","choice","purpose","discard","rewind",false,"source",null));
        if(count>1)d.put("group",Json.map("group_id",41L,"substep_index",(long)selected,"substep_count",(long)count));
        ObsIndex index=new ObsIndex(obs);List<Object> choices=new ArrayList<>();
        for(UUID id:c.player.getHand())if(!picked.contains(id))choices.add(Json.map("candidate_id",100L+id.getLeastSignificantBits(),"semantic",Json.map(
                "kind","select_object","source",null,"purpose","discard","choice",Json.map("object",index.ref(c.world.uuidToId.get(id))),
                "selected_count",(long)selected,"minimum",(long)count,"maximum",(long)count)));
        d.put("candidates",choices);return d;
    }
    static Map<String,Object> record(MaintainerDialogReplayCheck.Case c,int count,int prefix,boolean already,boolean sameName) {
        MaintainerReplayOpponent other=new MaintainerReplayOpponent(c.root.other);c.root.state.getPlayers().put(other.getId(),other);
        if(already)other.pass(c.world.game);c.step=PhaseStep.END_TURN;
        Map<String,Object> record=c.record(false),anchor=Json.obj(record,"anchor"),root=Json.obj(anchor,"decision");root.put("seat_step",0L);
        root.put("candidates",Collections.singletonList(Json.map("candidate_id",99L,"semantic",Json.map("kind","pass"))));
        anchor.put("selection",Json.map("candidate_id",99L,"semantic_echo",Json.map("kind","pass")));
        Json.obj(root,"observation").put("passed_seats",already?Collections.singletonList("p1"):Collections.emptyList());
        Json.obj(record,"replay").put("priority_passes",already?Collections.emptyList():Collections.singletonList("p1"));
        List<UUID> hand=new ArrayList<>(c.player.getHand()),picked=new ArrayList<>();List<Object> earlier=new ArrayList<>();
        for(int i=0;i<prefix;i++) {
            Map<String,Object> d=menu(c,count,i,picked);UUID pick=sameName?hand.get(i):hand.get(hand.size()-1-i);
            Map<String,Object> candidate=null;
            for(Object item:Json.arr(d,"candidates"))if(Long.valueOf(100+pick.getLeastSignificantBits()).equals(Json.obj(item).get("candidate_id")))candidate=Json.obj(item);
            earlier.add(Json.map("decision",d,"selection",Json.map("candidate_id",candidate.get("candidate_id"),"semantic_echo",Json.copy(candidate.get("semantic")))));
            picked.add(pick);
        }
        record.put("decision",menu(c,count,prefix,picked));Json.obj(record,"replay").put("earlier",earlier);
        Discard target=new Discard(c.player.getId(),count,hand);
        c.resumeWork=()->{
            require(c.player.isPassed(),"cleanup did not apply original end-step pass");
            if(!already)other.priority(c.world.game);c.step=PhaseStep.CLEANUP;
            c.player.choose(Outcome.Discard,target,null,c.world.game);
        };
        c.player.target=target;return record;
    }
    public static void main(String[] args) {
        List<Object> normalized=new ArrayList<>();
        for(int count:new int[]{1,2,3})for(int prefix=0;prefix<count;prefix++)for(boolean already:new boolean[]{false,true})for(boolean same:new boolean[]{false,true}) {
            MaintainerDialogReplayCheck.Case c=new MaintainerDialogReplayCheck.Case(7+count,same);Map<String,Object> r=record(c,count,prefix,already,same);
            Map<String,Object> result=c.control(r).choose();List<UUID> chosen=c.player.target.getTargets();
            require(Boolean.TRUE.equals(result.get("original_cleanup_path")) && Boolean.TRUE.equals(result.get("original_resolution_path")),"cleanup substituted an activation");
            require(c.backend.calls==(same?0:1) && c.backend.copies==0 && c.player.entered==0 && c.resumes==1,"cleanup changed original model or physical-copy draws");
            require(chosen.size()==prefix && c.compares==prefix+2,"cleanup prefix skipped original target mutation or projection");
            require(c.backend.heads.equals(same?Collections.emptyList():Collections.singletonList("target")),"cleanup used another original head");
            require(Long.valueOf(prefix).equals(result.get("original_dialog_prefix_replayed")) && !c.backend.closed,"cleanup lost prefix receipt or inference owner");
            normalized.add(Json.map("count",(long)count,"prefix",(long)prefix,"already",already,"same_name_direct",same,"model_calls",(long)c.backend.calls,"selection",result.get("selection")));c.registry.close();
        }
        for(String fault:Arrays.asList("root-phase","current-phase","active","source","passed","ref-owner","minimum","group","missing-prefix","actual-phase","actual-range")) {
            MaintainerDialogReplayCheck.Case c=new MaintainerDialogReplayCheck.Case(9,false);Map<String,Object> r=record(c,2,1,false,false);
            Map<String,Object> root=Json.obj(Json.obj(r,"anchor"),"decision"),current=Json.obj(r,"decision"),obs=Json.obj(current,"observation");
            if("root-phase".equals(fault))Json.obj(root,"observation").put("phase_step","postcombat_main");
            if("current-phase".equals(fault))obs.put("phase_step","end_step");
            if("active".equals(fault))obs.put("active_seat","p1");
            if("source".equals(fault))Json.obj(current,"context").put("source",Json.map("object_id","foreign"));
            if("passed".equals(fault))obs.put("passed_seats",Collections.singletonList("p0"));
            if("ref-owner".equals(fault))Json.obj(Json.obj(Json.obj(Json.obj(Json.arr(current,"candidates").get(0)),"semantic"),"choice"),"object").put("owner_seat","p1");
            if("minimum".equals(fault))Json.obj(Json.obj(Json.arr(current,"candidates").get(0)),"semantic").put("minimum",3L);
            if("group".equals(fault))Json.obj(current,"group").put("substep_index",0L);
            if("missing-prefix".equals(fault))Json.obj(r,"replay").put("earlier",Collections.emptyList());
            if("actual-phase".equals(fault) || "actual-range".equals(fault)) {
                MaintainerReplayOpponent other=(MaintainerReplayOpponent)c.world.game.getPlayer(c.root.other.getId());
                c.resumeWork=()->{other.priority(c.world.game);c.step="actual-phase".equals(fault)?PhaseStep.END_TURN:PhaseStep.CLEANUP;
                    c.player.choose(Outcome.Discard,new Discard(c.player.getId(),"actual-range".equals(fault)?3:2,new ArrayList<>(c.player.getHand())),null,c.world.game);};
            }
            refused(()->c.control(r).choose());require(c.backend.closed && c.backend.calls==0 && c.backend.copies==0,"invalid cleanup advanced inference");
        }
        System.out.println(Json.canonical(normalized));
        System.out.println("MaintainerCleanupReplayCheck PASS: end-step passes, fixed own-hand discard groups, original target head and direct returns, replayed target mutations without draws; scripted metadata resume, native cleanup unqualified");
    }
}
