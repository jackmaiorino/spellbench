package spellbench.kit.xmage;

import mage.MageObject;
import mage.cards.Card;
import spellbench.kit.core.Json;
import spellbench.kit.core.ObsIndex;
import java.util.*;

/** Bind unchanged inherited pile and replacement policies to their actual callback menus. */
final class JackInheritedChoices {
    private static Object reference(UUID id, Map<UUID,String> aliases, ObsIndex observed) {
        if(id==null || !aliases.containsKey(id))
            throw new IllegalArgumentException("inherited callback contains an object outside permitted visible aliases");
        Object ref=observed.ref(aliases.get(id));
        if(ref==null)throw new IllegalArgumentException("inherited callback object lacks a visible reference");
        return ref;
    }
    private static List<Object> pile(Object supplied,Map<UUID,String> aliases,ObsIndex observed) {
        if(!(supplied instanceof List))throw new IllegalArgumentException("original pile callback lacks its actual cards");
        List<Object> result=new ArrayList<>();
        if(((List<?>)supplied).size()>4096)throw new IllegalArgumentException("original pile exceeds the supported envelope");
        for(Object value:(List<?>)supplied) {
            if(!(value instanceof Card))throw new IllegalArgumentException("original pile contains a non-card");
            result.add(reference(((Card)value).getId(),aliases,observed));
        }
        return result;
    }
    static Map<Object,Map<String,Object>> replayChoices(World world,Map<String,Object> decision,String kind,Object[] args) {
        try {
            Map<String,Object> observation=Json.obj(decision,"observation"),context=Json.obj(decision,"context");
            if(!world.viewer.equals(Json.str(decision,"acting_seat"))
                    || !world.viewer.equals(Json.str(observation,"viewer"))
                    || !"choice".equals(Json.str(context,"kind")) || context.get("source")!=null || args.length!=2)
                throw new IllegalArgumentException("inherited callback differs from its acting wire choice");
            Map<UUID,String> aliases=JackModeEncoder.namedAliases(world,decision);ObsIndex observed=new ObsIndex(observation);
            List<Object> expected=new ArrayList<>();
            if("pile".equals(kind)) {
                List<Object> piles=Arrays.asList(pile(args[0],aliases,observed),pile(args[1],aliases,observed));
                for(long index=0;index<2;index++)expected.add(Json.map("kind","choose_pile","source",null,
                        "purpose","effect","pile_index",index,"piles",piles));
            } else if("replacement".equals(kind)) {
                if(!(args[0] instanceof Map) || args[1]!=null && !(args[1] instanceof Map))
                    throw new IllegalArgumentException("original replacement callback lacks its actual maps");
                Map<?,?> effects=(Map<?,?>)args[0],objects=(Map<?,?>)args[1];
                if(effects.size()<2 || effects.size()>4096)
                    throw new IllegalArgumentException("original replacement menu is implicit or exceeds the supported envelope");
                // The engine and inherited policy use the actual iterator order, without sorting labels or keys.
                for(Object key:effects.keySet()) {
                    if(!(key instanceof String) || !(effects.get(key) instanceof String))
                        throw new IllegalArgumentException("original replacement map has a non-string key or label");
                    Object object=objects==null?null:objects.get(key),ref=null;
                    if(object!=null) {
                        if(!(object instanceof MageObject))throw new IllegalArgumentException("replacement source is not an actual object");
                        ref=reference(((MageObject)object).getId(),aliases,observed);
                    }
                    expected.add(Json.map("kind","choose_replacement","affected",Json.map("player",world.viewer),
                            "event","other","replacement_source",ref,"replacement_index",(long)expected.size(),
                            "replacement_count",(long)effects.size()));
                }
            } else throw new IllegalArgumentException("unconnected inherited callback");
            List<Object> candidates=Json.arr(decision,"candidates");
            if(candidates.size()!=expected.size())throw new IllegalArgumentException("inherited wire menu omits or adds actual choices");
            Set<Long> ids=new HashSet<>();Set<Integer> indices=new HashSet<>();
            Map<Object,Map<String,Object>> choices=new LinkedHashMap<>();
            for(Object item:candidates) {
                Map<String,Object> candidate=Json.obj(item),semantic=Json.obj(candidate,"semantic");
                Object id=candidate.get("candidate_id"),index=semantic.get("pile".equals(kind)?"pile_index":"replacement_index");
                if(!(id instanceof Long) || (Long)id<0 || (Long)id>9007199254740991L || !ids.add((Long)id)
                        || !(index instanceof Long) || (Long)index<0 || (Long)index>=expected.size()
                        || !indices.add(((Long)index).intValue())
                        || !Json.canonical(semantic).equals(Json.canonical(expected.get(((Long)index).intValue()))))
                    throw new IllegalArgumentException("inherited action is aliased or differs from its actual ordered menu");
                Object value="pile".equals(kind)?(Object)Boolean.valueOf((Long)index==0):Integer.valueOf(((Long)index).intValue());
                choices.put(value,Json.map("candidate_id",id,"semantic_echo",Json.copy(semantic)));
            }
            return choices;
        } catch(RuntimeException failure) {throw failure;}
        catch(Exception failure) {throw new IllegalArgumentException("original inherited callback binding failed",failure);}
    }
}
