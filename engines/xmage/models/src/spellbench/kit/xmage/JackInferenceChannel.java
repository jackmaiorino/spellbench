package spellbench.kit.xmage;

import spellbench.kit.core.Json;
import java.io.*;
import java.lang.reflect.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.*;
import java.util.function.DoubleSupplier;

/** Original model API to one owned Python pair. No checkpoint executes in this JVM. */
public final class JackInferenceChannel implements AutoCloseable {
    public static final String SCHEMA="spellbench-jack-native-inference/v1";
    public static final String CALLBACK="b45257a66fc3914506fca4dd83461b6c8853d129b3e1f38b2d3aeba6137bd0c6";
    private final InputStream input;
    private final BufferedReader reader;
    private final PrintStream output;
    private final String profile, gameStartSha256;
    private final long seed;
    private long sequence;
    private boolean closed;
    private volatile boolean inputClosed;
    private volatile IOException inputCloseFailure;
    private final ExecutorService reads=Executors.newSingleThreadExecutor(r -> {
        Thread t=new Thread(r,"jack-owned-inference-read");t.setDaemon(true);return t;
    });
    public JackInferenceChannel(InputStream input,PrintStream output,String profile,long seed,String gameStartSha256) {
        if(input==null || output==null || seed<0 || gameStartSha256==null || !gameStartSha256.matches("[a-f0-9]{64}")
                || !("jack-april-eval-greedy-fair-v1".equals(profile) || "jack-april-no-training-sampled-fair-v1".equals(profile)))
            throw new IllegalArgumentException("original inference channel needs the owned game identity and profile");
        this.input=input;this.reader=new BufferedReader(new InputStreamReader(input,StandardCharsets.UTF_8));
        this.output=output;this.profile=profile;this.seed=seed;this.gameStartSha256=gameStartSha256;
    }
    private Map<String,Object> packet(String operation) {
        if(sequence==Long.MAX_VALUE) throw new IllegalArgumentException("original inference request sequence exhausted");
        return Json.map("schema",SCHEMA,"id",++sequence,"operation",operation,"callback_sha256",CALLBACK,
                "profile",profile,"seed",seed,"game_start_sha256",gameStartSha256);
    }
    private String readBounded() throws IOException {
        StringBuilder row=new StringBuilder();int ch;
        while((ch=reader.read())!=-1 && ch!='\n') {
            if(row.length()>=2*1024*1024) throw new IOException("original inference response exceeds private pipe bound");
            row.append((char)ch);
        }
        if(ch==-1 || row.length()==0) throw new EOFException("original inference owner closed its response pipe");
        return row.toString();
    }
    private synchronized Map<String,Object> exchange(String operation,Map<String,Object> payload,double seconds) {
        if(closed || !Double.isFinite(seconds) || seconds<=0)
            throw new IllegalArgumentException("original inference channel is closed or out of time");
        long started=System.nanoTime();Future<String> pending=null;
        try {
            Map<String,Object> request=packet(operation);request.putAll(payload);request.put("remaining_s",seconds);
            output.println(Json.canonical(request));output.flush();
            if(output.checkError()) throw new IOException("original inference request pipe failed");
            double left=seconds-(System.nanoTime()-started)/1e9;
            if(left<=0) throw new TimeoutException("original inference exhausted request write clock");
            pending=reads.submit(this::readBounded);
            Map<String,Object> response=Json.parseObject(pending.get(Math.max(1,(long)Math.ceil(left*1000)),TimeUnit.MILLISECONDS));
            if(!(response.get("id") instanceof Long) || ((Long)response.get("id"))!=sequence || response.containsKey("error"))
                throw new IllegalArgumentException("original inference response is stale or failed");
            if((System.nanoTime()-started)/1e9>=seconds) throw new TimeoutException("original inference exhausted response clock");
            return response;
        } catch(Exception failure) {
            if(pending!=null) pending.cancel(true);
            closeAfterFailure(failure);throw new IllegalArgumentException("owned original inference failed",failure);
        } catch(Error failure) {closeAfterFailure(failure);throw failure;}
    }
    private static Object get(Object object,String method) throws Exception { return object.getClass().getMethod(method).invoke(object); }
    private static List<Object> ints(int[] values) {
        List<Object> result=new ArrayList<>();for(int value:values) result.add((long)value);return result;
    }
    private static List<Object> mask(int[] values,boolean padding) {
        List<Object> result=new ArrayList<>();for(int value:values) {
            if(value!=0 && value!=1) throw new IllegalArgumentException("invalid original mask");
            result.add(padding?value==1:value!=0);
        }return result;
    }
    private static List<Object> floats(float[] values) {
        List<Object> result=new ArrayList<>();for(float value:values) {
            if(!Float.isFinite(value)) throw new IllegalArgumentException("non-finite original tensor");
            result.add((double)value);
        }return result;
    }
    private static List<Object> matrix(float[][] values) {
        List<Object> result=new ArrayList<>();for(float[] row:values) result.add(floats(row));return result;
    }
    private static float number(Object value) {
        if(!(value instanceof Number) || !Float.isFinite(((Number)value).floatValue()))
            throw new IllegalArgumentException("original inference returned a non-finite number");
        return ((Number)value).floatValue();
    }
    /** The private original interface is available only after its pinned source stage. */
    public Object model() throws Exception {
        Class<?> api=Class.forName("spellbench.models.jack.OriginalNeuralSelection$Model");
        return Proxy.newProxyInstance(api.getClassLoader(),new Class<?>[]{api},(proxy,method,args) -> {
            switch(method.getName()) {
                case "toString":return "owned original Jack inference";
                case "hashCode":return System.identityHashCode(proxy);
                case "equals":return proxy==args[0];
                case "callbackSourceSha256":return CALLBACK;
                case "profile":return profile;
                case "seed":return seed;
                case "close":close();return null;
                case "score": {
                    Object request=args[0];Class<?> type=request.getClass();
                    Map<String,Object> features=Json.map("kind","candidates","head",type.getField("head").get(request),
                        "sequence",matrix((float[][])get(request,"tokens")),"padding",mask((int[])get(request,"tokenMask"),true),
                        "token_ids",ints((int[])get(request,"tokenIds")),"candidate_features",matrix((float[][])get(request,"features")),
                        "candidate_ids",ints((int[])get(request,"actionIds")),"candidate_mask",mask((int[])get(request,"candidateMask"),false));
                    Map<String,Object> selection=Json.map("pick_index",type.getField("pickIndex").get(request),
                        "minimum",type.getField("minimum").get(request),"maximum",type.getField("maximum").get(request),"count",type.getField("count").get(request));
                    Map<String,Object> response=exchange("score",Json.map("features",features,"selection",selection),(Double)args[1]);
                    List<Object> probabilities=Json.arr(response,"probabilities");
                    if(probabilities==null || probabilities.size()!=64) throw new IllegalArgumentException("invalid original policy shape");
                    float[] scores=new float[64];for(int i=0;i<64;i++) scores[i]=number(probabilities.get(i));
                    return Class.forName("spellbench.models.jack.OriginalNeuralSelection$Prediction")
                            .getConstructor(float[].class,float.class).newInstance(scores,number(response.get("value")));
                }
                case "mulligan": {
                    Map<String,Object> response=exchange("mulligan",Json.map("features",Json.map("kind","mulligan",
                            "values",floats((float[])args[0]))),(Double)args[1]);
                    return Class.forName("spellbench.models.jack.OriginalNeuralSelection$MulliganPrediction")
                            .getConstructor(String.class,float.class,float.class).newInstance((String)response.get("format"),
                                    number(response.get("first")),number(response.get("second")));
                }
                case "physicalCopy": {
                    Map<String,Object> response=exchange("physical_copy",Json.map("count",args[0]),(Double)args[1]);
                    Object index=response.get("index");
                    if(!(index instanceof Long) || (Long)index<0 || (Long)index>Integer.MAX_VALUE)
                        throw new IllegalArgumentException("invalid original physical-copy index");
                    return ((Long)index).intValue();
                }
                default:throw new IllegalArgumentException("unsupported original model method: "+method.getName());
            }
        });
    }
    public Object session(DoubleSupplier remainingSeconds) throws Exception {
        Class<?> api=Class.forName("spellbench.models.jack.OriginalNeuralSelection$Model");
        return Class.forName("spellbench.models.jack.OriginalNeuralSelection$Session")
                .getConstructor(api,String.class,long.class,DoubleSupplier.class).newInstance(model(),profile,seed,remainingSeconds);
    }
    private void closeAfterFailure(Throwable failure) {
        try { close(); } catch(RuntimeException closing) { failure.addSuppressed(closing); }
    }
    public boolean inputCleanupComplete() { return inputClosed; }
    public String inputCleanupError() { return inputCloseFailure==null?null:inputCloseFailure.toString(); }
    @Override public synchronized void close() {
        if(closed)return;closed=true;
        try { output.println(Json.canonical(packet("close")));output.flush(); }
        finally {
            reads.shutdownNow();
            // System.in can hold its monitor during a blocked native pipe read on Windows.
            // Keep cleanup off the decision thread. The owning launcher must also release
            // the borrowed JVM peer, which ends blocked readers and closes its pipe handles.
            Thread closer=new Thread(() -> {
                try {input.close();inputClosed=true;} catch(IOException failure) {inputCloseFailure=failure;}
            },"jack-owned-inference-close");
            closer.setDaemon(true);closer.start();
        }
    }
}
