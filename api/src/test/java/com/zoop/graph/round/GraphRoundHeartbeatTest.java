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
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

/** The writer's heartbeat and the public web's status read from it (#55 PR-P4). */
class GraphRoundHeartbeatTest {
    private static final Instant NOW = Instant.parse("2026-11-03T01:00:00Z");
    private static final Duration INTERVAL = Duration.ofSeconds(15);

    @Test void theWebSeesTheFreshestLiveWriterAndNothingOnceItsBeatIsThreeIntervalsOld() {
        var rows = new ArrayList<Tick>();
        var ticks = new GraphRoundTicks(null) {
            @Override public List<Tick> all() { return rows; }
        };
        var status = new TickedGraphRoundStatus(ticks, Clock.fixed(NOW, ZoneOffset.UTC));
        assertFalse(status.enabled(), "no writer");

        rows.add(tick("writer-a-0000000a", NOW.minusSeconds(10), NOW.minusSeconds(12)));
        rows.add(tick("writer-b-0000000b", NOW.minusSeconds(40), NOW.minusSeconds(41)));
        assertTrue(status.enabled());
        assertEquals(Optional.of(NOW.minusSeconds(12)), status.lastTickAt(), "the freshest live writer's last pass");
        assertEquals(Optional.of(NOW.plusSeconds(300)), status.nextSlotAt());

        rows.clear();
        rows.add(tick("writer-a-0000000a", NOW.minus(INTERVAL.multipliedBy(3)), NOW.minusSeconds(50)));
        assertFalse(status.enabled(), "a beat three intervals old is a stopped writer");
        assertEquals(Optional.empty(), status.lastTickAt());
    }

    @Test void unreadableHeartbeatsLookLikeNoWriter() {
        var ticks = new GraphRoundTicks(null) {
            @Override public List<Tick> all() { throw new IllegalStateException("database away"); }
        };
        assertFalse(new TickedGraphRoundStatus(ticks, Clock.fixed(NOW, ZoneOffset.UTC)).enabled());
    }

    @Test void theSchedulerBeatsItsRowAndRemovesItOnStop() {
        GraphRoundTicks ticks = Mockito.mock(GraphRoundTicks.class);
        GraphRoundWorker worker = Mockito.mock(GraphRoundWorker.class);
        when(worker.owner()).thenReturn("writer-a-0000000a");
        when(worker.lastTick()).thenReturn(Optional.of(NOW.minusSeconds(5)));
        var calendar = new GraphRoundClock(ZoneId.of("Asia/Seoul"), LocalTime.of(9, 5), Duration.ofMinutes(30), 18, List.of(LocalTime.of(18, 5)));
        var scheduler = new GraphRoundScheduler(worker, calendar, Clock.fixed(NOW, ZoneOffset.UTC), Duration.ofHours(1), ticks);
        scheduler.start();
        verify(ticks, timeout(5_000)).beat(argThat(tick -> tick.owner().equals("writer-a-0000000a") && tick.beatAt().equals(NOW)
                && tick.lastPassAt().equals(Optional.of(NOW.minusSeconds(5))) && tick.interval().equals(Duration.ofHours(1))));
        scheduler.stop();
        verify(ticks).remove("writer-a-0000000a");

        doThrow(new IllegalStateException("database away")).when(ticks).beat(any());
        assertDoesNotThrow(scheduler::beat, "a failed beat waits for the next one");
    }

    private static Tick tick(String owner, Instant beatAt, Instant lastPassAt) {
        return new Tick(owner, NOW.minusSeconds(3600), beatAt, INTERVAL, Optional.of(lastPassAt), Optional.of(NOW.plusSeconds(300)));
    }
}
