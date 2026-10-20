package com.zoop.company.market;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;

import java.time.Instant;
import java.time.ZoneId;
import java.util.List;
import org.junit.jupiter.api.Test;

class PriceBarsTest {
    private static final ZoneId KST = ZoneId.of("Asia/Seoul");

    @Test
    void oneUnknownVolumeMakesTheBucketVolumeUnknownNotSmaller() {
        var known = new PriceBars.Bar(Instant.parse("2026-10-15T03:00:00Z"), 100, 101, 99, 100, 100.0);
        var unknown = new PriceBars.Bar(Instant.parse("2026-10-15T03:01:00Z"), 100, 102, 100, 101, null);

        assertNull(PriceBars.byInterval(List.of(known, unknown), 300, KST).get(0).volume());
        assertEquals(200.0, PriceBars.byInterval(List.of(known, known), 300, KST).get(0).volume());
    }

    @Test
    void weeksStartOnTheExchangeLocalMonday() {
        // Sunday 2026-10-18 23:00 in New York is still that week; in Seoul it is already Monday 10-19.
        Instant at = Instant.parse("2026-10-19T03:00:00Z");
        assertEquals(Instant.parse("2026-10-12T04:00:00Z"), PriceBars.weekStart(at, ZoneId.of("America/New_York")));
        assertEquals(Instant.parse("2026-10-18T15:00:00Z"), PriceBars.weekStart(at, KST));
    }
}
