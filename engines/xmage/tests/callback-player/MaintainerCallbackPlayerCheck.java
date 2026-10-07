package spellbench.models.maintainer;
import mage.MageObject;
import mage.abilities.*;
import mage.cards.*;
import mage.constants.*;
import mage.game.*;
import mage.players.*;
import mage.target.*;
import java.util.*;
import static spellbench.models.maintainer.MaintainerActivationPlayerCheck.*;
import static spellbench.models.maintainer.MaintainerNeuralSelectionCheck.refused;

/** Actual full callback dispatch with synthetic paired predictions and metadata worlds. */
public final class MaintainerCallbackPlayerCheck {
    static final class Full extends OriginalCallbackPlayer {
        Full() { super("original metadata",RangeOfInfluence.ALL); }
        Full(Full p) { super(p); }
        @Override public Full copy() { return new Full(this); }
        @Override protected List<MageObject> engineParentManaProducers(Game g) { return Collections.emptyList(); }
        PriorityRules rules() { return originalPriorityRules(); }
        OriginalNeuralSelection neural() { return originalNeuralSelection(); }
    }
    static final class Backend implements OriginalNeuralSelection.Model {
        int calls, mulligans, copies; boolean closed, fail;
        int slot=1; String format="keep-mull-q"; float first=1,second=1;
        OriginalNeuralSelection.Request request;
        float[] mulliganFeatures;
        public String callbackSourceSha256() { return OriginalCallbackPlayer.SOURCE_SHA256; }
        public String profile() { return OriginalNeuralSelection.GREEDY; }
        public long seed() { return 33; }
        public OriginalNeuralSelection.Prediction score(OriginalNeuralSelection.Request r,double seconds) {
            calls++; request=r; if(fail) throw new IllegalArgumentException("model unavailable");
            float[] scores=new float[64]; scores[slot]=1; return new OriginalNeuralSelection.Prediction(scores,0.25f);
        }
        public OriginalNeuralSelection.MulliganPrediction mulligan(float[] features,double seconds) {
            mulligans++; mulliganFeatures=features; return new OriginalNeuralSelection.MulliganPrediction(format,first,second);
        }
        public int physicalCopy(int count,double seconds) { copies++; return count-1; }
        public void close() { closed=true; }
        OriginalNeuralSelection.Session session() { return new OriginalNeuralSelection.Session(this,profile(),seed(),()->10); }
    }
    static final class World {
        final Full player; final Player other=new mage.player.ai.ComputerPlayer("other",RangeOfInfluence.ALL);
        final Players players=new Players(); final GameState state=new GameState(); final Game game;
        final Map<UUID,Card> cards=new HashMap<>(); final Map<UUID,String> aliases=new HashMap<>();
        boolean simulation; int builds;
        World() { this(new Full()); }
        World(Full p) {
            player=p; players.addPlayer(p); players.addPlayer(other);
            game=proxy(Game.class,(o,m,a)->{
                switch(m.getName()) {
                    case "getPlayer": return players.get(a[0]);
                    case "getPlayers": return players;
                    case "getOpponents": return Collections.singleton(other.getId());
                    case "getState": return state;
                    case "getId": return new UUID(0,88);
                    case "getPhase": return null;
                    case "getTurnNum": return 1;
                    case "getActivePlayerId": return player.getId();
                    case "getStartingLife": builds++; return 20;
                    case "getBattlefield": return state.getBattlefield();
                    case "getStack": return state.getStack();
                    case "getExile": return state.getExile();
                    case "getCard": case "getObject": return cards.get(a[0]);
                    case "getPermanent": return null;
                    case "isSimulation": return simulation;
                    case "createSimulationForPlayableCalc": {
                        World copied=new World(player.copy());copied.simulation=true;copied.cards.putAll(cards);return copied.game;
                    }
                    case "getRangeOfInfluence": return RangeOfInfluence.ALL;
                    case "inCheckPlayableState": return false;
                    default: throw new AssertionError("unexpected full callback read: "+m.getName());
                }
            });
        }
        OriginalNeuralSelection.Admission admission() {
            return new OriginalNeuralSelection.Admission() {
                public void require(Game g,Player p) { if(g!=game || p!=player) throw new IllegalArgumentException("world refused"); }
                public Map<UUID,String> aliases(Game g,Player p) { require(g,p); return aliases; }
                public OriginalNeuralSelection.Admission copy(Game source,Game copied,Player p) {
                    require(source,player);
                    return (g,v)->{ if(g!=copied || v!=p) throw new IllegalArgumentException("copy refused"); };
                }
            };
        }
        void bind(Backend backend) { player.bindOriginalWorld(game,aliases,backend.session(),admission()); }
        Card card(String name) {
            Card c=new MaintainerParentDialogCheck.Creature(player.getId(),name,SubType.ELF,2); cards.put(c.getId(),c); return c;
        }
    }
    static final class TargetFixture extends mage.target.common.TargetAnyTarget {
        final List<UUID> offered;
        TargetFixture(int min,int max,UUID... ids) { super(min,max); offered=Arrays.asList(ids); }
        @Override public Set<UUID> possibleTargets(UUID p,Ability a,Game g) { return new LinkedHashSet<>(offered); }
        @Override public boolean canTarget(UUID p,UUID id,Ability a,Game g) { return offered.contains(id); }
        @Override public void addTarget(UUID id,Ability a,Game g) { targets.put(id,0); }
        @Override public boolean isChosen(Game g) { return targets.size()>=getMinNumberOfTargets(); }
    }
    public static void main(String[] args) {
        Backend b=new Backend(); World w=new World(); w.bind(b); Full p=w.player;
        require(p.chooseUse(Outcome.Benefit,"use?",null,w.game)==false && b.request.head.equals("action"),"YES/NO neural dispatch changed");
        require(p.announceX(0,5,"X?",w.game,null,false)==1,"X candidate order changed");
        int calls=b.calls;
        require(p.announceX(7,7,"X?",w.game,null,false)==7 && b.calls==calls,"forced X entered model");
        Mode a=new Mode(new mage.abilities.effects.common.InfoEffect("first")),z=new Mode(new mage.abilities.effects.common.InfoEffect("second"));
        Modes modes=new Modes() { @Override public List<Mode> getAvailableModes(Ability ability,Game game) { return Arrays.asList(a,z); } };
        modes.addMode(a);modes.addMode(z);
        require(p.chooseMode(modes,null,w.game)==z && b.request.features()[1][0]==0.5f,"mode ordinal/application changed");
        Card c=w.card("Alpha"),d=w.card("Beta"),e=w.card("Gamma");
        TargetFixture target=new TargetFixture(2,2,c.getId(),d.getId(),e.getId());
        require(p.chooseTarget(Outcome.Benefit,target,null,w.game),"general target callback refused");
        require(target.getTargets().equals(Arrays.asList(d.getId(),e.getId())) && b.request.pickIndex==1,
                "target candidate removal/pick index changed");
        Cards cards=new CardsImpl();cards.add(c);cards.add(d);
        MaintainerParentDialogCheck.CardTarget ct=new MaintainerParentDialogCheck.CardTarget(c.getId(),d.getId());
        require(p.chooseTarget(Outcome.Benefit,cards,ct,null,w.game) && ct.getTargets().equals(Collections.singletonList(d.getId()))
                && b.request.head.equals("card_select") && b.copies==0,"provided card callback changed");
        p.getHand().add(c);
        require(!p.chooseMulligan(w.game) && !p.chooseMulligan(w.game) && b.mulligans==1,"Q tie/duplicate mulligan changed");
        require(b.mulliganFeatures.length==71,"mulligan encoder shape changed");
        p.getHand().clear();p.getHand().add(d);b.first=0;b.second=1;
        require(p.chooseMulligan(w.game) && p.chooseMulligan(w.game) && b.mulligans==2,"mulligan cache/count changed");
        p.getHand().clear();p.getHand().add(e);b.format="keep-logit";b.first=0;b.second=0.5f;
        require(!p.chooseMulligan(w.game) && b.mulliganFeatures[0]==1,"logit tie or mulligan counter changed");
        require(p.originalNeuralSession().physicalCopy(1)==0 && b.copies==0,"singleton copy consumed stream");
        require(p.originalNeuralSession().physicalCopy(3)==2 && b.copies==1,"physical-copy stream changed");
        p.getHand().clear();
        StateSequenceBuilder.SequenceOutput old=p.neural().capture(w.game);int builds=w.builds;
        require(p.neural().capture(w.game)==old && w.builds==builds,"unchanged callback cache rebuilt");
        w.aliases.put(new UUID(0,999),"public-new");
        require(p.neural().capture(w.game)!=old && p.rules().aliases().equals(w.aliases),"alias refresh did not invalidate cache");
        World child=new World(p.copy());child.simulation=true;
        p.admitOriginalSimulation(w.game,child.game);
        require(!child.player.chooseUse(Outcome.Benefit,"copy?",null,child.game) && b.calls>calls,"admitted copy lost shared backend");
        child.player.selectAttackers(child.game,child.player.getId());child.player.selectBlockers(null,child.game,child.player.getId());
        World missing=new World(); Backend bad=new Backend(); missing.bind(bad);
        refused(()->missing.player.admitOriginalSimulation(missing.game,new World(new Full()).game));
        require(bad.closed,"unadmitted copy did not close model session");
        World failure=new World(); Backend failed=new Backend();failure.bind(failed);failed.fail=true;
        refused(()->failure.player.chooseUse(Outcome.Benefit,"failure?",null,failure.game));
        require(failed.closed,"model failure did not close full callback session");
        System.out.println("PASS MaintainerCallbackPlayerCheck");
    }
}
