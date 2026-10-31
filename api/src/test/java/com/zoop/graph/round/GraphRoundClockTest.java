package com.zoop.graph.round;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.time.Duration;
import java.time.Instant;
import java.time.LocalTime;
import java.time.ZoneId;
import java.util.List;

import com.zoop.graph.round.GraphRoundClock.Slot;
import org.junit.jupiter.api.Test;

/** The slot calendar: 18 regular KST slots a day plus the freeze-only slot, round ids in KST, nothing across midnight. */
class GraphRoundClockTest {
    private static final ZoneId KST = ZoneId.of("Asia/Seoul");
    private final GraphRoundClock clock = new GraphRoundClock(KST, LocalTime.of(9, 5), Duration.ofMinutes(30), 18,
            List.of(LocalTime.of(18, 5)));

    @Test
    void aDayHasEighteenRegularSlotsAndTheFreezeOnlySlotInKst() {
        List<Slot> day = clock.slotsOn(java.time.LocalDate.of(2026, 10, 30));
        assertEquals(19, day.size());
        assertEquals("round-20261030T0905", day.get(0).roundId());
        assertEquals(Instant.parse("2026-10-30T00:05:00Z"), day.get(0).slotAt());
        assertFalse(day.get(0).freezeOnly());
        assertEquals("round-20261030T1735", day.get(17).roundId());
        assertEquals("round-20261030T1805", day.get(18).roundId());
        assertTrue(day.get(18).freezeOnly());
        assertTrue(clock.freezeOnly(Instant.parse("2026-10-30T09:05:00Z")));
        assertFalse(clock.freezeOnly(Instant.parse("2026-10-30T08:35:00Z")));
    }

    @Test
    void slotsBetweenIsHalfOpenOldestFirstAndCrossesTheDayBoundary() {
        List<Slot> none = clock.slotsBetween(Instant.parse("2026-10-30T00:05:00Z"), Instant.parse("2026-10-30T00:05:00Z"));
        assertTrue(none.isEmpty(), "from is exclusive");
        List<Slot> one = clock.slotsBetween(Instant.parse("2026-10-30T00:04:59Z"), Instant.parse("2026-10-30T00:05:00Z"));
        assertEquals(List.of("round-20261030T0905"), one.stream().map(Slot::roundId).toList());
        List<Slot> overnight = clock.slotsBetween(Instant.parse("2026-10-30T08:40:00Z"), Instant.parse("2026-10-31T00:10:00Z"));
        assertEquals(List.of("round-20261030T1805", "round-20261031T0905"), overnight.stream().map(Slot::roundId).toList());
    }

    @Test
    void theNextSlotIsTheFirstOneStrictlyAfterNowEvenAcrossMidnight() {
        assertEquals(Instant.parse("2026-10-30T00:35:00Z"), clock.nextSlotAt(Instant.parse("2026-10-30T00:05:00Z")).orElseThrow());
        assertEquals(Instant.parse("2026-10-30T09:05:00Z"), clock.nextSlotAt(Instant.parse("2026-10-30T08:35:00Z")).orElseThrow());
        assertEquals(Instant.parse("2026-10-31T00:05:00Z"), clock.nextSlotAt(Instant.parse("2026-10-30T09:05:00Z")).orElseThrow());
    }

    @Test
    void roundIdsAndMinutesFollowTheKstSlotForm() {
        assertEquals("round-20261030T2359", clock.roundId(Instant.parse("2026-10-30T14:59:30Z")));
        assertEquals(Instant.parse("2026-10-30T14:59:00Z"), clock.minute(Instant.parse("2026-10-30T14:59:30Z")));
    }

    @Test
    void thePropertiesRefuseACalendarThatCrossesMidnightOrRepeatsASlot() {
        assertThrows(GraphRoundConfigurationException.class, () -> properties("23:05", "PT30M", 3, List.of()));
        assertThrows(GraphRoundConfigurationException.class, () -> properties("09:05", "PT30M", 18, List.of("09:35")));
        assertThrows(GraphRoundConfigurationException.class, () -> properties("09:05", "PT30M", 18, List.of("18:05", "18:05")));
        assertThrows(GraphRoundConfigurationException.class, () -> properties("9:05", "PT30M", 18, List.of()));
        GraphRoundProperties ok = properties("09:05", "PT30M", 18, List.of("18:05"));
        assertEquals(List.of(LocalTime.of(18, 5)), ok.freezeOnlySlots());
        assertEquals(KST, ok.slotZone());
    }

    private static GraphRoundProperties properties(String first, String interval, int count, List<String> freezeOnly) {
        return new GraphRoundProperties(true, "scheduler", Duration.ofMinutes(1), Duration.ofMinutes(5), 20, "cli", "", "", "",
                Duration.ofSeconds(15), Duration.ofMinutes(2), "Asia/Seoul", first, Duration.parse(interval), count, freezeOnly,
                Duration.ofMinutes(30), 3, Duration.ofHours(2));
    }
}
