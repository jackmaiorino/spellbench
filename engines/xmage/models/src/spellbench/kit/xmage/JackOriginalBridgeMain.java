package spellbench.kit.xmage;

import mage.player.cabt.CardResolver;
import mage.player.spellbench.Warmup;
import spellbench.kit.core.Json;
import spellbench.kit.core.Seeds;

import java.io.*;
import java.util.*;

/** Borrowed original-player pipe. Launch only inside the caller's guarded native job. */
public final class JackOriginalBridgeMain {
    static final String SCHEMA="spellbench-jack-original-serving/v1";
    public static void main(String[] args) throws Exception {
        if(args.length!=4) throw new IllegalArgumentException("profile, game seed, game-start digest and idle seconds required");
        String profile=args[0],digest=args[2]; long seed=Long.parseLong(args[1]); double idle=Double.parseDouble(args[3]);
        if(!("jack-april-eval-greedy-fair-v1".equals(profile) || "jack-april-no-training-sampled-fair-v1".equals(profile))
                || seed<0 || seed>9007199254740991L || !digest.matches("[a-f0-9]{64}") || !Double.isFinite(idle) || idle<=0)
            throw new IllegalArgumentException("invalid original serving identity or idle clock");
        PrintStream out=new PrintStream(new FileOutputStream(FileDescriptor.out),true,"UTF-8"); System.setOut(System.err);
        Runner.quietLogs();KitRandom.installBoot();Warmup.framework();new CardResolver().resolve("Plains");
        JackInferenceChannel channel=new JackInferenceChannel(System.in,out,profile,seed,digest);
        final long[] deadline={0};
        Object session=channel.session(()->(deadline[0]-System.nanoTime())/1e9);
        JackPermittedWorlds registry=new JackPermittedWorlds(session);
        out.println(Json.canonical(Json.map("schema",SCHEMA,"ready",true,"callback_sha256",JackInferenceChannel.CALLBACK,
                "profile",profile,"seed",seed,"game_start_sha256",digest,"operations",Arrays.asList("decide"))));
        long last=0;
        try {
            while(true) {
                Map<String,Object> request=channel.receive(idle); World world=null;
                try {
                    String id=Json.str(request,"id");
                    if(!SCHEMA.equals(request.get("schema")) || !"decide".equals(request.get("operation"))
                            || id==null || !id.matches("[1-9][0-9]*") || Long.parseLong(id)<=last)
                        throw new IllegalArgumentException("stale or unsupported original serving command");
                    last=Long.parseLong(id);
                    Object seconds=request.get("remaining_s");
                    if(!(seconds instanceof Number) || !Double.isFinite(((Number)seconds).doubleValue())
                            || ((Number)seconds).doubleValue()<=0 || ((Number)seconds).doubleValue()>86400)
                        throw new IllegalArgumentException("bounded original decision clock required");
                    deadline[0]=System.nanoTime()+(long)Math.ceil(((Number)seconds).doubleValue()*1e9);
                    Map<String,Object> start=Json.obj(request,"game_start"),decision=Json.obj(request,"decision");
                    if(!digest.equals(JackPriorityBinding.hash(start)) || Json.num(start,"agent_seed",-1L)!=seed)
                        throw new IllegalArgumentException("original serving command belongs to another game");
                    for(String key:Arrays.asList("world_seed","id_seed")) {
                        String value=Json.str(request,key);
                        if(value==null || !value.matches("[a-f0-9]{64}")) throw new IllegalArgumentException("original reconstruction seed required");
                    }
                    long before=channel.requestCount(); KitContext.reset();KitRandom.installBoot();
                    KitRandom random=KitRandom.install(Seeds.unhex(Json.str(request,"world_seed")),Seeds.unhex(Json.str(request,"id_seed")));
                    world=registry.build(start,decision,random,JackRootDecision.mode(decision),0);
                    Map<String,Object> result=JackRootDecision.choose(world,start,decision);
                    result.put("inference_requests",channel.requestCount()-before);
                    registry.retire(world);world=null;
                    out.println(Json.canonical(Json.map("schema",SCHEMA,"id",id,"operation","decide",
                            "event","result","ok",true,"result",result)));
                    if(out.checkError()) throw new IOException("original serving result pipe failed");
                } catch(Throwable failure) {
                    registry.close();
                    world=null;
                    out.println(Json.canonical(Json.map("schema",SCHEMA,"id",request.get("id"),"operation","decide",
                            "event","result","ok",false,"result",Json.map("error",failure.toString()))));
                    if(failure instanceof Error) throw (Error)failure;
                    break;
                } finally {
                    if(world!=null) registry.retire(world);
                    deadline[0]=0;
                }
            }
        } finally {try {registry.close();} finally {channel.close();}}
    }
}
