package spellbench.models.maintainer;

import mage.*;
import mage.abilities.*;
import mage.abilities.effects.common.InfoEffect;
import mage.cards.*;
import mage.choices.*;
import mage.constants.*;
import mage.game.Game;
import mage.game.GameState;
import mage.game.permanent.Permanent;
import mage.players.Library;
import mage.target.*;
import mage.util.MultiAmountMessage;
import java.util.*;
import static spellbench.models.maintainer.MaintainerActivationPlayerCheck.*;

/** Executes actual inherited bodies with metadata engine hooks, without a native game. */
public final class MaintainerParentDialogCheck {
    static final class DialogPlayer extends OriginalParentDialogsPlayer {
        Game admitted;int gates,uses;List<MageObject> producers=new ArrayList<>();
        final List<UUID> libraryIds=new ArrayList<>();
        final Library library=new Library(getId()) { @Override public List<UUID> getCardList() {return libraryIds;} };
        DialogPlayer() {super("metadata parent dialogs",RangeOfInfluence.ALL);}
        DialogPlayer(DialogPlayer p) {super(p);}
        void metadataLife(int value) {life=value;}
        @Override public DialogPlayer copy() {return new DialogPlayer(this);}
        @Override protected void requireOriginalPermittedWorld(Game game) {
            gates++;if(game!=admitted)throw new IllegalArgumentException("world not admitted");
        }
        @Override public Library getLibrary() {return library;}
        @Override protected List<MageObject> engineParentManaProducers(Game g) {return new ArrayList<>(producers);}
        @Override public boolean choose(Outcome o,Choice c,Game g) {return originalParentChoice(o,c,g);}
        @Override public Mode chooseMode(Modes m,Ability a,Game g) {return originalParentMode(m,a,g);}
        @Override public boolean choose(Outcome o,Target t,Ability a,Game g) {return originalParentTargetChoice(o,t,a,g);}
        @Override public boolean chooseTarget(Outcome o,Target t,Ability a,Game g) {return originalParentTarget(o,t,a,g);}
        @Override public boolean chooseTarget(Outcome o,Cards c,TargetCard t,Ability a,Game g) {return originalParentTargetCards(o,c,t,a,g);}
        @Override public boolean choose(Outcome o,Cards c,TargetCard t,Ability a,Game g) {return originalParentCards(o,c,t,a,g);}
        @Override public int announceX(int min,int max,String msg,Game g,Ability a,boolean mana) {return originalParentAnnounceX(min,max,msg,g,a,mana);}
        @Override public boolean chooseUse(Outcome o,String m,Ability a,Game g) {return originalParentUse(o,m,a,g);}
        @Override public boolean chooseUse(Outcome o,String m,String second,String yes,String no,Ability a,Game g) {
            uses++;return originalParentUse(o,m,second,yes,no,a,g);
        }
        @Override public boolean priority(Game g) {throw unported();}
        @Override public void selectAttackers(Game g,UUID p) {throw unported();}
        @Override public void selectBlockers(Ability a,Game g,UUID p) {throw unported();}
        @Override public boolean chooseMulligan(Game g) {throw unported();}
    }
    static final class Creature extends CardImpl {
        Creature(UUID owner,String name,SubType type,int toughness) {
            super(owner,new CardSetInfo(name,"META","1",Rarity.COMMON),new CardType[]{CardType.CREATURE},"{G}");
            subtype.add(type);setPT(2,toughness);
        }
        Creature(Creature c) {super(c);}
        @Override public Creature copy() {return new Creature(this);}
    }
    static final class World {
        final DialogPlayer player;final DialogPlayer other=new DialogPlayer();final GameState state=new GameState();
        final Map<UUID,Card> cards=new HashMap<>();final Game game;int libraryReads;
        World() {this(new DialogPlayer());}
        World(DialogPlayer p) {
            player=p;other.metadataLife(3);
            game=proxy(Game.class,(o,m,a)->{
                switch(m.getName()) {
                    case "getPlayer": return player.getId().equals(a[0])?player:other.getId().equals(a[0])?other:null;
                    case "getCard": case "getObject": libraryReads++;return cards.get(a[0]);
                    case "getState": return state;
                    case "getPermanent": return state.getBattlefield().getPermanent((UUID)a[0]);
                    case "getBattlefield": return state.getBattlefield();
                    case "getOpponents": return Collections.singleton(other.getId());
                    case "getRangeOfInfluence": return RangeOfInfluence.ALL;
                    case "inCheckPlayableState": return false;
                    default: throw new AssertionError("unexpected parent dialog game read: "+m.getName());
                }
            });
            player.admitted=game;other.admitted=game;
        }
        Creature card(UUID owner,String name,SubType type,int toughness) {
            Creature c=new Creature(owner,name,type,toughness);cards.put(c.getId(),c);return c;
        }
        Permanent permanent(UUID owner,SubType type) {
            UUID id=UUID.randomUUID();
            Permanent p=proxy(Permanent.class,(o,m,a)->{
                switch(m.getName()) {
                    case "getId": return id;
                    case "getControllerId": case "getOwnerId": return owner;
                    case "isControlledBy": return owner.equals(a[0]);
                    case "isPhasedIn": return true;
                    case "isPhasedOut": return false;
                    case "getCardType": return Collections.singletonList(CardType.CREATURE);
                    case "getSubtype": mage.util.SubTypes sub=new mage.util.SubTypes();sub.add(type);return sub;
                    default: throw new AssertionError("unexpected creature permanent read: "+m.getName());
                }
            });
            state.getBattlefield().addPermanent(p);return p;
        }
    }
    static final class Amount extends mage.target.common.TargetAnyTargetAmount {
        final List<UUID> available;final int budget;int left,prepared;
        Amount(int amount,int min,int max,UUID... ids) {super(amount,min,max);budget=amount;left=amount;available=Arrays.asList(ids);}
        @Override public Amount copy() {throw unported();}
        @Override public void prepareAmount(Ability a,Game g) {prepared++;left=budget;}
        @Override public int getAmountRemaining() {return left;}
        @Override public UUID getAffectedAbilityControllerId(UUID player) {return player;}
        @Override public Set<UUID> possibleTargets(UUID p,Ability a,Game g,Set<UUID> from) {return new LinkedHashSet<>(available);}
        @Override public boolean canTarget(UUID p,UUID id,Ability a,Game g) {return available.contains(id);}
        @Override public boolean isChoiceCompleted(UUID p,Ability a,Game g,Cards from) {return left<=0;}
        @Override public boolean isChosen(Game g) {return targets.size()>=getMinNumberOfTargets();}
        @Override public void addTarget(UUID id,int amount,Ability a,Game g) {
            require(amount>0 && amount<=left && available.contains(id),"invalid metadata amount application");
            targets.put(id,amount);left-=amount;
        }
    }
    static final class CardTarget extends TargetCard {
        final List<UUID> offered;boolean complete;int adds,actualAdds;
        CardTarget(UUID... ids) {super(Zone.HAND);offered=Arrays.asList(ids);setMinNumberOfTargets(1);setMaxNumberOfTargets(1);}
        @Override public CardTarget copy() {throw unported();}
        @Override public UUID getAffectedAbilityControllerId(UUID p) {return p;}
        @Override public String getMessage(Game g) {return "metadata card choice";}
        @Override public Set<UUID> possibleTargets(UUID p,Ability a,Game g,Set<UUID> from) {return new LinkedHashSet<>(offered);}
        @Override public boolean isChoiceCompleted(UUID p,Ability a,Game g,Cards from) {return complete;}
        @Override public boolean isChosen(Game g) {return complete;}
        @Override public void add(UUID id,Game g) {adds++;targets.put(id,0);complete=true;}
        @Override public void addTarget(UUID id,Ability a,Game g) {actualAdds++;targets.put(id,0);complete=true;}
    }
    static ChoiceImpl types() {
        ChoiceImpl c=new ChoiceImpl(true);c.setMessage("Choose a creature type");
        c.setChoices(new LinkedHashSet<>(Arrays.asList("Elf","Human","Goblin")));return c;
    }
    public static void main(String[] args) throws Exception {
        World w=new World();DialogPlayer p=w.player;
        Creature elf=w.card(p.getId(),"hand elf",SubType.ELF,2),human=w.card(p.getId(),"sampled human",SubType.HUMAN,2);
        Creature goblin=w.card(w.other.getId(),"public goblin",SubType.GOBLIN,4);
        p.getHand().add(elf);p.libraryIds.add(human.getId());
        ChoiceImpl c=types();p.choose(Outcome.Benefit,c,w.game);require("Elf".equals(c.getChoice()),"hand creature priority changed");
        p.getHand().clear();c=types();p.choose(Outcome.Benefit,c,w.game);require("Human".equals(c.getChoice()),"permitted library scan changed");
        w.other.getGraveyard().add(goblin);c=types();p.choose(Outcome.Detriment,c,w.game);require("Goblin".equals(c.getChoice()),"public graveyard fallback changed");
        w.permanent(w.other.getId(),SubType.ELF);c=types();p.choose(Outcome.Detriment,c,w.game);require("Elf".equals(c.getChoice()),"battlefield priority changed");
        int reads=w.libraryReads;Game admitted=p.admitted;p.admitted=null;
        try {p.choose(Outcome.Benefit,types(),w.game);throw new AssertionError("unadmitted library world accepted");}
        catch(IllegalArgumentException expected) {require(w.libraryReads==reads,"unadmitted world read a card");}
        p.admitted=admitted;
        ActivatedAbility source=action(elf.getId(),false,false);
        Amount damage=new Amount(7,1,3,w.other.getId(),goblin.getId(),elf.getId());
        require(p.chooseTargetAmount(Outcome.Damage,damage,source,w.game),"original damage allocation refused");
        require(damage.getTargetAmount(w.other.getId())==3 && damage.getTargetAmount(goblin.getId())==4 && !damage.contains(elf.getId()),
                "damage did not kill opponent before creature");
        Amount avoidKill=new Amount(4,1,2,elf.getId(),human.getId());
        require(p.chooseTargetAmount(Outcome.Damage,avoidKill,source,w.game) && avoidKill.getTargets().size()==1
                && avoidKill.getTargetAmount(avoidKill.getTargets().get(0))==1,"original bad damage did not avoid killing/stop early");
        Amount counter=new Amount(5,1,1,elf.getId());
        require(p.chooseTargetAmount(Outcome.Benefit,counter,source,w.game) && counter.getTargetAmount(elf.getId())==5,"non-damage amount was split");
        Amount zero=new Amount(0,1,1,elf.getId());require(!p.chooseTargetAmount(Outcome.Damage,zero,source,w.game) && zero.prepared==1,"zero amount shortcut changed");
        CardTarget picked=new CardTarget(elf.getId());p.targets.add(elf.getId());DialogPlayer copy=p.copy();World copiedWorld=new World(copy);
        require(copy.choose(Outcome.Benefit,new CardsImpl(Collections.singleton(elf.getId())),picked,source,copiedWorld.game)
                && picked.adds==1 && picked.actualAdds==0 && copy.targets.isEmpty() && p.targets.size()==1,"queued target copy/simple add changed");
        picked=new CardTarget(elf.getId());require(p.chooseTarget(Outcome.Benefit,new CardsImpl(Collections.singleton(elf.getId())),picked,source,w.game)
                && picked.actualAdds==1 && picked.adds==0 && p.targets.isEmpty(),"queued actual target path changed");
        picked=new CardTarget(elf.getId());require(p.choose(Outcome.Benefit,picked,source,w.game,Collections.emptyMap())
                && picked.adds==1,"actual Target/Map callback did not reach original scorer");
        p.producers.addAll(Arrays.asList(elf,human,goblin));
        for(Creature producer:Arrays.asList(elf,human,goblin))producer.addAbility(new mage.abilities.mana.GreenManaAbility());
        SpellAbility manaBill=new SpellAbility(new mage.abilities.costs.mana.GenericManaCost(1),"metadata X spell");
        manaBill.setSourceId(elf.getId());manaBill.setControllerId(p.getId());
        manaBill.getManaCostsToPay().clear();manaBill.getManaCostsToPay().add(new mage.abilities.costs.mana.GenericManaCost(1));
        require(p.getAvailableManaProducers(w.game).size()==3 && manaBill.getManaCostsToPay().getUnpaid().manaValue()==1,
                "X metadata did not provide three usable producers and one unpaid mana");
        require(p.announceX(0,9,"X",w.game,manaBill,true)==2 && p.announceX(5,9,"X",w.game,manaBill,true)==5,
                "original X producer-count calculation/clamp changed");
        require(p.getAmount(4,4,"amount",source,w.game)==4,"inherited fixed amount changed");
        require(p.chooseUse(Outcome.Benefit,"use",source,w.game) && p.uses==1,"single use failed virtual delegation");
        require(!p.chooseUse(Outcome.AIDontUseIt,"use",null,null,null,source,w.game),"original parent use outcome changed");
        Mode first=new Mode(new InfoEffect("first")),second=new Mode(new InfoEffect("second"));
        Modes modes=new Modes() { @Override public List<Mode> getAvailableModes(Ability a,Game g) {return Arrays.asList(first,second);} };
        modes.addMode(first);modes.addMode(second);modes.clearSelectedModes();
        require(p.chooseMode(modes,source,w.game)==first,"original mode order changed");
        modes.addSelectedMode(second.getId());modes.setActiveMode(second);modes.setMaxModes(1);
        require(p.chooseMode(modes,source,w.game)==second,"already selected mode was replaced");
        List<MultiAmountMessage> messages=Arrays.asList(new MultiAmountMessage("a",0,3),new MultiAmountMessage("b",0,3));
        require(p.getMultiAmountWithIndividualConstraints(Outcome.Benefit,messages,0,4,MultiAmountType.COUNTERS,w.game)
                .equals(Arrays.asList(2,2)),"original good multi-amount allocation changed");
        require(p.getMultiAmountWithIndividualConstraints(Outcome.Detriment,messages,0,4,MultiAmountType.COUNTERS,w.game)
                .equals(Arrays.asList(0,0)),"original bad multi-amount allocation changed");
        require(p.chooseTriggeredAbility(Collections.emptyList(),w.game)==null && p.choosePile(Outcome.Neutral,"pile",Collections.emptyList(),Collections.emptyList(),w.game),
                "original ancillary shortcuts changed");
        require(p.chooseReplacementEffect(Collections.singletonMap("one","one"),Collections.emptyMap(),w.game)==0,"replacement order changed");
        try {p.getAmount(1,1,"wrong world",source,copiedWorld.game);throw new AssertionError("wrong player accepted");}
        catch(IllegalArgumentException expected) { }
        require(!PriorityRules.OriginalCallbacks.class.isInstance(p),"unfinished dialogs asserted complete neural callbacks");
        System.out.println("original parent dialogs: PASS (permitted gate, creature scan, damage/counter allocation, queued copy/application, original target scorer, X, use, modes and ancillary choices)");
    }
}
