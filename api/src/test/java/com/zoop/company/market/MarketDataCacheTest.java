package com.zoop.company.market;

import java.time.Duration;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

class MarketDataCacheTest {
    @Test
    void cachesUntilTtlExpiresAndEvictsLeastRecentlyUsedEntryAtCapacity() {
        var now = new AtomicLong(0);
        var cache = new MarketDataCache<String, String>(2, now::get);
        AtomicInteger loads = new AtomicInteger();
        var loader = (java.util.function.Supplier<String>) () -> "v" + loads.incrementAndGet();

        assertEquals("v1", cache.get("a", Duration.ofNanos(10), loader));
        assertEquals("v1", cache.get("a", Duration.ofNanos(10), loader));
        assertEquals("v2", cache.get("b", Duration.ofNanos(10), loader));
        assertEquals("v1", cache.get("a", Duration.ofNanos(10), loader)); // refresh access order
        assertEquals("v3", cache.get("c", Duration.ofNanos(10), loader));
        assertEquals("v1", cache.get("a", Duration.ofNanos(10), loader));
        assertEquals("v4", cache.get("b", Duration.ofNanos(10), loader)); // b was evicted
        now.set(11);
        assertEquals("v5", cache.get("a", Duration.ofNanos(10), loader));
    }

    @Test
    void concurrentMissesShareOneLoaderAndFailuresAreNotCached() throws Exception {
        var cache = new MarketDataCache<String, String>(8);
        var started = new CountDownLatch(1);
        var release = new CountDownLatch(1);
        var calls = new AtomicInteger();
        try (var pool = Executors.newFixedThreadPool(8)) {
            var futures = java.util.stream.IntStream.range(0, 8).mapToObj(ignored -> pool.submit(() ->
                    cache.get("same", Duration.ofMinutes(1), () -> {
                        calls.incrementAndGet();
                        started.countDown();
                        try {
                            if (!release.await(2, TimeUnit.SECONDS)) throw new IllegalStateException("test loader timed out");
                        } catch (InterruptedException interrupted) {
                            Thread.currentThread().interrupt();
                            throw new IllegalStateException(interrupted);
                        }
                        return "shared";
                    }))).toList();
            assertTrue(started.await(2, TimeUnit.SECONDS));
            release.countDown();
            for (var future : futures) assertEquals("shared", future.get(2, TimeUnit.SECONDS));
        }
        assertEquals(1, calls.get());

        AtomicInteger attempts = new AtomicInteger();
        assertThrows(IllegalArgumentException.class, () -> cache.get("error", Duration.ofMinutes(1), () -> {
            attempts.incrementAndGet();
            throw new IllegalArgumentException("synthetic provider error");
        }));
        assertEquals("recovered", cache.get("error", Duration.ofMinutes(1), () -> {
            attempts.incrementAndGet();
            return "recovered";
        }));
        assertEquals(2, attempts.get());
    }
}
