package spellbench.models.magezero.v02.search;

/** Architecture and failure boundaries without a checkpoint or game. */
public final class TransportCheck {
    private static int checks;
    private static void require(boolean value) {
        if (!value) throw new IllegalStateException("MageZero transport contract differs");
        checks++;
    }
    private static void refuses(Runnable operation) {
        try { operation.run(); }
        catch (IllegalArgumentException expected) { checks++; return; }
        throw new IllegalStateException("wrong architecture or feature input was accepted");
    }
    private static RemoteModelEvaluator.InferenceResult result(float[] player, float value) {
        return new RemoteModelEvaluator.InferenceResult(player, new float[128], new float[128], new float[2], value);
    }
    public static void main(String[] args) {
        refuses(() -> result(new float[1024], 0));
        refuses(() -> result(new float[127], 0));
        refuses(() -> result(new float[128], Float.NaN));
        float[] invalid = new float[128];
        invalid[17] = Float.POSITIVE_INFINITY;
        refuses(() -> result(invalid, 0));
        float[] original = new float[128];
        original[3] = 0.75f;
        RemoteModelEvaluator.InferenceResult copied = result(original, 0.5f);
        original[3] = 9;
        require(copied.policy_player[3] == 0.75f);
        int[] calls = {0};
        RemoteModelEvaluator transport = new RemoteModelEvaluator(features -> {
            calls[0]++;
            require(features.length == 2 && features[0] == 2000001 && features[1] == 2147483646L);
            features[0] = 0;
            return copied;
        });
        long[] features = {2000001, 2147483646L};
        require(transport.inferAsync(features).join() == copied);
        require(features[0] == 2000001 && calls[0] == 1);
        refuses(() -> transport.inferAsync(new long[]{2147483647L}));
        refuses(() -> transport.inferAsync(new long[]{-1}));
        refuses(() -> transport.inferAsync(new long[0]));
        require(calls[0] == 1);
        IllegalStateException failure = new IllegalStateException("retained transport failure");
        RemoteModelEvaluator failing = new RemoteModelEvaluator(input -> { throw failure; });
        try { failing.inferAsync(new long[]{1}); }
        catch (IllegalStateException actual) {
            require(actual == failure);
            System.out.println("{\"passed\":true,\"checks\":" + checks
                    + ",\"scope\":\"MageZero architecture and transport only; no weights, search or game qualification\"}");
            return;
        }
        throw new IllegalStateException("neural failure did not reach the caller");
    }
}
