package spellbench.kit.xmage;

import mage.cards.Card;
import mage.constants.Zone;
import mage.game.Game;
import mage.game.GameState;
import spellbench.kit.core.Json;
import spellbench.models.jack.OriginalCallbackPlayer;
import spellbench.models.jack.OriginalNeuralSelection;

import java.io.*;
import java.lang.reflect.Proxy;
import java.nio.charset.StandardCharsets;
import java.util.*;
import static spellbench.kit.xmage.JackPlayerBootstrapCheck.*;

/** One real borrowed pipe with actual original root/copy callbacks; metadata only. */
public final class JackNativeSessionCheck {
    static final String SCHEMA="spellbench-jack-original-serving/v1";
    // Before the channel owns stdin, read exactly this command without read-ahead.
    private static Map<String,Object> command() throws Exception {
        ByteArrayOutputStream row=new ByteArrayOutputStream(); int next;
        while((next=System.in.read())!=-1 && next!='\n') {
            if(row.size()>=8*1024*1024) throw new IllegalArgumentException("fixture command exceeds private bound");
            row.write(next);
        }
        if(next==-1) throw new EOFException("fixture command missing");
        return Json.parseObject(new String(row.toByteArray(),StandardCharsets.UTF_8));
    }
    public static void main(String[] args) throws Exception {
        if(args.length!=2) throw new IllegalArgumentException("game-start digest and metadata fixture mode required");
        PrintStream out=new PrintStream(new FileOutputStream(FileDescriptor.out),true,"UTF-8");
        System.setOut(System.err);
        String profile=OriginalNeuralSelection.GREEDY; long seed=31;
        out.println(Json.canonical(Json.map("schema",SCHEMA,"ready",true,
                "callback_sha256",JackInferenceChannel.CALLBACK,"profile",profile,"seed",seed,
                "game_start_sha256",args[0],"operations",Arrays.asList("decide"))));
        Map<String,Object> request=command();
        require(SCHEMA.equals(request.get("schema")) && "decide".equals(request.get("operation")),"wrong fixture command");
        if("stalled".equals(args[1])) { Thread.sleep(30000); return; }
        require("normal".equals(args[1]),"unknown fixture mode");
        long started=System.nanoTime(); double seconds=((Number)request.get("remaining_s")).doubleValue();
        JackInferenceChannel channel=new JackInferenceChannel(System.in,out,profile,seed,args[0]);
        OriginalNeuralSelection.Session shared=(OriginalNeuralSelection.Session)channel.session(
                ()->seconds-(System.nanoTime()-started)/1e9);
        JackPermittedWorlds registry=new JackPermittedWorlds(shared);
        Root root=new Root(); JackPlayerBootstrap.replaceViewer(root.world,2);
        OriginalCallbackPlayer player=(OriginalCallbackPlayer)root.world.viewerPlayer();
        JackPermittedWorlds.Projection projection=game->{
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
        try {
            boolean keep=!player.chooseMulligan(root.game);
            require(keep,"actual root Q tie changed");
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
            Map<String,Object> decision=Json.obj(request,"decision"),selection=null;
            for(Object item:Json.arr(decision,"candidates")) {
                Map<String,Object> candidate=Json.obj(item),semantic=Json.obj(candidate,"semantic");
                if("mulligan".equals(semantic.get("kind")) && Boolean.valueOf(keep).equals(semantic.get("keep")))
                    selection=Json.map("candidate_id",candidate.get("candidate_id"),"semantic_echo",Json.copy(semantic));
            }
            require(selection!=null,"fixture root choice was not offered");
            out.println(Json.canonical(Json.map("schema",SCHEMA,"id",request.get("id"),"operation","decide",
                    "event","result","ok",true,"result",Json.map("selection",selection,
                        "decision_sha256",JackModeEncoder.hash(decision),"game_start_sha256",args[0],
                        "profile",profile,"seed",seed,"inference_requests",3L,"world_flags",new ArrayList<>(),
                        "full_original_player_qualified",false,"metadata_original_root_copy_passed",true,
                        "physical_copy_index",(long)physical))));
            // The supervisor owns shutdown. No second input reader runs beside the channel.
            while(System.in.read()!=-1) throw new IllegalArgumentException("one-decision metadata fixture only");
        } finally { registry.close(); }
    }
}
