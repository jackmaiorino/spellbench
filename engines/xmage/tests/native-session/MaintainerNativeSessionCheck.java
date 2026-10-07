package spellbench.kit.xmage;

import mage.cards.Card;
import mage.constants.Zone;
import mage.game.Game;
import mage.game.GameState;
import spellbench.kit.core.Json;
import spellbench.models.maintainer.OriginalCallbackPlayer;
import spellbench.models.maintainer.OriginalNeuralSelection;

import java.io.*;
import java.lang.reflect.Proxy;
import java.util.*;
import static spellbench.kit.xmage.MaintainerPlayerBootstrapCheck.*;

/** One real borrowed pipe with actual original root/copy callbacks; metadata only. */
public final class MaintainerNativeSessionCheck {
    static final String SCHEMA="spellbench-maintainer-original-serving/v1";
    public static void main(String[] args) throws Exception {
        if(args.length!=2) throw new IllegalArgumentException("game-start digest and metadata fixture mode required");
        PrintStream out=new PrintStream(new FileOutputStream(FileDescriptor.out),true,"UTF-8");
        System.setOut(System.err);
        String profile=OriginalNeuralSelection.GREEDY; long seed=31;
        MaintainerInferenceChannel channel=new MaintainerInferenceChannel(System.in,out,profile,seed,args[0]);
        final long[] deadline={0};
        OriginalNeuralSelection.Session shared=(OriginalNeuralSelection.Session)channel.session(
                ()->(deadline[0]-System.nanoTime())/1e9);
        MaintainerPermittedWorlds registry=new MaintainerPermittedWorlds(shared);
        out.println(Json.canonical(Json.map("schema",SCHEMA,"ready",true,
                "callback_sha256",MaintainerInferenceChannel.CALLBACK,"profile",profile,"seed",seed,
                "game_start_sha256",args[0],"operations",Arrays.asList("decide"))));
        try {
        for(int iteration=0;iteration<("two".equals(args[1])?2:1);iteration++) {
        Map<String,Object> request=channel.receive(5);
        require(SCHEMA.equals(request.get("schema")) && "decide".equals(request.get("operation")),"wrong fixture command");
        if("stalled".equals(args[1])) { Thread.sleep(30000); return; }
        require("normal".equals(args[1]) || "two".equals(args[1]),"unknown fixture mode");
        double seconds=((Number)request.get("remaining_s")).doubleValue();
        deadline[0]=System.nanoTime()+(long)Math.ceil(seconds*1e9);
        long before=channel.requestCount();
        Root root=new Root(); MaintainerPlayerBootstrap.replaceViewer(root.world,2);
        OriginalCallbackPlayer player=(OriginalCallbackPlayer)root.world.viewerPlayer();
        MaintainerPermittedWorlds.Projection projection=game->{
            Map<UUID,Map<String,Object>> records=new LinkedHashMap<>();
            for(UUID id:game.getPlayer(player.getId()).getHand()) records.put(id,
                    Json.map("object_id","metadata-"+id,"card_name",root.cards.get(id).getName(),"zone","hand"));
            for(UUID id:game.getPlayer(player.getId()).getGraveyard()) records.put(id,
                    Json.map("object_id","metadata-"+id,"card_name",root.cards.get(id).getName(),"zone","graveyard"));
            return records;
        };
        Map<UUID,String> aliases=new LinkedHashMap<>();
        for(UUID id:projection.view(root.game).keySet()) aliases.put(id,"metadata-"+id);
        registry.register(root.world,aliases,projection);
            Map<String,Object> result=MaintainerRootDecision.choose(root.world,Json.obj(request,"game_start"),Json.obj(request,"decision"));
            require(Boolean.TRUE.equals(Json.obj(Json.obj(result,"selection"),"semantic_echo").get("keep")),"actual root Q tie changed");
            int physical=shared.physicalCopy(3); require(physical>=0 && physical<3,"physical-copy draw escaped group");
            GameState state=root.state.copy();
            Game copied=(Game)Proxy.newProxyInstance(Game.class.getClassLoader(),new Class<?>[]{Game.class},(o,m,a)->{
                switch(m.getName()) {
                    case "getPlayer": return state.getPlayers().get(a[0]);
                    case "getPlayers": return state.getPlayers();
                    case "getState": return state;
                    case "getCard": case "getObject": return root.cards.get(a[0]);
                    case "getPermanent": return null;
                    case "isSimulation": return true;
                    case "getId": return root.game.getId();
                    case "getZone": return state.getZone((UUID)a[0]);
                    default: throw new AssertionError("unexpected metadata copy read: "+m.getName());
                }
            });
            player.admitOriginalSimulation(root.game,copied);
            OriginalCallbackPlayer child=(OriginalCallbackPlayer)copied.getPlayer(player.getId());
            Card changed=new MetadataCard(player.getId(),"Island"); root.cards.put(changed.getId(),changed);
            child.getHand().add(changed); state.setZone(changed.getId(),Zone.HAND);
            require(!child.chooseMulligan(copied),"actual admitted copy did not share Q-tie inference");
            result.put("inference_requests",channel.requestCount()-before);
            result.put("metadata_original_root_copy_passed",true);result.put("physical_copy_index",(long)physical);
            registry.retire(root.world);
            out.println(Json.canonical(Json.map("schema",SCHEMA,"id",request.get("id"),"operation","decide",
                    "event","result","ok",true,"result",result)));
        }
        // The supervisor owns shutdown after this bounded fixture.
        while(System.in.read()!=-1) throw new IllegalArgumentException("metadata fixture request count exceeded");
        } finally {registry.close();channel.close();}
    }
}
