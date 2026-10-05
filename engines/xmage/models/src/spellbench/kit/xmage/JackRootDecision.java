package spellbench.kit.xmage;

import mage.abilities.Ability;
import mage.abilities.ActivatedAbility;
import mage.abilities.common.PassAbility;
import mage.game.Game;
import mage.players.Player;
import spellbench.kit.core.Json;

import java.lang.reflect.*;
import java.util.*;
import java.util.function.*;

/** Original root selection at the wire boundary; activation and callback replay follow separately. */
public final class JackRootDecision {
    private final World world;
    private final Player player;
    private final Object session,rules,neural;
    private final Method require,close;
    private final Map<String,Object> start,decision;
    private final String profile;
    private final long seed;
    private JackRootDecision(World world,Map<String,Object> start,Map<String,Object> decision) throws Exception {
        if(world==null || world.game==null) throw new IllegalArgumentException("owned original root required");
        this.world=world;
        Class<?> original=Class.forName("spellbench.models.jack.OriginalCallbackPlayer"),base=original.getSuperclass();
        player=world.viewerPlayer();
        if (!original.isInstance(player)) throw new IllegalArgumentException("actual original callback player required");
        session=get(base,"originalNeuralSession",player);
        if(session==null) throw new IllegalArgumentException("original root has not been admitted");
        close=session.getClass().getMethod("close");
        require=base.getDeclaredMethod("requireOriginalPermittedWorld",Game.class); require.setAccessible(true);
        rules=get(base,"originalPriorityRules",player); neural=get(base,"originalNeuralSelection",player);
        this.start=Json.obj(Json.copy(start)); this.decision=Json.obj(Json.copy(decision));
        Field modelField=session.getClass().getDeclaredField("model"); modelField.setAccessible(true);
        Object model=modelField.get(session); Class<?> api=Class.forName("spellbench.models.jack.OriginalNeuralSelection$Model");
        profile=(String)call(api.getMethod("profile"),model); seed=(Long)call(api.getMethod("seed"),model);
    }
    public static WorldBuilder.Mode mode(Map<String,Object> decision) {
        Map<String,Object> observation=Json.obj(decision,"observation"),context=Json.obj(decision,"context");
        if ("priority".equals(Json.str(context,"kind")) && !"pregame".equals(Json.str(observation,"phase_step")))
            return WorldBuilder.Mode.PRIORITY;
        List<Object> candidates=Json.arr(decision,"candidates");
        if ("pregame".equals(Json.str(observation,"phase_step")) && candidates!=null && !candidates.isEmpty()) {
            for(Object item:candidates) if (!"mulligan".equals(Json.str(Json.obj(Json.obj(item),"semantic"),"kind")))
                throw new IllegalArgumentException("original callback replay is not connected for this pregame choice");
            return WorldBuilder.Mode.PREGAME;
        }
        throw new IllegalArgumentException("original callback replay is not connected for this decision family");
    }
    public static Map<String,Object> choose(World world,Map<String,Object> start,Map<String,Object> decision) {
        JackRootDecision root=null;
        try { root=new JackRootDecision(world,start,decision); return root.choose(); }
        catch(Throwable failure) {
            if(root!=null) try {call(root.close,root.session);} catch(Throwable cleanup) {failure.addSuppressed(cleanup);}
            else if(world!=null) try {
                Class<?> original=Class.forName("spellbench.models.jack.OriginalCallbackPlayer");
                if(original.isInstance(world.viewerPlayer())) {
                    Object owned=get(original.getSuperclass(),"originalNeuralSession",world.viewerPlayer());
                    if(owned!=null) call(owned.getClass().getMethod("close"),owned);
                }
            } catch(Throwable cleanup) {failure.addSuppressed(cleanup);}
            if(failure instanceof Error) throw (Error)failure;
            throw failure instanceof RuntimeException?(RuntimeException)failure:new IllegalArgumentException("original root decision failed",failure);
        }
    }
    @SuppressWarnings({"unchecked","rawtypes"})
    private Map<String,Object> choose() throws Exception {
        call(require,player,world.game);
        if(start==null || decision==null) throw new IllegalArgumentException("original root inputs required");
        Map<String,Object> observation=Json.obj(decision,"observation");
        if (!world.viewer.equals(Json.str(start,"seat")) || !world.viewer.equals(Json.str(observation,"viewer"))
                || !world.viewer.equals(Json.str(decision,"acting_seat")) || !(start.get("agent_seed") instanceof Long)
                || ((Long)start.get("agent_seed"))!=seed || seed<0 || seed>9007199254740991L)
            throw new IllegalArgumentException("original root decision belongs to another game seed or viewer");
        for(String flag:world.flags) if(flag.startsWith("unsupported:") || flag.startsWith("horizon:"))
            throw new IllegalArgumentException("original root world is unsupported: "+flag);
        WorldBuilder.Mode mode=mode(decision);
        Map<String,Object> selection; boolean dispatched=false,passAfter=false;
        if(mode==WorldBuilder.Mode.PREGAME) {
            List<Object> offered=Json.arr(decision,"candidates");
            Map<Boolean,Map<String,Object>> choices=new HashMap<>(); Set<Long> ids=new HashSet<>();
            int count=JackPlayerBootstrap.observedMulligans(observation,world.viewer),size=player.getHand().size();
            for(Object item:offered) {
                Map<String,Object> candidate=Json.obj(item),semantic=Json.obj(candidate,"semantic"); Object id=candidate.get("candidate_id");
                if (!(id instanceof Long) || (Long)id<0 || (Long)id>9007199254740991L || !ids.add((Long)id)
                        || !(semantic.get("keep") instanceof Boolean) || choices.put((Boolean)semantic.get("keep"),candidate)!=null
                        || Json.num(semantic,"mulligans_taken",-1L)!=count || Json.num(semantic,"hand_size",-1L)!=size)
                    throw new IllegalArgumentException("original mulligan differs from its observed counter, hand or offered choices");
            }
            if(choices.size()!=2 || offered.size()!=2 || size<1 || size>7)
                throw new IllegalArgumentException("both original mulligan choices and a complete own hand required");
            Map<String,Object> own=null;
            for(Object item:Json.arr(observation,"players")) if(world.viewer.equals(Json.str(Json.obj(item),"seat"))) own=Json.obj(item);
            if(own==null || Json.num(own,"hand_count",-1L)!=size || Json.arr(own,"hand").size()!=size)
                throw new IllegalArgumentException("original mulligan hand differs from the observation");
            boolean keep=!player.chooseMulligan(world.game);
            selection=selection(choices.get(keep));
        } else {
            final JackPriorityBinding.Plan[] plan={null}; final Map<String,Object>[] selected=new Map[]{null};
            final boolean[] passedAfter={false};
            ToIntFunction<List<ActivatedAbility>> chooser=options->{
                try {
                    plan[0]=JackPriorityBinding.bind(start,decision,world,options);
                    Class<?> type=Class.forName("spellbench.models.jack.StateSequenceBuilder$ActionType");
                    Object action=Enum.valueOf((Class)type,"ACTIVATE_ABILITY_OR_SPELL");
                    List<?> picks=(List<?>)call(neural.getClass().getMethod("genericChoose",List.class,int.class,int.class,
                            type,Game.class,Ability.class),neural,options,1,1,action,world.game,null);
                    if(picks.size()!=1 || !(picks.get(0) instanceof Integer)) throw new IllegalArgumentException("original priority returned no exact slot");
                    return (Integer)picks.get(0);
                } catch(Exception failure) {throw new IllegalArgumentException("original priority binding failed",failure);}
            };
            Consumer<ActivatedAbility> activation=ability->{
                if(selected[0]!=null) throw new IllegalArgumentException("original priority emitted multiple root activations");
                JackPriorityBinding.Plan bound=plan[0];
                if(bound==null) bound=JackPriorityBinding.bind(start,decision,world,Collections.singletonList(ability));
                int slot=bound.abilities.indexOf(ability);
                selected[0]=bound.select(slot,decision);
            };
            Runnable passing=()->{
                if(selected[0]==null) selected[0]=JackPriorityBinding.bind(start,decision,world,
                        Collections.singletonList(new PassAbility())).select(0,decision);
                else passedAfter[0]=true;
            };
            dispatched=(Boolean)call(rules.getClass().getMethod("dispatch",Game.class,ToIntFunction.class,Consumer.class,Runnable.class),
                    rules,world.game,chooser,activation,passing);
            if(selected[0]==null) throw new IllegalArgumentException("original priority dispatch produced no wire choice");
            selection=selected[0]; passAfter=passedAfter[0] && !"pass".equals(Json.str(Json.obj(selection,"semantic_echo"),"kind"));
        }
        call(require,player,world.game);
        return Json.map("selection",selection,"decision_sha256",JackPriorityBinding.hash(decision),
                "game_start_sha256",JackPriorityBinding.hash(start),"profile",profile,"seed",seed,
                "world_flags",new ArrayList<>(world.flags),"priority_dispatch_result",dispatched,
                "priority_pass_after_activation",passAfter,"full_original_player_qualified",false);
    }
    private static Map<String,Object> selection(Map<String,Object> candidate) {
        return Json.map("candidate_id",candidate.get("candidate_id"),"semantic_echo",Json.copy(candidate.get("semantic")));
    }
    private static Object get(Class<?> owner,String name,Object player) throws Exception {
        Method method=owner.getDeclaredMethod(name);method.setAccessible(true);return call(method,player);
    }
    private static Object call(Method method,Object owner,Object...args) throws Exception {
        try{return method.invoke(owner,args);}
        catch(InvocationTargetException failure) {
            Throwable cause=failure.getCause();if(cause instanceof Error) throw (Error)cause;
            if(cause instanceof RuntimeException) throw (RuntimeException)cause;throw failure;
        }
    }
}
