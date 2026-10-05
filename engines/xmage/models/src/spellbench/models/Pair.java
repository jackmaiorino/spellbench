package spellbench.models;

import java.io.Serializable;
import java.util.Objects;

/** Value pair for upstream's optional feature debug map, without JavaFX. */
public final class Pair<K, V> implements Serializable {
    private static final long serialVersionUID = 1L;
    private final K key;
    private final V value;

    public Pair(K key, V value) {
        this.key = key;
        this.value = value;
    }

    public K getKey() { return key; }
    public V getValue() { return value; }

    @Override
    public boolean equals(Object other) {
        if (!(other instanceof Pair)) return false;
        Pair<?, ?> p = (Pair<?, ?>) other;
        return Objects.equals(key, p.key) && Objects.equals(value, p.value);
    }

    @Override
    public int hashCode() { return Objects.hash(key, value); }
}
