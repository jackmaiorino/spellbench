package spellbench.kit.xmage;

import java.util.*;
import spellbench.kit.core.Json;
import spellbench.kit.core.ObsIndex;
import static spellbench.kit.xmage.MaintainerPlayerBootstrapCheck.*;

/** Actual original London callbacks and owned inference, with metadata movement only. */
public final class MaintainerLondonPlanCheck {
    static MaintainerDialogReplayCheck.Case setup(int size) {
        MaintainerDialogReplayCheck.Case c=new MaintainerDialogReplayCheck.Case(size,false);
        c.pregame=true;c.player.londonMetadata=true;c.backend.wholeRank=true;return c;
    }
    static Map<String,Object> decision(MaintainerDialogReplayCheck.Case c,int count) {
        try {
            for(String name:new String[]{"startingHandSizes","openingHandSizes"}) {
                java.lang.reflect.Field field=mage.game.mulligan.LondonMulligan.class.getDeclaredField(name);field.setAccessible(true);
                @SuppressWarnings("unchecked") Map<UUID,Integer> sizes=(Map<UUID,Integer>)field.get(c.mulligan);
                sizes.put(c.player.getId(),"startingHandSizes".equals(name)?7:7-count);
            }
        } catch(ReflectiveOperationException failure) {throw new AssertionError(failure);}
        Map<String,Object> d=c.decision("x");d.put("seat_step",0L);
        d.put("context",Json.map("kind","choice","rewind",false));
        d.put("group",Json.map("group_id",88L,"substep_index",0L,"substep_count",(long)count));
        Map<String,Object> obs=Json.obj(d,"observation");obs.put("phase_step","pregame");
        for(Object item:Json.arr(obs,"players")) if("p0".equals(Json.str(Json.obj(item),"seat")))
            Json.obj(item).put("mulligans_taken",(long)count);
        ObsIndex index=new ObsIndex(obs);List<Object> offered=new ArrayList<>();
        for(UUID id:c.player.getHand()) offered.add(Json.map("candidate_id",100L+id.getLeastSignificantBits()-900,
                "semantic",Json.map("kind","order_pick","purpose","mulligan_bottom","source",null,
                        "position",0L,"count",(long)count,"item",Json.map("object",index.ref(c.world.uuidToId.get(id))))));
        Collections.reverse(offered);d.put("candidates",offered);return d;
    }
    public static void main(String[] args) throws Exception {
        List<Object> rows=new ArrayList<>();
        for(int size:new int[]{1,2,7}) for(int count:new int[]{1,size}) {
            MaintainerDialogReplayCheck.Case c=setup(size);Map<String,Object> d=decision(c,count);
            Map<String,Object> request=Json.map("game_start",Json.map("seat","p0","agent_seed",27L),"decision",d);
            require(MaintainerOriginalBridgeMain.reconstructionDecision(request)==d,"London reconstructed an activation anchor");
            Map<String,Object> result=MaintainerOriginalBridgeMain.choose(c.world,request);
            Map<String,Object> plan=Json.obj(result,"london_plan");List<Object> bottomed=Json.arr(plan,"bottomed");
            require(Boolean.TRUE.equals(result.get("original_london_path")) && bottomed.size()==count
                    && Long.valueOf(100+size-1).equals(Json.obj(result,"selection").get("candidate_id")),"original full-hand ranking selected another bottom card");
            require(c.player.getHand().size()==size-count && c.player.bottomed.size()==count
                    && c.backend.calls==Math.min(count,size-1) && c.backend.copies==0 && !c.backend.closed,
                    "London lost one-card movement, singleton bypass or its owned stream");
            for(int i=0;i<count;i++) require(new UUID(0,900+size-i-1).equals(c.player.bottomed.get(i)),"original reranking changed bottom order");
            for(int i=0;i<c.backend.ranks.size();i++)require(c.backend.ranks.get(i)==size-i,"London did not rank the shrinking whole hand");
            require(MaintainerPriorityBinding.hash(d).equals(result.get("decision_sha256")),"London lost its decision binding");
            rows.add(Json.map("hand",(long)size,"bottom_count",(long)count,"first_candidate",Json.obj(result,"selection").get("candidate_id"),
                    "ranking_counts",new ArrayList<>(c.backend.ranks),"remaining_hand",(long)c.player.getHand().size()));
            c.registry.close();
        }
        for(String fault:new String[]{"missing-menu","hidden","count","source","duplicate","position","counter","oversize"}) {
            MaintainerDialogReplayCheck.Case c=setup("oversize".equals(fault)?8:7);Map<String,Object> d=decision(c,2);
            List<Object> menu=Json.arr(d,"candidates");Map<String,Object> sem=Json.obj(Json.obj(menu.get(0)),"semantic");
            if("missing-menu".equals(fault))menu.remove(0);
            if("hidden".equals(fault))Json.obj(Json.obj(sem,"item"),"object").put("card_name","unknown secret");
            if("count".equals(fault))Json.obj(d,"group").put("substep_count",3L);
            if("source".equals(fault))sem.put("source",Json.map("object_id","another"));
            if("duplicate".equals(fault))menu.set(0,Json.copy(menu.get(1)));
            if("position".equals(fault))Json.obj(d,"group").put("substep_index",1L);
            if("counter".equals(fault))for(Object item:Json.arr(Json.obj(d,"observation"),"players"))
                if("p0".equals(Json.str(Json.obj(item),"seat")))Json.obj(item).put("mulligans_taken",1L);
            refused(()->MaintainerRootDecision.choose(c.world,Json.map("seat","p0","agent_seed",27L),d));
            require(c.backend.closed && c.backend.calls==0 && c.player.bottomed.isEmpty(),"invalid London group inferred or moved a card");
        }
        System.out.println(Json.canonical(rows));
        System.out.println("MaintainerLondonPlanCheck PASS: actual London callbacks, shrinking whole-hand card_select rankings, singleton bypass, one-card movement, first wire binding and pre-inference refusal");
    }
}
