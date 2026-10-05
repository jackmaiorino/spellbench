package spellbench.kit.xmage;

import mage.abilities.ActivatedAbility;
import mage.game.Game;
import spellbench.kit.core.Json;
import spellbench.kit.core.ObsIndex;
import java.lang.reflect.*;
import java.util.*;

/** Preserve the original priority validation result across permitted root reconstruction. */
final class JackPriorityState {
    private JackPriorityState() { }
    @SuppressWarnings("unchecked")
    static Map<String,Object> capture(World world,Map<String,Object> decision,Object rules) throws Exception {
        Map<UUID,Set<String>> actual=(Map<UUID,Set<String>>)call(rules.getClass().getMethod("alternatives"),rules);
        ObsIndex observed=new ObsIndex(Json.obj(decision,"observation"));
        Map<String,Object> rows=new TreeMap<>();
        for(Map.Entry<UUID,Set<String>> entry:actual.entrySet()) {
            String alias=world.uuidToId.get(entry.getKey());Map<String,Object> source=observed.ref(alias);
            if(source==null || alias==null || Json.str(source,"card_name")==null || Json.str(source,"card_name").isEmpty()
                    || !entry.getKey().equals(world.idToUuid.get(alias)))
                throw new IllegalArgumentException("original alternative-cost state has no permitted source");
            rows.put(alias,Json.map("source",Json.copy(source),"choices",new ArrayList<>(keys(entry.getValue()))));
        }
        return Json.map("alternatives",new ArrayList<>(rows.values()));
    }
    static void restore(World world,Map<String,Object> root,Object recorded,ActivatedAbility selected,Object rules) throws Exception {
        if(!(recorded instanceof Map)) throw new IllegalArgumentException("recorded original priority state required");
        Map<String,Object> state=Json.obj(recorded);
        if(state.size()!=1 || !(state.get("alternatives") instanceof List))
            throw new IllegalArgumentException("recorded original priority state has a different schema");
        List<Object> rows=Json.arr(state,"alternatives");
        if(rows.size()>4096) throw new IllegalArgumentException("recorded original priority state exceeds its bound");
        ObsIndex observed=new ObsIndex(Json.obj(root,"observation"));Map<UUID,Set<String>> restored=new LinkedHashMap<>();
        for(Object item:rows) {
            Map<String,Object> row=Json.obj(item),source=Json.obj(row,"source");String alias=Json.str(source,"object_id");
            UUID id=world.idToUuid.get(alias);
            if(row.size()!=2 || id==null || Json.str(source,"card_name")==null || Json.str(source,"card_name").isEmpty()
                    || !Json.canonical(source).equals(Json.canonical(observed.ref(alias)))
                    || !(row.get("choices") instanceof List) || restored.containsKey(id))
                throw new IllegalArgumentException("recorded alternative-cost state has an aliased or foreign source");
            restored.put(id,keys(Json.arr(row,"choices")));
        }
        call(rules.getClass().getMethod("restoreActivation",Game.class,ActivatedAbility.class,Map.class),rules,world.game,selected,restored);
    }
    private static Set<String> keys(Collection<?> values) {
        if(values==null || values.isEmpty() || values.size()>4096)
            throw new IllegalArgumentException("recorded alternative-cost key bound exceeded");
        Set<String> result=new TreeSet<>();
        for(Object value:values) if(!(value instanceof String) || ((String)value).isEmpty() || ((String)value).length()>1024 || !result.add((String)value))
            throw new IllegalArgumentException("recorded alternative-cost keys are invalid or aliased");
        return result;
    }
    private static Object call(Method method,Object owner,Object...args) throws Exception {
        try{return method.invoke(owner,args);} catch(InvocationTargetException failure) {
            Throwable cause=failure.getCause();if(cause instanceof Error) throw (Error)cause;
            if(cause instanceof RuntimeException) throw (RuntimeException)cause;throw failure;
        }
    }
}
