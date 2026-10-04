"""Connect the original generic chooser to cached features and paired inference."""
from __future__ import annotations

import hashlib

from xmage_jack_sources import CALLBACK_SHA256, extract, replace_once

NEURAL_VARIANT = (
    "original generic candidate prefix, pick bounds, features and head routing; "
    "shared paired inference and original seeded chooser across admitted copies; "
    "no training or model-error fallback; persistent player and native games unfinished")


def neural_selection_source(source: str) -> str:
    if hashlib.sha256(source.encode()).hexdigest() != CALLBACK_SHA256:
        raise ValueError("Jack neural selection requires the pinned April callback bytes")
    method = extract(source, "    public <T> List<Integer> genericChoose(",
                     "    private <T> void logCandidateExplosionDebug(")
    # Keep the actual prefix, count, clamps, singleton/empty shortcuts and tensors.
    prefix = extract(method, "        final int maxCandidates =", "        StateSequenceBuilder.SequenceOutput baseState =")
    logging = extract(prefix, "        if (candidates.size() > maxCandidates)",
                      "        // Prevent infinite loops")
    prefix = replace_once(prefix, logging, "")
    tensors = extract(method, "        // Build padded candidate tensors", "        // Get model predictions")
    tensors = tensors.replace("        long prepStartNanos = System.nanoTime();\n", "")
    tensors = tensors.replace("computeCandidateActionId(actionType, game, source, cand)",
                              "encoder.candidateId(actionType.name(), game, source, cand)")
    tensors = tensors.replace("computeCandidateFeatures(actionType, game, source, cand, candFeatDim, baseState)",
                              "encoder.candidateFeatures(actionType.name(), game, source, cand, baseState)")
    return '''package spellbench.models.jack;

import mage.abilities.Ability;
import mage.game.Game;
import mage.players.Player;
import java.util.*;
import java.util.function.DoubleSupplier;

/** Private original generic chooser connected to one owned model/RNG session. */
public final class OriginalNeuralSelection {
    public static final String SOURCE_SHA256 = "%s";
    public static final String VARIANT = "%s";
    public static final String GREEDY = "jack-april-eval-greedy-fair-v1";
    public static final String SAMPLED = "jack-april-no-training-sampled-fair-v1";

    public interface Admission { void require(Game game, Player viewer); }
    /** Implement with the isolated paired policy/value backend, never a baseline. */
    public interface Model {
        String callbackSourceSha256();
        String profile();
        long seed();
        Prediction score(Request request, double remainingSeconds);
        void close();
    }
    public static final class Prediction {
        public final float[] policy;
        public final float value;
        public Prediction(float[] policy, float value) {
            this.policy = policy == null ? null : policy.clone(); this.value = value;
        }
    }
    /** Model receives copies, so a backend cannot mutate cached state or choice masks. */
    public static final class Request {
        private final float[][] tokens, features;
        private final int[] tokenMask, tokenIds, actionIds, candidateMask;
        public final String head;
        public final int pickIndex = 0, minimum, maximum, count;
        private Request(StateSequenceBuilder.SequenceOutput state, int[] actionIds,
                float[][] features, int[] mask, String head, int minimum, int maximum, int count) {
            this.tokens = copy(state.tokens); this.tokenMask = state.mask.clone();
            this.tokenIds = state.tokenIds.clone(); this.actionIds = actionIds.clone();
            this.features = copy(features); this.candidateMask = mask.clone();
            this.head = head; this.minimum = minimum; this.maximum = maximum; this.count = count;
        }
        private static float[][] copy(float[][] source) {
            float[][] result = new float[source.length][];
            for (int i = 0; i < result.length; i++) result[i] = source[i].clone();
            return result;
        }
        public float[][] tokens() { return copy(tokens); }
        public float[][] features() { return copy(features); }
        public int[] tokenMask() { return tokenMask.clone(); }
        public int[] tokenIds() { return tokenIds.clone(); }
        public int[] actionIds() { return actionIds.clone(); }
        public int[] candidateMask() { return candidateMask.clone(); }
    }
    /** Shared by original-player copies; seeded stream is an explicit fair variant. */
    public static final class Session implements AutoCloseable {
        private final Model model;
        private final PolicySelector selector;
        private final DoubleSupplier remainingSeconds;
        private boolean closed;
        private float lastValue;
        public Session(Model model, String profile, long seed, DoubleSupplier remainingSeconds) {
            if (model == null || remainingSeconds == null || !SOURCE_SHA256.equals(model.callbackSourceSha256())
                    || !(GREEDY.equals(profile) || SAMPLED.equals(profile))
                    || !profile.equals(model.profile()) || seed != model.seed())
                throw new IllegalArgumentException("paired original model, profile and game seed must match");
            this.model = model; this.selector = new PolicySelector(GREEDY.equals(profile), seed);
            this.remainingSeconds = remainingSeconds;
        }
        private synchronized void requireOpen() {
            if (closed) throw new IllegalArgumentException("original neural session is closed");
        }
        private double remaining() {
            requireOpen(); double value = remainingSeconds.getAsDouble();
            if (!Double.isFinite(value) || value <= 0)
                throw new IllegalArgumentException("original neural decision deadline exceeded");
            return value;
        }
        private synchronized List<Integer> choose(StateSequenceBuilder.SequenceOutput state,
                int[] ids, float[][] features, int[] mask, String head,
                int minimum, int maximum, int count, int picks, boolean sequential) {
            try {
                double allowance = remaining();
                int valid = 0; for (int i = 0; i < count; i++) valid += mask[i];
                Prediction prediction;
                // Actual scoreCandidatesWithMetrics bypasses inference for <=1 legal slot.
                if (valid <= 1) {
                    float[] policy = new float[64];
                    for (int i = 0; i < count; i++) policy[i] = mask[i] != 0 ? 1.0f : 0.0f;
                    prediction = new Prediction(policy, 0.0f);
                } else {
                    prediction = model.score(new Request(state, ids, features, mask, head,
                            minimum, maximum, count), allowance);
                }
                remaining();
                if (prediction == null || prediction.policy == null || prediction.policy.length != 64
                        || !Float.isFinite(prediction.value))
                    throw new IllegalArgumentException("paired original prediction has invalid shape/value");
                for (float probability : prediction.policy)
                    if (!Float.isFinite(probability) || probability < 0 || probability > 1)
                        throw new IllegalArgumentException("paired original prediction has invalid probability");
                lastValue = prediction.value;
                // The original zero-pick path scores, normalizes and consumes no RNG.
                if (picks == 0) return Collections.emptyList();
                int[] selected = selector.choose(prediction.policy, mask, count, picks, sequential);
                remaining();
                List<Integer> result = new ArrayList<>(); for (int index : selected) result.add(index);
                return Collections.unmodifiableList(result);
            } catch (RuntimeException | Error failure) { closeAfterFailure(failure); throw failure; }
        }
        private synchronized void closeAfterFailure(Throwable failure) {
            if (closed) return; closed = true;
            try { model.close(); } catch (RuntimeException | Error closing) { failure.addSuppressed(closing); }
        }
        public synchronized float lastValue() { requireOpen(); return lastValue; }
        @Override public synchronized void close() { if (!closed) { closed = true; model.close(); } }
    }
    private final Player viewer;
    private final PriorityRules rules;
    private final CandidateEncoder encoder;
    private final Session session;
    private final Admission admission;
    public OriginalNeuralSelection(Player viewer, PriorityRules rules, Session session, Admission admission) {
        if (viewer == null || rules == null || rules.owner() != viewer || session == null || admission == null)
            throw new IllegalArgumentException("original neural path requires its owned cached rules and world admission");
        this.viewer = viewer; this.rules = rules; this.encoder = new CandidateEncoder(viewer);
        this.session = session; this.admission = admission;
    }
    public OriginalNeuralSelection forCopy(Player copiedViewer, PriorityRules copiedRules, Admission copiedAdmission) {
        return new OriginalNeuralSelection(copiedViewer, copiedRules, session, copiedAdmission);
    }
    public void requireWorld(Game game) { require(game); }
    private void require(Game game) {
        try {
            session.requireOpen();
            if (game == null || game.getPlayer(viewer.getId()) != viewer)
                throw new IllegalArgumentException("original neural path needs its owned player");
            admission.require(game, viewer);
            session.remaining();
        } catch (RuntimeException | Error failure) { session.closeAfterFailure(failure); throw failure; }
    }
    public <T> List<Integer> genericChoose(List<T> candidates, int maxTargets, int minTargets,
            StateSequenceBuilder.ActionType actionType, Game game, Ability source) {
        require(game);
        try {
            if (candidates == null || actionType == null || minTargets < 0 || maxTargets < minTargets)
                throw new IllegalArgumentException("invalid original generic callback");
''' % (CALLBACK_SHA256, NEURAL_VARIANT) + prefix + '''
        StateSequenceBuilder.SequenceOutput baseState = rules.baseState(game);
''' + tensors + '''
        return session.choose(baseState, candidateActionIds, candidateFeatures, candidateMask,
                CandidateEncoder.head(actionType.name()), minTargets, maxTargets,
                candidateCount, maxTargets, true);
        } catch (RuntimeException | Error failure) { session.closeAfterFailure(failure); throw failure; }
    }
}
'''
