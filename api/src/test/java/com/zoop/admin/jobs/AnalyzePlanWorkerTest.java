package com.zoop.admin.jobs;

import java.time.*;
import java.time.temporal.ChronoUnit;
import java.util.*;
import java.util.concurrent.atomic.AtomicInteger;

import com.jayway.jsonpath.JsonPath;
import com.zoop.admin.auth.provision.AdminProvisioningService;
import com.zoop.admin.auth.service.AdminSessionCookie;
import com.zoop.admin.jobs.AnalyzePlanState.*;
import com.zoop.ai.*;
import com.zoop.ai.extraction.*;
import com.zoop.ai.plan.*;
import com.zoop.ai.relation.*;
import com.zoop.common.json.Canonical;
import com.zoop.common.request.RequestIdFilter;
import jakarta.servlet.http.Cookie;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;
import org.springframework.context.annotation.Primary;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.context.WebApplicationContext;

import static org.junit.jupiter.api.Assertions.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

/** Real public registration and PostgreSQL ledger; deterministic external-AI boundary probes, not actual-stack proof. */
@SpringBootTest(properties = {
        "ZOOP_AUTH_CSRF_ACTIVE_KEY_ID=test", "ZOOP_AUTH_CSRF_KEYS=test=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        "ZOOP_AUTH_ALLOWED_ORIGINS=https://zoop.example", "zoop.analysis.analyze-plan.enabled=false"
})
@Import(AnalyzePlanWorkerTest.World.class)
@EnabledIfEnvironmentVariable(named = "DB_URL", matches = "jdbc:postgresql:.*")
@Tag("auth-postgres")
class AnalyzePlanWorkerTest {
    private static final String ORIGIN = "https://zoop.example";
    private static final String PASSWORD = "Secure admin password 2026";
    private static final String D = "a".repeat(64);
    private static final PipelineJob.Delivery AVAILABLE = new PipelineJob.Delivery(PipelineJob.DeliveryState.AVAILABLE, Optional.empty());
    private static final List<PipelineJob.Receipt> RECEIPTS = List.of(new PipelineJob.Receipt("extract", "ready", Optional.empty()));

    @Autowired WebApplicationContext context;
    @Autowired RequestIdFilter requestIds;
    @Autowired AdminProvisioningService provisioning;
    @Autowired JdbcTemplate jdbc;
    @Autowired AnalyzePlanWorker worker;
    @Autowired Script script;
    @Autowired MutableClock clock;
    private MockMvc mvc;
    private Cookie cookie;
    private String csrf;
    private String job;

    @BeforeEach
    void preparePublicJob() throws Exception {
        mvc = MockMvcBuilders.webAppContextSetup(context).addFilters(requestIds).build();
        script.reset();
        clock.afterAdvance = () -> {};
        String suffix = UUID.randomUUID().toString();
        String email = "worker-" + suffix + "@example.com";
        provisioning.provision(email, "Worker Probe", PASSWORD, "worker-provision-" + suffix);
        var login = mvc.perform(post("/api/v1/admin/auth/login").header("Origin", ORIGIN).contentType("application/json")
                .content("{\"email\":\"" + email + "\",\"password\":\"" + PASSWORD + "\"}"))
                .andExpect(status().isOk()).andReturn().getResponse();
        cookie = login.getCookie(AdminSessionCookie.NAME);
        assertNotNull(cookie);
        csrf = JsonPath.read(login.getContentAsString(), "$.csrfToken");
        var created = mvc.perform(post("/api/v1/admin/jobs").cookie(cookie).header("Origin", ORIGIN)
                .header("X-CSRF-Token", csrf).header("Idempotency-Key", "worker-create-" + suffix)
                .contentType("application/json").content("{\"kind\":\"analyze_plan\",\"reason\":\"합성 경계 시험\",\"plan\":{\"planId\":\""
                        + script.reference.planId() + "\",\"planDigest\":\"" + script.reference.planDigest() + "\"}}"))
                .andExpect(status().isAccepted()).andReturn().getResponse();
        job = JsonPath.read(created.getContentAsString(), "$.job.id");
        assertEquals(0, script.remoteCalls.get(), "create commits before any AI call");
    }

    @Test
    void completesOnlyPairedResultObservationsAndPersistsNoPayload() {
        assertTrue(worker.runOnce());
        terminal("succeeded", null);
        assertEquals(1, script.s2Submits);
        assertEquals(1, script.s3Submits);
        assertTrue(script.events.indexOf("s2-result") < script.events.indexOf("s3-submit"));
        String checkpoints = jdbc.queryForObject("SELECT s2_checkpoint::text || s3_checkpoint::text FROM analysis_plan_units WHERE plan_id=?",
                String.class, script.reference.planId());
        assertNotNull(checkpoints);
        assertFalse(checkpoints.contains("secret-model-text"));
        assertTrue(checkpoints.contains(Canonical.sha256(script.payload(script.s2.jobId(), D))));
        assertEquals(1, jdbc.queryForObject("SELECT count(*) FROM analysis_plan_units WHERE plan_id=? AND s3_input_digest=?",
                Integer.class, script.reference.planId(), D));
        assertTrue(script.admissionReads >= 5, "current authority checked per action and final completion");
    }

    @Test
    void lostAcceptedSubmitIsReconciledByStatusWithoutAnotherSubmit() {
        script.mode = Mode.LOST_ACCEPTED_SUBMIT;
        assertTrue(worker.runOnce());
        terminal("succeeded", null);
        assertEquals(1, script.s2Submits);
        assertEquals(0, script.recoveries);
    }

    @Test
    void reserved404RepostsOnlyTheExactStoredSubmission() {
        script.mode = Mode.RESERVED_SUBMIT;
        assertTrue(worker.runOnce());
        terminal("succeeded", null);
        assertEquals(2, script.s2Submits);
        assertEquals(List.of(script.s2, script.s2), script.submissions);
    }

    @Test
    void acceptedThen404IsLedgerLossNotPermissionToSubmit() {
        script.mode = Mode.ACCEPTED_THEN_MISSING;
        assertTrue(worker.runOnce());
        terminal("failed", "ai_state_missing");
        assertEquals(1, script.s2Submits);
        assertEquals(0, script.s3Submits);
    }

    @Test
    void resultOwnBindingCannotBorrowTheOlderReadyStatus() {
        script.mode = Mode.RESULT_WRONG_BINDING;
        assertTrue(worker.runOnce());
        terminal("failed", "ai_binding_mismatch");
        assertEquals(0, script.s3Submits);
        assertEquals(0, observedResults());
    }

    @Test
    void resultOwnWithheldGateDoesNotBecomeAReadyObservation() {
        script.mode = Mode.RESULT_WITHHELD;
        assertTrue(worker.runOnce());
        terminal("failed", "result_withheld");
        assertEquals(0, script.s3Submits);
        assertEquals(0, observedResults());
    }

    @Test
    void resultOwnUnknownUsageBlocksRecoveryAndCompletion() {
        script.mode = Mode.RESULT_UNKNOWN_USAGE;
        assertTrue(worker.runOnce());
        terminal("failed", "outcome_unknown");
        assertEquals(0, script.recoveries);
        assertEquals(0, script.s3Submits);
        assertEquals(0, observedResults());
    }

    @Test
    void s3ResultMustMatchTheStatusDigestCommittedBeforeTheFetch() {
        script.mode = Mode.S3_RESULT_REBOUND;
        assertTrue(worker.runOnce());
        terminal("failed", "ai_binding_mismatch");
        assertEquals(1, observedResults());
        assertEquals(D, jdbc.queryForObject("SELECT s3_input_digest FROM analysis_plan_units WHERE plan_id=?",
                String.class, script.reference.planId()));
    }

    @Test
    void explicitResumableIdleRecoveryUsesSameIdAndDurableAllowance() {
        script.mode = Mode.RECOVERY_LIMIT;
        assertTrue(worker.runOnce());
        terminal("failed", "recovery_limit");
        assertEquals(3, script.recoveries);
        assertEquals(Set.of(script.s2.jobId()), new HashSet<>(script.recoveredIds));
        assertTrue(jdbc.queryForObject("SELECT attempts::text FROM analysis_jobs WHERE id=?", String.class, job)
                .contains("recoveryDispatches"));
    }

    @Test
    void publicRetryGetsANewBoundedRecoveryAllowanceWithoutChangingAiIds() throws Exception {
        script.mode = Mode.RECOVERY_LIMIT;
        assertTrue(worker.runOnce());
        terminal("failed", "recovery_limit");
        assertEquals(3, script.recoveries);
        String original = job;
        var response = mutate("retry").andExpect(status().isAccepted()).andReturn().getResponse();
        job = JsonPath.read(response.getContentAsString(), "$.job.id");
        assertNotEquals(original, job);
        assertTrue(worker.runOnce());
        terminal("failed", "recovery_limit");
        assertAll(
                () -> assertEquals(6, script.recoveries, "three recover intents for each distinct app attempt"),
                () -> assertEquals(Set.of(script.s2.jobId()), new HashSet<>(script.recoveredIds)),
                () -> assertEquals(1, script.s2Submits, "continuation must not submit a new AI identity"),
                () -> assertEquals(0, script.s3Submits),
                () -> assertEquals(3, jdbc.queryForObject(
                        "SELECT sum((entry->'recoveryDispatches'->>?)::integer)::integer FROM analysis_jobs j,"
                                + "jsonb_array_elements(j.attempts) entry WHERE j.id=?",
                        Integer.class, script.s2.jobId(), original)),
                () -> assertEquals(3, jdbc.queryForObject(
                        "SELECT COALESCE(sum((entry->'recoveryDispatches'->>?)::integer),0)::integer FROM analysis_jobs j,"
                                + "jsonb_array_elements(j.attempts) entry WHERE j.id=?",
                        Integer.class, script.s2.jobId(), job)));
    }

    @Test
    void reconcileOnlyNeverDispatchesRecovery() {
        script.mode = Mode.RECONCILE_ONLY;
        assertTrue(worker.runOnce());
        terminal("failed", "outcome_unknown");
        assertEquals(0, script.recoveries);
    }

    @Test
    void cancellationSettlesKnownRunningChildAndNeverStartsS3() {
        script.mode = Mode.CANCEL_RUNNING;
        script.afterSubmit = this::cancelPublic;
        assertTrue(worker.runOnce());
        terminal("cancelled", null);
        assertEquals(1, script.cancels);
        assertEquals(0, script.s3Submits);
    }

    @Test
    void cancelReadyRefusalIsSettledWithoutFetchingOrStartingAnotherUnit() {
        script.mode = Mode.CANCEL_READY_RACE;
        script.afterSubmit = this::cancelPublic;
        assertTrue(worker.runOnce());
        terminal("cancelled", null);
        assertEquals(1, script.cancels);
        assertEquals(0, script.s3Submits);
        assertEquals(0, observedResults());
    }

    @Test
    void cancellationOfUnresolvedIntentStaysUnknownAndRetryIsDenied() throws Exception {
        script.mode = Mode.CANCEL_UNKNOWN;
        script.afterSubmit = this::cancelPublic;
        assertTrue(worker.runOnce());
        terminal("cancelled", "outcome_unknown");
        assertEquals(1, script.s2Submits);
        assertEquals(0, script.cancels);
        mutate("retry").andExpect(status().isConflict());
    }

    @Test
    void cancellationAtDeadlineKeepsAcceptedNonterminalChildUnknownAndDeniesPublicRetry() throws Exception {
        script.mode = Mode.WAIT_FOREVER;
        clock.afterAdvance = () -> {
            clock.afterAdvance = () -> {};
            clock.advance(Duration.ofMinutes(2));
            cancelPublic();
        };
        assertTrue(worker.runOnce());
        assertAll(
                () -> terminal("cancelled", "outcome_unknown"),
                () -> assertEquals(1, script.s2Submits),
                () -> assertEquals(0, script.s3Submits),
                () -> assertEquals(0, script.cancels, "the deadline prevented cancellation settlement"),
                this::assertPublicRetryDenied);
    }

    @Test
    void cancellationReadFailureExhaustionKeepsAcceptedChildUnknownAndDeniesPublicRetry() throws Exception {
        script.mode = Mode.CANCEL_STATUS_FAILURES;
        script.afterSubmit = this::cancelPublic;
        assertTrue(worker.runOnce());
        assertAll(
                () -> terminal("cancelled", "outcome_unknown"),
                () -> assertEquals(1, script.s2Submits),
                () -> assertEquals(0, script.s3Submits),
                () -> assertEquals(0, script.cancels, "status never established a cancellation-safe remote state"),
                this::assertPublicRetryDenied);
    }

    @Test
    void finalCurrentAdmissionRefusalRetainsPairedHistoryButCannotSucceed() {
        script.mode = Mode.FINAL_INACTIVE;
        assertTrue(worker.runOnce());
        terminal("failed", "policy_expired");
        assertEquals(2, observedResults());
    }

    @ParameterizedTest
    @ValueSource(strings = {"policy_disabled", "policy_expired", "policy_replaced"})
    void retiredPolicyRefusalBetweenActiveAdmissionReadAndS3SubmitBlocksPublicRetry(String retirementCode) throws Exception {
        script.mode = Mode.S3_POLICY_RETIRED;
        script.retirementCode = retirementCode;
        assertTrue(worker.runOnce());
        terminal("failed", retirementCode);
        assertAll(
                () -> assertEquals(1, observedResults(), "S2 result was durable before the between-stage retirement"),
                () -> assertEquals(1, script.s3Submits, "the exact S3 command reached the rejecting transport"),
                () -> assertFalse(script.s3Exists, "policy retirement refused S3 acceptance"),
                () -> assertEquals("authority:" + retirementCode, jdbc.queryForObject(
                        "SELECT (s3_checkpoint->>'failureCategory') || ':' || (s3_checkpoint->>'failureCode')"
                                + " FROM analysis_plan_units WHERE plan_id=?",
                        String.class, script.reference.planId())),
                this::assertPublicRetryDenied);
    }

    @Test
    void restorableS3PermissionRefusalStillAllowsSamePlanContinuation() throws Exception {
        script.mode = Mode.S3_PERMISSION_REFUSED;
        assertTrue(worker.runOnce());
        terminal("failed", "upstream_not_allowed");
        assertEquals(1, observedResults());
        script.mode = Mode.NORMAL;
        var retried = mutate("retry").andExpect(status().isAccepted()).andReturn().getResponse();
        job = JsonPath.read(retried.getContentAsString(), "$.job.id");
        assertTrue(worker.runOnce());
        terminal("succeeded", null);
        assertEquals(1, script.s2Submits);
        assertEquals(2, script.s3Submits, "retry reconciles the same refused S3 identity after permission restoration");
    }

    @Test
    void administrativeRetryContinuesTheSamePlanAndLeavesOldOutcomeFrozen() throws Exception {
        script.mode = Mode.RESULT_WITHHELD;
        assertTrue(worker.runOnce());
        terminal("failed", "result_withheld");
        String firstJob = job;
        script.mode = Mode.NORMAL;
        var retried = mutate("retry").andExpect(status().isAccepted()).andReturn().getResponse();
        job = JsonPath.read(retried.getContentAsString(), "$.job.id");
        assertNotEquals(firstJob, job);
        assertTrue(worker.runOnce());
        terminal("succeeded", null);
        assertEquals("failed", jdbc.queryForObject("SELECT status FROM analysis_jobs WHERE id=?", String.class, firstJob));
        assertEquals("result_withheld", jdbc.queryForObject("SELECT error->>'code' FROM analysis_jobs WHERE id=?", String.class, firstJob));
        assertEquals(1, script.s2Submits);
        assertEquals(1, script.s3Submits);
        assertEquals(1, jdbc.queryForObject("SELECT count(*) FROM analysis_plans WHERE plan_id=?", Integer.class, script.reference.planId()));
    }

    @Test
    void oneJvmCannotClaimAgainWhileItAlreadyOwnsAnAttempt() {
        script.afterSubmit = () -> assertFalse(worker.runOnce());
        assertTrue(worker.runOnce());
        terminal("succeeded", null);
    }

    @Test
    void waitingChildUsesPersistedFiniteDeadlineWithoutAnotherDispatch() {
        script.mode = Mode.WAIT_FOREVER;
        assertTrue(worker.runOnce());
        terminal("failed", "worker_deadline");
        assertEquals(1, script.s2Submits);
        assertEquals(0, script.recoveries);
        assertEquals(0, script.s3Submits);
    }

    private int observedResults() {
        return jdbc.queryForObject("SELECT (CASE WHEN s2_checkpoint->>'state'='result_observed' THEN 1 ELSE 0 END)"
                + "+ (CASE WHEN s3_checkpoint->>'state'='result_observed' THEN 1 ELSE 0 END) FROM analysis_plan_units WHERE plan_id=?",
                Integer.class, script.reference.planId());
    }

    private void terminal(String status, String error) {
        assertEquals(status, jdbc.queryForObject("SELECT status FROM analysis_jobs WHERE id=?", String.class, job));
        assertEquals(error, jdbc.queryForObject("SELECT error->>'code' FROM analysis_jobs WHERE id=?", String.class, job));
    }

    private org.springframework.test.web.servlet.ResultActions mutate(String action) throws Exception {
        return mvc.perform(post("/api/v1/admin/jobs/{id}/" + action, job).cookie(cookie).header("Origin", ORIGIN)
                .header("X-CSRF-Token", csrf).header("Idempotency-Key", "worker-" + action + "-" + UUID.randomUUID())
                .contentType("application/json").content("{\"reason\":\"합성 취소·계속 시험\"}"));
    }

    private void cancelPublic() {
        try { mutate("cancel").andExpect(status().isOk()); }
        catch (Exception failure) { throw new AssertionError(failure); }
    }

    private void assertPublicRetryDenied() throws Exception {
        var response = mutate("retry").andReturn().getResponse();
        if (response.getStatus() == 202) {
            // A red regression must not leave an incorrectly admitted queued retry in the shared admin slot.
            String original = job;
            try {
                job = JsonPath.read(response.getContentAsString(), "$.job.id");
                mutate("cancel").andExpect(status().isOk());
            } finally {
                job = original;
            }
        }
        assertEquals(409, response.getStatus(), "unsafe or permanently retired plan must block the real public retry");
    }

    enum Mode { NORMAL, LOST_ACCEPTED_SUBMIT, RESERVED_SUBMIT, ACCEPTED_THEN_MISSING, RESULT_WRONG_BINDING,
        RESULT_WITHHELD, RESULT_UNKNOWN_USAGE, S3_RESULT_REBOUND, RECOVERY_LIMIT, RECONCILE_ONLY,
        CANCEL_RUNNING, CANCEL_UNKNOWN, CANCEL_READY_RACE, CANCEL_STATUS_FAILURES, FINAL_INACTIVE, WAIT_FOREVER,
        S3_POLICY_RETIRED, S3_PERMISSION_REFUSED }

    @TestConfiguration(proxyBeanMethods = false)
    static class World {
        @Bean @Primary MutableClock workerClock() { return new MutableClock(); }
        @Bean @Primary AnalyzePlanProperties workerProperties() {
            return new AnalyzePlanProperties(false, "app", Duration.ofMillis(100), Duration.ofMinutes(2),
                    Duration.ofSeconds(150), 5, 3, 16);
        }
        @Bean ServiceBinding workerBinding() { return ServiceBinding.of("https://synthetic.invalid", "app"); }
        @Bean Script workerScript(MutableClock clock) { return new Script(clock); }
        @Bean AnalyzePlanWorker worker(JdbcAnalyzePlanRepository repository, Script script, MutableClock clock,
                AnalyzePlanProperties properties, ServiceBinding binding) {
            return new AnalyzePlanWorker(repository, script.admission(), script.extraction(), script.relation(), clock,
                    properties, binding, clock::advance);
        }
    }

    static final class MutableClock extends Clock {
        // Shared auth timestamps round-trip through PostgreSQL at microsecond precision.
        private Instant now = Instant.now().truncatedTo(ChronoUnit.MICROS);
        Runnable afterAdvance = () -> {};
        void advance(Duration duration) {
            now = now.plus(duration);
            afterAdvance.run();
        }
        @Override public ZoneId getZone() { return ZoneOffset.UTC; }
        @Override public Clock withZone(ZoneId zone) { return Clock.fixed(now, zone); }
        @Override public Instant instant() { return now; }
    }

    static final class Script {
        final MutableClock clock;
        final AtomicInteger remoteCalls = new AtomicInteger();
        final List<String> events = new ArrayList<>();
        final List<ExtractionSubmission> submissions = new ArrayList<>();
        final List<String> recoveredIds = new ArrayList<>();
        PlanReference reference;
        ExtractionSubmission s2;
        RelationSubmission s3;
        PlanAdmission accepted;
        Mode mode;
        boolean admitted;
        boolean s2Exists;
        boolean s3Exists;
        boolean cancelled;
        boolean s3Delivered;
        boolean readyOnCancel;
        boolean retiredAdmission;
        String retirementCode;
        int s2Submits;
        int s3Submits;
        int recoveries;
        int cancels;
        int admissionReads;
        Runnable afterSubmit;
        Script(MutableClock clock) { this.clock = clock; }
        void reset() {
            reference = new PlanReference("s2plan-" + Canonical.sha256(UUID.randomUUID().toString()), D);
            s2 = new ExtractionSubmission("probe-" + UUID.randomUUID(), D, ExecutionMode.REPLAY);
            s3 = new RelationSubmission(PlanIdentity.relationJobId(reference, s2.jobId(), D), PipelineJob.SourceKind.SYNTHETIC,
                    ExecutionMode.REPLAY, new RelationUpstream(s2.jobId(), D));
            var manifest = new PlanManifest(reference, D, "app", new PlanManifest.Round("probe", "round", D),
                    new PipelineJob.Provenance(PipelineJob.SourceKind.SYNTHETIC, ExecutionMode.REPLAY),
                    List.of(new PlanManifest.Unit(s2.jobId(), s2, D, s3)), D);
            // The real AI service's ledger.stamp emits whole-second admission timestamps.
            accepted = new PlanAdmission(PlanIdentity.admissionId("app", reference), clock.instant().truncatedTo(ChronoUnit.SECONDS), 1, D, manifest,
                    new PlanAdmission.Authority(PlanAdmission.State.ACTIVE, Optional.empty()));
            mode = Mode.NORMAL;
            retirementCode = "policy_disabled";
            admitted = s2Exists = s3Exists = cancelled = s3Delivered = readyOnCancel = retiredAdmission = false;
            s2Submits = s3Submits = recoveries = cancels = admissionReads = 0;
            afterSubmit = () -> {};
            remoteCalls.set(0); events.clear(); submissions.clear(); recoveredIds.clear();
        }
        PlanAdmissionClient admission() {
            return new PlanAdmissionClient() {
                public PlanAdmission status(PlanReference requested) {
                    remoteCalls.incrementAndGet(); admissionReads++;
                    assertEquals(reference, requested);
                    if (!admitted) throw new PlanAdmissionServiceErrorException(AiOperation.STATUS, "probe", 404,
                            "admission_not_found", false, Optional.empty(), Optional.empty(), Optional.empty());
                    if (retiredAdmission || mode == Mode.FINAL_INACTIVE && s3Delivered) return new PlanAdmission(accepted.admissionId(),
                            accepted.acceptedAt(), 1, D, accepted.manifest(),
                            new PlanAdmission.Authority(PlanAdmission.State.INACTIVE,
                                    Optional.of(retiredAdmission ? retirementCode : "policy_expired")));
                    return accepted;
                }
                public PlanAdmission admit(PlanReference requested) {
                    remoteCalls.incrementAndGet(); assertEquals(reference, requested); admitted = true; return accepted;
                }
            };
        }
        ExtractionClient extraction() {
            return new ExtractionClient() {
                public ExtractionJobStatus status(String id) {
                    remoteCalls.incrementAndGet(); assertEquals(s2.jobId(), id);
                    if (!s2Exists || mode == Mode.ACCEPTED_THEN_MISSING) throw s2Error(AiOperation.STATUS, 404, "job_not_found");
                    if (mode == Mode.CANCEL_STATUS_FAILURES) throw s2Error(AiOperation.STATUS, 503, "runtime_unavailable");
                    return s2Status(D, false, false);
                }
                public ExtractionAcknowledgement submit(ExtractionSubmission command) {
                    remoteCalls.incrementAndGet(); events.add("s2-submit"); s2Submits++; submissions.add(command); assertEquals(s2, command);
                    s2Exists = mode != Mode.CANCEL_UNKNOWN && !(mode == Mode.RESERVED_SUBMIT && s2Submits == 1);
                    afterSubmit.run();
                    if ((mode == Mode.LOST_ACCEPTED_SUBMIT || mode == Mode.RESERVED_SUBMIT) && s2Submits == 1
                            || mode == Mode.CANCEL_UNKNOWN) throw s2Error(AiOperation.SUBMIT, 503, "runtime_unavailable");
                    return new ExtractionAcknowledgement(PipelineJob.Disposition.NEWLY_ACCEPTED, s2Status(D, false, false));
                }
                public ExtractionResult result(String id) {
                    remoteCalls.incrementAndGet(); events.add("s2-result"); assertEquals(s2.jobId(), id);
                    String digest = mode == Mode.RESULT_WRONG_BINDING ? "b".repeat(64) : D;
                    boolean withheld = mode == Mode.RESULT_WITHHELD;
                    var own = s2Status(digest, withheld, mode == Mode.RESULT_UNKNOWN_USAGE);
                    return new ExtractionResult(own, own.delivery(), withheld ? Optional.empty()
                            : Optional.of(new UntrustedExtractionPayload(id, digest, payload(id, digest))), RECEIPTS);
                }
                public ExtractionJobStatus cancel(String id) {
                    remoteCalls.incrementAndGet(); assertEquals(s2.jobId(), id); cancels++;
                    if (mode == Mode.CANCEL_READY_RACE) {
                        readyOnCancel = true;
                        throw new ExtractionServiceErrorException(AiOperation.CANCEL, "probe", 409, "job_already_terminal", false,
                                Optional.empty(), Optional.empty(), Optional.empty(), Optional.of(s2Status(D, false, false)));
                    }
                    cancelled = true;
                    return s2Status(D, false, false);
                }
                public ExtractionAcknowledgement recover(String id) {
                    remoteCalls.incrementAndGet(); assertEquals(s2.jobId(), id); recoveries++; recoveredIds.add(id);
                    return new ExtractionAcknowledgement(PipelineJob.Disposition.RECOVERY_ENQUEUED, s2Status(D, false, false));
                }
            };
        }
        RelationClient relation() {
            return new RelationClient() {
                public RelationJobStatus status(String id) {
                    remoteCalls.incrementAndGet(); assertEquals(s3.jobId(), id);
                    if (!s3Exists) throw s3Error(AiOperation.STATUS, 404, "job_not_found");
                    return s3Status(D);
                }
                public RelationAcknowledgement submit(RelationSubmission command) {
                    remoteCalls.incrementAndGet(); events.add("s3-submit"); assertEquals(s3, command); s3Submits++;
                    if (mode == Mode.S3_POLICY_RETIRED) {
                        // The preceding current-admission GET was active; retirement occurs at the real POST boundary.
                        retiredAdmission = true;
                        throw s3Error(AiOperation.SUBMIT, 409, retirementCode);
                    }
                    if (mode == Mode.S3_PERMISSION_REFUSED) throw s3Error(AiOperation.SUBMIT, 403, "upstream_not_allowed");
                    s3Exists = true;
                    return new RelationAcknowledgement(PipelineJob.Disposition.NEWLY_ACCEPTED, s3Status(D));
                }
                public RelationResult result(String id) {
                    remoteCalls.incrementAndGet(); events.add("s3-result"); assertEquals(s3.jobId(), id); s3Delivered = true;
                    String digest = mode == Mode.S3_RESULT_REBOUND ? "b".repeat(64) : D;
                    return new RelationResult(s3Status(digest), AVAILABLE,
                            Optional.of(new UntrustedRelationPayload(id, digest, payload(id, digest), List.of())), RECEIPTS);
                }
                public RelationJobStatus cancel(String id) { throw new AssertionError("no relation child should need cancellation"); }
                public RelationAcknowledgement recover(String id) { throw new AssertionError("no relation recovery expected"); }
                public RelationOperationAcknowledgement review(String id, RelationReviewRequest request) { throw new AssertionError("review is outside worker ownership"); }
                public RelationOperationStatus operation(String id, String operationId) { throw new AssertionError("review is outside worker ownership"); }
            };
        }
        ExtractionJobStatus s2Status(String digest, boolean withheld, boolean unknown) {
            boolean recovering = mode == Mode.RECOVERY_LIMIT;
            boolean reconcile = mode == Mode.RECONCILE_ONLY;
            boolean running = (mode == Mode.CANCEL_RUNNING || mode == Mode.WAIT_FOREVER
                    || mode == Mode.CANCEL_READY_RACE || mode == Mode.CANCEL_STATUS_FAILURES) && !cancelled && !readyOnCancel;
            var state = cancelled ? PipelineJob.State.CANCELLED : recovering || reconcile ? PipelineJob.State.STOPPED
                    : running ? PipelineJob.State.RUNNING : PipelineJob.State.READY;
            var next = cancelled ? PipelineJob.Next.NONE : reconcile ? PipelineJob.Next.OPERATOR_RECONCILE
                    : recovering ? PipelineJob.Next.RECOVER : running ? PipelineJob.Next.WAIT : PipelineJob.Next.FETCH_RESULT;
            return new ExtractionJobStatus(s2.jobId(), digest, D, PipelineJob.SourceKind.SYNTHETIC, ExecutionMode.REPLAY,
                    state, "probe", reconcile ? PipelineJob.ResumeMode.RECONCILE_ONLY
                            : recovering ? PipelineJob.ResumeMode.RESUME : PipelineJob.ResumeMode.NONE,
                    Optional.empty(), new ExtractionJobStatus.Usage(1, unknown ? 1 : 0, 0, 0, 0, 0,
                            Optional.empty(), Optional.empty(), Optional.empty(), Optional.empty(), Optional.empty()),
                    List.of(), withheld ? new PipelineJob.Delivery(PipelineJob.DeliveryState.WITHHELD, Optional.of("source_revoked")) : AVAILABLE,
                    new PipelineJob.Dispatch(running ? PipelineJob.DispatchState.IN_FLIGHT : PipelineJob.DispatchState.IDLE,
                            1 + recoveries, Optional.empty(), Optional.empty(), clock.instant()),
                    next, accepted.acceptedAt(), clock.instant(), Optional.empty());
        }
        RelationJobStatus s3Status(String digest) {
            return new RelationJobStatus(s3.jobId(), digest, PipelineJob.SourceKind.SYNTHETIC, ExecutionMode.REPLAY,
                    s3.upstream(), PipelineJob.State.READY, "probe", PipelineJob.ResumeMode.NONE, Optional.empty(),
                    new RelationJobStatus.Usage(1, 0, 0, 0), AVAILABLE,
                    new PipelineJob.Dispatch(PipelineJob.DispatchState.IDLE, 1, Optional.empty(), Optional.empty(), clock.instant()),
                    PipelineJob.Next.FETCH_RESULT, accepted.acceptedAt(), clock.instant(), Optional.empty());
        }
        String payload(String id, String digest) {
            return "{\"jobId\":\"" + id + "\",\"inputDigest\":\"" + digest + "\",\"modelText\":\"secret-model-text\"}";
        }
        ExtractionServiceErrorException s2Error(AiOperation operation, int status, String code) {
            return new ExtractionServiceErrorException(operation, "probe", status, code, status >= 500,
                    Optional.empty(), Optional.empty(), Optional.empty(), Optional.empty());
        }
        RelationServiceErrorException s3Error(AiOperation operation, int status, String code) {
            return new RelationServiceErrorException(operation, "probe", status, code, status >= 500,
                    Optional.empty(), Optional.empty(), Optional.empty(), Optional.empty(), Optional.empty());
        }
    }
}
