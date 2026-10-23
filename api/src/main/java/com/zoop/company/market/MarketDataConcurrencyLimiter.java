package com.zoop.company.market;

import java.time.Duration;
import java.util.concurrent.Semaphore;
import java.util.concurrent.TimeUnit;
import java.util.function.Supplier;

/** Bounds simultaneous outbound requests to one market-data provider. */
final class MarketDataConcurrencyLimiter {
    private final Semaphore permits;
    private final Duration waitTimeout;

    MarketDataConcurrencyLimiter(int maximumConcurrentRequests, Duration waitTimeout) {
        if (maximumConcurrentRequests < 1) throw new IllegalArgumentException("maximumConcurrentRequests must be positive");
        this.permits = new Semaphore(maximumConcurrentRequests, true);
        this.waitTimeout = waitTimeout;
    }

    <T> T execute(Supplier<T> request) {
        boolean acquired;
        try {
            acquired = permits.tryAcquire(Math.max(1, waitTimeout.toMillis()), TimeUnit.MILLISECONDS);
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
            throw new MarketDataException(true);
        }
        if (!acquired) throw new MarketDataException(true);
        try { return request.get(); }
        finally { permits.release(); }
    }
}
