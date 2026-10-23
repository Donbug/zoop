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
            null, null, null, Duration.ofSeconds(10), null, null, null, 0, 0),
            JsonMapper.builder().build(), Clock.systemUTC());

    @Test
    void aggregatedPeriodsLandOnTheirBucketBoundaries() {
        for (String[] stock : List.of(new String[] {"KRX:005930", "KRX", "005930"}, new String[] {"NASDAQ:NVDA", "NASDAQ", "NVDA"})) {
            // 1d is the last regular session, even on a weekend; its 5-minute buckets never leave it.
            check(stock, "1d", "5m", null, null, t -> t.getMinute() % 5 == 0);
            check(stock, "1w", "1h", null, null, t -> t.getMinute() == 0);
            check(stock, "1y", "1wk", null, null, t -> t.getDayOfWeek() == DayOfWeek.MONDAY && t.getHour() == 0);
        }
    }

    /**
     * The 1d session comes from Toss's market calendar: a normal KRX day, the 2025 CSAT day (KRX 10:00–16:30), a KR holiday,
     * the US Thanksgiving holiday and the next day's 13:00 ET early close. Prints every range so a mismatch is visible.
     */
    @Test
    void dayFollowsTheMarketCalendar() {
        String[][] cases = {
                {"KRX:005930", "KRX", "005930", "2025-10-21T16:00:00+09:00", "2025-10-21T09:00:00+09:00", "2025-10-21T15:30:00+09:00"},
                {"KRX:005930", "KRX", "005930", "2025-11-13T17:00:00+09:00", "2025-11-13T10:00:00+09:00", "2025-11-13T16:30:00+09:00"},
                {"KRX:005930", "KRX", "005930", "2025-10-06T12:00:00+09:00", "2025-10-02T09:00:00+09:00", "2025-10-02T15:30:00+09:00"},
                {"NASDAQ:NVDA", "NASDAQ", "NVDA", "2025-11-27T12:00:00-05:00", "2025-11-26T09:30:00-05:00", "2025-11-26T16:00:00-05:00"},
                {"NASDAQ:NVDA", "NASDAQ", "NVDA", "2025-11-28T14:00:00-05:00", "2025-11-28T09:30:00-05:00", "2025-11-28T13:00:00-05:00"},
        };
        for (String[] c : cases) {
            CompanyPriceResponse r = toss.prices(c[0], c[1], c[2], "1d", null, OffsetDateTime.parse(c[3]).toInstant().plusNanos(1));
            System.out.printf("%s to %s -> %s %s%n", c[0], c[3], r.status(),
                    r.range() == null ? r.reasonCode() : r.range().from() + " .. " + r.range().to() + " (" + r.range().sessionDate() + ")");
            assertEquals("available", r.status(), c[0] + " " + c[3]);
            assertEquals(c[4] + " .. " + c[5], r.range().from() + " .. " + r.range().to(), c[0] + " " + c[3]);
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
            assertTrue(!"1d".equals(period) || (!t.isBefore(OffsetDateTime.parse(r.range().from()))
                    && t.isBefore(OffsetDateTime.parse(r.range().to()))), "1d point outside its session: " + p.time());
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
