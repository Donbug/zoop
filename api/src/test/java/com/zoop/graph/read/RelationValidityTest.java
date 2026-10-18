package com.zoop.graph.read;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;

import com.zoop.graph.snapshot.PublicGraphSnapshot.Basis;
import java.time.Instant;
import java.util.List;
import org.junit.jupiter.api.Test;

class RelationValidityTest {
    // 2026-10-31T15:30Z is 2026-11-01 00:30 in Seoul: the Seoul date, not the UTC date, is compared.
    private static final Instant SEOUL_NOV_1 = Instant.parse("2026-10-31T15:30:00Z");

    private static Basis basis(String validFrom, String validUntil) {
        return new Basis("b", "SUPPLIES", "2026-10-18T00:00:00Z", validFrom, validUntil, List.of(), null, null);
    }

    @Test
    void statusComparesSeoulDatesWithTheLastValidDayIncluded() {
        assertEquals("scheduled", RelationValidity.of(basis("2026-11-02", null), SEOUL_NOV_1));
        assertEquals("active", RelationValidity.of(basis("2026-11-01", null), SEOUL_NOV_1));
        assertEquals("active", RelationValidity.of(basis("2026-10-01", "2026-11-01"), SEOUL_NOV_1));
        assertEquals("ended", RelationValidity.of(basis("2026-10-01", "2026-10-31"), SEOUL_NOV_1));
        // No start date: period unknown unless it has already ended; no end date means not ended.
        assertEquals("unknown", RelationValidity.of(basis(null, null), SEOUL_NOV_1));
        assertEquals("unknown", RelationValidity.of(basis(null, "2026-12-31"), SEOUL_NOV_1));
        assertEquals("ended", RelationValidity.of(basis(null, "2026-10-31"), SEOUL_NOV_1));
    }

    @Test
    void anEdgeIsActiveIfAnyBasisIsAndEndedOnlyWhenAllAre() {
        Basis active = basis("2026-10-01", null), scheduled = basis("2026-12-01", null);
        Basis unknown = basis(null, null), ended = basis("2026-01-01", "2026-03-31");
        assertEquals("active", RelationValidity.of(List.of(ended, scheduled, active), SEOUL_NOV_1));
        assertEquals("scheduled", RelationValidity.of(List.of(ended, unknown, scheduled), SEOUL_NOV_1));
        assertEquals("unknown", RelationValidity.of(List.of(ended, unknown), SEOUL_NOV_1));
        assertEquals("ended", RelationValidity.of(List.of(ended, ended), SEOUL_NOV_1));
        assertNull(RelationValidity.of(List.of(), SEOUL_NOV_1));
    }
}
