package com.zoop.company.market;

import com.zoop.company.market.dto.CompanyPriceResponse;
import java.time.Clock;
import java.time.DayOfWeek;
import java.time.Duration;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import tools.jackson.databind.json.JsonMapper;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

/** Calls the real Toss API; runs only where ZOOP_TOSS_CLIENT_ID is set (never in CI). Prints no credentials. */
@EnabledIfEnvironmentVariable(named = "ZOOP_TOSS_CLIENT_ID", matches = ".+")
class TossPricesLiveTest {
    private final TossMarketClient toss = new TossMarketClient(new CompanyMarketSettings("toss",
            System.getenv("ZOOP_TOSS_CLIENT_ID"), System.getenv("ZOOP_TOSS_CLIENT_SECRET"), null, "off",
            null, null, null, Duration.ofSeconds(10)), JsonMapper.builder().build(), Clock.systemUTC());

    @Test
    void aggregatedPeriodsLandOnTheirBucketBoundaries() {
        for (String[] stock : List.of(new String[] {"KRX:005930", "KRX", "005930"}, new String[] {"NASDAQ:NVDA", "NASDAQ", "NVDA"})) {
            // Three days back always reaches a trading day, even on a weekend.
            Instant now = Instant.now();
            check(stock, "1d", "5m", now.minus(Duration.ofDays(3)), now, t -> t.getMinute() % 5 == 0);
            check(stock, "1w", "1h", null, null, t -> t.getMinute() == 0);
            check(stock, "1y", "1wk", null, null, t -> t.getDayOfWeek() == DayOfWeek.MONDAY && t.getHour() == 0);
        }
    }

    @Test
    void aFinishedWeekIsReadOnceThenServedFromTheCache() {
        long before = toss.requests.get();
        long first = timed(() -> toss.prices("NASDAQ:NVDA", "NASDAQ", "NVDA", "1w", null, null));
        long firstRequests = toss.requests.get() - before, firstNanos = toss.requestNanos.get();
        long second = timed(() -> toss.prices("NASDAQ:NVDA", "NASDAQ", "NVDA", "1w", null, null));
        System.out.printf("NVDA 1w: first %d ms (%d requests, %d ms each), second %d ms (%d requests)%n", first, firstRequests,
                firstNanos / 1_000_000 / Math.max(1, firstRequests), second, toss.requests.get() - before - firstRequests);
        assertTrue(second * 2 < first, "second 1w read should mostly come from the minute cache");
    }

    private void check(String[] stock, String period, String interval, Instant from, Instant to,
            java.util.function.Predicate<OffsetDateTime> onBoundary) {
        CompanyPriceResponse r = toss.prices(stock[0], stock[1], stock[2], period, from, to);
        assertEquals("available", r.status(), stock[0] + " " + period + " " + r.reasonCode() + " " + r.reason());
        assertEquals(interval, r.interval());
        OffsetDateTime previous = null;
        for (var p : r.points()) {
            OffsetDateTime t = OffsetDateTime.parse(p.time());
            assertTrue(onBoundary.test(t) && t.getSecond() == 0, stock[0] + " " + period + " off boundary: " + p.time());
            assertTrue(previous == null || t.isAfter(previous), "points oldest first");
            assertTrue(p.high() >= Math.max(p.open(), p.close()) && p.low() <= Math.min(p.open(), p.close()), p.toString());
            previous = t;
        }
        System.out.printf("%s %s: %d points, %s .. %s%n", stock[0], period, r.points().size(),
                r.points().getFirst().time(), r.points().getLast().time());
    }

    private static long timed(Runnable read) {
        long start = System.nanoTime();
        read.run();
        return Duration.ofNanos(System.nanoTime() - start).toMillis();
    }
}
