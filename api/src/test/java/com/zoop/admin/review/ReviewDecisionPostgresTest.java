package com.zoop.admin.review;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyBoolean;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.reset;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.zoop.admin.audit.JdbcAdminIdempotencyStore;
import com.zoop.admin.auth.provision.AdminProvisioningService;
import com.zoop.admin.auth.repository.AdminAuditRepository;
import com.zoop.admin.auth.service.AdminPrincipal;
import com.zoop.admin.review.RelationReviewClient.Lookup;
import com.zoop.admin.review.RelationReviewClient.Operation;
import com.zoop.admin.review.RelationReviewClient.Refusal;
import com.zoop.admin.review.RelationReviewClient.Refused;
import com.zoop.ai.AiOperation;
import com.zoop.ai.AiTransportException;
import com.zoop.ai.relation.RelationClient;
import com.zoop.ai.relation.RelationDecision;
import com.zoop.ai.relation.RelationOperationStatus;
import com.zoop.ai.relation.RelationReviewRequest;
import com.zoop.ai.relation.RelationOperationAcknowledgement;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.common.json.Canonical;
import java.sql.Timestamp;
import java.time.Clock;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.OptionalInt;
import java.util.Set;
import java.util.UUID;
import java.util.function.Function;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Primary;
import org.springframework.dao.DataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.bean.override.mockito.MockitoSpyBean;
import org.springframework.transaction.PlatformTransactionManager;
import tools.jackson.databind.ObjectMapper;
import com.jayway.jsonpath.JsonPath;
import com.zoop.admin.auth.service.AdminSessionCookie;
import com.zoop.common.request.RequestIdFilter;
import jakarta.servlet.http.Cookie;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.context.WebApplicationContext;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

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

    /**
     * What the AI source was asked and what its ledger holds (operation id -> the operation it reports). {@code next} is the error
     * code it answers before recording anything (null: it records); {@code loseReply} records and then answers as if the reply
     * were lost.
     */
    static final class FakeSource implements RelationReviewClient {
        final List<String> calls = new CopyOnWriteArrayList<>();
        final Map<String, Operation> ledger = new ConcurrentHashMap<>();
        final Set<String> brokenLookups = ConcurrentHashMap.newKeySet();
        final AtomicInteger lookups = new AtomicInteger();
        volatile String next;
        volatile boolean loseReply;
        /** Runs inside {@code review} before it answers (a test holding the call open). */
        volatile Runnable beforeAnswer;

        @Override
        public void review(String sourceJobId, String relationCandidateId, String expectedSourceVersion,
                String expectedSourceRevision, String decision, String operationId) {
            calls.add(String.join("|", sourceJobId, relationCandidateId, expectedSourceVersion, expectedSourceRevision,
                    decision, operationId));
            Runnable hold = beforeAnswer;
            if (hold != null) hold.run();
            String code = next;
            if (code != null) throw new Refused(code);
            ledger.putIfAbsent(operationId, new Operation(Lookup.RECORDED, sourceJobId, relationCandidateId, decision,
                    expectedSourceVersion, expectedSourceRevision, true));
            if (loseReply) throw new Refused("review_unconfirmed");
        }

        @Override
        public Operation lookup(String sourceJobId, String operationId) {
            lookups.incrementAndGet();
            if (brokenLookups.contains(operationId)) throw new IllegalStateException("broken lookup");
            return ledger.getOrDefault(operationId, Operation.notFound());
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
    @MockitoSpyBean JdbcReviewRepository reviews;
    @Autowired AdminProvisioningService provisioning;
    @Autowired JdbcAdminIdempotencyStore idempotencyStore;
    @Autowired AdminAuditRepository auditRepository;
    @Autowired PlatformTransactionManager transactions;
    @Autowired ObjectMapper objectMapper;

    private AdminPrincipal admin;
    private String adminEmail;
    private static final String ORIGIN = "https://zoop.example";
    @Autowired WebApplicationContext context;
    @Autowired RequestIdFilter requestIds;
    private String suffix;

    @BeforeEach
    void setUp() {
        source.calls.clear();
        source.next = null;
        source.loseReply = false;
        source.beforeAnswer = null;
        source.lookups.set(0);
        reset(reviews);
        suffix = UUID.randomUUID().toString();
        String email = "review-admin-" + suffix + "@example.com";
        String adminId = provisioning.provision(email, "Review Admin", PASSWORD, "review-provision-" + suffix);
        admin = new AdminPrincipal(adminId, email, "Review Admin", "admin", "session-" + suffix);
        adminEmail = email;
    }

    // ---- over HTTP (decideAnalysisCandidate) -------------------------------------------------------------------------------

    @Test
    void theDecisionOverHttpIsTheServicesAnswerUnderTheAdminSessionCsrfAndKey() throws Exception {
        MockMvc mvc = MockMvcBuilders.webAppContextSetup(context).addFilters(requestIds).build();
        var login = mvc.perform(post("/api/v1/admin/auth/login").header("Origin", ORIGIN).contentType("application/json")
                .content("{\"email\":\"" + adminEmail + "\",\"password\":\"" + PASSWORD + "\"}"))
                .andExpect(status().isOk()).andReturn().getResponse();
        Cookie cookie = login.getCookie(AdminSessionCookie.NAME);
        String csrf = JsonPath.read(login.getContentAsString(), "$.csrfToken");
        Ids ids = insertCandidateWithRelation("HOLD");
        String path = "/api/v1/admin/pipeline/candidates/" + ids.candidate() + "/decision";
        String allow = decisionBody("allow", ids.relation(), 0);

        mvc.perform(post(path).cookie(cookie).header("Origin", ORIGIN).header("Idempotency-Key", "h0-" + suffix)
                .contentType("application/json").content(allow)).andExpect(status().isForbidden());
        mvc.perform(post(path).cookie(cookie).header("Origin", ORIGIN).header("X-CSRF-Token", csrf)
                .contentType("application/json").content(allow)).andExpect(status().isUnprocessableContent());
        mvc.perform(post(path).cookie(cookie).header("Origin", ORIGIN).header("X-CSRF-Token", csrf)
                .header("Idempotency-Key", "h1-" + suffix).contentType("application/json")
                .content(decisionBody("allow", ids.relation(), 5))).andExpect(status().isConflict());
        mvc.perform(post(path).cookie(cookie).header("Origin", ORIGIN).header("X-CSRF-Token", csrf)
                .header("Idempotency-Key", "h2-" + suffix).contentType("application/json")
                .content(decisionBody("allow", null, 0))).andExpect(status().isUnprocessableContent());
        assertEquals(0, source.calls.size(), "nothing was sent for a refused request");

        for (int attempt = 0; attempt < 2; attempt++) {
            mvc.perform(post(path).cookie(cookie).header("Origin", ORIGIN).header("X-CSRF-Token", csrf)
                    .header("Idempotency-Key", "h3-" + suffix).contentType("application/json").content(allow))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.candidateId").value(ids.candidate()))
                    .andExpect(jsonPath("$.decision").value("approved"))
                    .andExpect(jsonPath("$.revision").value(1))
                    .andExpect(jsonPath("$.publicChanged").value(false));
        }
        assertEquals(1, source.calls.size(), "the replayed key answers again without sending again");
        assertEquals(1, decisionCount(ids.relationTarget()));
        assertEquals("ALLOW", jdbc.queryForObject("SELECT status FROM review_targets WHERE id = ?", String.class,
                ids.relationTarget()));
        assertEquals("ALLOW", jdbc.queryForObject("SELECT status FROM review_targets WHERE id = ?", String.class,
                ids.candidate()), "the candidate follows its relations at once");
        mvc.perform(post(path).cookie(cookie).header("Origin", ORIGIN).header("X-CSRF-Token", csrf)
                .header("Idempotency-Key", "h3-" + suffix).contentType("application/json")
                .content(decisionBody("reject", ids.relation(), 0))).andExpect(status().isConflict())
                .andExpect(jsonPath("$.error.code").value("IDEMPOTENCY_CONFLICT"));

        // No session: refused before the service.
        mvc.perform(post(path).header("Origin", ORIGIN).header("X-CSRF-Token", csrf).header("Idempotency-Key", "h4-" + suffix)
                .contentType("application/json").content(allow)).andExpect(status().isUnauthorized());
        // An id far longer than a target id names no candidate: 404, never a failed idempotency write.
        mvc.perform(post("/api/v1/admin/pipeline/candidates/" + "x".repeat(300) + "/decision").cookie(cookie)
                .header("Origin", ORIGIN).header("X-CSRF-Token", csrf).header("Idempotency-Key", "h5-" + suffix)
                .contentType("application/json").content(allow)).andExpect(status().isNotFound());

        Ids rejected = insertCandidateWithRelation("HOLD");
        mvc.perform(post("/api/v1/admin/pipeline/candidates/" + rejected.candidate() + "/decision").cookie(cookie)
                .header("Origin", ORIGIN).header("X-CSRF-Token", csrf).header("Idempotency-Key", "h6-" + suffix)
                .contentType("application/json").content(decisionBody("reject", rejected.relation(), 0)))
                .andExpect(status().isOk()).andExpect(jsonPath("$.decision").value("rejected"))
                .andExpect(jsonPath("$.publicChanged").value(false));

        // A relation the sync marked inactive (it left the latest AI reading) is refused before anything is sent.
        Ids left = insertCandidateWithRelation("HOLD");
        jdbc.update("UPDATE review_targets SET active = false WHERE id = ?", left.relationTarget());
        int sent = source.calls.size();
        mvc.perform(post("/api/v1/admin/pipeline/candidates/" + left.candidate() + "/decision").cookie(cookie)
                .header("Origin", ORIGIN).header("X-CSRF-Token", csrf).header("Idempotency-Key", "h7-" + suffix)
                .contentType("application/json").content(decisionBody("allow", left.relation(), 0)))
                .andExpect(status().isConflict());
        assertEquals(sent, source.calls.size());
        assertEquals(0, decisionCount(left.relationTarget()));
    }

    private String decisionBody(String decision, String relationId, long expectedRevision) {
        return "{\"decision\":\"" + decision + "\",\"reason\":\"검수 사유\","
                + (relationId == null ? "" : "\"relationId\":\"" + relationId + "\",")
                + "\"expectedRevision\":" + expectedRevision + ",\"expectedSourceVersion\":\"digest-" + suffix
                + "\",\"expectedSourceRevision\":\"7\"}";
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
        assertEquals("ALLOW", jdbc.queryForObject("SELECT status FROM review_targets WHERE id = ?", String.class,
                ids.candidate()), "the candidate follows its relations at once, before the sync reads the job again");
        assertEquals(1L, jdbc.queryForObject("SELECT current_revision FROM review_targets WHERE id = ?", Long.class,
                ids.relationTarget()));
        assertEquals(globalBefore + 1, global());
        // The audit row keeps the source version and revision the decision was made on.
        assertEquals("digest-" + suffix + "|7", jdbc.queryForObject("""
                SELECT detail->>'sourceVersion' || '|' || (detail->>'sourceRevision') FROM audit_logs
                WHERE action = 'review.decision' AND target_id = ?""", String.class, ids.relationTarget()));
        assertEquals(0, jdbc.queryForObject("SELECT count(*) FROM review_decisions WHERE target_id = ? AND job_id IS NOT NULL",
                Integer.class, ids.relationTarget()), "an approval creates no job");
        assertEquals("applied", intentStatus("key"));

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
        assertEquals(0, jdbc.queryForObject("SELECT count(*) FROM idempotency_records WHERE idem_key LIKE ?", Integer.class,
                "%-" + suffix), "a request refused before the source stores nothing, so the same key can be sent again");
    }

    @Test
    void aDefiniteRefusalClosesTheIntentAndTheKeyReplaysIt() {
        Ids ids = insertCandidateWithRelation("HOLD");
        source.next = "source_revision_conflict";
        assertEquals(ErrorCode.REVISION_CONFLICT, code(() -> decide(ids, "d1")));
        assertEquals("refused|source_revision_conflict", intentStatus("d1") + "|" + intentCode("d1"));
        source.next = null;
        assertEquals(ErrorCode.REVISION_CONFLICT, code(() -> decide(ids, "d1")), "the key replays the refusal");
        assertEquals(1, source.calls.size(), "and never sends it again");

        source.next = "review_candidate_ineligible";
        assertEquals(ErrorCode.VALIDATION_FAILED, code(() -> decide(ids, "d2")), "a deterministic check is never overridden");
        assertEquals("refused", intentStatus("d2"));

        assertEquals(0, decisionCount(ids.relationTarget()));
        assertEquals("HOLD", jdbc.queryForObject("SELECT status FROM review_targets WHERE id = ?", String.class,
                ids.relationTarget()));
    }

    @Test
    void aTemporaryAnswerKeepsTheIntentOpenAndTheSameKeySendsItAgain() {
        Ids ids = insertCandidateWithRelation("HOLD");
        source.next = "review_call_in_flight";
        CustomException busy = assertThrows(CustomException.class, () -> decide(ids, "t1"));
        assertEquals(ErrorCode.REVISION_CONFLICT, busy.getErrorCode());
        assertTrue(busy.isRetryable());
        assertEquals("pending|review_call_in_flight", intentStatus("t1") + "|" + intentCode("t1"));

        // Not read as a rights revocation: only "unavailable now".
        source.next = "upstream_unavailable";
        CustomException unavailable = assertThrows(CustomException.class, () -> decide(ids, "t1"));
        assertEquals(ErrorCode.SOURCE_UNAVAILABLE, unavailable.getErrorCode());
        assertTrue(unavailable.isRetryable());

        source.next = null;
        assertEquals("approved", decide(ids, "t1").decision());
        assertEquals(3, source.calls.size(), "the same operation was sent each time");
        assertEquals(1, source.calls.stream().map(c -> c.substring(c.lastIndexOf('|'))).distinct().count());
        assertEquals(1, decisionCount(ids.relationTarget()));
    }

    @Test
    void aDecisionTheSourceAppliedIsSettledEvenAfterTheProjectionMovedOn() {
        Ids ids = insertCandidateWithRelation("HOLD");
        source.loseReply = true;
        assertEquals(ErrorCode.SOURCE_UNAVAILABLE, code(() -> decide(ids, "l1")));
        assertEquals("pending", intentStatus("l1"));
        assertEquals(0, decisionCount(ids.relationTarget()), "the app has only the intent so far");

        // The sync moves on: a new source version becomes current and the old row's projection changes.
        jdbc.update("UPDATE review_targets SET is_current = false, source_revision = '9' WHERE id = ?", ids.relationTarget());
        jdbc.update("""
                INSERT INTO review_targets (id, target_type, source_job_id, external_id, source_version, candidate_id,
                                            status, source_revision, updated_at)
                SELECT ?, target_type, source_job_id, external_id, 'digest-next-' || ?, candidate_id, 'ALLOW', '1', now()
                FROM review_targets WHERE id = ?""", "rt-" + UUID.randomUUID(), suffix, ids.relationTarget());

        source.loseReply = false;
        assertTrue(decisions.reconcile(Instant.now().plusSeconds(1), 1000) >= 1);
        assertEquals("applied", intentStatus("l1"));
        assertEquals(1, decisionCount(ids.relationTarget()), "settled on the target the intent fixed");
        assertEquals("ALLOW|1", jdbc.queryForObject("SELECT status || '|' || current_revision FROM review_targets WHERE id = ?",
                String.class, ids.relationTarget()));
        assertEquals("digest-" + suffix + "|7", jdbc.queryForObject("""
                SELECT detail->>'sourceVersion' || '|' || (detail->>'sourceRevision') FROM audit_logs
                WHERE action = 'review.decision' AND target_id = ?""", String.class, ids.relationTarget()),
                "the audit keeps what the source checked, not the projection's later revision");
        int calls = source.calls.size();
        assertEquals("approved", decide(ids, "l1").decision(), "the key now replays the settled decision");
        assertEquals(calls, source.calls.size());

        // A lost reply the administrator retries is settled by that retry too.
        Ids other = insertCandidateWithRelation("HOLD");
        source.loseReply = true;
        assertEquals(ErrorCode.SOURCE_UNAVAILABLE, code(() -> decide(other, "l2")));
        source.loseReply = false;
        assertEquals("approved", decide(other, "l2").decision());
        assertEquals(1, decisionCount(other.relationTarget()));
    }

    @Test
    void theReconcilerReachesEveryOpenIntentAndOneFailureStopsNoOther() {
        // Never seen by the source (refused before recording, then nobody retried): the lookup never settles it.
        Ids unseen = insertCandidateWithRelation("HOLD");
        source.next = "review_unconfirmed";
        assertEquals(ErrorCode.SOURCE_UNAVAILABLE, code(() -> decide(unseen, "u1")));
        // Its lookup fails outright.
        Ids broken = insertCandidateWithRelation("HOLD");
        assertEquals(ErrorCode.SOURCE_UNAVAILABLE, code(() -> decide(broken, "u2")));
        source.brokenLookups.add(operationOf("u2"));
        // Applied, reply lost: the one the reconciler must settle.
        Ids lost = insertCandidateWithRelation("HOLD");
        source.next = null;
        source.loseReply = true;
        assertEquals(ErrorCode.SOURCE_UNAVAILABLE, code(() -> decide(lost, "u3")));
        source.loseReply = false;

        int open = jdbc.queryForObject("SELECT count(*) FROM review_decision_intents WHERE status IN ('pending', 'blocked')",
                Integer.class);
        Instant before = Instant.now().plusSeconds(1);
        for (int run = 0; run <= open && !"applied".equals(intentStatus("u3")); run++) {
            decisions.reconcile(before, 1);
        }
        assertEquals("applied", intentStatus("u3"), "a batch of one still reaches it behind intents that never settle");
        assertEquals("pending", intentStatus("u1"), "a decision the source never saw is not sent for the administrator");
        assertEquals("pending", intentStatus("u2"));
        source.brokenLookups.clear();
    }

    @Test
    void aRetryThatReadTheRecordBeforeARefusalCommittedReplaysTheStoredRefusal() throws Exception {
        Ids ids = insertCandidateWithRelation("HOLD");
        CountDownLatch inReview = new CountDownLatch(1);
        CountDownLatch answer = new CountDownLatch(1);
        CountDownLatch atIntent = new CountDownLatch(1);
        CountDownLatch readIntent = new CountDownLatch(1);
        source.next = "source_revision_conflict";
        source.beforeAnswer = () -> {
            inReview.countDown();
            await(answer);
        };
        // Only the retry reads the intent by its record; hold it between its record read and its intent read.
        doAnswer(call -> {
            atIntent.countDown();
            await(readIntent);
            return call.callRealMethod();
        }).when(reviews).intentForRecord(anyString(), anyBoolean());

        ExecutorService pool = Executors.newFixedThreadPool(2);
        try {
            Future<ErrorCode> first = pool.submit(() -> code(() -> decide(ids, "race")));
            assertTrue(inReview.await(10, TimeUnit.SECONDS), "the first request is at the AI source");
            Future<ErrorCode> retry = pool.submit(() -> code(() -> decide(ids, "race")));
            assertTrue(atIntent.await(10, TimeUnit.SECONDS), "the retry read the record while it was processing");
            answer.countDown();
            assertEquals(ErrorCode.REVISION_CONFLICT, first.get(10, TimeUnit.SECONDS), "the refusal is committed");
            readIntent.countDown();
            assertEquals(ErrorCode.REVISION_CONFLICT, retry.get(10, TimeUnit.SECONDS), "the retry replays it, not a 500");
        } finally {
            answer.countDown();
            readIntent.countDown();
            pool.shutdownNow();
        }
        assertEquals("refused", intentStatus("race"));
        assertEquals(0, source.lookups.get(), "a settled intent is never looked up");
        assertEquals(1, source.calls.size());
    }

    @Test
    void aContractMismatchIsNeverResentAndOnlyALookupSettlesIt() {
        Ids ids = insertCandidateWithRelation("HOLD");
        source.next = "idempotency_conflict";
        assertEquals(ErrorCode.INTERNAL_ERROR, code(() -> decide(ids, "c1")));
        assertEquals("blocked|idempotency_conflict", intentStatus("c1") + "|" + intentCode("c1"));

        source.next = null;
        assertEquals(ErrorCode.INTERNAL_ERROR, code(() -> decide(ids, "c1")), "the ledger has no such operation");
        assertEquals(1, source.calls.size(), "a blocked intent is never resent");

        // The wire's upper-case decision is the same command as the intent's.
        source.ledger.put(operationOf("c1"), command(ids, Lookup.RECORDED, "ALLOW", "7", true));
        assertEquals("approved", decide(ids, "c1").decision());
        assertEquals("applied", intentStatus("c1"));
    }

    @Test
    void anOperationHoldingAnotherCommandUnderTheSameIdIsNeverSettled() {
        // The ledger kept another body under this operation id (e.g. the app ledger was restored on its own): the POST is an
        // idempotency_conflict and no lookup may turn the other command into this intent's decision. Each reconcile takes its
        // cutoff after the intent it checks exists (openIntents reads created_at < cutoff), however long the earlier cases took.
        for (Function<Ids, Operation> other : List.<Function<Ids, Operation>>of(
                ids -> command(ids, Lookup.RECORDED, "reject", "7", true),
                ids -> command(ids, Lookup.RECORDED, "allow", "6", true),
                ids -> command(ids, Lookup.RECORDED, "allow", "7", false),
                ids -> new Operation(Lookup.RECORDED, "job-other", "rel-1", "allow", "digest-" + suffix, "7", true),
                ids -> new Operation(Lookup.RECORDED, ids.job(), "rel-other", "allow", "digest-" + suffix, "7", true))) {
            Ids ids = insertCandidateWithRelation("HOLD");
            String key = "m" + source.calls.size();
            source.next = "idempotency_conflict";
            assertEquals(ErrorCode.INTERNAL_ERROR, code(() -> decide(ids, key)));
            source.next = null;
            source.ledger.put(operationOf(key), other.apply(ids));

            assertEquals(ErrorCode.INTERNAL_ERROR, code(() -> decide(ids, key)), "the retry does not settle it");
            decisions.reconcile(Instant.now().plusSeconds(1), 1000);
            assertEquals("blocked", intentStatus(key), "nor does the reconciler");
            assertEquals(0, decisionCount(ids.relationTarget()));
        }

        // A pending intent whose id the ledger reports, unconfirmed, for another command is blocked instead of resent.
        Ids ids = insertCandidateWithRelation("HOLD");
        source.next = "review_unconfirmed";
        assertEquals(ErrorCode.SOURCE_UNAVAILABLE, code(() -> decide(ids, "mu")));
        source.next = null;
        source.ledger.put(operationOf("mu"), command(ids, Lookup.UNCONFIRMED, "reject", "7", true));
        int calls = source.calls.size();
        decisions.reconcile(Instant.now().plusSeconds(1), 1000);
        assertEquals("blocked|" + ReviewDecisionService.OPERATION_MISMATCH + ":review_unconfirmed",
                intentStatus("mu") + "|" + intentCode("mu"), "the answer that left it pending is kept");
        assertEquals(calls, source.calls.size(), "never resent");
        assertEquals(ErrorCode.INTERNAL_ERROR, code(() -> decide(ids, "mu")));
        assertEquals(0, decisionCount(ids.relationTarget()));
    }

    @Test
    void theRetryableServiceAnswersKeepTheIntentOpenForTheSameKey() {
        for (String code : List.of("runtime_busy", "runtime_unavailable", "service_busy", "queue_full",
                "service_configuration_invalid")) {
            Ids ids = insertCandidateWithRelation("HOLD");
            source.next = code;
            CustomException refused = assertThrows(CustomException.class, () -> decide(ids, "t-" + code));
            assertEquals(ErrorCode.SOURCE_UNAVAILABLE, refused.getErrorCode(), code);
            assertTrue(refused.isRetryable(), code);
            assertEquals("pending|" + code, intentStatus("t-" + code) + "|" + intentCode("t-" + code));

            source.next = null;
            assertEquals("approved", decide(ids, "t-" + code).decision(), code + ": the same key sends it again");
        }
        assertEquals(Refusal.CONTRACT, Refusal.of("a_code_this_app_does_not_know"), "unknown codes stay blocked");
    }

    @Test
    void theOperationIdCoversTheWholeIdempotencyScope() {
        Ids first = insertCandidateWithRelation("HOLD");
        Ids second = insertCandidateWithRelation("HOLD");
        decide(first, "same");
        decide(second, "same");
        assertEquals(2, source.calls.size());
        assertNotEquals(operation(source.calls.get(0)), operation(source.calls.get(1)),
                "one key on two targets is two AI operations");
        assertNotEquals(ReviewDecisionService.operationId("a", "/p", "k"), ReviewDecisionService.operationId("b", "/p", "k"));
        assertTrue(ReviewDecisionService.operationId("a", "/p", "k").matches("[A-Za-z0-9_.-]{1,120}"));
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
    void theTablesKeepTheirHistoryAndIdentity() {
        Ids ids = insertCandidateWithRelation("HOLD");
        decide(ids, "h1");
        String target = ids.relationTarget();

        refusedBy("append-only", "UPDATE review_decisions SET reason = 'x' WHERE target_id = ?", target);
        refusedBy("append-only", "DELETE FROM review_decisions WHERE target_id = ?", target);
        refusedBy("identity is immutable", "UPDATE review_targets SET source_version = 'x' WHERE id = ?", target);
        refusedBy("identity is immutable", "UPDATE review_targets SET external_id = 'x' WHERE id = ?", target);
        refusedBy("moves by one", "UPDATE review_targets SET current_revision = current_revision + 2 WHERE id = ?", target);
        jdbc.update("UPDATE review_targets SET source_revision = '8', status = 'HOLD' WHERE id = ?", target);
        refusedBy("ck_review_decisions_admin", """
                INSERT INTO review_decisions (target_id, decision, reason, admin_id, decided_at, revision, global_revision, origin)
                VALUES (?, 'reject', '사유', ?, now(), 2, 999999999, 'admin')""", target, admin.adminId());
        refusedBy("command is immutable", "UPDATE review_decision_intents SET reason = 'x' WHERE target_id = ?", target);
        refusedBy("is settled", "UPDATE review_decision_intents SET status = 'pending', decision_id = NULL WHERE target_id = ?",
                target);
        refusedBy("are kept", "DELETE FROM review_decision_intents WHERE target_id = ?", target);
    }

    /** The statement fails, and for the named rule, not for another constraint it happens to break. */
    private void refusedBy(String rule, String sql, Object... args) {
        DataAccessException refused = assertThrows(DataAccessException.class, () -> jdbc.update(sql, args), sql);
        String message = refused.getMostSpecificCause().getMessage();
        assertTrue(message.contains(rule), () -> sql + " failed for another reason: " + message);
    }

    @Test
    void withoutAConfiguredSourceADecisionFailsClosed() {
        var unconfigured = new RelationReviewClient.Unconfigured();
        Refused refused = assertThrows(Refused.class, () -> unconfigured.review("j", "c", "v", "1", "allow", "op"));
        assertEquals(Refusal.UNCONFIRMED, refused.refusal());
        assertFalse(refused.getMessage().isBlank());
        assertEquals(Refusal.UNCONFIRMED, assertThrows(Refused.class, () -> unconfigured.lookup("j", "op")).refusal());
        assertEquals(Refusal.CONTRACT, Refusal.of("a_code_this_app_does_not_know"));
    }

    // ---- the real AI adapter over the S3 transport (4-C) ---------------------------------------------------------------------

    /** The service with {@link AiRelationReviewClient} over a stubbed S3 transport, instead of the fake source. */
    private ReviewDecisionService overTransport(RelationClient relations) {
        return new ReviewDecisionService(reviews, idempotencyStore, auditRepository, new AiRelationReviewClient(relations),
                transactions, objectMapper, Clock.systemUTC());
    }

    /** A candidate and one HOLD relation whose ids, version and revision fit the AI review contract. */
    private Ids insertContractCandidate(String sourceRevision) {
        String job = "job-s3-" + UUID.randomUUID();
        String candidateCandidateId = "cand-" + UUID.randomUUID();
        String candidateTarget = "rt-" + UUID.randomUUID();
        String relationTarget = "rt-" + UUID.randomUUID();
        String relation = "rc-" + Canonical.sha256(suffix + relationTarget);
        Instant now = Instant.now();
        String sql = """
                INSERT INTO review_targets (id, target_type, source_job_id, external_id, source_version, candidate_id,
                                            status, source_revision, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 'HOLD', ?, ?)
                """;
        jdbc.update(sql, candidateTarget, "candidate", job, candidateCandidateId, contractVersion(), candidateCandidateId,
                sourceRevision, Timestamp.from(now));
        jdbc.update(sql, relationTarget, "relation", job, relation, contractVersion(), candidateCandidateId, sourceRevision,
                Timestamp.from(now));
        return new Ids(job, candidateTarget, relationTarget, relation);
    }

    private String contractVersion() {
        return Canonical.sha256("version-" + suffix);
    }

    private ReviewDecision.Response decideOver(ReviewDecisionService service, Ids ids, String key, String sourceRevision) {
        return service.decide(ids.candidate(), new ReviewDecision.Request("allow", "검수 사유", ids.relation(), 0L,
                contractVersion(), sourceRevision), key + "-" + suffix, admin, "r");
    }

    @Test
    void aLostReplyOverTheRealAdapterStaysOpenAndTheReconcilerSettlesItFromTheLedger() {
        Ids ids = insertContractCandidate("7");
        var relations = mock(RelationClient.class);
        when(relations.review(eq(ids.job()), any()))
                .thenThrow(new AiTransportException(AiOperation.REVIEW, "req-1",
                        AiTransportException.Failure.TIMEOUT, OptionalInt.empty(), "HttpTimeoutException"));
        ReviewDecisionService service = overTransport(relations);

        CustomException lost = assertThrows(CustomException.class, () -> decideOver(service, ids, "a1", "7"));

        assertEquals(ErrorCode.SOURCE_UNAVAILABLE, lost.getErrorCode());
        assertEquals("pending|" + AiRelationReviewClient.UNANSWERED, intentStatus("a1") + "|" + intentCode("a1"));
        assertEquals(0, decisionCount(ids.relationTarget()));

        String operationId = operationOf("a1");
        Instant at = Instant.now();
        when(relations.operation(ids.job(), operationId)).thenReturn(
                new RelationOperationStatus(operationId, ids.job(), ids.relation(),
                        RelationDecision.ALLOW, "reviewer", contractVersion(), "7",
                        new RelationOperationStatus.Review(
                                RelationOperationStatus.ReviewState.APPLIED, Optional.of("8"), Optional.of(at)),
                        new RelationOperationStatus.Revalidation(
                                RelationOperationStatus.RevalidationState.NOT_REQUESTED, 0, Optional.empty(),
                                Optional.empty(), Optional.empty(), Optional.empty(), Optional.empty()),
                        RelationOperationStatus.Next.NONE, Optional.empty(), at, at, Optional.empty()));

        service.reconcile(Instant.now().plusSeconds(60), 1000);

        assertEquals("applied", intentStatus("a1"), "settled from the ledger, not resent blindly");
        assertEquals(1, decisionCount(ids.relationTarget()));
    }

    @Test
    void aStoredCommandTheContractCannotCarryIsADefiniteRefusalAndIsNeverSent() {
        Ids ids = insertContractCandidate("0");
        var relations = mock(RelationClient.class);
        ReviewDecisionService service = overTransport(relations);

        CustomException refused = assertThrows(CustomException.class, () -> decideOver(service, ids, "a2", "0"));

        assertEquals(ErrorCode.VALIDATION_FAILED, refused.getErrorCode());
        assertEquals("refused|" + AiRelationReviewClient.REQUEST_INVALID, intentStatus("a2") + "|" + intentCode("a2"));
        verify(relations, never())
                .review(any(), any());
        assertEquals(refused.getErrorCode(), assertThrows(CustomException.class,
                () -> decideOver(service, ids, "a2", "0")).getErrorCode(), "the key replays the refusal");
    }

    @Test
    void aReplayedLegacyOperationOverTheRealAdapterIsBlockedAndNeverSettled() {
        Ids ids = insertContractCandidate("7");
        var relations = mock(RelationClient.class);
        Instant at = Instant.now();
        // The service's 200 for the same key and command of an operation applied under the earlier contract.
        when(relations.review(eq(ids.job()), any())).thenAnswer(call -> {
            RelationReviewRequest sent = call.getArgument(1);
            return new RelationOperationAcknowledgement(RelationOperationAcknowledgement.Disposition.REVIEW_RECORDED_OR_REPLAYED,
                    new RelationOperationStatus(sent.operationId(), ids.job(), ids.relation(), RelationDecision.ALLOW, "reviewer",
                            contractVersion(), "7",
                            new RelationOperationStatus.Review(RelationOperationStatus.ReviewState.APPLIED, Optional.of("8"),
                                    Optional.of(at)),
                            new RelationOperationStatus.Revalidation(RelationOperationStatus.RevalidationState.VERIFIED, 1,
                                    Optional.empty(), Optional.empty(), Optional.empty(), Optional.empty(), Optional.empty()),
                            RelationOperationStatus.Next.NONE,
                            Optional.of(RelationOperationStatus.Limitation.REVIEW_CONTRACT_CHANGED), at, at, Optional.empty()));
        });
        ReviewDecisionService service = overTransport(relations);

        assertThrows(CustomException.class, () -> decideOver(service, ids, "a3", "7"));

        assertEquals("blocked|" + AiRelationReviewClient.CONTRACT_CHANGED, intentStatus("a3") + "|" + intentCode("a3"));
        assertEquals(0, decisionCount(ids.relationTarget()), "history of the earlier contract is never an approval");
        assertEquals("HOLD", jdbc.queryForObject("SELECT status FROM review_targets WHERE id = ?", String.class,
                ids.relationTarget()));
        service.reconcile(Instant.now().plusSeconds(60), 1000);
        assertEquals(0, decisionCount(ids.relationTarget()), "nor does the reconciler settle it");
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
                "HOLD", Timestamp.from(now));
        jdbc.update(sql, relationTarget, "relation", job, "rel-1", "digest-" + suffix, candidateCandidateId, status,
                Timestamp.from(now));
        return new Ids(job, candidateTarget, relationTarget, "rel-1");
    }

    private String intentStatus(String key) {
        return intentColumn("status", key);
    }

    private String intentCode(String key) {
        return intentColumn("source_code", key);
    }

    private String intentColumn(String column, String key) {
        return jdbc.queryForObject("SELECT i." + column + " FROM review_decision_intents i JOIN idempotency_records r "
                + "ON r.id = i.idempotency_record_id WHERE r.idem_key = ?", String.class, key + "-" + suffix);
    }

    /** The command the intents of {@link #decide(Ids, String)} send, as the ledger would report it. */
    private Operation command(Ids ids, Lookup state, String decision, String sourceRevision, boolean currentContract) {
        return new Operation(state, ids == null ? null : ids.job(), "rel-1", decision, "digest-" + suffix, sourceRevision,
                currentContract);
    }

    private String operationOf(String key) {
        return intentColumn("operation_id", key);
    }

    private static void await(CountDownLatch latch) {
        try {
            if (!latch.await(10, TimeUnit.SECONDS)) throw new IllegalStateException("latch timed out");
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
            throw new IllegalStateException(interrupted);
        }
    }

    private static String operation(String call) {
        return call.substring(call.lastIndexOf('|') + 1);
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
