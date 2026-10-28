package com.zoop.admin.review;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;

import com.zoop.admin.review.JdbcReviewRepository.SyncUnit;
import com.zoop.ai.extraction.ExtractionClient;
import com.zoop.ai.extraction.UntrustedExtractionPayload;
import com.zoop.ai.relation.RelationClient;
import com.zoop.ai.relation.RelationUpstream;
import com.zoop.ai.relation.UntrustedRelationPayload;
import com.zoop.common.json.Canonical;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

/**
 * Projects the S3 results of analyze-plan units into {@code review_targets}, the list the administrator reviews HOLD relations
 * from (#133). The AI service has no HOLD list of its own and no webhook (AI owner 2026-10-22, answer 3): the app reads the result
 * of each job it ran, again and again, since a decision or a revalidation moves the AI source after the job was first read. The
 * S2 result the S3 job was built over is read too, since an S2 event candidate is what one candidate row stands for
 * ({@link ReviewTargetReader}), and it must be exactly the content the unit recorded.
 *
 * <p>It runs on its own schedule, never inside the analyze-plan worker's lease, so a failed or missed sync is simply tried again on
 * a later round. Each round reads the units that have no target yet (one that yielded nothing waits {@link #RETRY_AFTER} before the
 * first pass reads it again), then the next page of all observed units in key order. Each reading also marks the relations that
 * left the result inactive and derives every candidate's status from its active relations.
 * Nothing here is the authority: whether a relation is approved stays the AI source's {@code approvalBasis}.
 */
public final class ReviewTargetSync {
    private static final Logger log = LoggerFactory.getLogger(ReviewTargetSync.class);
    /** How long a unit that still has no target stays out of the first pass (the key-order pass still reads it). */
    public static final Duration RETRY_AFTER = Duration.ofMinutes(5);

    private final JdbcReviewRepository reviews;
    private final ExtractionClient extraction;
    private final RelationClient relation;
    private final TransactionTemplate transaction;
    private final Clock clock;
    private final int batch;
    private String afterPlan = "";
    private int afterOrdinal;
    /** S3 job id of a unit the first pass tried without a result, and when it may try again; in memory, a restart retries all. */
    private final Map<String, Instant> retryAt = new HashMap<>();

    public ReviewTargetSync(JdbcReviewRepository reviews, ExtractionClient extraction, RelationClient relation,
            PlatformTransactionManager transactions, Clock clock, int batch) {
        if (batch < 1) throw new IllegalArgumentException("review-target sync batch must be positive");
        this.reviews = reviews;
        this.extraction = extraction;
        this.relation = relation;
        this.transaction = new TransactionTemplate(transactions);
        this.clock = clock;
        this.batch = batch;
    }

    /** One round. A unit that fails is logged and left for the next round; it never stops the others. */
    public synchronized int runOnce() {
        int synced = 0;
        Instant now = clock.instant();
        retryAt.values().removeIf(at -> !now.isBefore(at));
        for (SyncUnit unit : reviews.unsyncedUnits(batch, Set.copyOf(retryAt.keySet()))) {
            Optional<Integer> written = attempt(unit);
            if (written.isPresent()) synced++;
            // Still no target (failed, withheld, nothing decided or nothing listed): let the newer units have the pass for a while.
            if (written.orElse(0) == 0) retryAt.put(unit.s3JobId(), now.plus(RETRY_AFTER));
        }
        List<SyncUnit> page = reviews.unitsAfter(afterPlan, afterOrdinal, batch);
        for (SyncUnit unit : page) if (attempt(unit).isPresent()) synced++;
        if (page.size() < batch) {
            afterPlan = "";
            afterOrdinal = 0;
        } else {
            afterPlan = page.getLast().planId();
            afterOrdinal = page.getLast().ordinal();
        }
        return synced;
    }

    private Optional<Integer> attempt(SyncUnit unit) {
        try {
            return syncUnit(unit);
        } catch (RuntimeException failed) {
            log.warn("review-target sync of {} failed: {}", unit.s3JobId(), failed.getClass().getSimpleName());
            return Optional.empty();
        }
    }

    /** @return the rows inserted or refreshed, or empty when the AI service withheld either result */
    Optional<Integer> syncUnit(SyncUnit unit) {
        Optional<UntrustedRelationPayload> s3 = relation.result(unit.s3JobId()).readyPayload();
        if (s3.isEmpty()) {
            log.info("review-target sync of {} skipped: result withheld", unit.s3JobId());
            return Optional.empty();
        }
        if (!s3.get().jobId().equals(unit.s3JobId()) || !s3.get().inputDigest().equals(unit.s3InputDigest())) {
            throw new IllegalStateException("S3 result is not the unit's observed job");
        }
        return sync(new RelationUpstream(unit.s2JobId(), unit.s2InputDigest()), unit.s2ResultSha256(), s3.get());
    }

    /**
     * @param s2ResultSha256 the S2 result content hash the analyze-plan unit recorded; the S2 result read again here must be
     *                       exactly that content, so the projection never pairs an S3 result with other S2 content
     * @return the rows inserted or refreshed, or empty when the S2 result was not available to read
     */
    Optional<Integer> sync(RelationUpstream upstream, String s2ResultSha256, UntrustedRelationPayload payload) {
        Optional<UntrustedExtractionPayload> s2 = extraction.result(upstream.jobId()).readyPayload();
        if (s2.isEmpty()) {
            log.info("review-target sync of {} skipped: upstream result withheld", payload.jobId());
            return Optional.empty();
        }
        if (!s2.get().jobId().equals(upstream.jobId()) || !s2.get().inputDigest().equals(upstream.inputDigest())) {
            throw new IllegalStateException("S2 result is not the S3 job's upstream");
        }
        if (s2ResultSha256 == null || !s2ResultSha256.equals(Canonical.sha256(s2.get().untrustedJson()))) {
            throw new IllegalStateException("S2 result differs from the content the plan unit recorded");
        }
        ReviewTargetReader.Projection projection = ReviewTargetReader.read(s2.get().untrustedJson(), payload.untrustedJson());
        if (projection.skipped() > 0) {
            log.warn("review-target sync of {}: {} unreadable item(s) left out", payload.jobId(), projection.skipped());
        }
        if (projection.unknownEvents() > 0) {
            log.warn("review-target sync of {}: {} relation(s) name an event outside the upstream result",
                    payload.jobId(), projection.unknownEvents());
        }
        Instant at = clock.instant();
        int written = transaction.execute(status -> {
            int rows = (int) projection.rows().stream()
                    .filter(row -> reviews.upsertTarget(payload.jobId(), payload.inputDigest(), row, at)).count();
            // An unreadable item may be a relation still there: only a complete reading tells which ones left.
            if (projection.skipped() == 0) {
                rows += reviews.markPresentRelations(payload.jobId(), payload.inputDigest(), projection.rows().stream()
                        .filter(row -> row.type().equals("relation")).map(ReviewTargetReader.Row::externalId).toList(), at);
            }
            return rows + reviews.refreshCandidates(payload.jobId(), at);
        });
        if (written > 0) {
            log.info("review-target sync of {}: {} row(s) changed", payload.jobId(), written);
        } else {
            log.debug("review-target sync of {}: unchanged", payload.jobId());
        }
        return Optional.of(written);
    }
}
