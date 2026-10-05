package spellbench.models.jack;

import mage.*;
import mage.abilities.*;
import mage.abilities.costs.*;
import mage.abilities.costs.common.*;
import mage.abilities.costs.mana.*;
import mage.abilities.effects.ContinuousEffects;
import mage.abilities.mana.*;
import mage.cards.*;
import mage.choices.*;
import mage.constants.*;
import mage.game.*;
import mage.game.permanent.Permanent;
import mage.players.ManaPoolItem;
import mage.target.*;
import java.io.Serializable;
import java.util.*;
import java.util.function.Function;
import static spellbench.models.jack.JackActivationPlayerCheck.*;

/** Actual private parent bodies with strict metadata hooks. No native game or model. */
public final class JackParentManaCheck {
    static final class PaymentPlayer extends OriginalParentManaPlayer {
        List<MageObject> producers = new ArrayList<>();List<Permanent> withCost = new ArrayList<>();
        final List<ActivatedAbility> attempts = new ArrayList<>();
        Function<ActivatedAbility,Boolean> activate = a -> true;
        Function<ActivatedAbility,Boolean> root = a -> true;
        PaymentPlayer() { super("metadata parent payment", RangeOfInfluence.ALL); }
        PaymentPlayer(PaymentPlayer p) { super(p); }
        @Override public PaymentPlayer copy() { return new PaymentPlayer(this); }
        @Override protected List<MageObject> engineParentManaProducers(Game g) { return new ArrayList<>(producers); }
        @Override public List<Permanent> getAvailableManaProducersWithCost(Game g) { return new ArrayList<>(withCost); }
        @Override public boolean activateAbility(ActivatedAbility a, Game g) { attempts.add(a); return activate.apply(a); }
        @Override protected boolean activateOriginalAbility(ActivatedAbility a, Game g) { return root.apply(a); }
        @Override public void pass(Game g) { }
        boolean paying() { return payManaMode; }
        void queue(String... answers) { choices.addAll(Arrays.asList(answers)); }
        int queued() { return choices.size(); }
        @Override protected boolean originalParentCreatureType(Outcome o, Choice c, Game g) { throw unported(); }
        @Override public boolean choose(Outcome o, Choice c, Game g) { return originalParentChoice(o,c,g); }
        @Override public boolean priority(Game g) { throw unported(); }
        @Override public boolean chooseTarget(Outcome o, Target t, Ability a, Game g) { throw unported(); }
        @Override public boolean chooseTarget(Outcome o, Cards c, TargetCard t, Ability a, Game g) { throw unported(); }
        @Override public boolean choose(Outcome o, Target t, Ability a, Game g) { throw unported(); }
        @Override public boolean choose(Outcome o, Cards c, TargetCard t, Ability a, Game g) { throw unported(); }
        @Override public boolean chooseTargetAmount(Outcome o, TargetAmount t, Ability a, Game g) { throw unported(); }
        @Override public boolean choose(Outcome o, Target t, Ability a, Game g, Map<String,Serializable> opts) { throw unported(); }
        @Override public Mode chooseMode(Modes m, Ability a, Game g) { throw unported(); }
        @Override public int announceX(int min,int max,String message,Game g,Ability a,boolean mana) { throw unported(); }
        @Override public boolean chooseUse(Outcome o,String m,Ability a,Game g) { throw unported(); }
        @Override public boolean chooseUse(Outcome o,String m,String n,String t,String f,Ability a,Game g) { throw unported(); }
        @Override public void selectAttackers(Game g,UUID p) { throw unported(); }
        @Override public void selectBlockers(Ability a,Game g,UUID p) { throw unported(); }
        @Override public boolean chooseMulligan(Game g) { throw unported(); }
    }
    static final class Effects extends ContinuousEffects {
        boolean approving; ManaType substitute; int checks;
        @Override public Set<ApprovingObject> asThough(UUID id,AsThoughEffectType type,Ability a,UUID controller,Game g) {
            require(type==AsThoughEffectType.SPEND_OTHER_MANA,"wrong as-though kind");
            return approving ? Collections.singleton(null) : Collections.emptySet();
        }
        @Override public ManaType asThoughMana(ManaType type,ManaPoolItem pool,UUID source,Ability a,UUID controller,Game g) {
            checks++;return substitute;
        }
    }
    static final class World {
        final PaymentPlayer player=new PaymentPlayer();final GameState state=new GameState();
        final Effects effects=new Effects();final Game game;
        final Map<UUID,Permanent> objects=new HashMap<>();
        World() {
            game=proxy(Game.class,(o,m,a)->{
                switch(m.getName()) {
                    case "getPlayer": return player.getId().equals(a[0])?player:null;
                    case "getState": return state;
                    case "getContinuousEffects": return effects;
                    case "getObject": case "getPermanent": return objects.get(a[0]);
                    case "getCard": return null;
                    case "getBattlefield": return state.getBattlefield();
                    case "inCheckPlayableState": return false;
                    default: throw new AssertionError("unexpected payment game read: "+m.getName());
                }
            });
        }
        Permanent add(UUID id,ActivatedAbility action,Mana... outputs) {
            SimpleManaAbility mana=new SimpleManaAbility(Zone.BATTLEFIELD,Mana.GreenMana(1),new TapSourceCost()) {
                @Override public List<Mana> getNetMana(Game g) { return Arrays.asList(outputs); }
            };
            mana.setSourceId(id);mana.setControllerId(player.getId());
            return add(id,action,mana);
        }
        Permanent add(UUID id,ActivatedAbility action,ActivatedManaAbilityImpl... mana) {
            AbilitiesImpl<Ability> abilities=new AbilitiesImpl<Ability>() {
                @Override public Abilities<ActivatedManaAbilityImpl> getAvailableActivatedManaAbilities(Zone z,UUID p,Game g) {
                    require(z==Zone.BATTLEFIELD && p.equals(player.getId()),"wrong original producer query");
                    AbilitiesImpl<ActivatedManaAbilityImpl> result=new AbilitiesImpl<>();result.addAll(Arrays.asList(mana));return result;
                }
            };
            if(action!=null)abilities.add(action);abilities.addAll(Arrays.asList(mana));
            Permanent permanent=proxy(Permanent.class,(o,m,a)->{
                switch(m.getName()) {
                    case "getId": return id;
                    case "getControllerId": case "getOwnerId": return player.getId();
                    case "getAbilities": return abilities;
                    case "getCardType": return Collections.singletonList(CardType.LAND);
                    case "isLand": return true;
                    case "isCreature": return false;
                    case "getName": return "metadata mana producer";
                    case "isTapped": case "isPhasedOut": return false;
                    case "isPhasedIn": return true;
                    case "isControlledBy": return player.getId().equals(a[0]);
                    default: throw new AssertionError("unexpected producer read: "+m.getName());
                }
            });
            objects.put(id,permanent);state.getBattlefield().addPermanent(permanent);player.producers.add(permanent);return permanent;
        }
    }
    static Choice color() { return new ChoiceColor().setManaColorChoice(true); }
    static void reset(World w) { w.player.attempts.clear();w.player.producers.clear();w.player.withCost.clear(); }
    public static void main(String[] args) throws Exception {
        World w=new World();PaymentPlayer p=w.player;UUID source=new UUID(0,10);
        ActivatedAbility bill=action(source,false,false);
        Permanent mixed=w.add(new UUID(0,11),null,Mana.GreenMana(1),Mana.RedMana(1));
        Permanent green=w.add(new UUID(0,12),null,Mana.GreenMana(1));
        require(p.playMana(bill,new ColoredManaCost(ColoredManaSymbol.G),"pay",w.game),"compatible producer refused");
        require(p.attempts.size()==1 && p.attempts.get(0).getSourceId().equals(green.getId()),"mixed source beat compatible color");
        reset(w);
        SimpleManaAbility small=new SimpleManaAbility(Zone.BATTLEFIELD,Mana.GreenMana(1),new TapSourceCost());
        SimpleManaAbility large=new SimpleManaAbility(Zone.BATTLEFIELD,Mana.GreenMana(3),new TapSourceCost());
        for(ActivatedAbility a:Arrays.asList(small,large)) {a.setSourceId(source);a.setControllerId(p.getId());}
        w.add(source,null,small,large);
        require(p.playMana(bill,new GenericManaCost(1),"pay",w.game) && p.attempts.get(0)==large,"original descending mana count changed");
        reset(w);p.withCost.add(mixed);p.activate=a->false;
        require(!p.playMana(bill,new GenericManaCost(1),"pay",w.game) && !p.attempts.isEmpty(),"with-cost source or false activation handling changed");
        require(!p.paying() && depth()==0 && unpaid()==null,"failed payment leaked context");
        reset(w);p.activate=a->true;
        ConditionalMana rejected=new ConditionalMana(Mana.GreenMana(1)) {
            @Override public boolean apply(Ability a,Game g,UUID id,Cost c) {return false;}
        };
        w.add(new UUID(0,13),null,rejected);
        w.add(new UUID(0,14),null,Mana.GreenMana(1));
        require(p.playMana(bill,new ColoredManaCost(ColoredManaSymbol.G),"pay",w.game)
                && p.attempts.get(0).getSourceId().equals(new UUID(0,14)),"conditional mana rejection changed");
        reset(w);w.add(new UUID(0,15),null,Mana.RedMana(1));w.effects.approving=true;
        require(!p.playMana(bill,new ColoredManaCost(ColoredManaSymbol.G),"pay",w.game) && p.attempts.isEmpty(),"as-though approval bypassed actual type check");
        w.effects.substitute=ManaType.RED;
        require(p.playMana(bill,new ColoredManaCost(ColoredManaSymbol.G),"pay",w.game) && w.effects.checks>0,"as-though effective pool type refused");
        w.effects.approving=false;w.effects.substitute=null;reset(w);
        Mana snow=Mana.GreenMana(1);snow.setFlag(true);
        ManaCost[] costs={new SnowManaCost(),new ColorlessManaCost(1),new HybridManaCost(ColoredManaSymbol.R,ColoredManaSymbol.G),
            new ColorlessHybridManaCost(ColoredManaSymbol.G),new MonoHybridManaCost(ColoredManaSymbol.G),new GenericManaCost(1)};
        Mana[] outputs={snow,Mana.ColorlessMana(1),Mana.GreenMana(1),Mana.ColorlessMana(1),Mana.GreenMana(1),Mana.GreenMana(1)};
        for(int i=0;i<costs.length;i++) {reset(w);w.add(new UUID(0,20+i),null,outputs[i]);
            require(p.playMana(bill,costs[i],"pay",w.game) && p.attempts.size()==1,"payment kind refused: "+costs[i].getText());}
        reset(w);
        final int[] lifeCalls={0};
        GenericManaCost phyrexian=new GenericManaCost(1) {
            @Override public boolean isPhyrexian() {return true;}
            @Override public boolean pay(Ability a,Game g,Ability source,UUID payer,boolean noMana,Cost cost) {
                lifeCalls[0]++;
                require(!p.playMana(a,this,"recursive life payment",g),"phyrexian guard allowed recursion");return true;
            }
        };
        require(p.playMana(bill,phyrexian,"pay",w.game) && lifeCalls[0]==1,"original phyrexian life path changed");
        require(p.playMana(bill,phyrexian,"pay",w.game) && lifeCalls[0]==2,"phyrexian guard failed to reset");
        SpecialAction special=new SpecialAction() {
            @Override public boolean isManaAction() {return true;}
            @Override public ManaOptions getManaOptions(Ability a,Game g,ManaCost cost) {
                ManaOptions options=new ManaOptions();options.add(Mana.GreenMana(1));options.add(Mana.RedMana(1));return options;
            }
            @Override public SpecialAction copy() {throw unported();}
        };
        special.setControllerId(p.getId());w.state.getSpecialActions().add(special);p.activate=a->false;
        require(!p.playMana(bill,new GenericManaCost(1),"pay",w.game) && p.attempts.equals(Collections.singletonList(special)),
                "special mana repeated failed activation");
        w.state.getSpecialActions().clear();p.activate=a->true;
        reset(w);w.add(new UUID(0,30),null,Mana.GreenMana(1));
        ManaCostsImpl<ManaCost> multicolor=new ManaCostsImpl<>("{W}{R}{G}");
        p.activate=a->{Choice c=color();p.choose(Outcome.PutManaInPool,c,w.game);require("White".equals(c.getChoice()),"original color hint priority changed");return true;};
        require(p.playMana(bill,multicolor,"pay",w.game),"multi-cost producer scoring refused");
        require(!p.paying() && depth()==0 && unpaid()==null,"successful payment leaked context");
        p.queue("Red");PaymentPlayer copy=p.copy();Choice queued=color();copy.choose(Outcome.PutManaInPool,queued,w.game);
        require("Red".equals(queued.getChoice()) && copy.queued()==0 && p.queued()==1,"queued choice copy/removal changed");
        p.choices.clear();p.queue("prefix");ChoiceImpl keyed=new ChoiceImpl(true);
        keyed.setKeyChoices(Collections.singletonMap("key","<b>prefix</b> answer"));p.choose(Outcome.Neutral,keyed,w.game);
        require("key".equals(keyed.getChoiceKey()) && p.queued()==0,"original HTML-cleaned queued prefix changed");
        reset(w);w.add(new UUID(0,31),null,Mana.GreenMana(1));
        ActivatedAbility inner=action(new UUID(0,32),false,false);
        final boolean[] nested={false};
        p.activate=a->{
            if(!nested[0]) {
                nested[0]=true;require(p.paying() && depth()==1,"outer parent context missing");
                Choice outer=color();p.choose(Outcome.PutManaInPool,outer,w.game);require("Green".equals(outer.getChoice()),"outer hint missing");
                try {p.playMana(inner,new GenericManaCost(1),"nested",w.game);throw new AssertionError("nested payment did not throw");}
                catch(IllegalStateException expected) { }
                require(depth()==1 && !p.paying(),"original nested parent pay mode or RL depth changed");
                outer=color();p.choose(Outcome.PutManaInPool,outer,w.game);require("Green".equals(outer.getChoice()),"outer hint was not restored");
                return true;
            }
            throw new IllegalStateException("nested payment failure");
        };
        require(p.playMana(bill,new ColoredManaCost(ColoredManaSymbol.G),"pay",w.game),"outer payment after nested failure refused");
        require(depth()==0 && !p.paying() && unpaid()==null,"successful outer payment leaked context");
        try {p.playMana(bill,new ColoredManaCost(ColoredManaSymbol.G),"pay",w.game);throw new AssertionError("payment exception swallowed");}
        catch(IllegalStateException expected) {require(depth()==0 && !p.paying() && unpaid()==null,"exception leaked parent or RL context");}
        reset(w);p.activate=a->true;
        ActivatedAbility tap=action(source,false,true);w.add(source,tap,Mana.GreenMana(1));
        UUID spare=new UUID(0,40);w.add(spare,null,Mana.GreenMana(1));
        p.root=a->{require(p.playMana(a,new ColoredManaCost(ColoredManaSymbol.G),"pay",w.game),"activation payment refused");
            require(p.attempts.get(0).getSourceId().equals(spare),"payment reused reserved tap source");return true;};
        p.applyOriginalPriorityAbility(w.game,tap);
        require(p.excludedManaSource()==null && p.activationAbility()==null,"activation reservation leaked");
        require(!PriorityRules.OriginalCallbacks.class.isInstance(p),"unfinished parent asserted full callbacks");
        System.out.println("original parent mana: PASS (producer order, mana kinds, conditions, as-though, phyrexian guard, special mana, color hints, queued copy, nested cleanup and activation reservations)");
    }
}
