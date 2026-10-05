package spellbench.models.jack;

import spellbench.kit.core.Json;
import spellbench.kit.core.Seeds;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.security.MessageDigest;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** Explicit pinned inputs, with no environment lookup, network or file writes. */
public final class EmbeddingCache {
    private EmbeddingCache() { }
    private static final int WIDTH = 32;
    private static final long MAX_BYTES = 16L * 1024 * 1024;

    private static final class Loaded {
        static final Map<String, float[]> VALUES = load();
    }

    private static Map<String, float[]> load() {
        String filename = System.getProperty("spellbench.jack.embeddingFile");
        String expected = System.getProperty("spellbench.jack.embeddingSha256");
        if (filename == null || expected == null || !expected.matches("[a-f0-9]{64}")) {
            throw new IllegalArgumentException("Jack encoding requires an explicit hash-pinned embedding cache");
        }
        try {
            Path path = Paths.get(filename);
            long size = Files.size(path);
            if (size <= 0 || size > MAX_BYTES) throw new IllegalArgumentException("embedding cache exceeds its byte bound");
            byte[] raw = Files.readAllBytes(path);
            if (raw.length > MAX_BYTES || !expected.equals(Seeds.hex(MessageDigest.getInstance("SHA-256").digest(raw)))) {
                throw new IllegalArgumentException("embedding cache differs from its pin");
            }
            Map<String, Object> records = Json.parseObject(new String(raw, StandardCharsets.UTF_8));
            if (records.isEmpty() || records.size() > 32768) {
                throw new IllegalArgumentException("embedding cache exceeds its card bound");
            }
            Map<String, float[]> result = new LinkedHashMap<>();
            for (Map.Entry<String, Object> record : records.entrySet()) {
                String name = record.getKey();
                if (name.isEmpty() || !name.equals(name.trim()) || !(record.getValue() instanceof List)) {
                    throw new IllegalArgumentException("embedding cache has a malformed card entry");
                }
                List<?> values = (List<?>) record.getValue();
                if (values.size() != WIDTH) throw new IllegalArgumentException("embedding cache has a wrong-width vector");
                float[] vector = new float[WIDTH];
                for (int i = 0; i < WIDTH; i++) {
                    Object value = values.get(i);
                    if (!(value instanceof Number) || !Double.isFinite(((Number) value).doubleValue())
                            || Math.abs(((Number) value).doubleValue()) > 1000000) {
                        throw new IllegalArgumentException("embedding cache has a nonfinite or unbounded vector");
                    }
                    vector[i] = ((Number) value).floatValue();
                }
                result.put(name, vector);
            }
            return result;
        } catch (RuntimeException e) { throw e; }
        catch (Exception e) { throw new IllegalArgumentException("embedding cache could not be verified", e); }
    }

    public static float[] getEmbedding(String cardName) {
        String name = cardName == null ? "<unknown-card>" : cardName.trim();
        if (name.isEmpty()) name = "<empty-card-name>";
        float[] value = Loaded.VALUES.get(name);
        if (value == null) throw new IllegalArgumentException("pinned text embedding is missing: " + name);
        return value.clone();
    }

    public static int size() { return Loaded.VALUES.size(); }
}
