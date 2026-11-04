package com.zoop.common.request;

import java.util.HashMap;
import java.util.Map;
import java.util.function.Supplier;

/**
 * Values computed once per read-only request (#151): inside an open scope, {@link #memo} keeps the first non-null value for a
 * key until the scope closes, so one request does not verify and parse the same immutable graph version again for every
 * evidence it checks. Outside a scope every call computes, exactly as before. A failure is never kept, so the next call
 * tries again. A scope opened inside another one shares the outer scope and leaves it open when it closes.
 */
public final class ReadScope implements AutoCloseable {
    private static final ThreadLocal<Map<String, Object>> CURRENT = new ThreadLocal<>();
    private final boolean owner;

    private ReadScope(boolean owner) {
        this.owner = owner;
    }

    public static ReadScope open() {
        if (CURRENT.get() != null) return new ReadScope(false);
        CURRENT.set(new HashMap<>());
        return new ReadScope(true);
    }

    @SuppressWarnings("unchecked")
    public static <T> T memo(String key, Supplier<T> compute) {
        Map<String, Object> values = CURRENT.get();
        if (values == null) return compute.get();
        Object kept = values.get(key);
        if (kept != null) return (T) kept;
        // Not computeIfAbsent: a computation may memo other keys of the same map.
        T value = compute.get();
        if (value != null) values.put(key, value);
        return value;
    }

    @Override
    public void close() {
        if (owner) CURRENT.remove();
    }
}
