package spellbench.kit.xmage;

import mage.cards.Card;
import spellbench.kit.core.Json;
import spellbench.kit.core.ObsIndex;
import spellbench.kit.core.Sampler;
import java.util.*;
import static spellbench.kit.xmage.MaintainerPlayerBootstrapCheck.*;

/** Real permitted-input sampling and original callbacks on metadata worlds, no native database. */
public final class MaintainerReplayKnowledgeCheck {
    @SuppressWarnings("unchecked") static Map<UUID,String> aliases(MaintainerDialogReplayCheck.Viewer player) throws Exception {
        java.lang.reflect.Method method=spellbench.models.maintainer.OriginalCallbackPlayer.class.getSuperclass().getDeclaredMethod("originalPriorityRules");method.setAccessible(true);
        Object rules=method.invoke(player);return (Map<UUID,String>)rules.getClass().getMethod("aliases").invoke(rules);
    }
    static Map<String,Object> fact(String id,String name,String how,Object top,Object bottom) {
        return Json.map("object_id",id,"card_name",name,"owner_seat","p0","zone","library","how",how,"position_from_top",top,"position_from_bottom",bottom);
    }
    static Map<String,Object> root() {
        return Json.map("acting_seat","p0","context",Json.map("kind","priority"),"observation",Json.map("viewer","p0","known",Collections.emptyList(),"stack",Collections.emptyList(),
                "players",Arrays.asList(Json.map("seat","p0","library_count",4L,"hand_count",0L,"hand",Collections.emptyList()),
                    Json.map("seat","p1","library_count",3L,"hand_count",0L,"hand",Collections.emptyList()))));
    }
    static Map<String,Object> request(Map<String,Object> root,List<Object> shown) {
        Map<String,Object> current=Json.obj(Json.copy(root));Json.obj(current,"observation").put("known",shown);Json.obj(current,"context").put("kind","choice");
        return Json.map("anchor",Json.map("decision",root),"decision",current,"replay",Json.map("earlier",Collections.emptyList()));
    }
    static void samples() {
        Map<String,Object> start=Json.map("own_deck",Json.map("decklist",Arrays.asList(Json.map("name","Forest","count",2L),Json.map("name","Island","count",1L),Json.map("name","Mountain","count",1L))),
                "opponent_deck",null,"rules",Json.map("opponent_decklist","hidden","card_name_domain",Json.map("names",Arrays.asList("Forest","Island"))));
        for(String how:Arrays.asList("searching","looked_at","revealed"))for(boolean bottom:new boolean[]{false,true}) {
            Map<String,Object> root=root(),pin=fact("new","Mountain",how,"searching".equals(how)?null:bottom?null:0L,"searching".equals(how)?null:bottom?0L:null);
            Map<String,Object> record=request(root,Collections.singletonList(pin));String before=Json.canonical(record);
            Map<String,Object> sampling=MaintainerReplayKnowledge.samplingObservation(root,record);
            require(before.equals(Json.canonical(record)) && Json.arr(Json.obj(root,"observation"),"known").isEmpty(),"conditioning changed root visibility or replay input");
            for(int seed=0;seed<8;seed++) {
                Sampler.Sample sample=Sampler.sample(start,sampling,new Random(seed));Sampler.SeatSample own=sample.seats.get("p0");
                require(own.library.size()==4 && own.pinned==1 && own.deficit==0 && own.surplus==0,"conditioned pool changed its size or composition");
                Sampler.Slot found=null;int position=-1;
                for(int i=0;i<own.library.size();i++)if("new".equals(own.library.get(i).objectId)){found=own.library.get(i);position=i;}
                require(found!=null && "Mountain".equals(found.name),"newly shown card was not sampled");
                if(!"searching".equals(how))require(position==(bottom?3:0),"permitted position changed");
                for(Sampler.Slot other:sample.seats.get("p1").library)require(other.objectId==null && !other.pinned,"future fact leaked into the opponent sample");
            }
        }
        Map<String,Object> root=root(),first=fact("first","Forest","looked_at",0L,null),last=fact("last","Island","searching",null,null);
        Map<String,Object> record=request(root,Arrays.asList(Json.copy(first),last));
        Map<String,Object> earlier=request(root,Collections.singletonList(first));
        Json.obj(record,"replay").put("earlier",Collections.singletonList(Json.map("decision",Json.obj(earlier,"decision"))));
        Map<String,Object> moved=Json.obj(Json.arr(Json.obj(Json.obj(record,"decision"),"observation"),"known").get(0));moved.put("position_from_top",2L);
        List<Object> known=Json.arr(MaintainerReplayKnowledge.samplingObservation(root,record),"known");
        require(known.size()==2 && Long.valueOf(0).equals(Json.obj(known.get(0)).get("position_from_top")),"first visibility was replaced by later engine movement");
        Map<String,Object> opponent=fact("other","Secret","searching",null,null);opponent.put("owner_seat","p1");
        require(Json.arr(MaintainerReplayKnowledge.samplingObservation(root,request(root,Collections.singletonList(opponent))),"known").isEmpty(),"future opponent library knowledge entered root sampling");
        for(String fault:Arrays.asList("how","position","missing-position","both-positions","owner-viewer","name-conflict","position-count-change","position-collision","capacity","fields","foreign-root")) {
            Map<String,Object> r=root(),f=fact("new","Mountain","looked_at",0L,null),q=request(r,new ArrayList<>(Collections.singletonList(f)));
            Map<String,Object> now=Json.obj(Json.obj(q,"decision"),"observation");
            if("how".equals(fault))f.put("how","hidden");if("position".equals(fault))f.put("position_from_top",4L);
            if("missing-position".equals(fault))f.put("position_from_top",null);if("both-positions".equals(fault))f.put("position_from_bottom",0L);
            if("owner-viewer".equals(fault))now.put("viewer","p1");
            if("name-conflict".equals(fault))Json.obj(q,"replay").put("earlier",Collections.singletonList(Json.map("decision",Json.obj(request(r,Collections.singletonList(fact("new","Island","looked_at",0L,null))),"decision"))));
            if("position-count-change".equals(fault))Json.obj(Json.arr(now,"players").get(0)).put("library_count",3L);
            if("position-collision".equals(fault))Json.arr(now,"known").add(fact("same-position","Forest","looked_at",0L,null));
            if("capacity".equals(fault)){Json.arr(now,"known").clear();for(int i=0;i<5;i++)Json.arr(now,"known").add(fact("pin"+i,"Forest","searching",null,null));}
            if("fields".equals(fault))f.put("private_deck",Arrays.asList("Secret"));
            if("foreign-root".equals(fault))Json.obj(q,"anchor").put("decision",root());
            if("foreign-root".equals(fault))r.put("changed",true);
            refused(()->MaintainerReplayKnowledge.samplingObservation(r,q));
        }
    }
    @SuppressWarnings("unchecked") static Object state(MaintainerDialogReplayCheck.Case c,Map<UUID,String> aliases) throws Exception {
        Class<?> type=Class.forName("spellbench.models.maintainer.StateSequenceBuilder");
        return type.getMethod("buildBaseState",mage.game.Game.class,mage.constants.TurnPhase.class,int.class,UUID.class,Map.class).invoke(null,c.world.game,null,256,c.player.getId(),aliases);
    }
    @SuppressWarnings("unchecked") static void callback(int count) throws Exception {
        MaintainerDialogReplayCheck.Case c=new MaintainerDialogReplayCheck.Case(0,false,true);
        UUID library=c.player.getLibrary().getCardList().get(0);Card card=c.root.cards.get(library);
        List<Card> shown=new ArrayList<>();shown.add(card);
        if(count==2) {
            Card second=new MetadataCard(c.player.getId(),"Forest");c.root.cards.put(second.getId(),second);c.player.getLibrary().putOnTop(second,c.world.game);
            c.hidden.add(second.getId());c.world.bind("future-extra",second.getId());shown.add(second);
        }
        require(!aliases(c.player).containsKey(library),"future library alias was admitted at the root");
        Map<UUID,Integer> rootTokens=(Map<UUID,Integer>)state(c,aliases(c.player)).getClass().getField("uuidToTokenIndex").get(state(c,aliases(c.player)));
        for(Card hidden:shown)require(!rootTokens.containsKey(hidden.getId()),"root encoder included future library knowledge");
        Map<String,Object> record=c.record(false),root=Json.obj(Json.obj(record,"anchor"),"decision");
        require(RoundTrip.diff(c.world,root).isEmpty(),"future binding changed root projection");
        List<Object> known=new ArrayList<>();for(Card showing:shown)known.add(fact(c.world.uuidToId.get(showing.getId()),showing.getName(),"searching",null,null));
        Map<String,Object> current=Json.obj(Json.copy(c.decision("use")));for(Card showing:shown)c.hidden.remove(showing.getId());
        current.put("observation",RoundTrip.project(c.world,MaintainerDialogReplayCheck.flags(),"p0",known));for(Card showing:shown)c.hidden.add(showing.getId());
        for(Object item:Json.arr(Json.obj(current,"observation"),"known"))for(Card showing:shown)if(showing.getName().equals(Json.str(Json.obj(item),"card_name")))c.world.bind(Json.str(Json.obj(item),"object_id"),showing.getId());
        ObsIndex index=new ObsIndex(Json.obj(current,"observation"));Object source=index.ref(c.world.uuidToId.get(c.ability.getSourceId()));
        current.put("context",Json.map("kind","choice","source",source));List<Object> candidates=new ArrayList<>();List<UUID> choices=new ArrayList<>();
        for(int i=0;i<shown.size();i++) {Card showing=shown.get(i);choices.add(showing.getId());candidates.add(Json.map("candidate_id",77L+i,"semantic",Json.map(
                "kind","choose_target","source",source,"slot",0L,"target",Json.map("object",index.ref(c.world.uuidToId.get(showing.getId()))),"selected_count",0L,"minimum",1L,"maximum",1L)));}
        current.put("candidates",candidates);record.put("decision",current);MaintainerTargetReplayCheck.Menu menu=new MaintainerTargetReplayCheck.Menu(choices,1,1);c.player.target=menu.target;
        c.player.playable=(mage.abilities.ActivatedAbility)java.lang.reflect.Proxy.newProxyInstance(mage.abilities.ActivatedAbility.class.getClassLoader(),new Class<?>[]{mage.abilities.ActivatedAbility.class},(o,m,a)->{
            if("getControllerId".equals(m.getName()))return c.player.getId();if("copy".equals(m.getName()))return o;
            try{return m.invoke(c.ability,a);}catch(java.lang.reflect.InvocationTargetException failure){throw failure.getCause();}
        });
        c.player.activationWork=()->{for(Card showing:shown){c.hidden.remove(showing.getId());c.world.game.getState().getLookedAt(c.player.getId()).add("actual own look",showing);}};
        Map<String,Object> result=MaintainerOriginalBridgeMain.choose(c.world,record);
        require(Long.valueOf(76+count).equals(Json.obj(result,"selection").get("candidate_id")) && c.backend.calls==count-1 && c.backend.copies==0 && c.player.entered==1,"new library target changed original policy or activation");
        if(count==2) {
            require(c.backend.heads.equals(Collections.singletonList("target")),"new library menu used another original head");
            Object currentState=state(c,aliases(c.player));Map<UUID,Integer> currentTokens=(Map<UUID,Integer>)currentState.getClass().getField("uuidToTokenIndex").get(currentState);
            for(Card showing:shown)require(currentTokens.containsKey(showing.getId()),"current encoder missed newly permitted library cards");
            require(Arrays.deepEquals(c.backend.lastRequest.tokens(),(float[][])currentState.getClass().getField("tokens").get(currentState)),"original policy used another current visibility state");
        }
        require(aliases(c.player).containsKey(library) && !c.backend.closed,"current own look was not admitted or owned pause closed inference");c.registry.close();
        MaintainerDialogReplayCheck.Case invalid=new MaintainerDialogReplayCheck.Case();Map<String,Object> badRoot=root();
        Map<String,Object> bad=request(badRoot,Collections.singletonList(fact("missing-deck-card","Mountain","searching",null,null)));
        Map<String,Object> start=Json.map("own_deck",Json.map("decklist",Collections.singletonList(Json.map("name","Forest","count",4L))),"opponent_deck",null,
                "rules",Json.map("opponent_decklist","hidden","card_name_domain",Json.map("names",Collections.singletonList("Forest"))));
        refused(()->invalid.registry.buildReplay(start,badRoot,bad,KitRandom.install(new byte[32],new byte[32]),WorldBuilder.Mode.PRIORITY,0));
        require(invalid.backend.closed && invalid.backend.calls==0,"contradictory conditioned pool reached bootstrap or inference");
    }
    public static void main(String[] args) throws Exception {
        samples();callback(1);callback(2);
        System.out.println("MaintainerReplayKnowledgeCheck PASS: real permitted sampler, first visibility and root isolation, original newly shown library target, no hidden alias admission/read, position and identity refusals; metadata worlds only, native reconstruction and position transport unqualified");
    }
}
