package spellbench.models.exp1;

import java.util.concurrent.CompletableFuture;

/** Private synchronous neural transport with Exp1's original result shape. */
public final class RemoteModelEvaluator {
    public interface Transport {
        InferenceResult infer(long[] features);
    }
    public static final class InferenceResult {
        public final float[] policy_player, policy_opponent, policy_target, policy_binary;
        public final float value;
        public InferenceResult(float[] player, float[] opponent, float[] target, float[] binary, float value) {
            check(player, 1024); check(opponent, 1024); check(target, 1024); check(binary, 2);
            if (!Float.isFinite(value)) throw new IllegalArgumentException("nonfinite neural value");
            policy_player = player.clone(); policy_opponent = opponent.clone();
            policy_target = target.clone(); policy_binary = binary.clone(); this.value = value;
        }
        private static void check(float[] values, int width) {
            if (values == null || values.length != width) throw new IllegalArgumentException("wrong neural head width");
            for (float value : values) if (!Float.isFinite(value)) throw new IllegalArgumentException("nonfinite neural logit");
        }
    }
    private final Transport transport;
    public RemoteModelEvaluator(Transport transport) {
        if (transport == null) throw new IllegalArgumentException("missing neural transport");
        this.transport = transport;
    }
    public CompletableFuture<InferenceResult> inferAsync(long[] features) {
        if (features == null || features.length == 0 || features.length > 16384) throw new IllegalArgumentException("feature envelope");
        for (long feature : features) if (feature < 0 || feature >= 2000000) throw new IllegalArgumentException("feature vocabulary");
        // Complete on the search thread. A failed transport throws immediately.
        return CompletableFuture.completedFuture(transport.infer(features.clone()));
    }
}
