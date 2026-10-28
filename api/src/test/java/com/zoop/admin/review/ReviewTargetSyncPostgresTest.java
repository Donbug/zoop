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
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertFalse;
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
import java.util.Map;
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
import org.springframework.transaction.support.TransactionTemplate;

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
    @Autowired com.zoop.admin.pipeline.JdbcPipelineOverviewReader overview;
    @Autowired JdbcCandidateRepository candidates;

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
    void aRowSyncedBeforeTheApprovalColumnGetsItFromTheSameRevision() {
        sync.sync(upstream, recorded, result("hold", "2"));
        // As the migration leaves a row synced before it: no approval value yet.
        jdbc.update("UPDATE review_targets SET operator_approved = NULL WHERE source_job_id = ?", s3Job);

        sync.sync(upstream, recorded, result("hold", "2"));
        assertEquals(Boolean.FALSE, jdbc.queryForObject("SELECT operator_approved FROM review_targets WHERE source_job_id = ? "
                + "AND target_type = 'relation' AND external_id = ?", Boolean.class, s3Job, rel('2')), "filled, same revision");
        assertNull(jdbc.queryForObject("SELECT operator_approved FROM review_targets WHERE source_job_id = ? "
                + "AND target_type = 'candidate' AND external_id = ?", Boolean.class, s3Job, EVENT_A), "a candidate row has none");
        assertEquals("HOLD", status("relation", rel('2')), "the status still moves only with a newer revision");
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
    void aRelationThatLeftTheResultIsInactiveAndTheCandidateFollowsWhatIsLeft() {
        sync.sync(upstream, recorded, result("hold", "2"));

        sync.sync(upstream, recorded, result("pending", "3"));
        assertFalse(active("relation", rel('2')), "no verdict any more: not listed with its last HOLD");
        assertEquals("ALLOW", status("candidate", EVENT_A), "only the allowed relation is left");
        assertTrue(active("candidate", EVENT_A));

        sync.sync(upstream, recorded, new UntrustedRelationPayload(s3Job, S3_DIGEST, s3(
                relation(rel('4'), "SUPPLIES", endpoint("company", "A"), endpoint("company", "B"), "hold", "1")), List.of()));
        assertFalse(active("candidate", EVENT_A), "no relation left: the candidate is not listed either");
        assertTrue(active("candidate", rel('4')), "the standalone one is untouched");

        sync.sync(upstream, recorded, result("hold", "4"));
        assertTrue(active("relation", rel('2')), "back in the result: listed again");
        assertEquals("HOLD", status("candidate", EVENT_A));
        assertTrue(active("candidate", EVENT_A));
    }

    @Test
    void anUnreadableRelationLeavesEveryRowAsItWas() {
        sync.sync(upstream, recorded, result("hold", "2"));

        sync.sync(upstream, recorded, new UntrustedRelationPayload(s3Job, S3_DIGEST, s3(
                relation(rel('1'), "PARTICIPATES_IN", endpoint("company", "SK"), endpoint("event", EVENT_A), "eligible", "1"),
                relation(rel('2'), "PARTICIPATES_IN", endpoint("company", "SS"), endpoint("event", EVENT_A), "unknown", "3")),
                List.of()));

        assertTrue(active("relation", rel('2')), "it may still be there: only a complete reading deactivates");
        assertEquals("HOLD", status("candidate", EVENT_A));
    }

    /** The same four relations read again by another S3 job: a re-analysis of the same S2 content under a new plan. */
    private UntrustedRelationPayload reanalysed(String job) {
        return new UntrustedRelationPayload(job, "4".repeat(64), s3(
                relation(rel('1'), "PARTICIPATES_IN", endpoint("company", "SK"), endpoint("event", EVENT_A), "eligible", "1"),
                relation(rel('2'), "PARTICIPATES_IN", endpoint("company", "SS"), endpoint("event", EVENT_A), "hold", "2"),
                relation(rel('3'), "PARTICIPATES_IN", endpoint("company", "SK"), endpoint("event", EVENT_HELD), "hold", "1"),
                relation(rel('4'), "SUPPLIES", endpoint("company", "A"), endpoint("company", "B"), "hold", "1")), List.of());
    }

    /** Both S2 events name this snapshot event, unique per test so the list can be searched by it. */
    private String linkTo(String eventId) {
        s2Json = s2Json.replace("\"targetEventId\":null", "\"targetEventId\":\"" + eventId + "\"");
        recorded = Canonical.sha256(s2Json);
        upstreamResult(Optional.of(new UntrustedExtractionPayload(upstream.jobId(), S2_DIGEST, s2Json)));
        return eventId;
    }

    /**
     * An admitted one-unit analyze plan whose S3 job is {@code s3JobId}, its S2 input {@code s2Input} and its S3 result observed at
     * {@code observedAt}: the row the newest-analysis rule reads. No S3 input digest, so the sync scheduler never picks it up.
     */
    private void planUnit(String s3JobId, String s2Input, Instant observedAt) {
        String key = Canonical.sha256(s3JobId);
        String planId = "s2plan-" + key;
        String s2Job = "s2-" + key.substring(0, 40);
        String extraction = "{\"jobId\":\"" + s2Job + "\",\"approvedRequestDigest\":\"" + "a".repeat(64) + "\"}";
        String relationSubmit = "{\"jobId\":\"" + s3JobId + "\"}";
        String manifest = """
                {"schemaVersion":"zoop-ai-plan-manifest-1","planId":"%s","planDigest":"%s","receiptSha256":"%s",
                 "principal":"app","round":{},"provenance":{},"manifestDigest":"%s",
                 "units":[{"unitKey":"%s","extractionSubmit":%s,"extractionInputDigest":"%s","relationSubmit":%s}]}"""
                .formatted(planId, "b".repeat(64), "c".repeat(64), "d".repeat(64), s2Job, extraction, s2Input, relationSubmit);
        String stage = """
                {"schemaVersion":"zoop-app-analyze-plan-stage-1","state":"result_observed","intentAt":null,
                 "acceptedObservedAt":"%1$s","resultObservedAt":"%1$s","resultContentSha256":"%2$s","receipts":[],
                 "lastStatus":{"extraction":{"state":"READY","delivery":{"state":"AVAILABLE"}},
                               "relation":{"state":"READY","delivery":{"state":"AVAILABLE"}}},
                 "failureCategory":null,"failureCode":null,"consecutiveFailures":0,"recoveryDispatches":0}"""
                .formatted(observedAt, "e".repeat(64));
        new TransactionTemplate(transactions).executeWithoutResult(status -> {
            jdbc.update("""
                    INSERT INTO analysis_plans (plan_id, plan_digest, service_binding, expected_principal, registered_at,
                        registered_by, admission_id, accepted_at, policy_revision, policy_digest, receipt_sha256, manifest_digest,
                        manifest)
                    VALUES (?, ?, ?, 'app', now(), 'sync-test', ?, now(), 1, ?, ?, ?, CAST(? AS jsonb))""",
                    planId, "b".repeat(64), "f".repeat(64), "pa-" + key, "a".repeat(64), "c".repeat(64), "d".repeat(64),
                    manifest);
            jdbc.update("""
                    INSERT INTO analysis_plan_units (plan_id, ordinal, unit_key, s2_job_id, s2_approved_request_digest,
                        s2_input_digest, s3_job_id, s2_submit, s3_submit, s2_checkpoint, s3_checkpoint)
                    VALUES (?, 1, ?, ?, ?, ?, ?, CAST(? AS jsonb), CAST(? AS jsonb), CAST(? AS jsonb), CAST(? AS jsonb))""",
                    planId, s2Job, s2Job, "a".repeat(64), s2Input, s3JobId, extraction, relationSubmit, stage, stage);
        });
    }

    /** The S3 jobs whose candidate row for {@code external} the list shows when searched by the event id, one row per page. */
    private List<String> listed(String event, String external, String status) {
        var filter = new JdbcCandidateRepository.Filter(status, null, null, null, event, List.of(), List.of());
        List<String> jobs = new java.util.ArrayList<>();
        Instant afterAt = null;
        String afterId = null;
        while (true) {
            var page = candidates.page(filter, afterAt, afterId, 1);
            if (page.isEmpty()) return jobs.stream().sorted().toList();
            var only = page.getFirst();
            if (only.candidateId().equals(external)) jobs.add(only.s3JobId());
            afterAt = only.updatedAt();
            afterId = only.id();
        }
    }

    /**
     * C2 (#132, PR #395 review): the same S2 input analysed again keeps the older job's rows current, so the list, the counts and
     * the overview show the analysis observed last; the older job's HOLD stays decidable.
     */
    @Test
    void theSameInputReanalysedIsListedAndCountedOnceUnderTheAnalysisObservedLast() {
        String event = linkTo("event-" + UUID.randomUUID());
        String input = Canonical.sha256(event);
        Instant earlier = Instant.parse("2026-10-28T00:00:00Z");
        sync.sync(upstream, recorded, result("hold", "2"));
        String olderJob = s3Job;
        planUnit(olderJob, input, earlier);
        Map<String, Integer> countsBefore = candidates.counts();
        long holdBefore = overview.decisions().holdPending();
        long activeBefore = overview.candidates().active();

        // Observed later but sorting first by id: the order is the observation, not the job id.
        String newerJob = "s3-0-" + UUID.randomUUID();
        planUnit(newerJob, input, earlier.plusSeconds(60));
        sync.sync(upstream, recorded, reanalysed(newerJob));

        assertEquals(List.of(newerJob), listed(event, EVENT_A, null), "listed once, page by page");
        assertEquals(List.of(newerJob), listed(event, EVENT_A, "HOLD"), "the older HOLD is not listed by status either");
        assertEquals(countsBefore.get("HOLD") + 1, candidates.counts().get("HOLD"), "only the standalone candidate is new");
        assertEquals(activeBefore + 1, overview.candidates().active());
        assertEquals(holdBefore + 1, overview.decisions().holdPending(), "the event's HOLD moved to the newer analysis");

        var older = reviews.currentCandidate(candidateTargetId(EVENT_A)).orElseThrow();
        assertEquals("HOLD", reviews.currentRelation(older, rel('2')).orElseThrow().status(),
                "the older job's HOLD can still be decided, and its row and history stay");
    }

    /**
     * The review's counterexamples: another document, or another snapshot whose local event id happens to match, reaches the
     * same {@code targetEventId} with another S2 input. Both stay listed. So do analyses observed at the same instant and jobs
     * no plan unit owns.
     */
    @Test
    void candidatesFromAnotherInputAtTheSameInstantOrWithoutAPlanUnitAreNeverHidden() {
        String event = linkTo("event-" + UUID.randomUUID());
        Instant at = Instant.parse("2026-10-28T00:00:00Z");
        sync.sync(upstream, recorded, result("hold", "2"));
        String first = s3Job;
        planUnit(first, Canonical.sha256(event + "-document-a"), at);

        String otherDocument = "s3-doc-" + UUID.randomUUID();
        planUnit(otherDocument, Canonical.sha256(event + "-document-b"), at.plusSeconds(60));
        sync.sync(upstream, recorded, reanalysed(otherDocument));
        String otherSnapshot = "s3-snap-" + UUID.randomUUID();
        planUnit(otherSnapshot, Canonical.sha256(event + "-snapshot-2"), at.plusSeconds(120));
        sync.sync(upstream, recorded, reanalysed(otherSnapshot));
        assertEquals(List.of(first, otherDocument, otherSnapshot).stream().sorted().toList(), listed(event, EVENT_A, null),
                "the same event id from other inputs is another candidate");

        String sameInstant = "s3-tie-" + UUID.randomUUID();
        planUnit(sameInstant, Canonical.sha256(event + "-document-a"), at);
        sync.sync(upstream, recorded, reanalysed(sameInstant));
        String noUnit = "s3-none-" + UUID.randomUUID();
        sync.sync(upstream, recorded, reanalysed(noUnit));
        assertEquals(List.of(first, otherDocument, otherSnapshot, sameInstant, noUnit).stream().sorted().toList(),
                listed(event, EVENT_A, null), "no strictly later analysis of the same input, nothing hidden");
    }

    @Test
    void aReanalysedNewEventWithoutAnEventIdIsListedOncePerJob() {
        sync.sync(upstream, recorded, result("hold", "2"));
        String olderJob = s3Job;
        String input = Canonical.sha256(olderJob);
        planUnit(olderJob, input, Instant.parse("2026-10-28T00:00:00Z"));
        String newerJob = olderJob + "-z";
        planUnit(newerJob, input, Instant.parse("2026-10-28T00:01:00Z"));

        sync.sync(upstream, recorded, reanalysed(newerJob));

        assertEquals(2, jdbc.queryForObject("""
                SELECT count(*) FROM review_targets t
                WHERE t.target_type = 'candidate' AND t.is_current AND t.external_id = ? AND t.source_job_id IN (?, ?) AND """
                + " " + JdbcCandidateRepository.newestAnalysis("t"), Integer.class, EVENT_A, olderJob, newerJob),
                "nothing tells the two analyses are of one event");
    }

    private boolean active(String type, String external) {
        return jdbc.queryForObject("SELECT active FROM review_targets WHERE source_job_id = ? AND target_type = ? "
                + "AND external_id = ?", Boolean.class, s3Job, type, external);
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
