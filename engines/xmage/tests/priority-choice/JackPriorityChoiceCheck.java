package spellbench.models.jack;

import mage.MageObject;
import mage.abilities.*;
import mage.cards.*;
import mage.choices.*;
import mage.constants.*;
import mage.game.*;
import mage.players.*;
import mage.target.*;
import java.lang.reflect.Field;
import java.util.*;
import static spellbench.models.jack.JackActivationPlayerCheck.*;

/** Actual priority and Choice bodies, synthetic paired inference and metadata worlds. */
public final class JackPriorityChoiceCheck {
    static void refused(Runnable run) {
        try { run.run(); } catch (IllegalArgumentException expected) { return; }
        throw new AssertionError("expected original callback refusal");
    }
    static final class CallbackPlayer extends OriginalPriorityChoicePlayer {
        int passes, activations; List<ActivatedAbility> playable = new ArrayList<>();
        boolean nestedChoice;
        CallbackPlayer() { super("metadata callback player", RangeOfInfluence.ALL); }
        CallbackPlayer(CallbackPlayer parent) { super(parent); }
        @Override public CallbackPlayer copy() { return new CallbackPlayer(this); }
        void queue(String text) { choices.add(text); }
        int queued() { return choices.size(); }
        @Override public void pass(Game game) { passes++; }
        @Override public List<ActivatedAbility> getPlayable(Game game, boolean hidden) {
            require(hidden, "original playable hidden flag changed"); return new ArrayList<>(playable);
        }
        @Override protected List<MageObject> engineParentManaProducers(Game game) { return Collections.emptyList(); }
        @Override protected boolean activateOriginalAbility(ActivatedAbility ability, Game game) {
            if (ability instanceof mage.abilities.common.PassAbility) {
                ability.setControllerId(getId());
                return new mage.abilities.effects.common.PassEffect().apply(game,ability);
            }
            if (nestedChoice) choose(Outcome.Benefit,values(true,"yes","no"),game);
            activations++; return true;
        }
        @Override public boolean choose(Outcome o, Target t, Ability a, Game g) { throw unported(); }
        @Override public boolean chooseTarget(Outcome o, Target t, Ability a, Game g) { throw unported(); }
        @Override public boolean choose(Outcome o, Cards c, TargetCard t, Ability a, Game g) { throw unported(); }
        @Override public boolean chooseTarget(Outcome o, Cards c, TargetCard t, Ability a, Game g) { throw unported(); }
        @Override public Mode chooseMode(Modes m, Ability a, Game g) { throw unported(); }
        @Override public int announceX(int min, int max, String msg, Game g, Ability a, boolean mana) { throw unported(); }
        @Override public boolean chooseUse(Outcome o, String msg, Ability a, Game g) { throw unported(); }
        @Override public boolean chooseUse(Outcome o, String msg, String s, String y, String n, Ability a, Game g) { throw unported(); }
        @Override public void selectAttackers(Game g, UUID p) { throw unported(); }
        @Override public void selectBlockers(Ability a, Game g, UUID p) { throw unported(); }
        @Override public boolean chooseMulligan(Game g) { throw unported(); }
    }
    static final class World {
        final CallbackPlayer player; final Player other = new mage.player.ai.ComputerPlayer("other", RangeOfInfluence.ALL);
        final Players players = new Players(); final GameState state = new GameState();
        final Map<UUID,Card> cards = new HashMap<>(); final Game game;
        int resumes, pauses, events, gameReads, turn = 1; PhaseStep step = PhaseStep.UPKEEP;
        World() { this(new CallbackPlayer()); }
        World(CallbackPlayer player) {
            this.player = player; players.addPlayer(player); players.addPlayer(other);
            game = proxy(Game.class, (o,m,a) -> {
                gameReads++;
                switch (m.getName()) {
                    case "getPlayer": return players.get(a[0]);
                    case "getPlayers": return players;
                    case "getOpponents": return Collections.singleton(other.getId());
                    case "getState": return state;
                    case "getId": return new UUID(0,42);
                    case "getPhase": return null;
                    case "getTurnNum": return turn;
                    case "getActivePlayerId": return player.getId();
                    case "getStartingLife": return 20;
                    case "getBattlefield": return state.getBattlefield();
                    case "getStack": return state.getStack();
                    case "getExile": return state.getExile();
                    case "getCard": case "getObject": return cards.get(a[0]);
                    case "getPermanent": return null;
                    case "getTurnStepType": return step;
                    case "firePriorityEvent": events++; return null;
                    case "resumeTimer": resumes++; return null;
                    case "pauseTimer": pauses++; return null;
                    case "getRangeOfInfluence": return RangeOfInfluence.ALL;
                    case "inCheckPlayableState": return false;
                    default: throw new AssertionError("unexpected callback game read: " + m.getName());
                }
            });
        }
        OriginalNeuralSelection.Admission admission() {
            return (g,p) -> { if (g != game || p != player) throw new IllegalArgumentException("unadmitted metadata world"); };
        }
        void bind(OriginalNeuralSelection.Session session) { player.bindOriginalWorld(game, Collections.emptyMap(), session, admission()); }
    }
    static ChoiceImpl values(boolean required, String... values) {
        ChoiceImpl result = new ChoiceImpl(required); result.getChoices().addAll(Arrays.asList(values)); return result;
    }
    static ChoiceImpl keys(String... values) {
        ChoiceImpl result = new ChoiceImpl(true);
        for (int i = 0; i < values.length; i += 2) result.getKeyChoices().put(values[i],values[i+1]); return result;
    }
    @SuppressWarnings("unchecked") static <T> ThreadLocal<T> local(Class<?> owner, String name) throws Exception {
        Field f = owner.getDeclaredField(name); f.setAccessible(true); return (ThreadLocal<T>)f.get(null);
    }
    public static void main(String[] args) throws Exception {
        World w = new World(); CallbackPlayer p = w.player;
        JackNeuralSelectionCheck.Backend model = new JackNeuralSelectionCheck.Backend(OriginalNeuralSelection.GREEDY, 4);
        Arrays.fill(model.scores,0); model.scores[1] = 1;
        OriginalNeuralSelection.Session shared = new OriginalNeuralSelection.Session(model, model.profile, model.seed, () -> 10);
        w.bind(shared);
        refused(() -> w.bind(shared));
        ChoiceImpl regular = values(true,"first","second"); require(p.choose(Outcome.Benefit,regular,w.game), "regular choice failed");
        require("second".equals(regular.getChoice()) && model.calls == 1, "original regular choices did not apply neural slot");
        ChoiceImpl keyed = keys("a","Alpha","z","Zebra"); List<String> order = new ArrayList<>(keyed.getKeyChoices().keySet());
        require(p.choose(Outcome.Benefit,keyed,w.game) && order.get(1).equals(keyed.getChoiceKey()), "original key order/application changed");
        require(model.request.head.equals("action") && model.request.maximum == 1 && model.request.minimum == 1, "choice model routing changed");
        int before = model.calls; ChoiceImpl one = values(true,"only");
        require(p.choose(Outcome.Benefit,one,w.game) && "only".equals(one.getChoice()), "singleton choice changed");
        require(!p.choose(Outcome.Benefit,values(true),w.game), "empty choice changed");
        p.queue("optional"); ChoiceImpl optional = values(false,"optional","other");
        require(p.choose(Outcome.Benefit,optional,w.game) && "optional".equals(optional.getChoice()), "optional parent queue changed");
        ChoiceImpl naming = values(true); for(int i=0;i<70;i++) naming.getChoices().add("Card " + i);
        naming.setMessage("Choose a card name"); p.queue("Card 69");
        require(p.choose(Outcome.Benefit,naming,w.game) && "Card 69".equals(naming.getChoice()), "giant naming menu was truncated");
        require(model.calls == before, "parent/forced choice entered neural scoring");

        // The original payment TLS overrides the parent queue only when an unpaid color applies.
        ThreadLocal<Integer> depth = local(OriginalActivationPlayer.class,"playManaDepth");
        ThreadLocal<String> unpaid = local(OriginalActivationPlayer.class,"currentUnpaidManaText");
        try {
            p.queue("Blue"); depth.set(1); unpaid.set("{R}"); Choice mana = new ChoiceColor().setManaColorChoice(true);
            require(p.choose(Outcome.PutManaInPool,mana,w.game) && "Red".equals(mana.getChoice()) && p.queued()==1,
                    "unpaid mana preference did not precede queued parent choice");
            depth.set(0); unpaid.remove(); Choice parentMana = new ChoiceColor().setManaColorChoice(true);
            require(p.choose(Outcome.PutManaInPool,parentMana,w.game) && "Blue".equals(parentMana.getChoice()) && p.queued()==0,
                    "ordinary mana choice did not delegate to actual parent");
        } finally { depth.remove(); unpaid.remove(); }
        ThreadLocal<String> forced = local(PriorityRules.class,"forcedAlternativeChoice");
        ThreadLocal<Object> tracking = local(PriorityRules.class,"choiceTrackingData");
        try {
            forced.set("b"); ChoiceImpl alternative = keys("a","normal cost","b","alternative cost");
            require(p.choose(Outcome.Benefit,alternative,w.game) && "b".equals(alternative.getChoiceKey()), "original forced alternative lost");
            forced.remove(); p.queue("normal cost"); ChoiceImpl fallback = keys("a","normal cost","b","alternative cost");
            require(p.choose(Outcome.Benefit,fallback,w.game) && "a".equals(fallback.getChoiceKey()), "alternative parent queue lost");
        } finally { forced.remove(); tracking.remove(); }
        require(model.calls == before, "mana/alternative choice entered neural scoring");

        require(!p.priority(w.game) && p.passes==1 && w.resumes==1 && w.pauses==1 && w.events==1, "original upkeep dispatch/timer changed");
        w.step = PhaseStep.PRECOMBAT_MAIN;
        boolean mainResult = p.priority(w.game);
        require(mainResult && p.passes==2 && w.resumes==2 && w.pauses==2 && model.calls==before,
                "original main pass-only dispatch/shortcut changed: result="+mainResult+", passes="+p.passes+
                ", resume="+w.resumes+", pause="+w.pauses+", calls="+model.calls+", before="+before);
        UUID id = new UUID(0,87); ActivatedAbility action = action(id,false,false); p.playable.add(action); w.cards.put(id,card(id,action));
        stateChanged(w);
        require(p.priority(w.game) && p.activations==1 && model.calls==before+1, "actual priority neural selection/activation not connected");
        require(model.request.count==2 && model.request.head.equals("action"), "priority candidate routing changed");

        p.queue("copy-only"); CallbackPlayer copied = p.copy(); World copy = new World(copied); copy.bind(shared);
        ChoiceImpl copyChoice = values(false,"copy-only"); require(copied.choose(Outcome.Benefit,copyChoice,copy.game), "admitted copy callback failed");
        require(copied.queued()==0 && p.queued()==1 && copied.originalNeuralSession()==shared, "copy queue/session semantics changed");
        require(!((Object)copied instanceof PriorityRules.OriginalCallbacks), "incomplete copied-player marker was implemented");
        refused(() -> copied.choose(Outcome.Benefit,values(true,"x"),w.game));
        require(model.closes==1, "wrong-world copy did not close shared model");
        refused(() -> p.choose(Outcome.Benefit,values(true,"x"),w.game));

        World failing = new World(); JackNeuralSelectionCheck.Backend broken = new JackNeuralSelectionCheck.Backend(OriginalNeuralSelection.GREEDY,2);
        broken.throwing=true; failing.bind(new OriginalNeuralSelection.Session(broken,broken.profile,broken.seed,()->10));
        UUID source = new UUID(0,100); ActivatedAbility bad = action(source,false,false);
        failing.player.playable.add(bad); failing.cards.put(source,card(source,bad)); failing.step=PhaseStep.PRECOMBAT_MAIN;
        refused(() -> failing.player.priority(failing.game));
        require(failing.resumes==1 && failing.pauses==1 && failing.player.passes==0 && broken.closes==1,
                "model failure forced a pass or left original timer running");
        // The original act body catches engine activation exceptions. A nested neural refusal
        // must survive that catch and fail the enclosing callback, even if it already passed.
        World nested = new World(); nested.player.nestedChoice = true;
        JackNeuralSelectionCheck.Backend inner = new JackNeuralSelectionCheck.Backend(OriginalNeuralSelection.GREEDY,8);
        Arrays.fill(inner.scores,0); inner.scores[1]=1; inner.after=()->{if(inner.calls==2)inner.throwing=true;};
        nested.bind(new OriginalNeuralSelection.Session(inner,inner.profile,inner.seed,()->10));
        UUID nestedSource=new UUID(0,101); ActivatedAbility nestedAction=action(nestedSource,false,false);
        nested.player.playable.add(nestedAction); nested.cards.put(nestedSource,card(nestedSource,nestedAction)); nested.step=PhaseStep.PRECOMBAT_MAIN;
        refused(()->nested.player.priority(nested.game));
        require(inner.calls==2 && inner.closes==1 && nested.pauses==1 && nested.player.activations==0,
                "original activation catch hid nested neural refusal");
        // Same player identity alone cannot admit a different engine world to helper calls.
        for (String entry : Arrays.asList("dispatch","activation","producers","mana","payment","cast","play","activate")) {
            World owned = new World(); JackNeuralSelectionCheck.Backend b = new JackNeuralSelectionCheck.Backend(OriginalNeuralSelection.GREEDY,3);
            owned.bind(new OriginalNeuralSelection.Session(b,b.profile,b.seed,()->10)); World foreign = new World(owned.player);
            refused(() -> {
                switch(entry) {
                    case "dispatch": owned.player.dispatchOriginalPriority(owned.player.originalPriorityRules(),foreign.game,x->0); break;
                    case "activation": owned.player.applyOriginalPriorityAbility(foreign.game,null); break;
                    case "producers": owned.player.getAvailableManaProducers(foreign.game); break;
                    case "mana": owned.player.getManaAvailable(foreign.game); break;
                    case "payment": owned.player.playMana(null,null,"",foreign.game); break;
                    case "cast": owned.player.cast(null,foreign.game,false,null); break;
                    case "play": owned.player.playAbility(null,foreign.game); break;
                    case "activate": owned.player.activateAbility(null,foreign.game); break;
                }
            });
            require(foreign.events==0 && foreign.resumes==0 && foreign.gameReads<=1 && b.closes==1,
                    entry+" read a foreign world or failed to close the shared session");
        }
        System.out.println("PASS JackPriorityChoiceCheck: actual neural priority/choice, original delegation, timers, copy admission and failure refusal");
    }
    static void stateChanged(World w) { w.turn++; }
}
