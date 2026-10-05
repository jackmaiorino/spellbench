package spellbench.kit.xmage;

import spellbench.kit.core.Json;
import spellbench.kit.core.ObsIndex;
import java.util.*;

/** Conditions hidden reconstruction on permitted callback facts, without changing root visibility. */
final class JackReplayKnowledge {
    private JackReplayKnowledge() { }
    static final Set<String> FIELDS=new HashSet<>(Arrays.asList("object_id","card_name","owner_seat","zone","how","position_from_top","position_from_bottom"));
    static Map<String,Object> samplingObservation(Map<String,Object> root,Map<String,Object> record) {
        Map<String,Object> observation=Json.obj(Json.copy(root.get("observation")));
        if(record.get("anchor")==null)return observation;
        if(!Json.canonical(root).equals(Json.canonical(Json.obj(Json.obj(record,"anchor"),"decision"))))
            throw new IllegalArgumentException("library conditioning has another saved root");
        String viewer=Json.str(observation,"viewer");
        Map<String,Object> rootPlayer=own(observation,viewer);long count=Json.num(rootPlayer,"library_count",-1);
        if(count<0 || count>4096)throw new IllegalArgumentException("library conditioning needs its bounded root count");
        List<Object> known=new ArrayList<>(Json.arr(observation,"known"));Map<String,Map<String,Object>> pins=new LinkedHashMap<>();
        for(Object item:known) {
            Map<String,Object> fact=Json.obj(item);
            if(viewer.equals(Json.str(fact,"owner_seat")) && "library".equals(Json.str(fact,"zone"))) {
                validate(fact,count);if(pins.put(Json.str(fact,"object_id"),fact)!=null)throw new IllegalArgumentException("root library repeats an identity");
            }
        }
        ObsIndex initial=new ObsIndex(observation);List<Object> decisions=new ArrayList<>();
        for(Object entry:Json.arr(Json.obj(record,"replay"),"earlier"))decisions.add(Json.obj(Json.obj(entry),"decision"));
        decisions.add(Json.obj(record,"decision"));
        for(Object item:decisions) {
            Map<String,Object> decision=Json.obj(item),now=Json.obj(decision,"observation");
            if(!viewer.equals(Json.str(now,"viewer")) || !viewer.equals(Json.str(decision,"acting_seat")))
                throw new IllegalArgumentException("library replay facts belong to another viewer");
            long currentCount=Json.num(own(now,viewer),"library_count",-1);
            Set<String> identities=new HashSet<>();
            for(Object shown:Json.arr(now,"known")) {
                Map<String,Object> fact=Json.obj(shown);
                if(!viewer.equals(Json.str(fact,"owner_seat")) || !"library".equals(Json.str(fact,"zone")))continue;
                validate(fact,currentCount);String id=Json.str(fact,"object_id");Map<String,Object> old=pins.get(id),visible=initial.ref(id);
                if(!identities.add(id))throw new IllegalArgumentException("one library observation repeats an identity");
                if(old!=null) {
                    if(!old.get("card_name").equals(fact.get("card_name")))throw new IllegalArgumentException("library replay identity changed name");
                    continue; // First observed position constrains reconstruction; later movement is replayed by the engine.
                }
                if(visible!=null) {
                    if(!viewer.equals(Json.str(visible,"owner_seat")) || !fact.get("card_name").equals(visible.get("card_name")))
                        throw new IllegalArgumentException("library fact conflicts with a root public object");
                    continue; // A root-visible card can move into the library during actual replay.
                }
                if((fact.get("position_from_top")!=null || fact.get("position_from_bottom")!=null) && currentCount!=count)
                    throw new IllegalArgumentException("new positional library fact needs unqualified root-position transport");
                Map<String,Object> pin=Json.obj(Json.copy(fact));pins.put(id,pin);known.add(pin);
            }
        }
        if(pins.size()>count)throw new IllegalArgumentException("library facts exceed root capacity");
        Set<Long> positions=new HashSet<>();
        for(Map<String,Object> fact:pins.values()) {
            Long position=fact.get("position_from_top")==null?fact.get("position_from_bottom")==null?null:count-1-(Long)fact.get("position_from_bottom"):(Long)fact.get("position_from_top");
            if(position!=null && !positions.add(position))throw new IllegalArgumentException("library facts collide at a root position");
        }
        observation.put("known",known);return observation;
    }
    private static Map<String,Object> own(Map<String,Object> observation,String viewer) {
        Map<String,Object> result=null;
        for(Object item:Json.arr(observation,"players"))if(viewer.equals(Json.str(Json.obj(item),"seat"))) {
            if(result!=null)throw new IllegalArgumentException("library facts repeat the viewer");result=Json.obj(item);
        }
        if(result==null)throw new IllegalArgumentException("library facts lack the viewer");return result;
    }
    private static void validate(Map<String,Object> fact,long count) {
        String how=Json.str(fact,"how"),id=Json.str(fact,"object_id"),name=Json.str(fact,"card_name");
        if(!fact.keySet().equals(FIELDS) || id==null || id.isEmpty() || name==null || name.isEmpty() || count<=0 || count>4096
                || !Arrays.asList("searching","looked_at","revealed").contains(how))
            throw new IllegalArgumentException("library fact is not an exact permitted named record");
        Object top=fact.get("position_from_top"),bottom=fact.get("position_from_bottom");
        for(Object position:Arrays.asList(top,bottom))if(position!=null && (!(position instanceof Long) || (Long)position<0 || (Long)position>=count))
            throw new IllegalArgumentException("library position exceeds its observed count");
        if(top!=null && bottom!=null && (Long)top+(Long)bottom!=count-1 || top==null && bottom==null && !"searching".equals(how))
            throw new IllegalArgumentException("library visibility has inconsistent or missing positions");
    }
}
