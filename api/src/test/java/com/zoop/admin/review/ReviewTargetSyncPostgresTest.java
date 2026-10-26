package com.zoop.admin.review;

import static com.zoop.admin.review.ReviewTargetReaderTest.EVENT_A;
import static com.zoop.admin.review.ReviewTargetReaderTest.EVENT_HELD;
import static com.zoop.admin.review.ReviewTargetReaderTest.endpoint;
import static com.zoop.admin.review.ReviewTargetReaderTest.event;
import static com.zoop.admin.review.ReviewTargetReaderTest.rel;
import static com.zoop.admin.review.ReviewTargetReaderTest.relation;
import static com.zoop.admin.review.ReviewTargetReaderTest.s2;
import static com.zoop.admin.review.ReviewTargetReaderTest.s3;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import com.zoop.ai.extraction.ExtractionClient;
import com.zoop.ai.extraction.ExtractionResult;
import com.zoop.ai.extraction.UntrustedExtractionPayload;
import com.zoop.ai.relation.RelationClient;
import com.zoop.ai.relation.RelationUpstream;
import com.zoop.ai.relation.UntrustedRelationPayload;
import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson.Malformed;
import java.time.Clock;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.PlatformTransactionManager;

/** The review-target projection over the real migration: unique keys, the identity trigger and the decision repository reads. */
@SpringBootTest(properties = {
        "ZOOP_AUTH_CSRF_ACTIVE_KEY_ID=test",
        "ZOOP_AUTH_CSRF_KEYS=test=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        "ZOOP_AUTH_ALLOWED_ORIGINS=https://zoop.example"
})
@EnabledIfEnvironmentVariable(named = "DB_URL", matches = "jdbc:postgresql:.*")
@Tag("auth-postgres")
class ReviewTargetSyncPostgresTest {
    private static final String S2_DIGEST = "2".repeat(64);
    private static final String S3_DIGEST = "3".repeat(64);

    @Autowired JdbcReviewRepository reviews;
    @Autowired PlatformTransactionManager transactions;
    @Autowired JdbcTemplate jdbc;

    private final ExtractionClient extraction = mock(ExtractionClient.class);
    private ReviewTargetSync sync;
    private RelationUpstream upstream;
    private String s3Job;
    private String s2Json;
    private String recorded;

    @BeforeEach
    void setUp() {
        String suffix = UUID.randomUUID().toString();
        upstream = new RelationUpstream("s2-" + suffix, S2_DIGEST);
        s3Job = "s3-" + suffix;
        s2Json = s2(event(EVENT_A, "candidate", "new-event-candidate", "SK"), event(EVENT_HELD, "candidate", "held", "SK"));
        recorded = Canonical.sha256(s2Json);
        sync = new ReviewTargetSync(reviews, extraction, mock(RelationClient.class), transactions, Clock.systemUTC(), 10);
        upstreamResult(Optional.of(new UntrustedExtractionPayload(upstream.jobId(), S2_DIGEST, s2Json)));
    }

    private void upstreamResult(Optional<UntrustedExtractionPayload> payload) {
        ExtractionResult result = mock(ExtractionResult.class);
        when(result.readyPayload()).thenReturn(payload);
        when(extraction.result(upstream.jobId())).thenReturn(result);
    }

    private UntrustedRelationPayload result(String holdStatus, String holdRevision) {
        return new UntrustedRelationPayload(s3Job, S3_DIGEST, s3(
                relation(rel('1'), "PARTICIPATES_IN", endpoint("company", "SK"), endpoint("event", EVENT_A), "eligible", "1"),
                relation(rel('2'), "PARTICIPATES_IN", endpoint("company", "SS"), endpoint("event", EVENT_A), holdStatus,
                        holdRevision),
                relation(rel('3'), "PARTICIPATES_IN", endpoint("company", "SK"), endpoint("event", EVENT_HELD), "hold", "1"),
                relation(rel('4'), "SUPPLIES", endpoint("company", "A"), endpoint("company", "B"), "hold", "1")), List.of());
    }

    private String status(String type, String external) {
        return jdbc.queryForObject("SELECT status FROM review_targets WHERE source_job_id = ? AND target_type = ? "
                + "AND external_id = ?", String.class, s3Job, type, external);
    }

    private String revision(String type, String external) {
        return jdbc.queryForObject("SELECT source_revision FROM review_targets WHERE source_job_id = ? AND target_type = ? "
                + "AND external_id = ?", String.class, s3Job, type, external);
    }

    private int count() {
        return jdbc.queryForObject("SELECT count(*) FROM review_targets WHERE source_job_id = ?", Integer.class, s3Job);
    }

    private String candidateTargetId(String candidateId) {
        return jdbc.queryForObject("SELECT id FROM review_targets WHERE source_job_id = ? AND target_type = 'candidate' "
                + "AND candidate_id = ? AND is_current", String.class, s3Job, candidateId);
    }

    @Test
    void registersEventAndStandaloneCandidatesTheDecisionServiceCanResolve() throws Exception {
        assertEquals(Optional.of(5), sync.sync(upstream, recorded, result("hold", "2")));

        assertEquals(5, count(), "event A + 2 relations, the standalone SUPPLIES + 1 relation; the held event left out");
        assertEquals("HOLD", status("candidate", EVENT_A));
        assertEquals("3", revision("candidate", EVENT_A));
        assertEquals("HOLD", status("candidate", rel('4')));
        assertEquals(List.of("SK", "SS"), List.of((String[]) jdbc.queryForObject(
                "SELECT company_ids FROM review_targets WHERE source_job_id = ? AND target_type = 'candidate' AND external_id = ?",
                java.sql.Array.class, s3Job, EVENT_A).getArray()));

        var candidate = reviews.currentCandidate(candidateTargetId(EVENT_A)).orElseThrow();
        var hold = reviews.currentRelation(candidate, rel('2')).orElseThrow();
        assertEquals(S3_DIGEST, hold.sourceVersion());
        assertEquals("2", hold.sourceRevision());
        assertEquals("HOLD", hold.status());
        assertEquals(0, hold.revision());
    }

    @Test
    void aRepeatedOrOlderReadingChangesNothingAndANewerOneRefreshesInPlace() {
        sync.sync(upstream, recorded, result("hold", "2"));
        String relationId = jdbc.queryForObject("SELECT id FROM review_targets WHERE source_job_id = ? AND external_id = ? "
                + "AND target_type = 'relation'", String.class, s3Job, rel('2'));

        assertEquals(Optional.of(0), sync.sync(upstream, recorded, result("hold", "2")), "same reading: nothing to write");
        assertEquals(Optional.of(0), sync.sync(upstream, recorded, result("eligible", "1")), "older reading: never moves back");
        assertEquals("HOLD", status("relation", rel('2')));

        assertEquals(Optional.of(2), sync.sync(upstream, recorded, result("eligible", "3")), "the relation and its candidate");
        assertEquals("ALLOW", status("relation", rel('2')));
        assertEquals("ALLOW", status("candidate", EVENT_A));
        assertEquals("4", revision("candidate", EVENT_A));
        assertEquals(relationId, jdbc.queryForObject("SELECT id FROM review_targets WHERE source_job_id = ? AND external_id = ? "
                + "AND target_type = 'relation'", String.class, s3Job, rel('2')), "same row, identity untouched");
        assertEquals(5, count());
    }

    @Test
    void aDecisionThisAppSettledIsNotUndoneByAReadingTakenBeforeIt() {
        sync.sync(upstream, recorded, result("hold", "2"));
        String relationId = jdbc.queryForObject("SELECT id FROM review_targets WHERE source_job_id = ? AND external_id = ? "
                + "AND target_type = 'relation'", String.class, s3Job, rel('2'));
        reviews.settleTarget(relationId, 0, "ALLOW", Instant.now());

        sync.sync(upstream, recorded, result("hold", "2"));

        assertEquals("ALLOW", status("relation", rel('2')));
    }

    @Test
    void aWithheldOrForeignUpstreamWritesNothing() {
        upstreamResult(Optional.empty());
        assertEquals(Optional.empty(), sync.sync(upstream, recorded, result("hold", "2")));

        upstreamResult(Optional.of(new UntrustedExtractionPayload(upstream.jobId(), "9".repeat(64), s2Json)));
        assertThrows(IllegalStateException.class, () -> sync.sync(upstream, recorded, result("hold", "2")));

        upstreamResult(Optional.of(new UntrustedExtractionPayload(upstream.jobId(), S2_DIGEST,
                s2(event(EVENT_A, "candidate", "new-event-candidate", "OTHER")))));
        assertThrows(IllegalStateException.class, () -> sync.sync(upstream, recorded, result("hold", "2")),
                "same job and digest, but not the content the plan unit recorded");
        assertThrows(IllegalStateException.class, () -> sync.sync(upstream, null, result("hold", "2")),
                "no recorded S2 content: nothing to pair with");

        upstreamResult(Optional.of(new UntrustedExtractionPayload(upstream.jobId(), S2_DIGEST, "{}")));
        assertThrows(Malformed.class, () -> sync.sync(upstream, Canonical.sha256("{}"), result("hold", "2")));
        assertEquals(0, count());
        assertTrue(reviews.currentCandidate("rt-missing").isEmpty());
    }
}
