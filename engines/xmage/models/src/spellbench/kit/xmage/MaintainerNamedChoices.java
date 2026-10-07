package spellbench.kit.xmage;

import mage.abilities.Ability;
import mage.choices.*;
import mage.game.Game;
import spellbench.kit.core.Json;
import spellbench.kit.core.ObsIndex;
import java.text.Normalizer;
import java.util.*;

/** Exact wire binding for the original Choice callback, without reordering its policy inputs. */
final class MaintainerNamedChoices {
    private final Choice choice;
    private final Map<String,Map<String,Object>> selections=new LinkedHashMap<>();

    static boolean accepts(Map<String,Object> decision) {
        List<Object> candidates=Json.arr(decision,"candidates");
        if(candidates.isEmpty()) return false;
        for(Object item:candidates) {
            String kind=Json.str(Json.obj(Json.obj(item),"semantic"),"kind");
            if(!Arrays.asList("choose_option","choose_color","choose_name","choose_cast_method").contains(kind)) return false;
        }
        return true;
    }
    static String implicitAlternative(Choice choice,Set<String> validated) {
        if(choice==null || !choice.isKeyChoice() || validated==null || validated.isEmpty()
                || choice.getKeyChoices()==null || choice.getKeyChoices().size()<2) return null;
        boolean alternative=false;
        for(String value:choice.getKeyChoices().values())
            if(value!=null && value.contains("alternative cost")) alternative=true;
        if(!alternative) return null;
        for(String key:choice.getKeyChoices().keySet()) if(validated.contains(key)) return key;
        return null;
    }
    MaintainerNamedChoices(World world,Map<String,Object> decision,Choice choice,Ability source,Game game) throws Exception {
        if(choice==null || !world.viewer.equals(Json.str(decision,"acting_seat"))
                || !world.viewer.equals(Json.str(Json.obj(decision,"observation"),"viewer"))
                || !"choice".equals(Json.str(Json.obj(decision,"context"),"kind")) || !accepts(decision))
            throw new IllegalArgumentException("original named callback differs from its acting wire choice");
        this.choice=choice;
        Map<String,String> options=new LinkedHashMap<>();
        if(choice.isKeyChoice()) options.putAll(choice.getKeyChoices());
        else for(String value:choice.getChoices()) options.put(value,value);
        List<Object> candidates=Json.arr(decision,"candidates");
        if(options.isEmpty() || options.size()>4096 || candidates.size()!=options.size())
            throw new IllegalArgumentException("original named options differ from the complete offered callback");
        List<String> visible=new ArrayList<>(options.keySet());
        Object collection=choice.isKeyChoice()?choice.getKeyChoices():choice.getChoices();
        if(collection instanceof HashMap && !(collection instanceof LinkedHashMap)
                || collection instanceof HashSet && !(collection instanceof LinkedHashSet))
            visible.sort((a,b)->{int c=codePoints(options.get(a),options.get(b));return c!=0?c:codePoints(a,b);});
        Set<Long> ids=new HashSet<>();Set<String> matched=new HashSet<>();String family=null;
        Object contextSource=Json.obj(decision,"context").get("source");
        for(Object item:candidates) {
            Map<String,Object> candidate=Json.obj(item),semantic=Json.obj(candidate,"semantic");
            String kind=Json.str(semantic,"kind");Object id=candidate.get("candidate_id");
            if(!(id instanceof Long) || (Long)id<0 || (Long)id>9007199254740991L || !ids.add((Long)id)
                    || family!=null && !family.equals(kind)
                    || !Json.canonical(contextSource).equals(Json.canonical(semantic.get("source"))))
                throw new IllegalArgumentException("named actions are aliased, mixed or differently sourced");
            family=kind;
            if("choose_cast_method".equals(kind)) validateSource(world,decision,source,game,contextSource);
            else if(contextSource!=null) throw new IllegalArgumentException("original effect Choice has an unexpected source reference");
            String key=null;
            if("choose_option".equals(kind)) {
                long index=Json.num(semantic,"option_index",-1);
                if(!"effect_option".equals(Json.str(semantic,"purpose")) || index<0 || index>=visible.size()
                        || Json.num(semantic,"option_count",-1)!=visible.size())
                    throw new IllegalArgumentException("named option index, count or purpose differs from the actual menu");
                key=visible.get((int)index);
                if(!Objects.equals(options.get(key),Json.str(semantic,"option_label")))
                    throw new IllegalArgumentException("named option label differs from its actual visible slot");
            } else {
                for(Map.Entry<String,String> option:options.entrySet()) {
                    String value=option.getValue();boolean same=false;
                    if(value==null) throw new IllegalArgumentException("original named option has a null label");
                    if("choose_color".equals(kind)) {
                        if(!(choice instanceof ChoiceColor) || !"effect".equals(Json.str(semantic,"purpose")))
                            throw new IllegalArgumentException("color callback differs from its actual Choice");
                        same=value.toLowerCase(Locale.ROOT).equals(Json.str(semantic,"color"));
                    } else if("choose_name".equals(kind)) {
                        String purpose=Json.str(semantic,"purpose");requireNamePurpose(choice,purpose);
                        same=Objects.equals(nameValue(purpose,value),Json.str(semantic,"value"));
                    } else if("choose_cast_method".equals(kind)) {
                        if(choice.getMessage()==null || !choice.getMessage().toLowerCase(Locale.ROOT).contains("alternative cost"))
                            throw new IllegalArgumentException("cast-method callback lacks its actual alternative-cost menu");
                        same=methodOfLabel(value).equals(Json.str(semantic,"method"));
                    }
                    if(same) {
                        if(key!=null) throw new IllegalArgumentException("named semantic aliases multiple actual choices");
                        key=option.getKey();
                    }
                }
            }
            if(key==null || !matched.add(key)) throw new IllegalArgumentException("named action is absent or repeated in the actual menu");
            selections.put(key,Json.map("candidate_id",id,"semantic_echo",Json.copy(semantic)));
        }
    }
    Map<String,Object> current(Object returned) {
        if(!Boolean.TRUE.equals(returned) || !choice.isChosen())
            throw new IllegalArgumentException("original Choice did not apply a selected offered option");
        String key=choice.isKeyChoice()?choice.getChoiceKey():choice.getChoice();
        Map<String,Object> selected=selections.get(key);
        if(selected==null) throw new IllegalArgumentException("original Choice applied an unbound option");
        return selected;
    }
    boolean earlier(Map<String,Object> selection) {
        for(Map.Entry<String,Map<String,Object>> option:selections.entrySet())
            if(Json.canonical(selection).equals(Json.canonical(option.getValue()))) {
                if(choice.isKeyChoice()) choice.setChoiceByKey(option.getKey());else choice.setChoice(option.getKey());
                current(Boolean.TRUE);return true;
            }
        throw new IllegalArgumentException("recorded named choice differs from the actual callback");
    }
    private static void validateSource(World world,Map<String,Object> decision,Ability source,Game game,Object supplied) throws Exception {
        Map<String,Object> ref=Json.obj(supplied);ObsIndex index=new ObsIndex(Json.obj(decision,"observation"));
        if(source==null || source.getSourceId()==null || ref==null
                || !Json.canonical(ref).equals(Json.canonical(index.ref(Json.str(ref,"object_id")))))
            throw new IllegalArgumentException("cast Choice lacks its actual visible source");
        for(Map.Entry<UUID,String> alias:MaintainerModeEncoder.namedAliases(world,decision).entrySet())
            if(alias.getValue().equals(Json.str(ref,"object_id")) && (alias.getKey().equals(source.getSourceId())
                    || game.getStack().getStackObject(alias.getKey())!=null
                    && source.getSourceId().equals(game.getStack().getStackObject(alias.getKey()).getSourceId()))) return;
        throw new IllegalArgumentException("cast Choice has another source");
    }
    private static void requireNamePurpose(Choice choice,String purpose) {
        boolean matches="creature_type".equals(purpose)?choice instanceof ChoiceCreatureType
                :"basic_land_type".equals(purpose)?choice instanceof ChoiceBasicLandType
                :"land_type".equals(purpose)?choice instanceof ChoiceLandType
                :"card_type".equals(purpose)?choice instanceof ChoiceCardType
                :"card_name".equals(purpose) && choice.getMessage()!=null
                    && choice.getMessage().toLowerCase(Locale.ROOT).contains("card name");
        if(!matches) throw new IllegalArgumentException("name callback purpose differs from the actual Choice");
    }
    private static String nameValue(String purpose,String raw) {
        if("card_name".equals(purpose)) return Normalizer.normalize(raw,Normalizer.Form.NFC);
        String value=Normalizer.normalize(raw,Normalizer.Form.NFD).replaceAll("\\p{M}","")
                .toLowerCase(Locale.ROOT).replace("'","").replace("\u2019","").replace(' ','_').replace('-','_');
        return value.matches("[a-z][a-z0-9_]*")?value:null;
    }
    private static String methodOfLabel(String raw) {
        String value=raw.toLowerCase(Locale.ROOT);
        if(value.contains("no alternative cost")) return "normal";
        for(String method:new String[]{"disguise","morph","evoke","foretell","plot","madness","miracle","flashback",
                "escape","overload","prototype","suspend","disturb"}) if(value.contains(method)) return method;
        return "alternative";
    }
    private static int codePoints(String a,String b) {
        PrimitiveIterator.OfInt x=a.codePoints().iterator(),y=b.codePoints().iterator();
        while(x.hasNext() && y.hasNext()) {int c=Integer.compare(x.nextInt(),y.nextInt());if(c!=0) return c;}
        return x.hasNext()?1:y.hasNext()?-1:0;
    }
}
