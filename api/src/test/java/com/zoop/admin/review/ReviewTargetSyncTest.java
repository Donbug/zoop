package com.zoop.admin.review;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.mockito.ArgumentMatchers.anyCollection;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.timeout;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.zoop.admin.review.JdbcReviewRepository.SyncUnit;
import com.zoop.ai.extraction.ExtractionClient;
import com.zoop.ai.relation.RelationClient;
import com.zoop.ai.relation.RelationResult;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneId;
import java.time.ZoneOffset;
import java.util.Collection;
import java.util.List;
import java.util.Optional;
import java.util.Set;
import org.junit.jupiter.api.Test;
import org.springframework.transaction.PlatformTransactionManager;

class ReviewTargetSyncTest {
    private static final SyncUnit STUCK = new SyncUnit("plan", 1, "s3-stuck", "3".repeat(64), "s2", "2".repeat(64),
            "a".repeat(64));

    private final JdbcReviewRepository reviews = mock(JdbcReviewRepository.class);
    private final RelationClient relations = mock(RelationClient.class);

    @Test
    void aUnitThatYieldedNothingLeavesTheFirstPassToNewerUnitsForAWhile() {
        MovingClock clock = new MovingClock(Instant.parse("2026-10-26T01:00:00Z"));
        RelationResult withheld = mock(RelationResult.class);
        when(withheld.readyPayload()).thenReturn(Optional.empty());
        when(relations.result("s3-stuck")).thenReturn(withheld);
        when(reviews.unsyncedUnits(eq(20), anyCollection())).thenAnswer(call -> {
            Collection<String> skip = call.getArgument(1);
            return skip.contains("s3-stuck") ? List.of() : List.of(STUCK);
        });
        when(reviews.unitsAfter(anyString(), anyInt(), anyInt())).thenReturn(List.of());
        var sync = new ReviewTargetSync(reviews, mock(ExtractionClient.class), relations,
                mock(PlatformTransactionManager.class), clock, 20);

        sync.runOnce();
        verify(reviews).unsyncedUnits(20, Set.of());
        sync.runOnce();
        verify(reviews).unsyncedUnits(20, Set.of("s3-stuck"));

        clock.advance(ReviewTargetSync.RETRY_AFTER);
        sync.runOnce();
        verify(reviews, times(2)).unsyncedUnits(20, Set.of());
    }

    @Test
    void anErrorInARoundNeverEndsTheSchedule() {
        ReviewTargetSync sync = mock(ReviewTargetSync.class);
        when(sync.runOnce()).thenThrow(new AssertionError("unexpected")).thenReturn(0);
        var scheduler = new ReviewTargetSyncScheduler(sync, Duration.ofMillis(10));
        scheduler.start();
        try {
            verify(sync, timeout(5_000).atLeast(2)).runOnce();
        } finally {
            scheduler.stop();
        }
        assertFalse(scheduler.isRunning());
    }

    private static final class MovingClock extends Clock {
        private Instant now;

        MovingClock(Instant now) {
            this.now = now;
        }

        void advance(Duration duration) {
            now = now.plus(duration);
        }

        @Override
        public ZoneId getZone() {
            return ZoneOffset.UTC;
        }

        @Override
        public Clock withZone(ZoneId zone) {
            return this;
        }

        @Override
        public Instant instant() {
            return now;
        }
    }
}
