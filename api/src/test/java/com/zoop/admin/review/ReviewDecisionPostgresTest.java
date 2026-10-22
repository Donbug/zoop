package com.zoop.admin.review;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.zoop.admin.auth.provision.AdminProvisioningService;
import com.zoop.admin.auth.service.AdminPrincipal;
import com.zoop.admin.review.RelationReviewClient.Refusal;
import com.zoop.admin.review.RelationReviewClient.Refused;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import java.time.Instant;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.CopyOnWriteArrayList;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Primary;
import org.springframework.jdbc.core.JdbcTemplate;

/** Review decisions over the real migration, publication lock, idempotency and audit tables, with a recording AI source. */
@SpringBootTest(properties = {
        "ZOOP_AUTH_CSRF_ACTIVE_KEY_ID=test",
        "ZOOP_AUTH_CSRF_KEYS=test=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        "ZOOP_AUTH_ALLOWED_ORIGINS=https://zoop.example"
})
@EnabledIfEnvironmentVariable(named = "DB_URL", matches = "jdbc:postgresql:.*")
@Tag("auth-postgres")
class ReviewDecisionPostgresTest {
    private static final String PASSWORD = "Secure admin password 2026";

    /** What the AI source was asked, and what it should answer next (null: recorded). */
    static final class FakeSource implements RelationReviewClient {
        final List<String> calls = new CopyOnWriteArrayList<>();
        volatile Refusal next;

        @Override
        public void review(String sourceJobId, String relationCandidateId, String expectedSourceVersion,
                String expectedSourceRevision, String decision, String operationId) {
            calls.add(String.join("|", sourceJobId, relationCandidateId, expectedSourceVersion, expectedSourceRevision,
                    decision, operationId));
            Refusal refusal = next;
            if (refusal != null) throw new Refused(refusal, "fake_" + refusal);
        }
    }

    @TestConfiguration
    static class FakeSourceConfiguration {
        @Bean
        @Primary
        FakeSource fakeRelationReviewClient() {
            return new FakeSource();
        }
    }

    @Autowired ReviewDecisionService decisions;
    @Autowired FakeSource source;
    @Autowired JdbcTemplate jdbc;
    @Autowired AdminProvisioningService provisioning;

    private AdminPrincipal admin;
    private String suffix;

    @BeforeEach
    void setUp() {
        source.calls.clear();
        source.next = null;
        suffix = UUID.randomUUID().toString();
        String email = "review-admin-" + suffix + "@example.com";
        String adminId = provisioning.provision(email, "Review Admin", PASSWORD, "review-provision-" + suffix);
        admin = new AdminPrincipal(adminId, email, "Review Admin", "admin", "session-" + suffix);
    }

    @Test
    void anAllowOnAHoldRelationIsRecordedAfterTheSourceAndPublishesNothing() {
        Ids ids = insertCandidateWithRelation("HOLD");
        long globalBefore = global();

        var response = decisions.decide(ids.candidate(), request("allow", ids.relation(), 0, "7"), "key-" + suffix, admin, "r1");

        assertEquals(new ReviewDecision.Response(ids.candidate(), "approved", 1, false), response);
        assertEquals(1, source.calls.size(), "the AI source got the decision once");
        assertTrue(source.calls.get(0).startsWith(ids.job() + "|rel-1|digest-" + suffix + "|7|allow|zoop-review-"));
        assertEquals("ALLOW", jdbc.queryForObject("SELECT status FROM review_targets WHERE id = ?", String.class,
                ids.relationTarget()));
        assertEquals(1L, jdbc.queryForObject("SELECT current_revision FROM review_targets WHERE id = ?", Long.class,
                ids.relationTarget()));
        assertEquals(globalBefore + 1, global());
        // The audit row keeps the source version and revision the decision was made on.
        assertEquals("digest-" + suffix + "|7", jdbc.queryForObject("""
                SELECT detail->>'sourceVersion' || '|' || (detail->>'sourceRevision') FROM audit_logs
                WHERE action = 'review.decision' AND target_id = ?""", String.class, ids.relationTarget()));
        assertEquals(0, jdbc.queryForObject("SELECT count(*) FROM review_decisions WHERE target_id = ? AND job_id IS NOT NULL",
                Integer.class, ids.relationTarget()), "an approval creates no job");

        // Same key and body: the stored response, no second call or row. Another body under the key: conflict.
        assertEquals(response, decisions.decide(ids.candidate(), request("allow", ids.relation(), 0, "7"), "key-" + suffix,
                admin, "r2"));
        assertEquals(1, source.calls.size());
        assertEquals(ErrorCode.IDEMPOTENCY_CONFLICT, code(() -> decisions.decide(ids.candidate(),
                request("reject", ids.relation(), 0, "7"), "key-" + suffix, admin, "r3")));
        assertEquals(1, decisionCount(ids.relationTarget()));
    }

    @Test
    void anyStaleExpectedValueOrANonHoldTargetIsRefusedBeforeTheSource() {
        Ids ids = insertCandidateWithRelation("HOLD");
        assertEquals(ErrorCode.REVISION_CONFLICT, code(() -> decisions.decide(ids.candidate(),
                request("allow", ids.relation(), 1, "7"), "k1-" + suffix, admin, "r")), "target revision");
        assertEquals(ErrorCode.REVISION_CONFLICT, code(() -> decisions.decide(ids.candidate(),
                request("allow", ids.relation(), 0, "8"), "k2-" + suffix, admin, "r")), "source revision");
        assertEquals(ErrorCode.REVISION_CONFLICT, code(() -> decisions.decide(ids.candidate(),
                new ReviewDecision.Request("allow", "이유", ids.relation(), 0L, "other-digest", "7"), "k3-" + suffix, admin, "r")),
                "source version");

        Ids allowed = insertCandidateWithRelation("ALLOW");
        assertEquals(ErrorCode.REVISION_CONFLICT, code(() -> decisions.decide(allowed.candidate(),
                request("allow", allowed.relation(), 0, "7"), "k4-" + suffix, admin, "r")), "only a HOLD is decided");
        assertEquals(ErrorCode.INVALID_REQUEST, code(() -> decisions.decide(ids.candidate(),
                request("allow", null, 0, "7"), "k5-" + suffix, admin, "r")), "no candidate-level decision yet");
        assertEquals(ErrorCode.RESOURCE_NOT_FOUND, code(() -> decisions.decide(ids.candidate(),
                request("allow", "rel-unknown", 0, "7"), "k6-" + suffix, admin, "r")));

        assertTrue(source.calls.isEmpty(), "nothing was sent to the AI source");
        assertEquals(0, decisionCount(ids.relationTarget()));
    }

    @Test
    void aSourceRefusalRecordsNothingAndMapsToTheContractCodes() {
        Ids ids = insertCandidateWithRelation("HOLD");
        source.next = Refusal.STALE;
        assertEquals(ErrorCode.REVISION_CONFLICT, code(() -> decide(ids, "s1")));
        source.next = Refusal.IN_FLIGHT;
        assertEquals(ErrorCode.REVISION_CONFLICT, code(() -> decide(ids, "s2")));
        source.next = Refusal.INELIGIBLE;
        assertEquals(ErrorCode.VALIDATION_FAILED, code(() -> decide(ids, "s3")), "a deterministic check is never overridden");
        source.next = Refusal.UNCONFIRMED;
        CustomException unconfirmed = assertThrows(CustomException.class, () -> decide(ids, "s4"));
        assertEquals(ErrorCode.SOURCE_UNAVAILABLE, unconfirmed.getErrorCode());

        assertEquals(0, decisionCount(ids.relationTarget()));
        assertEquals("HOLD", jdbc.queryForObject("SELECT status FROM review_targets WHERE id = ?", String.class,
                ids.relationTarget()));
        assertEquals(0, jdbc.queryForObject("SELECT count(*) FROM idempotency_records WHERE idem_key LIKE ?", Integer.class,
                "%-" + suffix), "a refused request leaves no idempotency record, so the same key can be sent again");

        // The same key after the source recovers goes through.
        source.next = null;
        assertEquals("approved", decide(ids, "s4").decision());
    }

    @Test
    void globalRevisionsAreAppWideAndTargetRevisionsAreOwn() {
        Ids first = insertCandidateWithRelation("HOLD");
        Ids second = insertCandidateWithRelation("HOLD");
        long before = global();
        decide(first, "g1");
        decisions.decide(second.candidate(), request("reject", second.relation(), 0, "7"), "g2-" + suffix, admin, "r");
        assertEquals(before + 2, global());
        assertEquals(1L, jdbc.queryForObject("SELECT revision FROM review_decisions WHERE target_id = ?", Long.class,
                second.relationTarget()), "the target's own revision starts at 1");
        assertEquals("REJECT", jdbc.queryForObject("SELECT status FROM review_targets WHERE id = ?", String.class,
                second.relationTarget()));
    }

    @Test
    void withoutAConfiguredSourceADecisionFailsClosed() {
        Refused refused = assertThrows(Refused.class, () -> new RelationReviewClient.Unconfigured()
                .review("j", "c", "v", "1", "allow", "op"));
        assertEquals(Refusal.UNCONFIRMED, refused.refusal());
        assertFalse(refused.getMessage().isBlank());
    }

    private record Ids(String job, String candidate, String relationTarget, String relation) {
    }

    private ReviewDecision.Response decide(Ids ids, String key) {
        return decisions.decide(ids.candidate(), request("allow", ids.relation(), 0, "7"), key + "-" + suffix, admin, "r");
    }

    /** The expected source version is the one every inserted target carries. */
    private ReviewDecision.Request request(String decision, String relationId, long revision, String sourceRevision) {
        return new ReviewDecision.Request(decision, "검수 사유", relationId, revision, "digest-" + suffix, sourceRevision);
    }

    /** A candidate and one relation of it in one S3 job; the relation's source version is the job's input digest. */
    private Ids insertCandidateWithRelation(String status) {
        String job = "job-s3-" + UUID.randomUUID();
        String candidateCandidateId = "cand-" + UUID.randomUUID();
        String candidateTarget = "rt-" + UUID.randomUUID();
        String relationTarget = "rt-" + UUID.randomUUID();
        Instant now = Instant.now();
        String sql = """
                INSERT INTO review_targets (id, target_type, source_job_id, external_id, source_version, candidate_id,
                                            status, source_revision, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, '7', ?)
                """;
        jdbc.update(sql, candidateTarget, "candidate", job, candidateCandidateId, "digest-" + suffix, candidateCandidateId,
                "HOLD", java.sql.Timestamp.from(now));
        jdbc.update(sql, relationTarget, "relation", job, "rel-1", "digest-" + suffix, candidateCandidateId, status,
                java.sql.Timestamp.from(now));
        return new Ids(job, candidateTarget, relationTarget, "rel-1");
    }

    private long global() {
        return jdbc.queryForObject("SELECT COALESCE(MAX(global_revision), 0) FROM review_decisions", Long.class);
    }

    private int decisionCount(String targetId) {
        return jdbc.queryForObject("SELECT count(*) FROM review_decisions WHERE target_id = ?", Integer.class, targetId);
    }

    private static ErrorCode code(Runnable call) {
        return assertThrows(CustomException.class, call::run).getErrorCode();
    }
}
