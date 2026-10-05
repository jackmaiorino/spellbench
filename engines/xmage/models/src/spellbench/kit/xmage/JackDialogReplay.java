package spellbench.kit.xmage;

import mage.abilities.ActivatedAbility;
import mage.game.Game;
import mage.players.Player;
import spellbench.kit.core.Json;
import spellbench.kit.core.ObsCompare;
import spellbench.kit.core.ObsIndex;

import java.lang.reflect.*;
import java.util.*;
import java.util.function.Supplier;

/** Actual original activation to an exact binary, X or spell-mode wire callback. */
public final class JackDialogReplay {
    interface Projection {void compare(World world,Map<String,Object> decision) throws Exception;}
    private final World world;
    private final Player player;
    private final Map<String,Object> start,decision,anchor;
    private final List<Object> earlier;
    private final Projection projection;
    private int replayed;
    private Object bridge;
    private final Object session;
    private final String profile;
    private final long seed;

    private static void project(World world,Map<String,Object> decision) throws Exception {
        Map<String,Object> current=Json.obj(decision,"observation");
        Map<String,Object> observed=RoundTrip.project(world,RoundTrip.flagsFrom(decision),
                Json.str(current,"priority_seat"),Json.arr(current,"known"));
        List<String> differences=ObsCompare.diff(current,observed,8);
        if(!differences.isEmpty()) throw new IllegalArgumentException("original dialog replay observation differs: "+differences);
    }
    public JackDialogReplay(World world,Map<String,Object> record) {this(world,record,JackDialogReplay::project);}
    JackDialogReplay(World world,Map<String,Object> record,Projection projection) {
        try {
            this.world=Objects.requireNonNull(world);this.player=world.viewerPlayer();this.projection=projection;
            Map<String,Object> copy=Json.obj(Json.copy(record));start=Json.obj(copy,"game_start");decision=Json.obj(copy,"decision");
            anchor=Json.obj(copy,"anchor");Map<String,Object> history=Json.obj(copy,"replay");
            if(start==null || decision==null || anchor==null || history==null
                    || !world.viewer.equals(Json.str(start,"seat")) || !Json.arr(history,"priority_passes").isEmpty())
                throw new IllegalArgumentException("direct original activation needs a same-viewer anchor and no unresolved priority passes");
            earlier=new ArrayList<>(Json.arr(history,"earlier"));
            if(earlier.size()>4096) throw new IllegalArgumentException("original dialog replay prefix exceeds its bound");
            check(decision);check(Json.obj(anchor,"decision"));
            for(Object item:earlier) {
                Map<String,Object> entry=Json.obj(item);check(Json.obj(entry,"decision"));
                ModelReplay.selectedSemantic(Json.obj(entry,"decision"),Json.obj(entry,"selection"));
            }
            if(!"priority".equals(Json.str(Json.obj(Json.obj(anchor,"decision"),"context"),"kind"))
                    || !(anchor.get("priority_pass_after_activation") instanceof Boolean))
                throw new IllegalArgumentException("original activation needs its recorded root priority dispatch");
            ModelReplay.selectedSemantic(Json.obj(anchor,"decision"),Json.obj(anchor,"selection"));
            Class<?> original=Class.forName("spellbench.models.jack.OriginalCallbackPlayer");
            if(!original.isInstance(player)) throw new IllegalArgumentException("actual original callback player required");
            Method getter=original.getSuperclass().getDeclaredMethod("originalNeuralSession");getter.setAccessible(true);
            session=call(getter,player);Field modelField=session.getClass().getDeclaredField("model");modelField.setAccessible(true);
            Object model=modelField.get(session);Class<?> api=Class.forName("spellbench.models.jack.OriginalNeuralSelection$Model");
            profile=(String)call(api.getMethod("profile"),model);seed=(Long)call(api.getMethod("seed"),model);
            if(!(start.get("agent_seed") instanceof Long) || (Long)start.get("agent_seed")!=seed)
                throw new IllegalArgumentException("original dialog replay seed differs from its game-owned chooser");
        } catch(Throwable failure) {
            try {
                if(world!=null) {
                    Class<?> original=Class.forName("spellbench.models.jack.OriginalCallbackPlayer");
                    if(original.isInstance(world.viewerPlayer())) {
                        Method getter=original.getSuperclass().getDeclaredMethod("originalNeuralSession");getter.setAccessible(true);
                        Object owned=call(getter,world.viewerPlayer());
                        if(owned!=null) call(owned.getClass().getMethod("close"),owned);
                    }
                }
            } catch(Throwable closing) {failure.addSuppressed(closing);}
            if(failure instanceof Error) throw (Error)failure;
            throw failure instanceof RuntimeException?(RuntimeException)failure:new IllegalArgumentException("original dialog replay binding unavailable",failure);
        }
    }
    private void check(Map<String,Object> supplied) {
        if(supplied==null || !world.viewer.equals(Json.str(supplied,"acting_seat"))
                || !world.viewer.equals(Json.str(Json.obj(supplied,"observation"),"viewer")))
            throw new IllegalArgumentException("original replay callback belongs to another seat");
        for(String flag:world.flags) if(flag.startsWith("unsupported:") || flag.startsWith("horizon:"))
            throw new IllegalArgumentException("unsupported original replay world: "+flag);
    }
    public void bind() {
        try {
            Class<?> original=Class.forName("spellbench.models.jack.OriginalCallbackPlayer"),api=Class.forName(original.getName()+"$Replay");
            bridge=Proxy.newProxyInstance(api.getClassLoader(),new Class<?>[]{api},(proxy,method,args)->{
                if(method.getDeclaringClass()==Object.class) {
                    if("equals".equals(method.getName())) return proxy==args[0];
                    if("hashCode".equals(method.getName())) return System.identityHashCode(proxy);
                    return "owned original dialog replay";
                }
                if(!"invoke".equals(method.getName()) || args[1]!=player || args[2]!=world.game)
                    throw new IllegalArgumentException("original replay hook belongs to another root");
                String kind=(String)args[0];Map<String,Object> past=replayed<earlier.size()?Json.obj(earlier.get(replayed)):null;
                Map<String,Object> current=past==null?decision:Json.obj(past,"decision");
                check(current);projection.compare(world,current);
                Object[] callback=(Object[])args[3];
                Map<Object,Map<String,Object>> choices;
                if("mode".equals(kind)) {
                    if(callback.length!=2 || !(callback[0] instanceof mage.abilities.Modes)
                            || !(callback[1] instanceof mage.abilities.Ability))
                        throw new IllegalArgumentException("original spell-mode callback lacks its modes or source");
                    choices=JackModeEncoder.replayChoices(world,current,(mage.abilities.Modes)callback[0],
                            (mage.abilities.Ability)callback[1],world.game,past!=null);
                } else choices=JackDialogEncoder.replayChoices(world,current,kind,callback,world.game);
                if(past!=null) {
                    Map<String,Object> selected=Json.obj(past,"selection");ModelReplay.selectedSemantic(current,selected);
                    for(Map.Entry<Object,Map<String,Object>> entry:choices.entrySet())
                        if(Json.canonical(selected).equals(Json.canonical(entry.getValue()))) {replayed++;return entry.getKey();}
                    throw new IllegalArgumentException("recorded dialog choice differs from the actual original callback");
                }
                Object value=((Supplier<?>)args[4]).get();Map<String,Object> selection=choices.get(value);
                if(selection==null) throw new IllegalArgumentException("original dialog chose an unbound wire value");
                Error stop=(Error)call(original.getMethod("pauseOriginalReplay",Game.class,Object.class),player,world.game,selection);
                throw stop;
            });
            call(original.getMethod("bindOriginalReplay",Game.class,api),player,world.game,bridge);
        } catch(Throwable failure) {throw failed(failure);}
    }
    /** Calls the original act path, including payment reservations and copied activation rules. */
    Map<String,Object> activate(ActivatedAbility ability) {
        try {
            if(bridge==null) throw new IllegalArgumentException("original dialog replay was not bound");
            Class<?> activation=Class.forName("spellbench.models.jack.OriginalActivationPlayer");
            Method act=activation.getDeclaredMethod("act",Game.class,ActivatedAbility.class);act.setAccessible(true);
            call(act,player,world.game,ability);
            throw new IllegalArgumentException("original activation ended without the requested callback");
        } catch(Throwable failure) {
            try {
                Class<?> stop=Class.forName("spellbench.models.jack.OriginalCallbackPlayer$ReplayStop");
                if(stop.isInstance(failure) && stop.getField("player").get(failure)==player
                        && stop.getField("game").get(failure)==world.game && replayed==earlier.size()) {
                    Map<String,Object> selection=Json.obj(stop.getField("result").get(failure));
                    ModelReplay.selectedSemantic(decision,selection);
                    return Json.map("selection",Json.copy(selection),"decision_sha256",JackPriorityBinding.hash(decision),
                            "game_start_sha256",JackPriorityBinding.hash(start),"profile",profile,"seed",seed,
                            "world_flags",new ArrayList<>(world.flags),"original_dialog_prefix_replayed",(long)replayed,
                            "original_activation_path",true,"full_original_player_qualified",false);
                }
            } catch(Throwable binding) {failure.addSuppressed(binding);}
            throw failed(failure);
        }
    }
    public Map<String,Object> choose() {
        try {
            Map<String,Object> root=Json.obj(anchor,"decision");projection.compare(world,root);
            Map<String,Object> semantic=ModelReplay.selectedSemantic(root,Json.obj(anchor,"selection"));
            if("pass".equals(Json.str(semantic,"kind"))) throw new IllegalArgumentException("direct dialog replay requires an activation anchor");
            ActivatedAbility ability=Mapping.findPlayable(world,player,semantic,new ObsIndex(Json.obj(root,"observation")));
            if(ability==null) throw new IllegalArgumentException("original activation anchor is not playable");
            Class<?> original=Class.forName("spellbench.models.jack.OriginalCallbackPlayer");
            Method getter=original.getSuperclass().getDeclaredMethod("originalPriorityRules");getter.setAccessible(true);
            JackPriorityState.restore(world,root,anchor.get("original_priority_state"),ability,call(getter,player));
            bind();return activate(ability);
        } catch(Throwable failure) {throw failed(failure);}
    }
    private RuntimeException failed(Throwable failure) {
        try {call(session.getClass().getMethod("close"),session);} catch(Throwable closing) {failure.addSuppressed(closing);}
        if(failure instanceof Error) throw (Error)failure;
        return failure instanceof RuntimeException?(RuntimeException)failure:new IllegalArgumentException("original dialog activation replay failed",failure);
    }
    private static Object call(Method method,Object owner,Object...args) throws Exception {
        try {return method.invoke(owner,args);} catch(InvocationTargetException failure) {
            Throwable cause=failure.getCause();
            if(cause instanceof Error) throw (Error)cause;
            if(cause instanceof RuntimeException) throw (RuntimeException)cause;
            throw failure;
        }
    }
}
