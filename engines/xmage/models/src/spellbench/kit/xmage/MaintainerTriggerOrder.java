package spellbench.kit.xmage;

import mage.MageObject;
import mage.abilities.TriggeredAbility;
import mage.constants.Zone;
import mage.game.Game;
import spellbench.kit.core.Json;
import spellbench.kit.core.ObsIndex;
import java.lang.reflect.Method;
import java.text.Normalizer;
import java.util.*;
import java.util.function.Supplier;

/** Replay all posed trigger picks before the engine applies any, then verify its implicit returns. */
final class MaintainerTriggerOrder {
    private List<UUID> remaining;
    boolean scripted() {return remaining!=null;}
    static List<TriggeredAbility> abilities(Object[] args) {
        if(args.length!=2 || !(args[0] instanceof List) || !(args[1] instanceof java.util.function.Function))
            throw new IllegalArgumentException("trigger replay lacks its actual abilities and parent chooser");
        List<TriggeredAbility> result=new ArrayList<>();
        if(((List<?>)args[0]).size()>4096)throw new IllegalArgumentException("trigger group exceeds its supported envelope");
        for(Object value:(List<?>)args[0]) {
            if(!(value instanceof TriggeredAbility) || ((TriggeredAbility)value).getId()==null)
                throw new IllegalArgumentException("trigger replay contains a non-ability");
            result.add((TriggeredAbility)value);
        }
        return result;
    }
    static int index(List<TriggeredAbility> left,Object chosen) {
        for(int i=0;i<left.size();i++)if(left.get(i)==chosen)return i;
        throw new IllegalArgumentException("original parent selected a trigger outside its actual input list");
    }
    private static List<UUID> ids(List<TriggeredAbility> list) {
        List<UUID> ids=new ArrayList<>();for(TriggeredAbility t:list)ids.add(t.getId());return ids;
    }
    Object implicit(List<TriggeredAbility> actual,Supplier<?> parent) {
        if(remaining!=null && !remaining.equals(ids(actual)))
            throw new IllegalArgumentException("implicit engine trigger list differs from the recorded ordering group");
        Object picked=parent.get();
        if(actual.isEmpty()) {
            if(picked!=null)throw new IllegalArgumentException("empty original trigger callback returned an ability");
        } else if(index(actual,picked)!=0)
            throw new IllegalArgumentException("implicit original trigger chooser changed its fixed ordering");
        if(remaining!=null) {
            if(!remaining.isEmpty())remaining.remove(0);
            // GameImpl applies its final singleton directly without calling the chooser.
            if(remaining.size()<=1)remaining=null;
        }
        return picked;
    }
    Object complete(List<TriggeredAbility> actual,List<TriggeredAbility> order,Supplier<?> parent) {
        if(!ids(actual).equals(ids(order)))throw new IllegalArgumentException("original inherited trigger policy changed its list order");
        Object picked=parent.get();if(index(actual,picked)!=0)throw new IllegalArgumentException("original first trigger disagrees with its ordered group");
        remaining=ids(order);remaining.remove(0);
        if(remaining.size()<=1)remaining=null;
        return picked;
    }
    private static Map<String,Object> item(World world,Map<String,Object> decision,Map<String,Object> root,TriggeredAbility trigger,
                                           Map<String,Integer> instances) throws Exception {
        UUID sourceId=trigger.getSourceId();ObsIndex observed=new ObsIndex(Json.obj(decision,"observation"));
        Map<UUID,String> aliases=MaintainerModeEncoder.namedAliases(world,decision);
        Object visible=aliases.containsKey(sourceId)?observed.ref(aliases.get(sourceId)):null;
        Object original=world.uuidToId.containsKey(sourceId)?new ObsIndex(Json.obj(root,"observation")).ref(world.uuidToId.get(sourceId)):null;
        Map<String,Object> source=null;String name=null;Long abilityIndex=null;MageObject still=null;
        if(sourceId!=null && visible==null && original==null)
            throw new IllegalArgumentException("trigger source lacks current or recorded public identity");
        if(visible!=null || original!=null) {
            Zone zone=world.game.getState().getZone(sourceId);
            if(visible==null && (zone==Zone.LIBRARY || zone==Zone.HAND))
                throw new IllegalArgumentException("trigger source moved to an unobserved hidden zone");
            still=trigger.getSourceObjectIfItStillExists(world.game);
            if(still!=null) {
                if(!aliases.containsKey(still.getId()))throw new IllegalArgumentException("trigger source lacks its current permitted reference");
                source=Json.obj(observed.ref(aliases.get(still.getId())));name=Json.str(source,"card_name");
            } else {
                MageObject known=world.game.getObject(sourceId);
                if(known==null)known=world.game.getLastKnownInformation(sourceId,Zone.BATTLEFIELD);
                if(known!=null && known.getName()!=null && !known.getName().isEmpty())name=Normalizer.normalize(known.getName(),Normalizer.Form.NFC);
            }
            // Reuse the exact engine ordering, including granted abilities and original/copy identifiers.
            Method index=Class.forName("mage.player.spellbench.decide.SeatPlayer").getDeclaredMethod("triggerIndex",Game.class,TriggeredAbility.class);
            index.setAccessible(true);long value=(Long)index.invoke(null,world.game,trigger);if(value>=0)abilityIndex=value;
        }
        String key=(still==null?"gone:"+name:still.getId().toString())+":"+(abilityIndex==null?-1:abilityIndex);
        long instance=instances.merge(key,1,Integer::sum)-1;
        return Json.map("trigger",Json.map("source",source,"source_name",name,"ability_index",abilityIndex,
                "event_objects",new ArrayList<>(),"instance",instance,"label",null));
    }
    static Map<Integer,Map<String,Object>> choices(World world,Map<String,Object> decision,Map<String,Object> root,
            Map<String,Object> first,List<TriggeredAbility> left,int position,int count) {
        try {
            Map<String,Object> group=Json.obj(decision,"group"),initial=Json.obj(first,"group"),context=Json.obj(decision,"context");
            if(!world.viewer.equals(Json.str(decision,"acting_seat")) || !world.viewer.equals(Json.str(Json.obj(decision,"observation"),"viewer"))
                    || !"choice".equals(Json.str(context,"kind")) || context.get("source")!=null
                    || !(group.get("group_id") instanceof Long) || !Objects.equals(group.get("group_id"),initial.get("group_id"))
                    || !Long.valueOf(position).equals(group.get("substep_index"))
                    || !Long.valueOf(count-1).equals(group.get("substep_count")) || count-position!=left.size())
                throw new IllegalArgumentException("trigger callback differs from its complete ordering group");
            List<Object> expected=new ArrayList<>();Map<String,Integer> instances=new LinkedHashMap<>();
            for(TriggeredAbility trigger:left)expected.add(Json.map("kind","order_pick","source",null,"purpose","triggers",
                    "item",item(world,decision,root,trigger,instances),"position",(long)position,"count",(long)count));
            List<Object> candidates=Json.arr(decision,"candidates");
            if(candidates.size()!=expected.size())throw new IllegalArgumentException("trigger menu omits or adds actual abilities");
            Map<Integer,Map<String,Object>> choices=new LinkedHashMap<>();Set<Long> ids=new HashSet<>();
            for(int i=0;i<candidates.size();i++) {
                Map<String,Object> candidate=Json.obj(candidates.get(i));Object id=candidate.get("candidate_id");
                if(!(id instanceof Long) || (Long)id<0 || (Long)id>9007199254740991L || !ids.add((Long)id)
                        || !Json.canonical(expected.get(i)).equals(Json.canonical(candidate.get("semantic"))))
                    throw new IllegalArgumentException("trigger menu differs from the actual unsorted ability list or instance order");
                choices.put(i,Json.map("candidate_id",id,"semantic_echo",Json.copy(candidate.get("semantic"))));
            }
            return choices;
        } catch(RuntimeException failure) {throw failure;}
        catch(Exception failure) {throw new IllegalArgumentException("original trigger order binding failed",failure);}
    }
}
