package com.zoop.company.market;

import java.time.Duration;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

class MarketDataConcurrencyLimiterTest {
    @Test
    void capsConcurrentProviderCalls() throws Exception {
        var limiter = new MarketDataConcurrencyLimiter(2, Duration.ofSeconds(2));
        var started = new CountDownLatch(2);
        var release = new CountDownLatch(1);
        var active = new AtomicInteger();
        var peak = new AtomicInteger();
        try (var pool = Executors.newFixedThreadPool(6)) {
            var tasks = java.util.stream.IntStream.range(0, 6).mapToObj(ignored -> pool.submit(() ->
                    limiter.execute(() -> {
                        int now = active.incrementAndGet();
                        peak.accumulateAndGet(now, Math::max);
                        started.countDown();
                        try {
                            if (!release.await(2, TimeUnit.SECONDS)) throw new IllegalStateException("test request timed out");
                        } catch (InterruptedException interrupted) {
                            Thread.currentThread().interrupt();
                            throw new IllegalStateException(interrupted);
                        } finally { active.decrementAndGet(); }
                        return null;
                    }))).toList();
            assertTrue(started.await(2, TimeUnit.SECONDS));
            assertEquals(2, peak.get());
            release.countDown();
            for (var task : tasks) task.get(3, TimeUnit.SECONDS);
        }
    }
}
