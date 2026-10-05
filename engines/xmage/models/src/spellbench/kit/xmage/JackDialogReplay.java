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

/** Actual original activation to an exact dialog, target or provided-card callback. */
public final class JackDialogReplay {
    interface Projection {void compare(World world,Map<String,Object> decision) throws Exception;}
    private final World world;
    private final Player player;
    private final Map<String,Object> start,decision,anchor;
    private final List<Object> earlier;
    private final Projection projection;
    private int replayed;
    private final JackTriggerOrder triggers=new JackTriggerOrder();
    private Object bridge;
    private final Object session;
    private final String profile;
    private final long seed;
    private final boolean continuation;
    private final boolean resolution;
    private final boolean cleanup;
    private final boolean phaseAdvance;
    private final ArrayDeque<String> passes=new ArrayDeque<>();
    private int passesReplayed;
    private boolean applyingAnchorPass;
    private boolean deferredPass;

    private static final List<String> PHASES=Arrays.asList("upkeep","draw","precombat_main","beginning_of_combat","declare_attackers",
            "declare_blockers","combat_damage","end_of_combat","postcombat_main","end_step");
    static boolean phaseAdvance(Map<String,Object> root,Map<String,Object> current,String viewer) {
        Map<String,Object> before=Json.obj(root,"observation"),now=Json.obj(current,"observation");
        String context=Json.str(Json.obj(current,"context"),"kind");
        int first=PHASES.indexOf(Json.str(before,"phase_step")),last=PHASES.indexOf(Json.str(now,"phase_step"));
        if("choice".equals(context))for(Object item:Json.arr(current,"candidates"))
            if(Arrays.asList("pass","cast_spell","activate_ability","activate_mana_ability","play_land").contains(
                    Json.str(Json.obj(Json.obj(item),"semantic"),"kind")))return false;
        return "priority".equals(Json.str(Json.obj(root,"context"),"kind")) && Arrays.asList("priority","choice").contains(context)
                && viewer.equals(Json.str(root,"acting_seat")) && viewer.equals(Json.str(current,"acting_seat"))
                && viewer.equals(Json.str(before,"viewer")) && viewer.equals(Json.str(now,"viewer"))
                && viewer.equals(Json.str(before,"priority_seat")) && ("choice".equals(context) || viewer.equals(Json.str(now,"priority_seat")))
                && Arrays.asList("p0","p1").contains(Json.str(before,"active_seat")) && Objects.equals(before.get("active_seat"),now.get("active_seat"))
                && before.get("turn") instanceof Long && (Long)before.get("turn")>0 && Objects.equals(before.get("turn"),now.get("turn"))
                && Json.arr(before,"stack").isEmpty() && first>=0 && last>first;
    }

    private static void project(World world,Map<String,Object> decision) throws Exception {
        JackReplayKnowledge.verifyPositions(world,decision);
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
                    || !world.viewer.equals(Json.str(start,"seat")))
                throw new IllegalArgumentException("original replay needs a same-viewer priority anchor");
            earlier=new ArrayList<>(Json.arr(history,"earlier"));
            continuation="priority".equals(Json.str(Json.obj(decision,"context"),"kind"));
            resolution="pass".equals(Json.str(ModelReplay.selectedSemantic(Json.obj(anchor,"decision"),Json.obj(anchor,"selection")),"kind"));
            cleanup=resolution && JackGeneralTargetEncoder.cleanupTransition(Json.obj(anchor,"decision"),decision);
            phaseAdvance=resolution && phaseAdvance(Json.obj(anchor,"decision"),decision,world.viewer);
            if(earlier.size()>4096) throw new IllegalArgumentException("original dialog replay prefix exceeds its bound");
            check(decision);check(Json.obj(anchor,"decision"));
            if(continuation || resolution) {
                Map<String,Object> before=Json.obj(Json.obj(anchor,"decision"),"observation"),now=Json.obj(decision,"observation");
                for(String key:Arrays.asList("turn","phase_step"))if(!Objects.equals(before.get(key),now.get(key)))
                    if(!cleanup && !phaseAdvance)throw new IllegalArgumentException("original priority continuation crossed an unrecorded turn or phase");
            }
            Map<String,Object> previous=Json.obj(Json.obj(anchor,"decision"),"observation");
            List<Object> phasePrefix=new ArrayList<>(earlier);phasePrefix.add(Json.map("decision",decision));
            if(phaseAdvance)for(Object item:phasePrefix) {
                Map<String,Object> now=Json.obj(Json.obj(Json.obj(item),"decision"),"observation"),root=Json.obj(Json.obj(anchor,"decision"),"observation");
                int beforePhase=PHASES.indexOf(Json.str(previous,"phase_step")),nowPhase=PHASES.indexOf(Json.str(now,"phase_step"));
                if(!Objects.equals(root.get("turn"),now.get("turn")) || !Objects.equals(root.get("active_seat"),now.get("active_seat"))
                        || nowPhase<beforePhase || nowPhase>PHASES.indexOf(Json.str(Json.obj(decision,"observation"),"phase_step")))
                    throw new IllegalArgumentException("phase callback prefix crossed an unrecorded turn or reversed phase");
                previous=now;
            }
            for(Object item:earlier) {
                Map<String,Object> entry=Json.obj(item);check(Json.obj(entry,"decision"));
                ModelReplay.selectedSemantic(Json.obj(entry,"decision"),Json.obj(entry,"selection"));
            }
            if(cleanup) {
                List<Object> prefix=new ArrayList<>(earlier);prefix.add(Json.map("decision",decision));int selected=0;
                for(Object item:prefix) {
                    Map<String,Object> received=Json.obj(Json.obj(item),"decision"),group=Json.obj(received,"group"),finalGroup=Json.obj(decision,"group");
                    Map<String,Object> first=Json.obj(Json.obj(Json.arr(received,"candidates").get(0)),"semantic"),last=Json.obj(Json.obj(Json.arr(decision,"candidates").get(0)),"semantic");
                    if(!JackGeneralTargetEncoder.cleanupTransition(Json.obj(anchor,"decision"),received) || !Long.valueOf(selected++).equals(first.get("selected_count"))
                            || !first.get("minimum").equals(last.get("minimum")) || !Objects.equals(group==null?null:group.get("group_id"),finalGroup==null?null:finalGroup.get("group_id")))
                        throw new IllegalArgumentException("cleanup replay crossed an unrecorded discard group or pick");
                }
            }
            if(!"priority".equals(Json.str(Json.obj(Json.obj(anchor,"decision"),"context"),"kind"))
                    || !(anchor.get("priority_pass_after_activation") instanceof Boolean))
                throw new IllegalArgumentException("original activation needs its recorded root priority dispatch");
            ModelReplay.selectedSemantic(Json.obj(anchor,"decision"),Json.obj(anchor,"selection"));
            List<Object> recordedPasses=Json.arr(history,"priority_passes");
            if(resolution) {
                Map<String,Object> before=Json.obj(Json.obj(anchor,"decision"),"observation");
                String other="p0".equals(world.viewer)?"p1":"p0";
                List<Object> passed=Json.arr(before,"passed_seats");
                if(Json.arr(before,"stack").isEmpty() && !cleanup && !phaseAdvance || Boolean.TRUE.equals(anchor.get("priority_pass_after_activation"))
                        || passed==null || passed.contains(world.viewer) || new HashSet<>(passed).size()!=passed.size()
                        || !Arrays.asList("p0","p1").containsAll(passed))
                    throw new IllegalArgumentException("resolution replay needs a public nonempty stack and passed-seat facts");
                List<Object> expected=passed.contains(other)?Collections.emptyList():Collections.singletonList(other);
                if(!expected.equals(recordedPasses))throw new IllegalArgumentException("resolution pass order differs from public anchor facts");
                for(Object seat:recordedPasses)passes.add((String)seat);
            } else if(!recordedPasses.isEmpty())throw new IllegalArgumentException("activation replay has unrecorded priority passes");
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
                try {
                if(!"invoke".equals(method.getName()) || args[1]!=player || args[2]!=world.game)
                    throw new IllegalArgumentException("original replay hook belongs to another root");
                String kind=(String)args[0];Map<String,Object> past=replayed<earlier.size()?Json.obj(earlier.get(replayed)):null;
                Map<String,Object> current=past==null?decision:Json.obj(past,"decision");
                Object[] callback=(Object[])args[3];
                check(current);
                if("priority-pass".equals(kind)) {
                    if(resolution && applyingAnchorPass && callback.length==0)return ((Supplier<?>)args[4]).get();
                    if(!continuation || past!=null || callback.length!=0)
                        throw new IllegalArgumentException("original pass occurred before its activation prefix completed");
                    deferredPass=true;return null;
                }
                if("priority".equals(kind) && resolution) {
                    if(!continuation || past!=null || !passes.isEmpty() || callback.length!=0)
                        throw new IllegalArgumentException("unrecorded viewer priority during original resolution replay");
                    projection.compare(world,decision);
                    Map<String,Object> result=resolutionReceipt(JackRootDecision.choose(world,start,decision));
                    result.put("original_priority_continuation",true);result.put("original_activation_pass_deferred",false);
                    throw (Error)call(original.getMethod("pauseOriginalReplay",Game.class,Object.class),player,world.game,result);
                }
                if("trigger-order".equals(kind)) {
                    List<mage.abilities.TriggeredAbility> actual=JackTriggerOrder.abilities(callback);
                    Supplier<?> parent=(Supplier<?>)args[4];
                    if(triggers.scripted() || actual.size()<2)return triggers.implicit(actual,parent);
                    if(resolution && !passes.isEmpty())throw new IllegalArgumentException("trigger group preceded its recorded public passes");
                    @SuppressWarnings("unchecked") java.util.function.Function<List<mage.abilities.TriggeredAbility>,mage.abilities.TriggeredAbility> picker=
                            (java.util.function.Function<List<mage.abilities.TriggeredAbility>,mage.abilities.TriggeredAbility>)callback[1];
                    List<mage.abilities.TriggeredAbility> left=new ArrayList<>(actual),order=new ArrayList<>();
                    Map<String,Object> first=current;
                    for(int position=0;position<actual.size()-1;position++) {
                        past=replayed<earlier.size()?Json.obj(earlier.get(replayed)):null;
                        current=past==null?decision:Json.obj(past,"decision");check(current);projection.compare(world,current);
                        Map<Integer,Map<String,Object>> choices=JackTriggerOrder.choices(world,current,Json.obj(anchor,"decision"),first,left,position,actual.size());
                        mage.abilities.TriggeredAbility picked=picker.apply(Collections.unmodifiableList(left));
                        int index=JackTriggerOrder.index(left,picked);Map<String,Object> selected=choices.get(index);
                        if(past==null)throw (Error)call(original.getMethod("pauseOriginalReplay",Game.class,Object.class),player,world.game,selected);
                        ModelReplay.selectedSemantic(current,Json.obj(past,"selection"));
                        if(!Json.canonical(selected).equals(Json.canonical(past.get("selection"))))
                            throw new IllegalArgumentException("recorded trigger order differs from its original parent chooser");
                        order.add(picked);left.remove(index);replayed++;
                    }
                    order.add(left.get(0));return triggers.complete(actual,order,parent);
                }
                if(resolution && !passes.isEmpty())throw new IllegalArgumentException("resolution callback occurred before recorded public passes");
                if(continuation && past==null)
                    throw new IllegalArgumentException("unrecorded original callback before priority continuation");
                if("choice".equals(kind)) {
                    if(callback.length!=4 || !(callback[1] instanceof mage.choices.Choice))
                        throw new IllegalArgumentException("original named callback lacks its actual Choice");
                    mage.choices.Choice choice=(mage.choices.Choice)callback[1];
                    @SuppressWarnings("unchecked") Set<String> validated=(Set<String>)callback[3];
                    String forced=JackNamedChoices.implicitAlternative(choice,validated);
                    JackNamedChoices named=null;
                    if(forced!=null && JackNamedChoices.accepts(current)) {
                        try {named=new JackNamedChoices(world,current,choice,(mage.abilities.Ability)callback[2],world.game);}
                        catch(IllegalArgumentException unmatched) { /* A recorded cost can precede a different posed menu. */ }
                    }
                    if(forced!=null && named==null) {
                        Object result=((Supplier<?>)args[4]).get();
                        if(!Boolean.TRUE.equals(result) || !choice.isChosen() || !forced.equals(choice.getChoiceKey()))
                            throw new IllegalArgumentException("implicit original alternative Choice changed its recorded dispatch");
                        return Boolean.TRUE;
                    }
                    if(!JackNamedChoices.accepts(current)) throw new IllegalArgumentException("unrecorded original named callback");
                    projection.compare(world,current);
                    if(named==null) named=new JackNamedChoices(world,current,choice,(mage.abilities.Ability)callback[2],world.game);
                    if(past!=null) {
                        Map<String,Object> selected=Json.obj(past,"selection");ModelReplay.selectedSemantic(current,selected);
                        boolean result=named.earlier(selected);replayed++;return result;
                    }
                    Map<String,Object> selection=named.current(((Supplier<?>)args[4]).get());
                    throw (Error)call(original.getMethod("pauseOriginalReplay",Game.class,Object.class),player,world.game,selection);
                }
                projection.compare(world,current);
                Map<Object,Map<String,Object>> choices;
                if("card-set".equals(kind)) {
                    choices=JackCardSetEncoder.replayChoices(world,current,callback,world.game);
                } else if("pile".equals(kind) || "replacement".equals(kind)) {
                    choices=JackInheritedChoices.replayChoices(world,current,kind,callback);
                } else if("parent-card".equals(kind)) {
                    choices=JackParentCardEncoder.replayChoices(world,current,callback,world.game);
                } else if("target".equals(kind)) {
                    choices=JackGeneralTargetEncoder.replayChoices(world,current,callback,world.game);
                } else if("mode".equals(kind)) {
                    if(callback.length!=2 || !(callback[0] instanceof mage.abilities.Modes)
                            || !(callback[1] instanceof mage.abilities.Ability))
                        throw new IllegalArgumentException("original spell-mode callback lacks its modes or source");
                    choices=JackModeEncoder.replayChoices(world,current,(mage.abilities.Modes)callback[0],
                            (mage.abilities.Ability)callback[1],world.game,past!=null);
                } else choices=JackDialogEncoder.replayChoices(world,current,kind,callback,world.game);
                if(past!=null) {
                    Map<String,Object> selected=Json.obj(past,"selection");ModelReplay.selectedSemantic(current,selected);
                    for(Map.Entry<Object,Map<String,Object>> entry:choices.entrySet())
                        if(Json.canonical(selected).equals(Json.canonical(entry.getValue()))) {
                            // Restore the engine RNG for amounts; verify the fixed inherited pile/replacement answer.
                            if(Arrays.asList("amount","pile","replacement").contains(kind)
                                    && !Objects.equals(entry.getKey(),((Supplier<?>)args[4]).get()))
                                throw new IllegalArgumentException("recorded inherited choice differs from its original body");
                            replayed++;return entry.getKey();
                        }
                    throw new IllegalArgumentException("recorded dialog choice differs from the actual original callback");
                }
                Object value=((Supplier<?>)args[4]).get();Map<String,Object> selection=choices.get(value);
                if(selection==null) throw new IllegalArgumentException("original dialog chose an unbound wire value");
                Error stop=(Error)call(original.getMethod("pauseOriginalReplay",Game.class,Object.class),player,world.game,selection);
                throw stop;
                } catch(RuntimeException failure) {
                    if(resolution)throw new JackReplayOpponent.Refusal(failure);
                    throw failure;
                }
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
            ActivatedAbility ability=resolution?new mage.abilities.common.PassAbility():Mapping.findPlayable(world,player,semantic,new ObsIndex(Json.obj(root,"observation")));
            if(ability==null) throw new IllegalArgumentException("original activation anchor is not playable");
            Class<?> original=Class.forName("spellbench.models.jack.OriginalCallbackPlayer");
            Method getter=original.getSuperclass().getDeclaredMethod("originalPriorityRules");getter.setAccessible(true);
            JackPriorityState.restore(world,root,anchor.get("original_priority_state"),ability,call(getter,player));
            bind();
            if(resolution)return resolve();
            if(!continuation)return activate(ability);
            Class<?> activation=Class.forName("spellbench.models.jack.OriginalActivationPlayer");
            Method act=activation.getDeclaredMethod("act",Game.class,ActivatedAbility.class);act.setAccessible(true);
            call(act,player,world.game,ability);
            if(replayed!=earlier.size())throw new IllegalArgumentException("original activation did not consume its complete prefix");
            projection.compare(world,decision);
            Class<?> api=Class.forName(original.getName()+"$Replay");
            call(original.getMethod("finishOriginalReplay",Game.class,api),player,world.game,bridge);bridge=null;
            boolean pass=deferredPass || Boolean.TRUE.equals(anchor.get("priority_pass_after_activation"));
            Map<String,Object> result=pass?JackRootDecision.continuationPass(world,start,decision):JackRootDecision.choose(world,start,decision);
            result.put("original_activation_path",true);result.put("original_dialog_prefix_replayed",(long)replayed);
            result.put("original_priority_continuation",true);result.put("original_activation_pass_deferred",deferredPass);
            return result;
        } catch(Throwable failure) {throw failed(failure);}
    }
    private Map<String,Object> resolutionReceipt(Map<String,Object> result) {
        result.put("original_activation_path",false);result.put("original_resolution_path",true);
        result.put("original_cleanup_path",cleanup);
        result.put("original_phase_advance_path",phaseAdvance);
        result.put("original_dialog_prefix_replayed",(long)replayed);
        result.put("original_priority_passes_replayed",(long)passesReplayed);return result;
    }
    /** Resume only the reconstructed game, with every intervening opponent priority bound. */
    private Map<String,Object> resolve() {
        JackReplayOpponent other=null;
        boolean otherBound=false;
        try {
            Player opponent=world.game.getPlayer(world.player("p0".equals(world.viewer)?"p1":"p0"));
            if(!(opponent instanceof JackReplayOpponent))throw new IllegalArgumentException("resolution replay needs its owned non-playing opponent");
            other=(JackReplayOpponent)opponent;
            other.bind(world.game,(p,g)->{
                if(passes.isEmpty() || !p.getId().equals(world.player(passes.removeFirst())))
                    throw new JackReplayOpponent.Refusal(new IllegalArgumentException("unrecorded or reordered opponent priority during original resolution replay"));
                p.recordedPass(g);passesReplayed++;
            });
            otherBound=true;
            world.game.getState().resume();
            applyingAnchorPass=true;
            try {player.pass(world.game);} finally {applyingAnchorPass=false;}
            world.game.pause();world.game.resume();
            throw new IllegalArgumentException("original resolution ended without its requested callback");
        } catch(Throwable failure) {
            try {
                Class<?> stop=Class.forName("spellbench.models.jack.OriginalCallbackPlayer$ReplayStop");
                if(stop.isInstance(failure) && stop.getField("player").get(failure)==player
                        && stop.getField("game").get(failure)==world.game && replayed==earlier.size() && passes.isEmpty()) {
                    Map<String,Object> value=Json.obj(stop.getField("result").get(failure));
                    if(continuation) {
                        if(!Boolean.TRUE.equals(value.get("original_resolution_path")))throw new IllegalArgumentException("resolution priority receipt was lost");
                        ModelReplay.selectedSemantic(decision,Json.obj(value,"selection"));return value;
                    }
                    ModelReplay.selectedSemantic(decision,value);
                    return resolutionReceipt(Json.map("selection",Json.copy(value),"decision_sha256",JackPriorityBinding.hash(decision),
                            "game_start_sha256",JackPriorityBinding.hash(start),"profile",profile,"seed",seed,
                            "world_flags",new ArrayList<>(world.flags),"full_original_player_qualified",false));
                }
            } catch(Throwable binding) {failure.addSuppressed(binding);}
            throw failed(failure);
        } finally {if(otherBound)other.release(world.game);}
    }
    private RuntimeException failed(Throwable failure) {
        if(failure instanceof JackReplayOpponent.Refusal)failure=((JackReplayOpponent.Refusal)failure).failure;
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
