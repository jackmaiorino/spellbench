"""Bind the remaining original strategic callbacks to the owned neural session."""
from __future__ import annotations

import hashlib

from xmage_jack_sources import CALLBACK_SHA256, extract

CALLBACK_PLAYER_VARIANT = (
    "original priority, target, card, mode, use, X, combat and London callbacks; "
    "declared checkpoint mulligan format; shared original chooser and copy session; "
    "explicit world/copy admission and dynamic permitted aliases; "
    "native backend, deck associations and full-game qualification unfinished")


def callback_player_source(source: str) -> str:
    if hashlib.sha256(source.encode()).hexdigest() != CALLBACK_SHA256:
        raise ValueError("Jack callback player requires the pinned April callback bytes")
    x_method = extract(source, "    public int announceX(", "    @Override\n    public boolean chooseUse(Outcome outcome, String message, Ability source, Game game)")
    x_bounds = extract(x_method, "            int realMin = min;", "            candidateCount = xValues.size();")
    use = extract(source, "        // Mana feasibility gate: for optional additional costs",
                  "            // Build 2-candidate decision: index 0 = Yes, index 1 = No")
    use = use[:use.rindex("        try {")]
    parser = extract(source, "    private Mana parseManaCostFromMessage(", "    /**\n     * Logs every target that has been recorded")
    fingerprint = extract(source, "    private int computeHandFingerprint(", "    /**\n     * If true, the agent will act greedily")
    return '''package spellbench.models.jack;
import mage.Mana;
import mage.ConditionalMana;
import mage.abilities.*;
import mage.abilities.costs.mana.*;
import mage.abilities.mana.ManaOptions;
import mage.cards.*;
import mage.constants.*;
import mage.choices.Choice;
import mage.game.Game;
import mage.players.Player;
import mage.target.*;
import java.util.*;
import java.util.function.Supplier;

/** Original no-training callbacks. Binding requires the actual permitted world. */
public class OriginalCallbackPlayer extends OriginalPriorityChoicePlayer implements PriorityRules.OriginalCallbacks {
    public static final String SOURCE_SHA256 = "%s";
    public static final String VARIANT = "%s";
    private int mulligansTaken;
    private int lastMulliganHandFingerprint = Integer.MIN_VALUE;
    private int lastMulliganHandSize = -1;
    private Boolean lastMulliganDecisionShouldMulligan;
    /** Root-only wire replay. Simulation copies always execute the original policy. */
    public interface Replay {
        Object invoke(String kind, OriginalCallbackPlayer player, Game game, Object[] arguments, Supplier<?> original);
    }
    public static final class ReplayStop extends Error {
        private static final long serialVersionUID = 1L;
        public final OriginalCallbackPlayer player;
        public final Game game;
        public final Object result;
        private final Replay owner;
        private ReplayStop(OriginalCallbackPlayer player, Game game, Replay owner, Object result) {
            super("original wire callback reached", null, false, false);
            this.player=player;this.game=game;this.owner=owner;this.result=result;
        }
    }
    private transient Replay replay;
    private transient Game replayGame;
    private transient int replayDepth;
    public final void bindOriginalReplay(Game game, Replay replay) {
        requireOriginalPermittedWorld(game);
        if (game.isSimulation() || replay==null || this.replay!=null)
            throw new IllegalArgumentException("one root-only original replay binding required");
        this.replay=replay;this.replayGame=game;
    }
    public final ReplayStop pauseOriginalReplay(Game game, Object result) {
        requireOriginalPermittedWorld(game);
        if (replay==null || replayDepth!=1 || game!=replayGame || game.isSimulation() || result==null)
            throw new IllegalArgumentException("active owned root callback required for replay pause");
        return new ReplayStop(this,game,replay,result);
    }
    public OriginalCallbackPlayer(String name, RangeOfInfluence range) { super(name,range); }
    /** Called after permitted-world reconstruction, before binding or any policy callback. */
    public OriginalCallbackPlayer(mage.player.ai.ComputerPlayer bootstrap, int observedMulligans) {
        super(requireBootstrap(bootstrap, observedMulligans));
        mulligansTaken=observedMulligans;
    }
    private static mage.player.ai.ComputerPlayer requireBootstrap(mage.player.ai.ComputerPlayer player, int mulligans) {
        if (player==null || player instanceof OriginalActivationPlayer || mulligans<0 || mulligans>7)
            throw new IllegalArgumentException("initialized bootstrap and observed London mulligan count required");
        return player;
    }
    protected OriginalCallbackPlayer(OriginalCallbackPlayer player) {
        super(player); mulligansTaken=player.mulligansTaken;
        lastMulliganHandFingerprint=player.lastMulliganHandFingerprint;
        lastMulliganHandSize=player.lastMulliganHandSize;
        lastMulliganDecisionShouldMulligan=player.lastMulliganDecisionShouldMulligan;
    }
    @Override public OriginalCallbackPlayer copy() { return new OriginalCallbackPlayer(this); }
    @Override public final String priorityCallbackSourceSha256() { return SOURCE_SHA256; }
    @Override protected final void requireOriginalManaSimulation(Game source,Game copied) {
        admitOriginalSimulation(source,copied);
    }
    private <T> T callback(Game game, Supplier<T> work) {
        return callback(game,"unconnected",new Object[0],work);
    }
    @Override protected final boolean ownsOriginalReplayPause(Game game,Throwable failure) {
        if (!(failure instanceof ReplayStop)) return false;
        ReplayStop stop=(ReplayStop)failure;
        return replay!=null && stop.player==this && stop.game==game && stop.owner==replay
                && game==replayGame && !game.isSimulation();
    }
    @Override protected final boolean replayOriginalChoice(Outcome outcome,Choice choice,Game game,Supplier<Boolean> work) {
        // The engine's automatic mana chooser is not a posed public decision.
        if (outcome==Outcome.PutManaInPool && choice!=null && choice.isManaColorChoice())
            return callback(game,"automatic-mana-choice",new Object[]{outcome,choice},work);
        Ability source=activationAbility();
        Set<String> validated=source==null?null:originalPriorityRules().alternatives().get(source.getSourceId());
        return callback(game,"choice",new Object[]{outcome,choice,source,validated},work);
    }
    @SuppressWarnings("unchecked")
    private <T> T callback(Game game,String kind,Object[] arguments,Supplier<T> work) {
        requireOriginalPermittedWorld(game);
        try {
            T result;
            if (replay!=null && game==replayGame && !game.isSimulation()
                    && !"simulation-copy".equals(kind) && !"automatic-mana-choice".equals(kind)) {
                if (replayDepth!=0) throw new IllegalArgumentException("unrecorded nested original replay callback");
                replayDepth++;
                try { result=(T)replay.invoke(kind,this,game,arguments,()-> {
                    T picked=work.get();requireOriginalPermittedWorld(game);return picked;
                }); } finally {replayDepth--;}
            } else result=work.get();
            requireOriginalPermittedWorld(game);return result;
        } catch (ReplayStop stop) {
            if (ownsOriginalReplayPause(game,stop)) throw stop;
            try {originalNeuralSession().close();} catch(RuntimeException | Error closing) {stop.addSuppressed(closing);}
            throw stop;
        }
        catch (RuntimeException | Error failure) {
            try { originalNeuralSession().close(); } catch (RuntimeException | Error closing) { failure.addSuppressed(closing); }
            throw failure;
        }
    }
    @Override public final void admitOriginalSimulation(Game source, Game copied) {
        callback(source,"simulation-copy",new Object[0], () -> {
            if (copied==null || copied==source || !copied.isSimulation())
                throw new IllegalArgumentException("original simulation must be a distinct permitted copy");
            Player player=copied.getPlayer(getId());
            if (!(player instanceof OriginalCallbackPlayer) || player==this)
                throw new IllegalArgumentException("simulation player does not preserve original callbacks");
            OriginalCallbackPlayer child=(OriginalCallbackPlayer)player;
            if (child.originalNeuralSession()!=originalNeuralSession())
                throw new IllegalArgumentException("simulation changed original model/RNG session");
            OriginalNeuralSelection.Admission admission=originalWorldAdmission().copy(source,copied,child);
            if (admission==null) throw new IllegalArgumentException("simulation admission unavailable");
            Map<UUID,String> aliases=admission.aliases(copied,child);
            child.bindOriginalWorld(copied,aliases==null?originalPriorityRules().aliases():aliases,
                    originalNeuralSession(),admission);
            return null;
        });
    }
    @Override public final boolean choose(Outcome outcome, Target target, Ability source, Game game) {
        return chooseTarget(outcome,target,source,game);
    }
    @Override public final boolean choose(Outcome outcome, Cards cards, TargetCard target, Ability source, Game game) {
        return callback(game, () -> originalParentCards(outcome,cards,target,source,game));
    }
    @Override public final boolean chooseTarget(Outcome outcome, Target target, Ability source, Game game) {
        return callback(game, () -> {
            if (target==null) throw new IllegalArgumentException("original target required");
            if ("starting player".equalsIgnoreCase(target.getTargetName())) {
                target.addTarget(getId(),source,game); return true;
            }
            if (source==null && outcome==Outcome.Discard && target instanceof mage.target.common.TargetCardInHand) {
                try {
                    return new LondonRules(this, hand -> originalNeuralSelection().genericChoose(hand,hand.size(),hand.size(),
                            StateSequenceBuilder.ActionType.LONDON_MULLIGAN,game,null)).chooseLondonMulliganCards(target,game);
                } catch (RuntimeException failure) { throw failure; }
                catch (Exception failure) { throw new IllegalArgumentException("original London callback failed",failure); }
            }
            Boolean mana=originalManaTarget(outcome,target,source,game, () -> originalParentTarget(outcome,target,source,game));
            if (mana!=null) return mana;
            return new TargetRules(this).select(outcome,target,source,game,(possible,chosen,min,max,forced,direct,reason) -> {
                if (forced) return direct;
                int pick=originalNeuralSelection().select(possible,StateSequenceBuilder.ActionType.SELECT_TARGETS,source,
                        game,originalNeuralSelection().capture(game),null,chosen,min,max,1,false,false,false).get(0);
                return possible.get(pick);
            });
        });
    }
    @Override public final boolean chooseTarget(Outcome outcome, Cards cards, TargetCard target, Ability source, Game game) {
        return callback(game, () -> new CardSetRules(this).select(outcome,cards,target,source,game,(groups,chosen,min,max,forced,dedup) -> {
            int selected=0;
            if (!forced) {
                List<UUID> representatives=new ArrayList<>();
                for (List<UUID> group:groups) representatives.add(group.isEmpty()?null:group.get(0));
                selected=originalNeuralSelection().select(representatives,StateSequenceBuilder.ActionType.SELECT_CARD,source,
                        game,originalNeuralSelection().capture(game),null,chosen,min,max,1,false,false,false).get(0);
            }
            List<UUID> group=groups.get(selected);
            return group.isEmpty()?null:group.get(originalNeuralSession().physicalCopy(group.size()));
        }));
    }
    @Override public final Mode chooseMode(Modes modes, Ability source, Game game) {
        return callback(game,"mode",new Object[]{modes,source}, () -> {
            if (modes==null) return originalParentMode(modes,source,game);
            List<Mode> available=modes.getAvailableModes(source,game);
            if (available.isEmpty()) return null;
            if (available.size()==1) return available.get(0);
            StateSequenceBuilder.SequenceOutput state=originalNeuralSelection().capture(game);
            int[] mask=new int[64]; int legal=0;
            ModeRules rules=new ModeRules(this);
            for(int i=0;i<Math.min(64,available.size());i++) if(rules.legal(available.get(i),source,game)) { mask[i]=1; legal++; }
            if (legal==0) return originalParentMode(modes,source,game);
            int pick=originalNeuralSelection().select(available,StateSequenceBuilder.ActionType.CHOOSE_MODE,source,game,
                    state,mask,0,1,1,1,false,true,false).get(0);
            return available.get(pick);
        });
    }
    private static void trace(String ignored) { }
    private Boolean forcedOriginalUse(Outcome outcome,String message,Ability source,Game game) {
''' % (CALLBACK_SHA256, CALLBACK_PLAYER_VARIANT) + use + '''        return null;
    }
    @Override public final boolean chooseUse(Outcome outcome,String message,Ability source,Game game) {
        return chooseUse(outcome,message,null,"Yes","No",source,game);
    }
    @Override public final boolean chooseUse(Outcome outcome,String message,String secondMessage,String trueText,String falseText,Ability source,Game game) {
        return callback(game,"use",new Object[]{outcome,message,source}, () -> {
            Boolean forced=forcedOriginalUse(outcome,message,source,game);
            if (forced!=null) return forced;
            List<Boolean> candidates=Arrays.asList(Boolean.TRUE,Boolean.FALSE);
            int pick=originalNeuralSelection().select(candidates,StateSequenceBuilder.ActionType.CHOOSE_USE,source,game,
                    originalNeuralSelection().capture(game),null,0,1,1,1,false,false,true).get(0);
            return candidates.get(pick);
        });
    }
    @Override public final int announceX(int min,int max,String message,Game game,Ability source,boolean isManaPay) {
        return callback(game,"x",new Object[]{min,max,isManaPay,source}, () -> {
''' + x_bounds + '''
            int pick=originalNeuralSelection().select(xValues,StateSequenceBuilder.ActionType.ANNOUNCE_X,source,game,
                    originalNeuralSelection().capture(game),null,0,1,1,1,false,false,false).get(0);
            return xValues.get(pick);
        });
    }
    private CombatRules.Picker combatPicker(Game game,Ability source,StateSequenceBuilder.SequenceOutput state) {
        return (type,candidates,picks,sequential) -> {
            List<Object> encoded=new ArrayList<>();
            for (CombatRules.CombatCandidate candidate:candidates)
                encoded.add(CandidateEncoder.combatCandidate(candidate.creature,candidate.context));
            return originalNeuralSelection().select(encoded,StateSequenceBuilder.ActionType.valueOf(type),source,game,
                    state,null,0,1,picks,picks,sequential,false,false);
        };
    }
    @Override public final void selectAttackers(Game game,UUID attackingPlayerId) {
        callback(game, () -> {
            if (!game.isSimulation()) {
                final StateSequenceBuilder.SequenceOutput[] state={null};
                new CombatRules(this,(type,candidates,picks,sequential) -> {
                    if(state[0]==null) state[0]=originalNeuralSelection().capture(game);
                    return combatPicker(game,null,state[0]).choose(type,candidates,picks,sequential);
                }).selectAttackers(game,attackingPlayerId);
            }
            return null;
        });
    }
    @Override public final void selectBlockers(Ability source,Game game,UUID defendingPlayerId) {
        callback(game, () -> {
            if (!game.isSimulation()) {
                final StateSequenceBuilder.SequenceOutput[] state={null};
                new CombatRules(this,(type,candidates,picks,sequential) -> {
                    if(state[0]==null) state[0]=originalNeuralSelection().capture(game);
                    return combatPicker(game,source,state[0]).choose(type,candidates,picks,sequential);
                }).selectBlockers(source,game,defendingPlayerId);
            }
            return null;
        });
    }
    @Override public final boolean chooseMulligan(Game game) {
        return callback(game, () -> {
            int size=getHand().size(), fingerprint=computeHandFingerprint(game);
            if(lastMulliganDecisionShouldMulligan!=null && lastMulliganHandSize==size && lastMulliganHandFingerprint==fingerprint)
                return lastMulliganDecisionShouldMulligan;
            boolean mulligan=originalNeuralSession().mulligan(new MulliganEncoder().features(this,game,mulligansTaken));
            lastMulliganHandSize=size; lastMulliganHandFingerprint=fingerprint;
            lastMulliganDecisionShouldMulligan=mulligan;
            if(mulligan) mulligansTaken++;
            return mulligan;
        });
    }
''' + fingerprint + parser + "}\n"
