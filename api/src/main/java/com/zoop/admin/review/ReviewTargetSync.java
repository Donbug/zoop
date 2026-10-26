package com.zoop.admin.review;

import java.time.Clock;
import java.time.Instant;
import java.util.Optional;

import com.zoop.admin.jobs.RelationResultListener;
import com.zoop.ai.extraction.ExtractionClient;
import com.zoop.ai.extraction.UntrustedExtractionPayload;
import com.zoop.ai.relation.RelationUpstream;
import com.zoop.ai.relation.UntrustedRelationPayload;
import com.zoop.common.json.Canonical;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

/**
 * Projects an S3 result the analyze-plan worker fetched into {@code review_targets}, the list the administrator reviews HOLD
 * relations from (#133). The AI service has no HOLD list of its own and no webhook (AI owner 2026-10-22, answer 3): the app reads
 * the result of each job it runs. The S2 result the S3 job was built over is read again here, since an S2 event candidate is what
 * one candidate row stands for ({@link ReviewTargetReader}).
 *
 * <p>Nothing here is the authority: whether a relation is approved stays the AI source's {@code approvalBasis}. A withheld S2
 * result or a document this reader refuses writes nothing; the next sync of the job tries again.
 */
public final class ReviewTargetSync implements RelationResultListener {
    private static final Logger log = LoggerFactory.getLogger(ReviewTargetSync.class);

    private final JdbcReviewRepository reviews;
    private final ExtractionClient extraction;
    private final TransactionTemplate transaction;
    private final Clock clock;

    public ReviewTargetSync(JdbcReviewRepository reviews, ExtractionClient extraction, PlatformTransactionManager transactions,
            Clock clock) {
        this.reviews = reviews;
        this.extraction = extraction;
        this.transaction = new TransactionTemplate(transactions);
        this.clock = clock;
    }

    @Override
    public void relationResultFetched(RelationUpstream upstream, String s2ResultSha256, UntrustedRelationPayload payload) {
        sync(upstream, s2ResultSha256, payload);
    }

    /**
     * @param s2ResultSha256 the S2 result content hash the analyze-plan unit recorded; the S2 result read again here must be
     *                       exactly that content, so the projection never pairs an S3 result with other S2 content
     * @return the rows inserted or refreshed, or empty when the S2 result was not available to read
     */
    public Optional<Integer> sync(RelationUpstream upstream, String s2ResultSha256, UntrustedRelationPayload payload) {
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
