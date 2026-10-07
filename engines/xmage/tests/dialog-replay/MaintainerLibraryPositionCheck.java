package spellbench.kit.xmage;

import mage.cards.Card;
import spellbench.kit.core.Json;
import java.util.*;
import static spellbench.kit.xmage.MaintainerPlayerBootstrapCheck.*;

/** Position validation on reconstructed metadata libraries, before original policy scoring. */
public final class MaintainerLibraryPositionCheck {
    interface Checked { void run() throws Exception; }
    static void refusedChecked(Checked action) {
        try { action.run(); } catch (IllegalArgumentException expected) { return; }
        catch (Exception unexpected) { throw new AssertionError(unexpected); }
        throw new AssertionError("invalid library position was accepted");
    }
    static Map<String,Object> decision(MaintainerDialogReplayCheck.Case c,String id,Object top,Object bottom,String how,String owner) {
        String name="second".equals(id)?"Island":"other".equals(id)?"Permitted public reveal":"Mountain";
        Map<String,Object> d=c.decision("use"),fact=MaintainerReplayKnowledgeCheck.fact(id,name,how,top,bottom);
        fact.put("owner_seat",owner);Json.obj(d,"observation").put("known",Collections.singletonList(fact));return d;
    }
    public static void main(String[] args) throws Exception {
        MaintainerDialogReplayCheck.Case c=new MaintainerDialogReplayCheck.Case(0,false,true);
        UUID first=c.player.getLibrary().getCardList().get(0);Card second=new MetadataCard(c.player.getId(),"Island");
        c.root.cards.put(second.getId(),second);c.player.getLibrary().putOnTop(second,c.world.game);c.hidden.add(second.getId());c.world.bind("second",second.getId());
        Card other=new MetadataCard(c.root.other.getId(),"Permitted public reveal");c.root.cards.put(other.getId(),other);
        c.root.other.getLibrary().putOnTop(other,c.world.game);c.hidden.add(other.getId());c.world.bind("other",other.getId());
        List<Object> facts=new ArrayList<>();
        for(String id:Arrays.asList("second","future-library","other"))for(String how:Arrays.asList("searching","looked_at","revealed")) {
            boolean opponent="other".equals(id);long top="future-library".equals(id)?1:0,bottom="second".equals(id)?1:0;
            Map<String,Object> d=decision(c,id,top,bottom,how,opponent?"p1":"p0");
            MaintainerReplayKnowledge.verifyPositions(c.world,d);facts.add(Json.obj(Json.copy(Json.arr(Json.obj(d,"observation"),"known").get(0))));
            Json.obj(Json.arr(Json.obj(d,"observation"),"known").get(0)).put("position_from_bottom",null);MaintainerReplayKnowledge.verifyPositions(c.world,d);
            Json.obj(Json.arr(Json.obj(d,"observation"),"known").get(0)).put("position_from_top",null);
            Json.obj(Json.arr(Json.obj(d,"observation"),"known").get(0)).put("position_from_bottom",bottom);MaintainerReplayKnowledge.verifyPositions(c.world,d);
            Json.obj(Json.arr(Json.obj(d,"observation"),"known").get(0)).put("position_from_bottom",null);
            if("searching".equals(how))MaintainerReplayKnowledge.verifyPositions(c.world,d);else refused(()->MaintainerReplayKnowledge.verifyPositions(c.world,d));
        }
        for(String fault:Arrays.asList("top","bottom","both","fractional","bool","unbound","owner","zone","viewer")) {
            Map<String,Object> d=decision(c,"future-library",1L,0L,"looked_at","p0"),fact=Json.obj(Json.arr(Json.obj(d,"observation"),"known").get(0));
            if("top".equals(fault))fact.put("position_from_top",0L);if("bottom".equals(fault))fact.put("position_from_bottom",1L);
            if("both".equals(fault)){fact.put("position_from_top",0L);fact.put("position_from_bottom",1L);}
            if("fractional".equals(fault))fact.put("position_from_top",1.5);if("bool".equals(fault))fact.put("position_from_top",true);
            if("unbound".equals(fault))fact.put("object_id","absent");if("owner".equals(fault))fact.put("owner_seat","p1");
            if("zone".equals(fault))fact.put("object_id",c.world.uuidToId.get(c.player.getHand().iterator().next()));
            if("viewer".equals(fault))Json.obj(d,"observation").put("viewer","p1");
            refused(()->MaintainerReplayKnowledge.verifyPositions(c.world,d));
        }
        // A real rearrangement updates validity; copying a claimed position does not.
        Map<String,Object> stale=decision(c,"future-library",1L,0L,"looked_at","p0");
        c.hidden.remove(first);c.player.getLibrary().remove(first,c.world.game);c.player.getLibrary().putOnTop(c.root.cards.get(first),c.world.game);c.hidden.add(first);
        refused(()->MaintainerReplayKnowledge.verifyPositions(c.world,stale));
        Map<String,Object> current=decision(c,"future-library",0L,1L,"looked_at","p0");MaintainerReplayKnowledge.verifyPositions(c.world,current);
        // Before this fix the projection accepted this wrong position solely from the supplied Look.
        c.hidden.remove(first);Map<String,Object> forged=decision(c,"future-library",1L,null,"looked_at","p0");
        require(Json.arr(RoundTrip.project(c.world,MaintainerDialogReplayCheck.flags(),"p0",Json.arr(Json.obj(forged,"observation"),"known")),"known").size()==1,"fixture no longer demonstrates copied-position projection");
        refusedChecked(()->MaintainerWorldAliases.namedAliases(c.world,forged));
        Map<String,Object> record=c.record(false),root=Json.obj(Json.obj(record,"anchor"),"decision");Json.obj(root,"observation").put("known",Json.arr(Json.obj(forged,"observation"),"known"));
        refusedChecked(()->MaintainerOriginalBridgeMain.choose(c.world,record));
        require(c.backend.closed && c.backend.calls==0 && c.backend.copies==0 && c.player.entered==0,"forged position reached activation or inference");
        System.out.println(Json.canonical(facts));
        System.out.println("MaintainerLibraryPositionCheck PASS: actual top/bottom and membership checks for either permitted library, no hidden names fetched, rearrangement and copied-position forgery refused before activation/inference; metadata worlds only");
    }
}
