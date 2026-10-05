package spellbench.kit.xmage;

import mage.abilities.Ability;
import mage.abilities.Mode;
import mage.constants.Outcome;
import mage.game.stack.Spell;
import mage.game.stack.StackAbility;
import mage.game.stack.StackObject;
import mage.target.Target;
import mage.target.TargetAmount;
import spellbench.kit.core.Json;
import spellbench.kit.core.ObsIndex;
import java.util.*;

/** Bind the unchanged whole allocation to the wire's target picks and amount group. */
final class JackTargetAmount {
    final World world;
    final TargetAmount target;
    final Ability ability;
    final Map<String,Object> initial;
    final Map<UUID,Object> refs=new LinkedHashMap<>();
    final List<UUID> possible=new ArrayList<>(),order=new ArrayList<>();
    final List<Integer> amounts=new ArrayList<>();
    final List<int[]> offsets=new ArrayList<>();
    final Map<UUID,String> aliases;
    Object source;
    String stackAlias,purpose;
    long slot;
    int total,min,max;
    boolean implicit,prepared;
    Long groupId;

    JackTargetAmount(World world,Map<String,Object> decision,Object[] args) throws Exception {
        if(args.length!=3 || !(args[0] instanceof Outcome) || !(args[1] instanceof TargetAmount)
                || args[2]!=null && !(args[2] instanceof Ability))
            throw new IllegalArgumentException("divided targets lack their actual outcome, target or source");
        this.world=world;target=(TargetAmount)args[1];ability=(Ability)args[2];initial=Json.obj(Json.copy(decision));
        if(!target.getTargets().isEmpty())throw new IllegalArgumentException("divided targets need their complete original empty group");
        aliases=JackModeEncoder.namedAliases(world,decision);
    }
    /** Called by the original parent immediately after its one amount preparation. */
    void prepared(TargetAmount actual) {
        if(actual!=target || prepared)throw new IllegalArgumentException("divided target preparation changed");
        prepared=true;total=target.getAmountRemaining();min=target.getMinNumberOfTargets();
        max=target.getMaxNumberOfTargets()<=0?Integer.MAX_VALUE:target.getMaxNumberOfTargets();
        if(total<=0 || min==0 && target.getMaxNumberOfTargets()==0) {implicit=true;return;}
        if(total>4096 || min<0 || min>4096 || !target.getTargets().isEmpty()
                || !world.player(world.viewer).equals(target.getAffectedAbilityControllerId(world.player(world.viewer))))
            throw new IllegalArgumentException("divided target bounds or choosing controller are unsupported");
        if(ability==null)throw new IllegalArgumentException("nonempty divided targets need the wire's actual source");
        ObsIndex observed=new ObsIndex(Json.obj(initial,"observation"));
        StackObject stack=null;
        for(StackObject item:world.game.getStack())if(item.getId().equals(ability.getId())) {
            if(stack!=null)throw new IllegalArgumentException("divided target source has multiple stack entries");stack=item;
        }
        UUID sourceId=stack==null?ability.getSourceId():stack.getId();
        source=aliases.containsKey(sourceId)?observed.ref(aliases.get(sourceId)):null;
        if(source==null)throw new IllegalArgumentException("divided target source lacks its permitted public reference");
        if(stack!=null) {
            stackAlias=aliases.get(stack.getId());slot=JackTargetEncoder.slot(ability,target);
            List<Ability> abilities=stack instanceof Spell?new ArrayList<>(((Spell)stack).getSpellAbilities())
                    :Collections.singletonList(((StackAbility)stack).getStackAbility());
            int targetOffset=0,dividedOffset=0;
            for(Ability a:abilities)for(UUID modeId:a.getModes().getSelectedModes()) {
                Mode mode=a.getModes().get(modeId);if(mode==null)continue;
                for(Target t:mode.getTargets()) {
                    if(t==target)offsets.add(new int[]{targetOffset,dividedOffset});
                    targetOffset+=t.getTargets().size();if(t instanceof TargetAmount)dividedOffset+=t.getTargets().size();
                }
            }
            if(offsets.isEmpty())throw new IllegalArgumentException("divided target is absent from its actual public stack ability");
        }
        String rule=ability.getRule();purpose=rule!=null && rule.contains("damage")?"damage":rule!=null && rule.contains("counter")?"counters":"other";
        Set<UUID> ids=target.possibleTargets(target.getAffectedAbilityControllerId(world.player(world.viewer)),ability,world.game,null);
        if(ids.size()>4096 || ids.contains(null))throw new IllegalArgumentException("divided targets exceed the complete public menu");
        for(UUID id:ids) {
            Object ref=null;
            for(Map.Entry<String,UUID> seat:world.seatPlayer.entrySet())if(seat.getValue().equals(id))ref=Json.map("player",seat.getKey());
            if(ref==null && aliases.containsKey(id) && observed.ref(aliases.get(id))!=null)
                ref=Json.map("object",observed.ref(aliases.get(id)));
            if(ref==null)throw new IllegalArgumentException("divided target lacks its permitted public identity");
            possible.add(id);refs.put(id,ref);
        }
        if(possible.isEmpty()) {implicit=true;return;}
        targetMenu(initial,0);
    }
    void completed(boolean result) throws Exception {
        if(!prepared)throw new IllegalArgumentException("divided targets skipped original preparation");
        order.addAll(target.getTargets());int sum=0;
        for(UUID id:order) {
            int amount=target.getTargetAmount(id);
            if(!possible.contains(id) || amount<=0 || amount>total-sum)throw new IllegalArgumentException("original divided target result is outside its public group");
            amounts.add(amount);sum+=amount;
        }
        if(implicit) {
            if(result || !order.isEmpty())throw new IllegalArgumentException("implicit divided target changed its original false return");
        } else if(new HashSet<>(order).size()!=order.size() || order.size()>Math.min(max,total)
                || !order.isEmpty() && (!result || order.size()<min || sum!=total)
                || order.isEmpty() && (result || min!=0))
            throw new IllegalArgumentException("original allocation cannot complete the wire's exact target bounds");
        Map<String,Object> observed=RoundTrip.project(world,RoundTrip.flagsFrom(initial),
                Json.str(Json.obj(initial,"observation"),"priority_seat"),Json.arr(Json.obj(initial,"observation"),"passed_seats"));
        if(!Json.canonical(observation(order.size(),order.size())).equals(Json.canonical(observed)))
            throw new IllegalArgumentException("original target allocation changed other public state");
    }
    Map<String,Object> observation(int selected,int assigned) {
        Map<String,Object> result=Json.obj(Json.copy(initial.get("observation")));
        if(stackAlias==null)return result;
        Map<String,Object> stack=null;
        for(Object item:Json.arr(result,"stack"))if(stackAlias.equals(Json.str(Json.obj(item),"object_id")))stack=Json.obj(item);
        if(stack==null)throw new IllegalArgumentException("divided targets lost their public stack entry");
        List<Object> targets=Json.arr(stack,"targets"),divided=stack.get("divided")==null?new ArrayList<>():Json.arr(stack,"divided");
        List<Object> inserted=new ArrayList<>(),values=new ArrayList<>();
        for(int i=0;i<selected;i++) {inserted.add(Json.copy(refs.get(order.get(i))));values.add(i<assigned?(long)amounts.get(i):0L);}
        for(int i=offsets.size()-1;i>=0;i--) {
            int[] offset=offsets.get(i);targets.addAll(offset[0],inserted);divided.addAll(offset[1],values);
        }
        stack.put("divided",divided.isEmpty()?null:divided);return result;
    }
    private void check(Map<String,Object> decision,int selected,int assigned) {
        if(!world.viewer.equals(Json.str(decision,"acting_seat")) || !"choice".equals(Json.str(Json.obj(decision,"context"),"kind"))
                || !Json.canonical(observation(selected,assigned)).equals(Json.canonical(decision.get("observation"))))
            throw new IllegalArgumentException("divided target group changed its public observation");
    }
    int cap(int selected) {return Math.min(Math.min(max,total),possible.size());}
    boolean targetPosed(int selected) {return selected<cap(selected) && selected<possible.size();}
    Map<UUID,Map<String,Object>> targetMenu(Map<String,Object> decision,int selected) {
        check(decision,selected,0);
        if(decision.get("group")!=null || selected<0 || selected>order.size() && selected!=0)
            throw new IllegalArgumentException("divided target selection has an unexpected group or prefix");
        Set<UUID> left=new LinkedHashSet<>(possible);for(int i=0;i<selected;i++)left.remove(order.get(i));
        Map<UUID,Object> expected=new LinkedHashMap<>();
        for(UUID id:left) {
            Map<String,Object> semantic=Json.map("kind",stackAlias==null?"select_object":"choose_target","source",source,
                    "selected_count",(long)selected,"minimum",(long)Math.min(min,cap(selected)),"maximum",(long)cap(selected));
            if(stackAlias==null) {semantic.put("purpose","other");semantic.put("choice",refs.get(id));}
            else {semantic.put("slot",slot);semantic.put("target",refs.get(id));}
            expected.put(id,semantic);
        }
        if(selected>=min) {
            Map<String,Object> semantic=Json.map("kind",stackAlias==null?"finish_selection":"finish_target_selection","source",source,"selected_count",(long)selected);
            if(stackAlias==null)semantic.put("purpose","other");else semantic.put("slot",slot);expected.put(null,semantic);
        }
        return bind(decision,expected);
    }
    Map<Integer,Map<String,Object>> amountMenu(Map<String,Object> decision,int position) {
        check(decision,order.size(),position);Map<String,Object> group=Json.obj(decision,"group");
        if(group==null || !(group.get("group_id") instanceof Long) || (Long)group.get("group_id")<0
                || (Long)group.get("group_id")>9007199254740991L || !Long.valueOf(position).equals(group.get("substep_index"))
                || !Long.valueOf(order.size()).equals(group.get("substep_count"))
                || groupId!=null && !groupId.equals(group.get("group_id")))
            throw new IllegalArgumentException("divided amount group lost its complete positions or identity");
        groupId=(Long)group.get("group_id");int remaining=total;for(int i=0;i<position;i++)remaining-=amounts.get(i);
        int least=position==order.size()-1?remaining:1,most=remaining-(order.size()-1-position);
        Map<Integer,Object> expected=new LinkedHashMap<>();
        for(int value=least;value<=most;value++)expected.put(value,Json.map("kind","distribute","source",source,"purpose",purpose,
                "recipient",refs.get(order.get(position)),"amount",(long)value,"remaining",(long)remaining));
        return bind(decision,expected);
    }
    private static <K> Map<K,Map<String,Object>> bind(Map<String,Object> decision,Map<K,Object> expected) {
        Map<K,Map<String,Object>> result=new LinkedHashMap<>();Set<Long> seen=new HashSet<>();
        for(Object item:Json.arr(decision,"candidates")) {
            Map<String,Object> candidate=Json.obj(item);Object cid=candidate.get("candidate_id");K found=null;boolean matched=false;
            for(Map.Entry<K,Object> e:expected.entrySet())if(Json.canonical(e.getValue()).equals(Json.canonical(candidate.get("semantic")))) {
                if(matched)throw new IllegalArgumentException("divided target menu aliases two actual choices");found=e.getKey();matched=true;
            }
            if(!(cid instanceof Long) || (Long)cid<0 || (Long)cid>9007199254740991L || !seen.add((Long)cid)
                    || !matched || result.containsKey(found))throw new IllegalArgumentException("divided target menu differs from its complete original group");
            result.put(found,Json.map("candidate_id",cid,"semantic_echo",Json.copy(candidate.get("semantic"))));
        }
        if(result.size()!=expected.size())throw new IllegalArgumentException("divided target menu omits actual legal choices");
        return result;
    }
}
