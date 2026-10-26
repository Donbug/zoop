package com.zoop.admin.review;

import java.time.Clock;
import java.time.Instant;
import java.util.List;
import java.util.Optional;

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
 * a later round. Each round reads every unit that has no target yet, then the next page of all observed units in key order.
 * Nothing here is the authority: whether a relation is approved stays the AI source's {@code approvalBasis}.
 */
public final class ReviewTargetSync {
    private static final Logger log = LoggerFactory.getLogger(ReviewTargetSync.class);

    private final JdbcReviewRepository reviews;
    private final ExtractionClient extraction;
    private final RelationClient relation;
    private final TransactionTemplate transaction;
    private final Clock clock;
    private final int batch;
    private String afterPlan = "";
    private int afterOrdinal;

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
        for (SyncUnit unit : reviews.unsyncedUnits(batch)) synced += attempt(unit);
        List<SyncUnit> page = reviews.unitsAfter(afterPlan, afterOrdinal, batch);
        for (SyncUnit unit : page) synced += attempt(unit);
        if (page.size() < batch) {
            afterPlan = "";
            afterOrdinal = 0;
        } else {
            afterPlan = page.getLast().planId();
            afterOrdinal = page.getLast().ordinal();
        }
        return synced;
    }

    private int attempt(SyncUnit unit) {
        try {
            return syncUnit(unit).isPresent() ? 1 : 0;
        } catch (RuntimeException failed) {
            log.warn("review-target sync of {} failed: {}", unit.s3JobId(), failed.getClass().getSimpleName());
            return 0;
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
        int written = transaction.execute(status -> (int) projection.rows().stream()
                .filter(row -> reviews.upsertTarget(payload.jobId(), payload.inputDigest(), row, at)).count());
        log.info("review-target sync of {}: {} of {} row(s) written", payload.jobId(), written, projection.rows().size());
        return Optional.of(written);
    }
}
