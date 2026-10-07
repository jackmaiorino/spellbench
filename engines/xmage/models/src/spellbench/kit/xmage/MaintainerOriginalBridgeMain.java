package spellbench.kit.xmage;

import mage.player.cabt.CardResolver;
import mage.player.spellbench.Warmup;
import spellbench.kit.core.Json;
import spellbench.kit.core.Seeds;

import java.io.*;
import java.lang.reflect.InvocationTargetException;
import java.util.*;

/** Borrowed original-player pipe. Launch only inside the caller's guarded native job. */
public final class MaintainerOriginalBridgeMain {
    static final String SCHEMA="spellbench-maintainer-original-serving/v1";
    /** Callback worlds start at their saved priority, before activation mutates the engine. */
    static Map<String,Object> reconstructionDecision(Map<String,Object> request) {
        Map<String,Object> current=Json.obj(request,"decision");
        if(request.get("anchor")!=null && "priority".equals(Json.str(Json.obj(current,"context"),"kind"))) {
            Map<String,Object> root=Json.obj(Json.obj(request,"anchor"),"decision");
            if(root==null || MaintainerRootDecision.mode(root)!=WorldBuilder.Mode.PRIORITY
                    || !Json.str(current,"acting_seat").equals(Json.str(root,"acting_seat")))
                throw new IllegalArgumentException("original continuation needs its own saved priority root");
            return root;
        }
        try {MaintainerRootDecision.mode(current);return current;}
        catch(IllegalArgumentException unsupported) {
            Map<String,Object> anchor=Json.obj(request,"anchor"),root=Json.obj(anchor,"decision");
            if(root==null || MaintainerRootDecision.mode(root)!=WorldBuilder.Mode.PRIORITY)
                throw new IllegalArgumentException("original callback needs its saved priority decision",unsupported);
            if(!Json.str(current,"acting_seat").equals(Json.str(root,"acting_seat")))
                throw new IllegalArgumentException("original callback anchor belongs to another actor");
            return root;
        }
    }
    static Map<String,Object> choose(World world,Map<String,Object> request) throws Exception {
        Map<String,Object> current=Json.obj(request,"decision");
        if(reconstructionDecision(request)==current) return MaintainerRootDecision.choose(world,Json.obj(request,"game_start"),current);
        // Reduced encoder-only builds omit the optional callback/search layer.
        // A guarded complete-player launch must supply it; absence never substitutes a policy.
        try {
            Class<?> replay=Class.forName("spellbench.kit.xmage.MaintainerDialogReplay");
            Object controller=replay.getConstructor(World.class,Map.class).newInstance(world,request);
            @SuppressWarnings("unchecked") Map<String,Object> result=(Map<String,Object>)replay.getMethod("choose").invoke(controller);
            return result;
        } catch(InvocationTargetException failure) {
            Throwable cause=failure.getCause();if(cause instanceof Error) throw (Error)cause;
            if(cause instanceof RuntimeException) throw (RuntimeException)cause;throw failure;
        }
    }
    public static void main(String[] args) throws Exception {
        if(args.length!=4) throw new IllegalArgumentException("profile, game seed, game-start digest and idle seconds required");
        String profile=args[0],digest=args[2]; long seed=Long.parseLong(args[1]); double idle=Double.parseDouble(args[3]);
        if(!("maintainer-april-eval-greedy-fair-v1".equals(profile) || "maintainer-april-no-training-sampled-fair-v1".equals(profile))
                || seed<0 || seed>9007199254740991L || !digest.matches("[a-f0-9]{64}") || !Double.isFinite(idle) || idle<=0)
            throw new IllegalArgumentException("invalid original serving identity or idle clock");
        PrintStream out=new PrintStream(new FileOutputStream(FileDescriptor.out),true,"UTF-8"); System.setOut(System.err);
        Runner.quietLogs();KitRandom.installBoot();Warmup.framework();new CardResolver().resolve("Plains");
        MaintainerInferenceChannel channel=new MaintainerInferenceChannel(System.in,out,profile,seed,digest);
        final long[] deadline={0};
        Object session=channel.session(()->(deadline[0]-System.nanoTime())/1e9);
        MaintainerPermittedWorlds registry=new MaintainerPermittedWorlds(session);
        out.println(Json.canonical(Json.map("schema",SCHEMA,"ready",true,"callback_sha256",MaintainerInferenceChannel.CALLBACK,
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
                    if(!digest.equals(MaintainerPriorityBinding.hash(start)) || Json.num(start,"agent_seed",-1L)!=seed)
                        throw new IllegalArgumentException("original serving command belongs to another game");
                    for(String key:Arrays.asList("world_seed","id_seed")) {
                        String value=Json.str(request,key);
                        if(value==null || !value.matches("[a-f0-9]{64}")) throw new IllegalArgumentException("original reconstruction seed required");
                    }
                    long before=channel.requestCount(); KitContext.reset();KitRandom.installBoot();
                    KitRandom random=KitRandom.install(Seeds.unhex(Json.str(request,"world_seed")),Seeds.unhex(Json.str(request,"id_seed")));
                    Map<String,Object> root=reconstructionDecision(request);
                    world=registry.buildReplay(start,root,request,random,MaintainerRootDecision.mode(root),0);
                    Map<String,Object> result=choose(world,request);
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
