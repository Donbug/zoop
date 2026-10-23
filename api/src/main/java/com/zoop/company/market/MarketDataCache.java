package com.zoop.company.market;

import java.time.Duration;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Objects;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CompletionException;
import java.util.concurrent.ConcurrentHashMap;
import java.util.function.Function;
import java.util.function.LongSupplier;
import java.util.function.Supplier;

/** Bounded process-local cache with per-key single-flight loading for public market data. */
final class MarketDataCache<K, V> {
    private record Entry<V>(V value, long expiresAtNanos) { }

    private final int maximumEntries;
    private final LongSupplier nanoTime;
    private final Map<K, Entry<V>> entries = new LinkedHashMap<>(16, 0.75f, true);
    private final ConcurrentHashMap<K, CompletableFuture<V>> inFlight = new ConcurrentHashMap<>();

    MarketDataCache(int maximumEntries) {
        this(maximumEntries, System::nanoTime);
    }

    MarketDataCache(int maximumEntries, LongSupplier nanoTime) {
        if (maximumEntries < 1) throw new IllegalArgumentException("maximumEntries must be positive");
        this.maximumEntries = maximumEntries;
        this.nanoTime = Objects.requireNonNull(nanoTime);
    }

    V get(K key, Duration ttl, Supplier<V> loader) {
        return get(key, loader, ignored -> ttl);
    }

    V get(K key, Supplier<V> loader, Function<V, Duration> ttlForValue) {
        Objects.requireNonNull(key);
        Objects.requireNonNull(loader);
        Objects.requireNonNull(ttlForValue);
        V cached = cached(key);
        if (cached != null) return cached;

        var candidate = new CompletableFuture<V>();
        var active = inFlight.putIfAbsent(key, candidate);
        if (active != null) return await(active);
        try {
            // Another loader can finish between the first cache check and becoming the in-flight owner.
            cached = cached(key);
            if (cached != null) {
                candidate.complete(cached);
                return cached;
            }
            V value = Objects.requireNonNull(loader.get(), "market data loader returned null");
            Duration ttl = Objects.requireNonNull(ttlForValue.apply(value));
            if (!ttl.isNegative() && !ttl.isZero()) put(key, value, ttl);
            candidate.complete(value);
            return value;
        } catch (Throwable failure) {
            candidate.completeExceptionally(failure);
            throw propagate(failure);
        } finally {
            inFlight.remove(key, candidate);
        }
    }

    private synchronized V cached(K key) {
        var entry = entries.get(key);
        if (entry == null) return null;
        if (nanoTime.getAsLong() - entry.expiresAtNanos() >= 0) {
            entries.remove(key);
            return null;
        }
        return entry.value();
    }

    private synchronized void put(K key, V value, Duration ttl) {
        long now = nanoTime.getAsLong();
        long duration;
        try { duration = ttl.toNanos(); }
        catch (ArithmeticException overflow) { duration = Long.MAX_VALUE; }
        long expires = duration == Long.MAX_VALUE || now > Long.MAX_VALUE - duration
                ? Long.MAX_VALUE : now + duration;
        entries.put(key, new Entry<>(value, expires));
        while (entries.size() > maximumEntries) entries.remove(entries.keySet().iterator().next());
    }

    private static <V> V await(CompletableFuture<V> future) {
        try { return future.join(); }
        catch (CompletionException failure) { throw propagate(failure.getCause()); }
    }

    private static RuntimeException propagate(Throwable failure) {
        if (failure instanceof RuntimeException runtime) return runtime;
        if (failure instanceof Error error) throw error;
        return new IllegalStateException(failure);
    }
}
