package spellbench.kit.xmage;

import mage.abilities.Ability;
import mage.constants.MultiAmountType;
import mage.constants.Outcome;
import mage.game.Game;
import mage.util.MultiAmountMessage;
import spellbench.models.maintainer.OriginalCallbackPlayer;
import java.util.*;
import static spellbench.kit.xmage.MaintainerPlayerBootstrapCheck.*;

/** Unsupported groups must stop before the inherited body or another policy draw. */
public final class MaintainerUnconnectedDistributionCheck {
    static final class Amount extends mage.target.common.TargetAnyTargetAmount {
        int prepared;
        Amount() {super(0,1,1);}
        @Override public void prepareAmount(Ability source,Game game) {prepared++;}
        @Override public int getAmountRemaining() {return 0;}
    }
    static final class Messages extends AbstractList<MultiAmountMessage> {
        int reads;
        @Override public int size() {reads++;return 0;}
        @Override public MultiAmountMessage get(int index) {throw new AssertionError("empty messages read");}
    }
    static List<Integer> amounts(OriginalCallbackPlayer player,Game game,Outcome outcome,List<MultiAmountMessage> messages) {
        return player.getMultiAmountWithIndividualConstraints(outcome,messages,0,4,MultiAmountType.COUNTERS,game);
    }
    static void unsupported(boolean divided,boolean prefix) {
        MaintainerDialogReplayCheck.Case c=new MaintainerDialogReplayCheck.Case();
        Amount target=new Amount();Messages messages=new Messages();
        Map<String,Object> record=c.record(prefix);
        c.player.activationWork=()->{
            if(prefix)c.player.chooseUse(Outcome.Benefit,"earlier",null,c.world.game);
            if(divided)c.player.chooseTargetAmount(Outcome.Damage,target,c.ability,c.world.game);
            else amounts(c.player,c.world.game,Outcome.Benefit,messages);
        };
        // The script invokes the unsupported group before its recorded later dialog.
        refused(()->c.control(record).choose());
        require(target.prepared==0 && target.getTargets().isEmpty() && messages.reads==0,
                "unconnected distribution entered or mutated its inherited body");
        require(c.backend.calls==0 && c.backend.copies==0 && c.backend.closed,
                "unconnected distribution advanced inference or retained its session");
        c.registry.close();
    }
    public static void main(String[] args) {
        int cases=0;
        for(boolean prefix:new boolean[]{false,true}) {
            unsupported(false,prefix);cases++;
        }
        MaintainerDialogReplayCheck.Case c=new MaintainerDialogReplayCheck.Case();
        Amount target=new Amount();
        require(!c.player.chooseTargetAmount(Outcome.Damage,target,c.ability,c.world.game)
                && target.prepared==1,"unbound inherited target-amount behavior changed");cases++;
        List<MultiAmountMessage> messages=Arrays.asList(new MultiAmountMessage("a",0,3),new MultiAmountMessage("b",0,3));
        for(Outcome outcome:new Outcome[]{Outcome.Benefit,Outcome.Detriment}) {
            List<Integer> expected=outcome.isGood()?Arrays.asList(2,2):Arrays.asList(0,0);
            require(amounts(c.player,c.world.game,outcome,messages).equals(expected),
                    "unbound inherited distribution policy changed");cases++;
        }
        Game simulation=c.simulation(c.world.game);c.player.admitOriginalSimulation(c.world.game,simulation);
        OriginalCallbackPlayer child=(OriginalCallbackPlayer)simulation.getPlayer(c.player.getId());
        require(amounts(child,simulation,Outcome.Benefit,messages).equals(Arrays.asList(2,2)),
                "admitted simulation lost the original inherited distribution");cases++;
        require(c.backend.calls==0 && c.backend.copies==0 && !c.backend.closed,
                "inherited distribution consumed policy/copy draws or closed its admitted session");c.registry.close();
        for(boolean divided:new boolean[]{false,true}) {
            MaintainerDialogReplayCheck.Case foreign=new MaintainerDialogReplayCheck.Case();Amount a=new Amount();Messages m=new Messages();
            OriginalCallbackPlayer unadmitted=foreign.player.copy();
            refused(()->{
                if(divided)unadmitted.chooseTargetAmount(Outcome.Damage,a,foreign.ability,foreign.world.game);
                else amounts(unadmitted,foreign.world.game,Outcome.Benefit,m);
            });
            require(a.prepared==0 && m.reads==0 && foreign.backend.calls==0 && foreign.backend.closed,
                    "foreign distribution read its arguments or retained the shared session");foreign.registry.close();cases++;
        }
        System.out.println("MaintainerUnconnectedDistributionCheck PASS: "+cases+" metadata cases; unsupported replay refused before inherited work; original unbound/copy policy preserved");
    }
}
