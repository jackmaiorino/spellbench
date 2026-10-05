package spellbench.kit.xmage;

import mage.cards.Card;
import mage.cards.CardsImpl;
import mage.constants.Outcome;
import mage.filter.FilterCard;
import mage.players.Player;
import mage.target.common.TargetCardInHand;
import spellbench.kit.core.Json;
import spellbench.kit.core.ObsIndex;

import java.util.*;

/** Bind the actual original shrinking-hand callbacks to one public London group. */
public final class JackLondonPlan {
    private JackLondonPlan() { }
    public static boolean accepts(Map<String,Object> decision) {
        Map<String,Object> observation=Json.obj(decision,"observation");
        List<Object> offered=Json.arr(decision,"candidates");
        if(!"pregame".equals(Json.str(observation,"phase_step")) || offered==null || offered.isEmpty()) return false;
        for(Object item:offered) {
            Map<String,Object> semantic=Json.obj(Json.obj(item),"semantic");
            if(!"order_pick".equals(Json.str(semantic,"kind")) || !"mulligan_bottom".equals(Json.str(semantic,"purpose"))) return false;
        }
        return true;
    }
    public static Map<String,Object> choose(World world,Map<String,Object> decision) throws Exception {
        Player player=world.viewerPlayer();
        Map<String,Object> observation=Json.obj(decision,"observation"),group=Json.obj(decision,"group"),context=Json.obj(decision,"context");
        long count=Json.num(group,"substep_count",-1L),groupId=Json.num(group,"group_id",-1L);
        int size=player.getHand().size();
        if(!accepts(decision) || !"choice".equals(Json.str(context,"kind")) || !Boolean.FALSE.equals(context.get("rewind"))
                || !world.viewer.equals(Json.str(decision,"acting_seat")) || !world.viewer.equals(Json.str(observation,"viewer"))
                || groupId<0 || groupId>9007199254740991L || Json.num(group,"substep_index",-1L)!=0
                || count<1 || count>size || size>7 || count!=JackPlayerBootstrap.observedMulligans(observation,world.viewer))
            throw new IllegalArgumentException("original London needs the first complete acting-viewer bottom group");
        Map<String,Object> own=null;
        for(Object item:Json.arr(observation,"players")) if(world.viewer.equals(Json.str(Json.obj(item),"seat"))) {
            if(own!=null) throw new IllegalArgumentException("original London viewer is duplicated");
            own=Json.obj(item);
        }
        if(own==null || Json.num(own,"hand_count",-1L)!=size || Json.arr(own,"hand").size()!=size)
            throw new IllegalArgumentException("original London hand differs from the observation");
        Map<String,UUID> hand=new LinkedHashMap<>();Map<String,Map<String,Object>> refs=new HashMap<>();
        ObsIndex index=new ObsIndex(observation);
        Map<UUID,String> named=JackModeEncoder.namedAliases(world,decision);
        for(UUID id:player.getHand()) {
            String alias=world.uuidToId.get(id);Card card=world.game.getCard(id);
            Map<String,Object> ref=alias==null?null:index.ref(alias);
            if(alias==null || !named.containsKey(id) || card==null || ref==null
                    || !card.getName().equals(Json.str(ref,"card_name")) || !"hand".equals(Json.str(ref,"zone"))
                    || !world.viewer.equals(Json.str(ref,"owner_seat")) || !player.getId().equals(card.getOwnerId())
                    || hand.put(alias,id)!=null)
                throw new IllegalArgumentException("original London requires the complete named own hand");
            refs.put(alias,ref);
        }
        Map<String,Map<String,Object>> choices=new LinkedHashMap<>();Set<Long> ids=new HashSet<>();
        for(Object item:Json.arr(decision,"candidates")) {
            Map<String,Object> candidate=Json.obj(item),semantic=Json.obj(candidate,"semantic"),entry=Json.obj(semantic,"item"),ref=Json.obj(entry,"object");
            Object cid=candidate.get("candidate_id");String alias=Json.str(ref,"object_id");
            if(!(cid instanceof Long) || (Long)cid<0 || (Long)cid>9007199254740991L || !ids.add((Long)cid)
                    || entry.size()!=1 || !hand.containsKey(alias) || !Json.canonical(ref).equals(Json.canonical(refs.get(alias)))
                    || !semantic.containsKey("source") || semantic.get("source")!=null
                    || Json.num(semantic,"position",-1L)!=0 || Json.num(semantic,"count",-1L)!=count
                    || choices.put(alias,candidate)!=null)
                throw new IllegalArgumentException("original London menu is incomplete, aliased or outside its group");
        }
        if(choices.size()!=size) throw new IllegalArgumentException("original London menu omits a hand card");
        List<Object> bottomed=new ArrayList<>();
        for(int position=0;position<count;position++) {
            TargetCardInHand target=new TargetCardInHand(new FilterCard());target.setTargetController(player.getId());
            if(!player.chooseTarget(Outcome.Discard,target,null,world.game) || target.getTargets().size()!=1)
                throw new IllegalArgumentException("original London callback did not choose exactly one card");
            UUID picked=target.getFirstTarget();String alias=world.uuidToId.get(picked);
            if(!hand.containsKey(alias) || bottomed.contains(alias) || !player.getHand().contains(picked))
                throw new IllegalArgumentException("original London callback left its remaining named hand");
            bottomed.add(alias);
            if(!player.putCardsOnBottomOfLibrary(new CardsImpl(target.getTargets()),world.game,null,true)
                    || player.getHand().contains(picked) || player.getHand().size()!=size-position-1)
                throw new IllegalArgumentException("original London card did not move to the library bottom");
        }
        Map<String,Object> first=choices.get((String)bottomed.get(0));
        return Json.map("selection",Json.map("candidate_id",first.get("candidate_id"),"semantic_echo",Json.copy(first.get("semantic"))),
                "london_plan",Json.map("group_id",groupId,"count",count,"bottomed",bottomed),"original_london_path",true);
    }
}
