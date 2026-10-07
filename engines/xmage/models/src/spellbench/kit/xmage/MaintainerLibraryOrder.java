package spellbench.kit.xmage;

import mage.abilities.Ability;
import mage.cards.Cards;
import mage.cards.Card;
import spellbench.kit.core.Json;
import spellbench.kit.core.ObsIndex;
import java.util.*;

/** Preserve the complete inherited movement loop, and expose its resulting block in wire order. */
final class MaintainerLibraryOrder {
    final List<UUID> cards;
    final UUID owner;
    final boolean top;
    final Map<String,Object> initial;
    final Object source;
    final Map<UUID,Object> refs=new LinkedHashMap<>();
    MaintainerLibraryOrder(World world,Map<String,Object> decision,Object[] args) throws Exception {
        if(args.length!=3 || !(args[0] instanceof Cards) || args[1]!=null && !(args[1] instanceof Ability) || !(args[2] instanceof Boolean))
            throw new IllegalArgumentException("library order lacks its actual cards, source or destination");
        cards=new ArrayList<>((Cards)args[0]);top=(Boolean)args[2];initial=Json.obj(Json.copy(decision));
        if(cards.size()<2 || cards.size()>4096 || new HashSet<>(cards).size()!=cards.size())
            throw new IllegalArgumentException("library ordering is implicit, aliased or exceeds its supported envelope");
        Map<UUID,String> aliases=MaintainerModeEncoder.namedAliases(world,decision);ObsIndex observed=new ObsIndex(Json.obj(decision,"observation"));
        UUID actualOwner=null;
        for(UUID id:cards) {
            Object ref=aliases.containsKey(id)?observed.ref(aliases.get(id)):null;
            if(ref==null)throw new IllegalArgumentException("ordered library card lacks its permitted public reference");
            refs.put(id,ref);Card card=world.game.getCard(id);
            if(card==null || card.isCopy() || actualOwner!=null && !actualOwner.equals(card.getOwnerId()))
                throw new IllegalArgumentException("ordered library cards do not share an actual owner or contain a copy");
            actualOwner=card.getOwnerId();
        }
        owner=actualOwner;
        Ability ability=(Ability)args[1];Object ref=null;
        if(ability!=null) {
            UUID id=ability.getSourceId();ref=aliases.containsKey(id)?observed.ref(aliases.get(id)):null;
            if(ref==null)for(Map.Entry<UUID,String> alias:aliases.entrySet()) {
                mage.game.stack.StackObject stack=world.game.getStack().getStackObject(alias.getKey());
                if(stack!=null && id.equals(stack.getSourceId()) && observed.ref(alias.getValue())!=null) {
                    if(ref!=null)throw new IllegalArgumentException("library ordering source has ambiguous public stack identity");
                    ref=observed.ref(alias.getValue());
                }
            }
            if(ref==null)throw new IllegalArgumentException("library ordering source lacks a permitted reference");
        }
        source=ref;
        menu(world,decision,cards,0);
    }
    Map<UUID,Map<String,Object>> menu(World world,Map<String,Object> decision,List<UUID> left,int position) {
        Map<String,Object> group=Json.obj(decision,"group"),first=Json.obj(initial,"group"),context=Json.obj(decision,"context");
        Map<String,Object> now=Json.obj(Json.copy(decision.get("observation"))),before=Json.obj(initial,"observation");
        Set<String> optional=new HashSet<>();
        for(UUID id:cards)if(!left.contains(id))optional.add(Json.str(Json.obj(refs.get(id)),"object_id"));
        Map<String,String> facts=new HashMap<>();Set<String> required=new HashSet<>();
        for(Object item:Json.arr(before,"known")) {
            String key=Json.canonical(item);facts.put(key,key);
            if(!optional.contains(Json.str(Json.obj(item),"object_id")))required.add(key);
        }
        Set<String> seen=new HashSet<>();
        for(Object item:Json.arr(now,"known")) {
            String key=Json.canonical(item);
            if(!facts.containsKey(key) || !seen.add(key))throw new IllegalArgumentException("library ordering changed a supplied public fact");
        }
        if(!seen.containsAll(required))throw new IllegalArgumentException("library ordering omitted an unchanged public fact");
        now.put("known",Json.copy(before.get("known")));
        if(!world.viewer.equals(Json.str(decision,"acting_seat")) || !world.viewer.equals(Json.str(Json.obj(decision,"observation"),"viewer"))
                || !"choice".equals(Json.str(context,"kind"))
                || !Json.canonical(before).equals(Json.canonical(now))
                || group==null || first==null || !(group.get("group_id") instanceof Long)
                || !Objects.equals(group.get("group_id"),first.get("group_id"))
                || !Long.valueOf(position).equals(group.get("substep_index")) || !Long.valueOf(cards.size()-1).equals(group.get("substep_count"))
                || left.size()!=cards.size()-position)
            throw new IllegalArgumentException("library ordering changed its observation or complete group");
        Set<UUID> remaining=new HashSet<>(left);Set<Long> ids=new HashSet<>();Map<UUID,Map<String,Object>> result=new LinkedHashMap<>();
        Object visibleSource=source==null?null:new ObsIndex(Json.obj(decision,"observation")).ref(Json.str(Json.obj(source),"object_id"));
        for(Object item:Json.arr(decision,"candidates")) {
            Map<String,Object> candidate=Json.obj(item),semantic=Json.obj(candidate,"semantic");Object cid=candidate.get("candidate_id");
            String alias=Json.str(Json.obj(Json.obj(semantic,"item"),"object"),"object_id");UUID id=world.idToUuid.get(alias);
            Object expected=Json.map("kind","order_pick","source",visibleSource,"purpose",top?"library_top":"library_bottom",
                    "item",Json.map("object",refs.get(id)),"position",(long)position,"count",(long)cards.size());
            if(!(cid instanceof Long) || (Long)cid<0 || (Long)cid>9007199254740991L || !ids.add((Long)cid)
                    || !remaining.contains(id) || result.containsKey(id) || !Json.canonical(expected).equals(Json.canonical(semantic)))
                throw new IllegalArgumentException("library ordering menu differs from its actual physical cards/source");
            result.put(id,Json.map("candidate_id",cid,"semantic_echo",Json.copy(semantic)));
        }
        if(result.size()!=left.size())throw new IllegalArgumentException("library ordering menu omits actual physical cards");
        return result;
    }
    List<UUID> placed(World world) {
        if(owner==null || world.game.getPlayer(owner)==null)throw new IllegalArgumentException("library ordering lost its actual owner");
        List<UUID> library=world.game.getPlayer(owner).getLibrary().getCardList();
        if(library.size()<cards.size())throw new IllegalArgumentException("inherited ordering failed to place its complete block");
        List<UUID> block=new ArrayList<>(library.subList(top?0:library.size()-cards.size(),top?cards.size():library.size()));
        if(!new HashSet<>(block).equals(new HashSet<>(cards)))throw new IllegalArgumentException("inherited library loop did not produce its exact contiguous card block");
        return block;
    }
}
