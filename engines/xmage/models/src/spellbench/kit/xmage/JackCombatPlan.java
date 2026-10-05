package spellbench.kit.xmage;

import mage.game.permanent.Permanent;
import mage.players.Player;
import spellbench.kit.core.Json;
import spellbench.kit.core.ObsIndex;
import java.util.*;

/** Original root combat declarations, bound to the first public group substep. */
public final class JackCombatPlan {
    private JackCombatPlan() { }
    public static Map<String,Object> choose(World world,Map<String,Object> decision,boolean attack) throws Exception {
        Player player=world.viewerPlayer();Map<String,Object> obs=Json.obj(decision,"observation"),group=Json.obj(decision,"group"),context=Json.obj(decision,"context");
        String family=attack?"attack":"block",kind="declare_"+family,name=attack?"attacker":"blocker",reference=attack?"defender":"attacker";
        long groupId=Json.num(group,"group_id",-1L),count=Json.num(group,"substep_count",-1L);
        if(world.game.isSimulation() || !world.viewer.equals(Json.str(decision,"acting_seat")) || !world.viewer.equals(Json.str(obs,"viewer"))
                || !"choice".equals(Json.str(context,"kind")) || !Boolean.FALSE.equals(context.get("rewind"))
                || !(attack?"declare_attackers":"declare_blockers").equals(Json.str(obs,"phase_step"))
                || groupId<0 || groupId>9007199254740991L || count<1 || count>4096 || Json.num(group,"substep_index",-1L)!=0)
            throw new IllegalArgumentException("original combat needs its first acting-viewer declaration group");
        ObsIndex index=new ObsIndex(obs);Map<UUID,String> named=JackModeEncoder.namedAliases(world,decision);
        Set<Long> ids=new HashSet<>();Set<UUID> targets=new HashSet<>();UUID creatureId=null;
        Map<UUID,Map<String,Object>> choices=new HashMap<>();
        for(Object item:Json.arr(decision,"candidates")) {
            Map<String,Object> candidate=Json.obj(item),semantic=Json.obj(candidate,"semantic"),creature=Json.obj(semantic,name);
            Object cid=candidate.get("candidate_id");String alias=Json.str(creature,"object_id");UUID id=world.idToUuid.get(alias);
            Permanent own=id==null?null:world.game.getPermanent(id);
            if(!(cid instanceof Long) || (Long)cid<0 || (Long)cid>9007199254740991L || !ids.add((Long)cid)
                    || !kind.equals(Json.str(semantic,"kind")) || own==null || !named.containsKey(id)
                    || !player.getId().equals(own.getControllerId()) || !own.isCreature()
                    || !Json.canonical(creature).equals(Json.canonical(index.ref(alias)))
                    || creatureId!=null && !creatureId.equals(id))
                throw new IllegalArgumentException("original combat creature is unbound, aliased or belongs to another seat");
            creatureId=id;Object offered=semantic.get(reference);UUID target=null;
            if(!semantic.containsKey(reference))throw new IllegalArgumentException("original combat target is missing");
            if(offered!=null) {
                Map<String,Object> ref=Json.obj(offered);
                if(attack && ref.get("player")!=null) {
                    String seat=Json.str(ref,"player");target=world.seatPlayer.get(seat);
                    if(ref.size()!=1 || target==null || seat.equals(world.viewer))throw new IllegalArgumentException("original attack has another player target");
                } else {
                    if(attack)ref=Json.obj(ref,"object");
                    String targetAlias=Json.str(ref,"object_id");target=world.idToUuid.get(targetAlias);
                    Permanent other=target==null?null:world.game.getPermanent(target);
                    if(other==null || !named.containsKey(target) || player.getId().equals(other.getControllerId())
                            || !Json.canonical(ref).equals(Json.canonical(index.ref(targetAlias))))
                        throw new IllegalArgumentException("original combat has an unbound opposing target");
                }
                if(attack?(!world.game.getCombat().getDefenders().contains(target) || !own.canAttack(target,world.game))
                        :(!world.game.getCombat().getAttackers().contains(target) || !own.canBlock(target,world.game)))
                    throw new IllegalArgumentException("original combat target is outside the actual legal combat");
            }
            if(!targets.add(target))throw new IllegalArgumentException("original combat target is aliased");
            choices.put(target,candidate);
        }
        if(creatureId==null)throw new IllegalArgumentException("original combat menu has no creature");
        if(attack)player.selectAttackers(world.game,player.getId());else player.selectBlockers(null,world.game,player.getId());
        List<Object> pairs=Runner.combatPairs(world,world.game,attack);UUID wanted=null;boolean assigned=false;
        for(Object item:pairs) {
            Map<String,Object> pair=Json.obj(item);
            if(world.uuidToId.get(creatureId).equals(Json.str(pair,name))) {
                if(assigned)throw new IllegalArgumentException("original combat assigned the same creature twice");assigned=true;
                if(attack) {
                    Map<String,Object> defender=Json.obj(pair,"defender");
                    wanted=defender.get("player")!=null?world.seatPlayer.get(Json.str(defender,"player"))
                            :world.idToUuid.get(Json.str(defender,"object_id"));
                } else wanted=world.idToUuid.get(Json.str(pair,"attacker"));
                if(wanted==null)throw new IllegalArgumentException("original combat declaration lost its target binding");
            }
        }
        Map<String,Object> chosen=choices.get(wanted);
        if(chosen==null)throw new IllegalArgumentException("original combat assignment is not offered by the engine");
        return Json.map("selection",Json.map("candidate_id",chosen.get("candidate_id"),"semantic_echo",Json.copy(chosen.get("semantic"))),
                "combat",family,"pairs",pairs,"original_combat_path",true);
    }
}
