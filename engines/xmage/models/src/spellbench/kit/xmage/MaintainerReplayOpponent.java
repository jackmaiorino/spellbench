package spellbench.kit.xmage;

import mage.MageObject;
import mage.abilities.*;
import mage.cards.*;
import mage.choices.Choice;
import mage.constants.*;
import mage.game.Game;
import mage.player.ai.KitPayPlayer;
import mage.target.*;
import java.util.*;
import java.util.function.BiConsumer;

/** Non-playing reconstruction helper. A root replay admits only recorded passes. */
public final class MaintainerReplayOpponent extends KitPayPlayer {
    private static final long serialVersionUID=1L;
    static final class Refusal extends Error {
        private static final long serialVersionUID=1L;
        final RuntimeException failure;
        Refusal(RuntimeException failure) {super("original resolution replay refused",failure,false,false);this.failure=failure;}
    }
    private transient Game root;
    private transient BiConsumer<MaintainerReplayOpponent,Game> replay;
    public MaintainerReplayOpponent(String name) {super(name,RangeOfInfluence.ALL);}
    MaintainerReplayOpponent(Puppet old) {super(old);}
    private MaintainerReplayOpponent(MaintainerReplayOpponent old) {super(old);}
    @Override public MaintainerReplayOpponent copy() {return new MaintainerReplayOpponent(this);}
    void bind(Game game,BiConsumer<MaintainerReplayOpponent,Game> handler) {
        if(game==null || game.isSimulation() || game.getPlayer(getId())!=this || replay!=null || handler==null)
            throw new IllegalArgumentException("one initialized opponent replay root required");
        root=game;replay=handler;
    }
    void release(Game game) {
        if(game!=root || replay==null)throw new IllegalArgumentException("opponent replay release belongs to another root");
        root=null;replay=null;
    }
    void recordedPass(Game game) {
        if(game!=root || replay==null || game.isSimulation() || game.getPlayer(getId())!=this)
            throw new IllegalArgumentException("recorded opponent pass belongs to another root");
        super.pass(game);
    }
    private void posed(Game game) {
        if(replay!=null)
            throw new Refusal(new IllegalArgumentException("unrecorded opponent choice during original resolution replay"));
    }
    @Override public boolean priority(Game game) {
        if(replay!=null) {
            if(game!=root || game.isSimulation() || game.getPlayer(getId())!=this)
                throw new Refusal(new IllegalArgumentException("opponent priority belongs to another replay root"));
            replay.accept(this,game);return false;
        }
        pass(game);return false;
    }
    @Override public void selectAttackers(Game game,UUID player) {posed(game);}
    @Override public void selectBlockers(Ability source,Game game,UUID player) {posed(game);}
    @Override public boolean chooseMulligan(Game game) {posed(game);return false;}
    @Override public SpellAbility chooseAbilityForCast(Card card,Game game,boolean noMana) {posed(game);return super.chooseAbilityForCast(card,game,noMana);}
    @Override public ActivatedAbility chooseLandOrSpellAbility(Card card,Game game,boolean noMana) {posed(game);return super.chooseLandOrSpellAbility(card,game,noMana);}
    @Override public boolean choose(Outcome outcome,Choice choice,Game game) {posed(game);return super.choose(outcome,choice,game);}
    @Override public boolean choose(Outcome outcome,Target target,Ability source,Game game) {posed(game);return super.choose(outcome,target,source,game);}
    @Override public boolean choose(Outcome outcome,Target target,Ability source,Game game,Map<String,java.io.Serializable> options) {posed(game);return super.choose(outcome,target,source,game,options);}
    @Override public boolean chooseUse(Outcome outcome,String message,Ability source,Game game) {posed(game);return super.chooseUse(outcome,message,source,game);}
    @Override public boolean chooseUse(Outcome outcome,String message,String inform,String accept,String reject,Ability source,Game game) {posed(game);return super.chooseUse(outcome,message,inform,accept,reject,source,game);}
    @Override public int announceX(int min,int max,String message,Game game,Ability source,boolean mana) {posed(game);return super.announceX(min,max,message,game,source,mana);}
    @Override public boolean chooseTarget(Outcome outcome,Target target,Ability source,Game game) {posed(game);return super.chooseTarget(outcome,target,source,game);}
    @Override public boolean chooseTarget(Outcome outcome,Cards cards,TargetCard target,Ability source,Game game) {posed(game);return super.chooseTarget(outcome,cards,target,source,game);}
    @Override public boolean choose(Outcome outcome,Cards cards,TargetCard target,Ability source,Game game) {posed(game);return super.choose(outcome,cards,target,source,game);}
    @Override public Mode chooseMode(Modes modes,Ability source,Game game) {posed(game);return super.chooseMode(modes,source,game);}
    @Override public boolean chooseTargetAmount(Outcome outcome,TargetAmount target,Ability source,Game game) {posed(game);return super.chooseTargetAmount(outcome,target,source,game);}
    @Override public boolean choosePile(Outcome outcome,String message,List<? extends Card> first,List<? extends Card> second,Game game) {posed(game);return super.choosePile(outcome,message,first,second,game);}
    @Override public int chooseReplacementEffect(Map<String,String> effects,Map<String,MageObject> objects,Game game) {posed(game);return super.chooseReplacementEffect(effects,objects,game);}
    @Override public TriggeredAbility chooseTriggeredAbility(List<TriggeredAbility> abilities,Game game) {posed(game);return super.chooseTriggeredAbility(abilities,game);}
    @Override public void chooseRingBearer(Game game) {posed(game);super.chooseRingBearer(game);}
}
