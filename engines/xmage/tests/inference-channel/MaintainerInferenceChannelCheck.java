package spellbench.models.maintainer;

import spellbench.kit.xmage.MaintainerInferenceChannel;
import spellbench.kit.core.Json;
import mage.cards.Card;
import mage.constants.Outcome;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import static spellbench.models.maintainer.MaintainerActivationPlayerCheck.require;
import static spellbench.models.maintainer.MaintainerNeuralSelectionCheck.refused;

/** Real original callbacks through the private pipe. Parent owns synthetic paired inference. */
public final class MaintainerInferenceChannelCheck {
    public static void main(String[] args) throws Exception {
        if(args.length!=1) throw new IllegalArgumentException("game-start SHA256 required");
        PrintStream out=new PrintStream(new FileOutputStream(FileDescriptor.out),true,"UTF-8");
        MaintainerInferenceChannel channel=new MaintainerInferenceChannel(System.in,out,OriginalNeuralSelection.GREEDY,31,args[0]);
        final double[] allowance={5};
        OriginalNeuralSelection.Session shared=(OriginalNeuralSelection.Session)channel.session(()->allowance[0]);
        MaintainerCallbackPlayerCheck.World world=new MaintainerCallbackPlayerCheck.World();
        world.player.bindOriginalWorld(world.game,world.aliases,shared,world.admission());
        require(!world.player.chooseUse(Outcome.Benefit,"pipe?",null,world.game),"actual callback pipe changed Yes/No choice");
        require(world.player.announceX(0,3,"X",world.game,null,false)==3,"actual X pipe changed candidate order");
        Card card=world.card("Forest");world.player.getHand().add(card);
        require(!world.player.chooseMulligan(world.game),"actual Q tie changed through pipe");
        require(shared.physicalCopy(3)>=0,"physical-copy pipe failed");
        MaintainerCallbackPlayerCheck.World child=new MaintainerCallbackPlayerCheck.World(world.player.copy());child.simulation=true;
        world.player.admitOriginalSimulation(world.game,child.game);
        require(!child.player.chooseUse(Outcome.Benefit,"copy pipe?",null,child.game),"copy did not share actual pipe");
        allowance[0]=0.05;
        long pipeStarted=System.nanoTime();
        refused(()->child.player.chooseUse(Outcome.Benefit,"parent withholds response",null,child.game));
        require((System.nanoTime()-pipeStarted)/1e9<2,"actual stdin pipe timeout failed to release blocked reader");
        shared.close();
        // A stale owner response must close its actual shared session.
        ByteArrayInputStream stale=new ByteArrayInputStream(("{\"id\":9}\n").getBytes(StandardCharsets.UTF_8));
        ByteArrayOutputStream events=new ByteArrayOutputStream();
        MaintainerInferenceChannel failed=new MaintainerInferenceChannel(stale,new PrintStream(events,true,"UTF-8"),OriginalNeuralSelection.GREEDY,31,args[0]);
        OriginalNeuralSelection.Session broken=(OriginalNeuralSelection.Session)failed.session(()->5);
        MaintainerCallbackPlayerCheck.World bad=new MaintainerCallbackPlayerCheck.World();
        bad.player.bindOriginalWorld(bad.game,bad.aliases,broken,bad.admission());
        refused(()->bad.player.chooseUse(Outcome.Benefit,"stale?",null,bad.game));
        refused(()->broken.physicalCopy(2));
        require(events.toString("UTF-8").contains("\"operation\":\"close\""),"stale response did not close owned transport");
        InputStream stalled=new InputStream() {
            private boolean closed;
            @Override public synchronized int read() throws IOException {
                while(!closed) try {wait();} catch(InterruptedException interrupted) {throw new InterruptedIOException("cancelled read");}
                return -1;
            }
            @Override public synchronized void close() {closed=true;notifyAll();}
        };
        MaintainerInferenceChannel timeout=new MaintainerInferenceChannel(stalled,new PrintStream(new ByteArrayOutputStream()),OriginalNeuralSelection.GREEDY,31,args[0]);
        OriginalNeuralSelection.Session timed=(OriginalNeuralSelection.Session)timeout.session(()->0.02);
        MaintainerCallbackPlayerCheck.World slow=new MaintainerCallbackPlayerCheck.World();
        slow.player.bindOriginalWorld(slow.game,slow.aliases,timed,slow.admission());
        long started=System.nanoTime();
        refused(()->slow.player.chooseUse(Outcome.Benefit,"timeout?",null,slow.game));
        require((System.nanoTime()-started)/1e9<2,"owned inference timeout failed to release blocked read");
        out.println(Json.canonical(Json.map("check","PASS MaintainerInferenceChannelCheck","native_started",false)));
    }
}
