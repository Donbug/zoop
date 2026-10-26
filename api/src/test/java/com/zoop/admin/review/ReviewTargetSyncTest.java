package com.zoop.admin.review;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.anyCollection;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.mock;
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
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
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
    void anErrorInARoundNeverEndsTheSchedule() throws Exception {
        ReviewTargetSync sync = mock(ReviewTargetSync.class);
        AtomicInteger rounds = new AtomicInteger();
        CountDownLatch next = new CountDownLatch(1);
        doAnswer(call -> {
            if (rounds.incrementAndGet() == 1) throw new Error("unexpected");
            next.countDown();
            return 0;
        }).when(sync).runOnce();
        var scheduler = new ReviewTargetSyncScheduler(sync, Duration.ofMillis(10));
        scheduler.start();
        try {
            assertTrue(next.await(30, TimeUnit.SECONDS), "a round after the failed one still ran");
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
