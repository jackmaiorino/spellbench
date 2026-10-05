package spellbench.kit.xmage;

import mage.abilities.TriggeredAbility;
import mage.constants.Outcome;
import mage.constants.Zone;
import mage.game.Game;
import spellbench.kit.core.Json;
import spellbench.kit.core.ObsIndex;
import java.util.*;
import static spellbench.kit.xmage.JackPlayerBootstrapCheck.*;

/** Original parent oracle and whole wire ordering groups on metadata worlds. */
public final class JackTriggerReplayCheck {
    static final class Trigger extends mage.abilities.TriggeredAbilityImpl {
        Trigger() {super(Zone.BATTLEFIELD,new mage.abilities.effects.common.InfoEffect("metadata trigger"));}
        Trigger(Trigger old) {super(old);}
        @Override public Trigger copy() {return new Trigger(this);}
        @Override public boolean checkEventType(mage.game.events.GameEvent event,Game game) {return false;}
        @Override public boolean checkTrigger(mage.game.events.GameEvent event,Game game) {return false;}
    }
    static final class Case {
        final JackDialogReplayCheck.Case c=new JackDialogReplayCheck.Case(3,true);
        final List<TriggeredAbility> actual=new ArrayList<>();final boolean gone,anonymous;
        int physicalReturns;
        Case(int count,boolean gone,boolean anonymous) {
            this.gone=gone;this.anonymous=anonymous;
            List<UUID> hand=new ArrayList<>(c.player.getHand());List<Trigger> originals=new ArrayList<>();
            for(UUID id:hand) {
                Trigger trigger=new Trigger();trigger.setSourceId(id);trigger.setControllerId(c.player.getId());
                trigger.setSourceObjectZoneChangeCounter(c.root.cards.get(id).getZoneChangeCounter(c.world.game));
                c.root.cards.get(id).addAbility(trigger);originals.add(trigger);
            }
            for(int i=0;i<count;i++) {
                Trigger trigger=originals.get(i%originals.size()).copy();
                if(gone)trigger.setSourceObjectZoneChangeCounter(999);
                if(anonymous)trigger.setSourceId(null);
                actual.add(trigger);
            }
        }
        Map<String,Object> menu(int position) {
            Map<String,Object> d=c.decision("use");List<Object> candidates=new ArrayList<>();Map<String,Integer> instances=new LinkedHashMap<>();
            for(int i=position;i<actual.size();i++) {
                TriggeredAbility trigger=actual.get(i);Object source=anonymous || gone?null:new ObsIndex(Json.obj(d,"observation")).ref(c.world.uuidToId.get(trigger.getSourceId()));
                String name=anonymous?null:"Forest";Long index=anonymous?null:0L;
                String key=(gone || anonymous?"gone:"+name:trigger.getSourceId().toString())+":"+index;
                long instance=instances.merge(key,1,Integer::sum)-1;
                candidates.add(Json.map("candidate_id",900L+i-position,"semantic",Json.map("kind","order_pick","source",null,
                        "purpose","triggers","position",(long)position,"count",(long)actual.size(),"item",Json.map("trigger",Json.map(
                        "source",source,"source_name",name,"ability_index",index,"event_objects",Collections.emptyList(),"instance",instance,"label",null)))));
            }
            d.put("candidates",candidates);d.put("group",Json.map("group_id",700L,"substep_index",(long)position,"substep_count",(long)actual.size()-1));return d;
        }
        Map<String,Object> record(int prefix,boolean after) {
            return record(prefix,after,false);
        }
        void applyGroup(boolean nativeFinal) {
            List<TriggeredAbility> left=new ArrayList<>(actual);
            while(!left.isEmpty()) {
                if(!(nativeFinal && left.size()==1)) {
                    TriggeredAbility picked=c.player.chooseTriggeredAbility(left,c.world.game);
                    require(picked==left.get(0),"physical original trigger choice changed");
                }
                physicalReturns++;left.remove(0);
            }
            if(!nativeFinal)require(c.player.chooseTriggeredAbility(left,c.world.game)==null,"empty trigger callback changed");
        }
        Map<String,Object> record(int prefix,boolean after,boolean nativeFinal) {
            Map<String,Object> r=c.record(false);List<Object> earlier=new ArrayList<>();
            for(int i=0;i<prefix;i++) {
                Map<String,Object> d=menu(i),first=Json.obj(Json.arr(d,"candidates").get(0));
                earlier.add(Json.map("decision",d,"selection",Json.map("candidate_id",first.get("candidate_id"),"semantic_echo",first.get("semantic"))));
            }
            Json.obj(r,"replay").put("earlier",earlier);r.put("decision",after?c.decision("use"):menu(prefix));
            c.player.activationWork=()->{
                applyGroup(nativeFinal);
                c.player.chooseUse(Outcome.Benefit,"after group",null,c.world.game);
            };return r;
        }
        Map<String,Object> nextGroup(int prefix,boolean after) {
            Map<String,Object> r=record(actual.size()-1,true,true);
            List<Object> earlier=Json.arr(Json.obj(r,"replay"),"earlier");
            for(int i=0;i<prefix;i++) {
                Map<String,Object> d=menu(i);Json.obj(d,"group").put("group_id",701L);
                Map<String,Object> first=Json.obj(Json.arr(d,"candidates").get(0));
                earlier.add(Json.map("decision",d,"selection",Json.map("candidate_id",first.get("candidate_id"),"semantic_echo",first.get("semantic"))));
            }
            if(!after) {
                Map<String,Object> d=menu(prefix);Json.obj(d,"group").put("group_id",701L);r.put("decision",d);
            }
            c.player.activationWork=()->{
                applyGroup(true);applyGroup(true);
                c.player.chooseUse(Outcome.Benefit,"after two groups",null,c.world.game);
            };return r;
        }
        void oracle() {
            JackAmountReplayCheck.Oracle oracle=new JackAmountReplayCheck.Oracle(c.player);oracle.admitted=c.world.game;
            // Parent-world entry also checks owner identity; use the same proxy pattern as the amount oracle.
            oracle.admitted=(Game)java.lang.reflect.Proxy.newProxyInstance(Game.class.getClassLoader(),new Class<?>[]{Game.class},(o,m,a)->{
                if("getPlayer".equals(m.getName()) && oracle.getId().equals(a[0]))return oracle;
                try{return m.invoke(c.world.game,a);}catch(java.lang.reflect.InvocationTargetException failure){throw failure.getCause();}
            });
            List<TriggeredAbility> left=new ArrayList<>(actual);
            while(!left.isEmpty()) {require(oracle.chooseTriggeredAbility(left,oracle.admitted)==left.get(0),"parent trigger oracle changed");left.remove(0);}
            require(oracle.chooseTriggeredAbility(left,oracle.admitted)==null,"empty parent oracle changed");
        }
    }
    public static void main(String[] args) throws Exception {
        List<Object> rows=new ArrayList<>();
        for(int count:new int[]{2,3,4,6})for(boolean gone:new boolean[]{false,true})for(boolean anonymous:new boolean[]{false,true}) {
            for(String loop:Arrays.asList("explicit-singleton","native-singleton","two-native-groups"))for(int prefix=0;prefix<count;prefix++) {
                boolean after=prefix==count-1,two="two-native-groups".equals(loop);Case c=new Case(count,gone,anonymous);c.oracle();
                Map<String,Object> record=two?c.nextGroup(prefix,after):c.record(prefix,after,"native-singleton".equals(loop));
                Map<String,Object> result=c.c.control(record).choose(),semantic=Json.obj(Json.obj(result,"selection"),"semantic_echo");
                require(after?"choose_boolean".equals(semantic.get("kind")):Long.valueOf(0).equals(Json.obj(Json.obj(semantic,"item"),"trigger").get("instance")),"original trigger ordering changed");
                require(c.physicalReturns==((two?count:0)+(after?count:0)),"engine advanced between posed ordering picks");
                require(c.c.backend.calls==(after?1:0) && c.c.backend.copies==0 && !c.c.backend.closed,"trigger replay consumed neural/copy scoring or closed session");
                require(Long.valueOf(prefix+(two?count-1:0)).equals(result.get("original_dialog_prefix_replayed")),"trigger prefix count changed");
                rows.add(Json.map("count",(long)count,"gone",gone,"anonymous",anonymous,"loop",loop,"prefix",(long)prefix,"after",after));c.c.registry.close();
            }
        }
        for(String fault:Arrays.asList("hole","reorder","duplicate-id","group-id","group-index","group-count","position","count","instance","ability-index","events","historical","hidden-source","scripted-order")) {
            Case c=new Case(4,false,false);boolean scripted="scripted-order".equals(fault),past="historical".equals(fault);
            Map<String,Object> r=c.record(scripted?3:past?1:0,scripted),d=Json.obj(r,"decision");
            if(!scripted) {
                Map<String,Object> candidate=Json.obj(Json.arr(d,"candidates").get(0)),sem=Json.obj(candidate,"semantic"),trigger=Json.obj(Json.obj(sem,"item"),"trigger");
                if("hole".equals(fault))Json.arr(d,"candidates").remove(0);
                if("reorder".equals(fault))Collections.reverse(Json.arr(d,"candidates"));
                if("duplicate-id".equals(fault))candidate.put("candidate_id",901L);
                if("group-id".equals(fault))Json.obj(d,"group").put("group_id",0.5);
                if("group-index".equals(fault))Json.obj(d,"group").put("substep_index",1L);
                if("group-count".equals(fault))Json.obj(d,"group").put("substep_count",4L);
                if("position".equals(fault))sem.put("position",1L);
                if("count".equals(fault))sem.put("count",5L);
                if("instance".equals(fault))trigger.put("instance",1L);
                if("ability-index".equals(fault))trigger.put("ability_index",1L);
                if("events".equals(fault))trigger.put("event_objects",Collections.singletonList(Json.map("player","p1")));
                if("historical".equals(fault)) {
                    Map<String,Object> entry=Json.obj(Json.arr(Json.obj(r,"replay"),"earlier").get(0)),other=Json.obj(Json.arr(Json.obj(entry,"decision"),"candidates").get(1));
                    entry.put("selection",Json.map("candidate_id",other.get("candidate_id"),"semantic_echo",other.get("semantic")));
                }
                if("hidden-source".equals(fault))c.actual.get(0).setSourceId(c.c.root.other.getHand().iterator().next());
            } else c.c.player.activationWork=()->{
                List<TriggeredAbility> left=new ArrayList<>(c.actual);require(c.c.player.chooseTriggeredAbility(left,c.c.world.game)==left.get(0),"initial trigger return");
                left.remove(0);Collections.reverse(left);c.c.player.chooseTriggeredAbility(left,c.c.world.game);
            };
            refused(()->c.c.control(r).choose());require(c.c.backend.calls==0 && c.c.backend.copies==0 && c.c.backend.closed,"invalid trigger ordering performed scoring or retained session");
        }
        System.out.println(Json.canonical(rows));
        System.out.println("JackTriggerReplayCheck PASS: unchanged parent oracle, complete virtual ordering before physical returns, repeated instances, gone/public/anonymous sources, explicit and engine-skipped singletons, consecutive groups and historical/order refusals; metadata only, native event loop unqualified");
    }
}
