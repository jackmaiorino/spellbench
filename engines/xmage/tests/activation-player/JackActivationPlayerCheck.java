package spellbench.models.jack;

import mage.MageObject;
import mage.abilities.*;
import mage.abilities.costs.CostsImpl;
import mage.abilities.costs.common.TapSourceCost;
import mage.abilities.costs.common.TapTargetCost;
import mage.abilities.mana.GreenManaAbility;
import mage.abilities.costs.mana.*;
import mage.cards.*;
import mage.choices.Choice;
import mage.constants.*;
import mage.game.*;
import mage.game.permanent.Battlefield;
import mage.game.permanent.Permanent;
import mage.game.stack.SpellStack;
import mage.players.Player;
import mage.target.*;
import java.io.Serializable;
import java.lang.reflect.*;
import java.util.*;
import java.util.function.Consumer;

/** Actual staged activation bodies with metadata engine hooks. No native game/database/model. */
public final class JackActivationPlayerCheck {
    static void require(boolean value, String message) { if (!value) throw new AssertionError(message); }
    static AssertionError unported() { return new AssertionError("unported strategic callback reached"); }
    static final class PlayerFixture extends OriginalActivationPlayer {
        int passes, activationCalls, parentDepth; boolean successful = true, throwsActivation, castResult = true;
        boolean leak; ActivatedAbility activated; Consumer<ActivatedAbility> observer = a -> { };
        boolean nestedPayment; List<ActivatedAbility> playable = new ArrayList<>();
        List<MageObject> producers = new ArrayList<>();
        PlayerFixture() { super("metadata activation", RangeOfInfluence.ALL); }
        PlayerFixture(PlayerFixture parent) { super(parent); }
        @Override public PlayerFixture copy() { return new PlayerFixture(this); }
        @Override public void pass(Game game) { passes++; }
        @Override public List<ActivatedAbility> getPlayable(Game game, boolean hidden) {
            require(hidden, "original playable visibility changed"); return new ArrayList<>(playable);
        }
        @Override protected boolean activateOriginalAbility(ActivatedAbility ability, Game game) {
            activationCalls++; activated = ability; observer.accept(ability);
            if (throwsActivation) throw new IllegalStateException("fixture engine failure");
            return successful;
        }
        @Override protected boolean castOriginalSpell(SpellAbility ability, Game game, boolean noMana, mage.ApprovingObject object) {
            if (leak) ((StackFixture)game.getStack()).count++; return castResult;
        }
        @Override protected boolean playOriginalAbility(ActivatedAbility ability, Game game) {
            if (leak) ((StackFixture)game.getStack()).count++; return castResult;
        }
        public boolean exercisePlay(ActivatedAbility ability, Game game) { return playAbility(ability, game); }
        @Override protected boolean originalParentPlayMana(Ability ability, ManaCost cost, String text, Game game) {
            int outer = depth(); require(outer == parentDepth+1, "payment depth changed"); parentDepth++;
            String unpaid = unpaid();
            try {
                if (nestedPayment && parentDepth == 1) {
                    try { playMana(ability, new ColoredManaCost(ColoredManaSymbol.R), text, game); throw new AssertionError("nested payment did not fail"); }
                    catch (IllegalStateException expected) { }
                    require(depth() == outer && Objects.equals(unpaid(), unpaid), "nested payment context was not restored");
                } else if (parentDepth == 2) throw new IllegalStateException("nested payment fixture");
                return true;
            } finally { parentDepth--; }
        }
        @Override protected List<MageObject> originalParentManaProducers(Game game) { return new ArrayList<>(producers); }
        @Override public boolean priority(Game game) { throw unported(); }
        @Override public boolean chooseTarget(Outcome o, Target t, Ability a, Game g) { throw unported(); }
        @Override public boolean chooseTarget(Outcome o, Cards c, TargetCard t, Ability a, Game g) { throw unported(); }
        @Override public boolean choose(Outcome o, Target t, Ability a, Game g) { throw unported(); }
        @Override public boolean choose(Outcome o, Cards c, TargetCard t, Ability a, Game g) { throw unported(); }
        @Override public boolean choose(Outcome o, Choice c, Game g) { throw unported(); }
        @Override public boolean chooseTargetAmount(Outcome o, TargetAmount t, Ability a, Game g) { throw unported(); }
        @Override public boolean choose(Outcome o, Target t, Ability a, Game g, Map<String, Serializable> opts) { throw unported(); }
        @Override public Mode chooseMode(Modes m, Ability a, Game g) { throw unported(); }
        @Override public int announceX(int min, int max, String message, Game g, Ability a, boolean mana) { throw unported(); }
        @Override public boolean chooseUse(Outcome o, String m, Ability a, Game g) { throw unported(); }
        @Override public boolean chooseUse(Outcome o, String m, String n, String t, String f, Ability a, Game g) { throw unported(); }
        @Override public void selectAttackers(Game g, UUID p) { throw unported(); }
        @Override public void selectBlockers(Ability a, Game g, UUID p) { throw unported(); }
        @Override public boolean chooseMulligan(Game g) { throw unported(); }
    }
    static final class StackFixture extends SpellStack { int count; @Override public int size() { return count; } }
    @SuppressWarnings("unchecked")
    static <T> T proxy(Class<T> type, InvocationHandler handler) {
        return (T)Proxy.newProxyInstance(type.getClassLoader(), new Class<?>[]{type}, (o,m,a) -> {
            if (m.getName().equals("toString")) return "metadata "+type.getSimpleName();
            if (m.getName().equals("hashCode")) return System.identityHashCode(o);
            if (m.getName().equals("equals")) return o == a[0];
            return handler.invoke(o,m,a);
        });
    }
    static ActivatedAbility action(UUID source, boolean stack, boolean tap) {
        CostsImpl costs = new CostsImpl(); if (tap) costs.add(new TapSourceCost());
        return proxy(ActivatedAbility.class, (o,m,a) -> {
            switch (m.getName()) {
                case "getSourceId": return source;
                case "getSourceObject": return ((Game)a[0]).getObject(source);
                case "getId": case "getOriginalId": return source;
                case "getControllerId": return null;
                case "getRule": return "fixture activation";
                case "getAbilityType": return AbilityType.ACTIVATED_NONMANA;
                case "getCosts": return costs;
                case "getTargets": return new Targets();
                case "getModes": return new Modes();
                case "getManaCostsToPay": return new ManaCostsImpl<>();
                case "isUsesStack": return stack;
                case "canActivate": return ActivatedAbility.ActivationStatus.withoutApprovingObject(true);
                default: throw new AssertionError("unexpected ability read: "+m.getName());
            }
        });
    }
    static Card card(UUID id, Ability ability) {
        AbilitiesImpl<Ability> abilities = new AbilitiesImpl<>(); abilities.add(ability);
        return proxy(Card.class, (o,m,a) -> {
            switch (m.getName()) {
                case "getId": return id;
                case "getName": return "fixture card";
                case "getAbilities": return abilities;
                default: throw new AssertionError("unexpected card read: "+m.getName());
            }
        });
    }
    static Permanent permanent(UUID id, UUID controller, Ability action) {
        AbilitiesImpl<Ability> abilities = new AbilitiesImpl<>();
        if (action != null) abilities.add(action);
        GreenManaAbility mana = new GreenManaAbility();mana.setSourceId(id);mana.setControllerId(controller);abilities.add(mana);
        return proxy(Permanent.class, (o,m,a) -> {
            switch(m.getName()) {
                case "getId": return id;
                case "getControllerId": case "getOwnerId": return controller;
                case "getName": return "metadata producer";
                case "getAbilities": return abilities;
                case "isTapped": case "isPhasedOut": return false;
                case "isPhasedIn": return true;
                case "isControlledBy": return controller.equals(a[0]);
                default: throw new AssertionError("unexpected permanent read: "+m.getName());
            }
        });
    }
    static final class WorldFixture {
        final PlayerFixture player = new PlayerFixture(); final Map<UUID,Card> cards = new HashMap<>();
        final StackFixture stack = new StackFixture(); final GameState state = new GameState();
        final Battlefield battlefield = new Battlefield();
        final UUID gameId = new UUID(1,1); final Game game; final List<String> bookmarks = new ArrayList<>();
        PhaseStep step = PhaseStep.UPKEEP; int events;
        WorldFixture() {
            state.setPriorityPlayerId(player.getId());
            game = proxy(Game.class, (o,m,a) -> {
                switch(m.getName()) {
                    case "getPlayer": return player.getId().equals(a[0]) ? player : null;
                    case "getPermanent": return battlefield.getPermanent((UUID)a[0]);
                    case "getPhase": return null;
                    case "getCard": case "getObject": return cards.get(a[0]);
                    case "getState": return state;
                    case "getStack": return stack;
                    case "getBattlefield": return battlefield;
                    case "getTurnStepType": return step;
                    case "getId": return gameId;
                    case "getTurnNum": return 1;
                    case "getActivePlayerId": return player.getId();
                    case "getRangeOfInfluence": return RangeOfInfluence.ALL;
                    case "inCheckPlayableState": return false;
                    case "firePriorityEvent": events++; return null;
                    case "bookmarkState": bookmarks.add("bookmark"); return 9;
                    case "removeBookmark": require(a[0].equals(9), "wrong removed bookmark"); bookmarks.add("remove"); return null;
                    case "restoreState": require(a[0].equals(9), "wrong restored bookmark"); bookmarks.add("restore"); stack.count--; return null;
                    default: throw new AssertionError("unexpected game read: "+m.getName());
                }
            });
        }
        PriorityRules rules() throws Exception {
            PriorityRules rules = new PriorityRules(player, Collections.emptyMap());
            Object empty = StateSequenceBuilder.SequenceOutput.class.getConstructor(List.class,List.class,List.class)
                    .newInstance(Collections.emptyList(), Collections.emptyList(), Collections.emptyList());
            set(rules,"cachedBaseState",empty);set(rules,"cachedBaseStateHash",1);set(rules,"cachedBaseStateGameId",gameId);
            set(rules,"cachedBaseStateActivePlayerId",player.getId());set(rules,"cachedBaseStatePriorityPlayerId",player.getId());
            set(rules,"cachedBaseStateChoosingPlayerId",state.getChoosingPlayerId());set(rules,"cachedBaseStateTurnNum",1);
            set(rules,"cachedBaseStateStepNum",state.getStepNum());set(rules,"cachedBaseStateApplyEffectsCounter",state.getApplyEffectsCounter());
            set(rules,"cachedBaseStateStackSize",0);return rules;
        }
    }
    static void set(Object target,String key,Object value) throws Exception {
        Field f = target.getClass().getDeclaredField(key);f.setAccessible(true);f.set(target,value);
    }
    static int depth() { return (Integer)tls("playManaDepth"); }
    static String unpaid() { return (String)tls("currentUnpaidManaText"); }
    static Object tls(String key) {
        try { Field f = OriginalActivationPlayer.class.getDeclaredField(key);f.setAccessible(true);return ((ThreadLocal<?>)f.get(null)).get(); }
        catch (Exception error) { throw new AssertionError(error); }
    }
    public static void main(String[] args) throws Exception {
        WorldFixture w = new WorldFixture(); PlayerFixture p = w.player; UUID source = new UUID(0,1);
        ActivatedAbility stale = action(source,true,false), fresh = action(source,true,true);
        w.cards.put(source,card(source,fresh));
        p.observer = a -> {
            require(a == fresh && p.activationAbility() == fresh && source.equals(p.excludedManaSource()), "fresh activation context changed");
            PlayerFixture copied = p.copy();
            require(copied.activationAbility() == fresh && copied.excludedManaSource() == null && copied.reservedTapSources().isEmpty(), "original copy context changed");
        };
        p.applyOriginalPriorityAbility(w.game,stale);
        require(p.activated == fresh && p.passes == 1 && p.activationAbility() == null && p.excludedManaSource() == null,
                "successful activation did not clear context and pass");
        ActivatedAbility noStack = action(source,false,false);
        p.applyOriginalPriorityAbility(w.game,noStack);require(p.passes == 1,"non-stack action passed priority");
        p.successful=false;p.applyOriginalPriorityAbility(w.game,stale);require(p.passes==2 && p.activationAbility()==null,"failed activation cleanup changed");
        p.throwsActivation=true;p.applyOriginalPriorityAbility(w.game,stale);require(p.passes==3 && p.excludedManaSource()==null,"exception did not force pass/cleanup");
        p.throwsActivation=false;p.successful=true;p.applyOriginalPriorityAbility(w.game,null);require(p.passes==4,"null original action did not pass");
        p.nestedPayment=true;require(p.playMana(fresh,new GenericManaCost(1),"pay",w.game),"parent payment result changed");
        require(depth()==0 && unpaid()==null,"outer payment context was retained");

        SpellAbility spell = new SpellAbility(new GenericManaCost(1),"fixture spell");spell.setSourceId(source);
        for(boolean spellPath:new boolean[]{true,false}) for(boolean result:new boolean[]{true,false}) for(boolean leak:new boolean[]{true,false}) {
            p.castResult=result;p.leak=leak;w.stack.count=0;w.bookmarks.clear();
            boolean actual=spellPath?p.cast(spell,w.game,false,null):p.exercisePlay(fresh,w.game);
            require(actual==result && w.bookmarks.equals(Arrays.asList("bookmark",!result && leak?"restore":"remove")), "bookmark recovery changed");
            require(p.activationHadStateLeak()==(!result && leak),"state-leak receipt changed");
        }
        require(!p.getStrictChooseMode(),"original engine-choice default changed");
        require(!PriorityRules.OriginalCallbacks.class.isInstance(p),"unfinished player asserted complete copied callbacks");
        PriorityRules rules=w.rules();
        WorldFixture other = new WorldFixture();
        try { p.dispatchOriginalPriority(other.rules(),w.game,items -> 0);throw new AssertionError("other player's rules accepted"); }
        catch (IllegalArgumentException expected) { }
        try { p.applyOriginalPriorityAbility(other.game,fresh);throw new AssertionError("other game accepted"); }
        catch (IllegalArgumentException expected) { }
        require(!p.dispatchOriginalPriority(rules,w.game,items -> {throw new AssertionError("upkeep used neural chooser");}) && p.passes==5,"original upkeep dispatch changed");
        w.stack.count=0;w.step=PhaseStep.PRECOMBAT_MAIN;p.playable.add(stale);
        require(p.dispatchOriginalPriority(rules,w.game,items -> { require(items.size()==2 && items.get(1)==stale,"original options changed");return 1; })
                && p.activated==fresh && p.passes==6,"original dispatch did not reach fresh activation");
        UUID reserved = new UUID(0,2), remaining = new UUID(0,3);
        ActivatedAbility tapTargets = action(source,true,true);
        mage.target.common.TargetControlledPermanent target = new mage.target.common.TargetControlledPermanent(1) {
            @Override public boolean canTarget(UUID controller, UUID id, Ability ability, Game game) { return id != null; }
        };
        tapTargets.getCosts().add(new TapTargetCost(target));
        Permanent sourcePerm = permanent(source,p.getId(),tapTargets), reservedPerm = permanent(reserved,p.getId(),null), sparePerm = permanent(remaining,p.getId(),null);
        for(Permanent perm:Arrays.asList(sourcePerm,reservedPerm,sparePerm)) {w.battlefield.addPermanent(perm);p.producers.add(perm);}
        p.observer = a -> {
            require(p.reservedTapSources().equals(Collections.singleton(reserved)),"original first tap-target reservation changed");
            require(p.getAvailableManaProducers(w.game).equals(Collections.singletonList(sparePerm)),"tap source or reserved target remained a mana producer");
            require(p.copy().reservedTapSources().isEmpty(),"tap-target reservation leaked to copy");
        };
        p.applyOriginalPriorityAbility(w.game,tapTargets);
        require(p.reservedTapSources().isEmpty() && p.excludedManaSource()==null,"tap reservations were retained after activation");
        System.out.println("original activation player: PASS (fresh action, tap exclusion, copy semantics, cleanup, nested payment, bookmarks and real priority dispatch)");
    }
}
