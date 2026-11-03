package com.zoop.graph.round;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.LocalTime;
import java.time.ZoneId;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import com.zoop.graph.round.GraphRoundTicks.Tick;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;
import org.springframework.transaction.support.TransactionOperations;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

/** The writer's heartbeat and the public web's status read from it (#55 PR-P4). */
class GraphRoundHeartbeatTest {
    private static final Instant NOW = Instant.parse("2026-11-03T01:00:00Z");
    private static final GraphRoundClock CALENDAR = new GraphRoundClock(ZoneId.of("Asia/Seoul"), LocalTime.of(9, 5), Duration.ofMinutes(30),
            18, List.of(LocalTime.of(18, 5)));

    @Test void theWebCountsTheFreshestLiveWriterWithItsCalendarAndNothingElse() {
        var rows = new ArrayList<Tick>();
        var status = status(() -> rows);
        assertFalse(status.enabled(), "no writer");
        assertEquals(Optional.empty(), status.nextSlotAt());

        rows.add(tick("writer-a-0000000a", NOW.minusSeconds(12), CALENDAR.digest(), true));
        rows.add(tick("writer-b-0000000b", NOW.minusSeconds(41), CALENDAR.digest(), true));
        assertTrue(status.enabled());
        assertEquals(Optional.of(NOW.minusSeconds(12)), status.lastTickAt(), "the freshest live writer's last pass");
        assertEquals(CALENDAR.nextSlotAt(NOW), status.nextSlotAt(), "the next slot from this process's own calendar");

        rows.clear();
        rows.add(tick("writer-a-0000000a", NOW.minusSeconds(50), CALENDAR.digest(), false));
        assertFalse(status.enabled(), "a beat three intervals old (by the database's clock) is a stopped writer");

        rows.clear();
        rows.add(tick("writer-c-0000000c", NOW.minusSeconds(5), "0".repeat(64), true));
        assertFalse(status.enabled(), "a writer with another slot calendar is not counted");
    }

    @Test void unreadableHeartbeatsLookLikeNoWriter() {
        assertFalse(status(() -> { throw new IllegalStateException("database away"); }).enabled());
    }

    @Test void theSchedulerBeatsItsRowWithItsCalendarAndRemovesItOnStop() {
        GraphRoundTicks ticks = Mockito.mock(GraphRoundTicks.class);
        GraphRoundWorker worker = Mockito.mock(GraphRoundWorker.class);
        when(worker.owner()).thenReturn("writer-a-0000000a");
        when(worker.lastTick()).thenReturn(Optional.of(NOW.minusSeconds(5)));
        var scheduler = new GraphRoundScheduler(worker, CALENDAR, Clock.fixed(NOW, ZoneOffset.UTC), Duration.ofHours(1), ticks);
        scheduler.start();
        verify(ticks, timeout(5_000)).beat(eq("writer-a-0000000a"), eq(NOW), eq(Duration.ofHours(1)), eq(Optional.of(NOW.minusSeconds(5))),
                eq(CALENDAR.digest()));
        scheduler.stop();
        verify(ticks).remove("writer-a-0000000a");

        doThrow(new IllegalStateException("database away")).when(ticks).beat(any(), any(), any(), any(), any());
        assertDoesNotThrow(scheduler::beat, "a failed beat waits for the next one");
    }

    @Test void theCalendarDigestNamesTheCalendar() {
        var other = new GraphRoundClock(ZoneId.of("Asia/Seoul"), LocalTime.of(9, 0), Duration.ofMinutes(30), 18, List.of(LocalTime.of(18, 5)));
        assertEquals(CALENDAR.digest(), new GraphRoundClock(ZoneId.of("Asia/Seoul"), LocalTime.of(9, 5), Duration.ofMinutes(30), 18,
                List.of(LocalTime.of(18, 5))).digest());
        assertNotEquals(CALENDAR.digest(), other.digest());
    }

    private interface Rows {
        List<Tick> read();
    }

    private static TickedGraphRoundStatus status(Rows rows) {
        var ticks = new GraphRoundTicks(null) {
            @Override public List<Tick> all() { return rows.read(); }
        };
        return new TickedGraphRoundStatus(ticks, CALENDAR, Clock.fixed(NOW, ZoneOffset.UTC), TransactionOperations.withoutTransaction());
    }

    private static Tick tick(String owner, Instant lastPassAt, String digest, boolean alive) {
        return new Tick(owner, NOW.minusSeconds(3600), NOW.minusSeconds(1), Duration.ofSeconds(15), Optional.of(lastPassAt), digest, alive);
    }
}
