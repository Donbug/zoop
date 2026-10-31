package com.zoop.admin.jobs;

import static com.zoop.admin.jobs.AnalyzePlanState.*;
import static org.junit.jupiter.api.Assertions.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

import com.jayway.jsonpath.JsonPath;
import com.zoop.admin.auth.provision.AdminProvisioningService;
import com.zoop.admin.auth.repository.AdminAuditRepository;
import com.zoop.admin.auth.service.AdminPrincipal;
import com.zoop.admin.auth.service.AdminSessionCookie;
import com.zoop.ai.ExecutionMode;
import com.zoop.ai.PipelineJob;
import com.zoop.ai.extraction.ExtractionSubmission;
import com.zoop.ai.plan.*;
import com.zoop.ai.relation.*;
import com.zoop.auth.service.CsrfKeyRing;
import com.zoop.common.exception.CustomException;
import com.zoop.common.request.RequestIdFilter;
import jakarta.servlet.http.Cookie;
import java.sql.Timestamp;
import java.time.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicReference;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.support.DefaultListableBeanFactory;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;
import org.springframework.dao.DataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.ResultActions;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.context.WebApplicationContext;
import tools.jackson.databind.ObjectMapper;

/** Real DB/API invariants. The capability double never executes; actual worker/HTTP replay is a separate gate. */
@SpringBootTest(properties = {"ZOOP_AUTH_CSRF_ACTIVE_KEY_ID=test",
        "ZOOP_AUTH_CSRF_KEYS=test=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        "ZOOP_AUTH_ALLOWED_ORIGINS=https://zoop.example", "zoop.analysis.analyze-plan.enabled=false"})
@Import(AnalyzePlanPersistencePostgresTest.Binding.class)
@EnabledIfEnvironmentVariable(named="DB_URL",matches="jdbc:postgresql:.*")
@Tag("auth-postgres")
class AnalyzePlanPersistencePostgresTest {
    private static final String ORIGIN="https://zoop.example";
    private static final String DIGEST="a".repeat(64);
    private static final ServiceBinding BINDING=ServiceBinding.of("http://127.0.0.1:9999","queue-test");
    @TestConfiguration(proxyBeanMethods=false) static class Binding {
        @Bean ServiceBinding binding() { return BINDING; }
    }
    @MockitoBean AnalyzePlanWorker capability;
    @Autowired WebApplicationContext context;
    @Autowired RequestIdFilter requestIds;
    @Autowired AdminProvisioningService provisioning;
    @Autowired JdbcTemplate jdbc;
    @Autowired NamedParameterJdbcTemplate named;
    @Autowired JdbcAnalyzePlanRepository plans;
    @Autowired JdbcAnalysisJobRepository jobs;
    @Autowired AdminAuditRepository audit;
    @Autowired ObjectMapper mapper;
    @Autowired CsrfKeyRing keys;
    @Autowired PlatformTransactionManager transactions;
    @Autowired AnalyzePlanProperties properties;
    private MockMvc mvc;
    private final List<String> created=new ArrayList<>();
    private record Login(Cookie cookie,String csrf,String adminId,String email) {}
    private record Accepted(String id,String key,String body,PlanReference reference,Login login,String receipt) {}

    @BeforeEach void setup() { mvc=MockMvcBuilders.webAppContextSetup(context).addFilters(requestIds).build(); }
    @AfterEach void settleOwnedRows() {
        for(String id:created) {
            var row=jobs.adminJob(id).orElseThrow();
            if("queued".equals(row.status())) new TransactionTemplate(transactions).execute(s->{jobs.lockAdmin(id);plans.cancelQueued(id,Instant.now());return null;});
            if("running".equals(row.status())) {
                jdbc.update("UPDATE analysis_jobs SET lease_until=clock_timestamp()-interval '1 second' WHERE id=?",id);
                var claim=plans.claimNext().orElseThrow();
                assertEquals(id,claim.appJobId());
                assertTrue(plans.finish(claim,new AnalyzePlanTerminal(row.cancelRequested()?"cancelled":"failed","transient","worker_deadline")));
            }
        }
    }

    @Test void createCommitsReferenceJobAuditAndExactReceiptBeforeAnyRemoteWork() throws Exception {
        Accepted a=accept();
        assertEquals(1,jdbc.queryForObject("SELECT count(*) FROM analysis_plans WHERE plan_id=? AND admission_intent_at IS NULL AND admission_id IS NULL",Integer.class,a.reference().planId()));
        assertEquals(1,jdbc.queryForObject("SELECT count(*) FROM audit_logs WHERE action='analysis.job.create' AND target_id=?",Integer.class,a.id()));
        assertEquals(0,jdbc.queryForObject("SELECT count(*) FROM analysis_plan_units WHERE plan_id=?",Integer.class,a.reference().planId()));
        assertEquals("completed",jdbc.queryForObject("SELECT status FROM idempotency_records WHERE idem_key=? AND principal_id=?",String.class,a.key(),a.login().adminId()));
        String first=request(a.login(),a.key(),a.body()).andExpect(status().isAccepted()).andReturn().getResponse().getContentAsString();
        assertEquals(mapper.readTree(a.receipt()),mapper.readTree(first));
        request(a.login(),a.key(),a.body().replace("운영 확인","다른 사유")).andExpect(status().isConflict()).andExpect(jsonPath("$.error.code").value("IDEMPOTENCY_CONFLICT"));
        request(a.login(),UUID.randomUUID().toString(),a.body()).andExpect(status().isAccepted())
                .andExpect(jsonPath("$.job.id").value(a.id())).andExpect(jsonPath("$.deduplicated").value(true));
        assertEquals(1,jdbc.queryForObject("SELECT count(*) FROM analysis_jobs WHERE plan_id=?",Integer.class,a.reference().planId()));
        Login other=login();
        request(other,UUID.randomUUID().toString(),a.body()).andExpect(status().isAccepted()).andExpect(jsonPath("$.deduplicated").value(true));
        assertEquals(a.login().adminId(),jdbc.queryForObject("SELECT registered_by FROM analysis_plans WHERE plan_id=?",String.class,a.reference().planId()));
        request(a.login(),UUID.randomUUID().toString(),a.body().replace(DIGEST,"b".repeat(64))).andExpect(status().isConflict());
        org.mockito.Mockito.verifyNoInteractions(capability);
    }

    @Test void historicalCreateAndRetryReceiptsReplayWithCapabilityAbsent() throws Exception {
        Accepted a=accept();
        var empty=new DefaultListableBeanFactory();
        var disabled=new AnalysisJobService(jobs,audit,mapper,keys,Clock.systemUTC(),plans,
                empty.getBeanProvider(AnalyzePlanWorker.class),empty.getBeanProvider(ServiceBinding.class));
        var admin=new AdminPrincipal(a.login().adminId(),a.login().email(),"Queue Test","admin","test-session");
        var tx=new TransactionTemplate(transactions);
        var replay=tx.execute(s->disabled.create(new AnalyzePlanCommand("운영 확인",a.reference()),a.key(),admin,"historical-replay"));
        assertEquals(a.id(),replay.job().id());
        assertFalse(replay.deduplicated());
        String fresh="disabled-"+UUID.randomUUID();
        assertThrows(CustomException.class,()->tx.execute(s->disabled.create(new AnalyzePlanCommand("운영 확인",a.reference()),fresh,admin,"disabled")));
        assertEquals(0,jdbc.queryForObject("SELECT count(*) FROM idempotency_records WHERE idem_key=?",Integer.class,fresh));
        var claim=plans.claimNext().orElseThrow();assertEquals(a.id(),claim.appJobId());
        assertTrue(plans.finish(claim,new AnalyzePlanTerminal("failed","transient","admission_unavailable")));
        String retryKey="retry-"+UUID.randomUUID();
        String response=mutate(a.login(),a.id(),"retry",retryKey).andExpect(status().isAccepted()).andReturn().getResponse().getContentAsString();
        String retryId=JsonPath.read(response,"$.job.id");created.add(retryId);
        var historical=tx.execute(s->disabled.retry(a.id(),new JobReasonRequest("운영 확인"),retryKey,admin,"replay-retry"));
        assertEquals(retryId,historical.job().id());
        assertEquals(a.reference().planId(),jobs.adminJob(retryId).orElseThrow().planId());
    }

    /** #55 D-R3: the round scheduler queues a plan under the system actor; the command key dedups, a failed job is retried once. */
    @Test void theSystemEntryPointQueuesAPlanOnceUnderTheSystemActorAndRetriesAFailedJobAsANewOne() throws Exception {
        String seed=UUID.randomUUID().toString().replace("-","");
        PlanReference reference=new PlanReference("s2plan-"+seed+seed,DIGEST);
        var service=new AnalysisJobService(jobs,audit,mapper,keys,Clock.systemUTC(),plans,
                context.getBeanProvider(AnalyzePlanWorker.class),context.getBeanProvider(ServiceBinding.class));
        var tx=new TransactionTemplate(transactions);
        int idempotencyRows=jdbc.queryForObject("SELECT count(*) FROM idempotency_records",Integer.class);
        var first=tx.execute(s->service.createForSystem(reference,"정기 회차 round-20261030T0905","round-20261030T0905"));
        created.add(first.job().id());
        assertFalse(first.deduplicated());
        assertEquals(AnalysisJobService.SYSTEM_ACTOR,first.job().requestedBy());
        assertEquals(AnalysisJobService.SYSTEM_ACTOR,jdbc.queryForObject("SELECT registered_by FROM analysis_plans WHERE plan_id=?",String.class,reference.planId()));
        assertEquals(1,jdbc.queryForObject("SELECT count(*) FROM audit_logs WHERE action='analysis.job.create' AND target_id=? AND actor_kind='system' AND admin_id IS NULL AND actor_id=?",Integer.class,first.job().id(),AnalysisJobService.SYSTEM_ACTOR));
        assertEquals(idempotencyRows,jdbc.queryForObject("SELECT count(*) FROM idempotency_records",Integer.class),"the command key is the idempotency; no admin record");
        var again=tx.execute(s->service.createForSystem(reference,"정기 회차 round-20261030T0905","round-again"));
        assertTrue(again.deduplicated());
        assertEquals(first.job().id(),again.job().id());
        assertEquals(1,jdbc.queryForObject("SELECT count(*) FROM analysis_jobs WHERE plan_id=?",Integer.class,reference.planId()));
        // The job fails; the next round asking for the same plan gets one retry job, chained to the failed one.
        var claim=plans.claimNext().orElseThrow();assertEquals(first.job().id(),claim.appJobId());
        assertTrue(plans.finish(claim,new AnalyzePlanTerminal("failed","transient","admission_unavailable")));
        var retried=tx.execute(s->service.createForSystem(reference,"정기 회차 round-20261030T0935","round-20261030T0935"));
        created.add(retried.job().id());
        assertFalse(retried.deduplicated());
        assertEquals(first.job().id(),retried.job().retryOf());
        assertEquals(AnalysisJobService.SYSTEM_ACTOR,retried.job().requestedBy());
        assertEquals(1,jdbc.queryForObject("SELECT count(*) FROM audit_logs WHERE action='analysis.job.retry' AND target_id=? AND actor_kind='system'",Integer.class,first.job().id()));
        var queued=tx.execute(s->service.createForSystem(reference,"정기 회차 round-20261030T1005","round-20261030T1005"));
        assertTrue(queued.deduplicated(),"the retry job is the plan's current job now");
        assertEquals(retried.job().id(),queued.job().id());
        // A retry of a retry is found through the chain, so the plan never gets two live jobs.
        var claim2=plans.claimNext().orElseThrow();assertEquals(retried.job().id(),claim2.appJobId());
        assertTrue(plans.finish(claim2,new AnalyzePlanTerminal("failed","transient","admission_unavailable")));
        var second=tx.execute(s->service.createForSystem(reference,"정기 회차 round-20261030T1035","round-20261030T1035"));
        created.add(second.job().id());
        assertEquals(retried.job().id(),second.job().retryOf());
        var third=tx.execute(s->service.createForSystem(reference,"정기 회차 round-20261030T1105","round-20261030T1105"));
        assertTrue(third.deduplicated());
        assertEquals(second.job().id(),third.job().id());
        assertEquals(3,jdbc.queryForObject("SELECT count(*) FROM analysis_jobs WHERE plan_id=?",Integer.class,reference.planId()));
    }

    @Test void queuedCancelFreezesSummaryAndRetryContinuesOneRegisteredExecution() throws Exception {
        Accepted a=accept();
        String cancelKey="cancel-"+UUID.randomUUID();
        mutate(a.login(),a.id(),"cancel",cancelKey).andExpect(status().isOk())
                .andExpect(jsonPath("$.planRun.phase").value("cancelled")).andExpect(jsonPath("$.planRun.totalUnits").isEmpty());
        String frozen=jobs.adminJob(a.id()).orElseThrow().checkpoint();
        String retryKey="retry-"+UUID.randomUUID();
        String response=mutate(a.login(),a.id(),"retry",retryKey).andExpect(status().isAccepted()).andReturn().getResponse().getContentAsString();
        String next=JsonPath.read(response,"$.job.id");created.add(next);
        assertEquals(a.reference().planId(),jobs.adminJob(next).orElseThrow().planId());
        mutate(a.login(),a.id(),"retry",UUID.randomUUID().toString()).andExpect(status().isConflict());
        assertEquals(frozen,jobs.adminJob(a.id()).orElseThrow().checkpoint());
        request(a.login(),UUID.randomUUID().toString(),a.body()).andExpect(status().isAccepted()).andExpect(jsonPath("$.job.id").value(a.id()));
        assertThrows(DataAccessException.class,()->jdbc.update("UPDATE analysis_jobs SET checkpoint=jsonb_set(checkpoint,'{phase}','\"failed\"') WHERE id=?",a.id()));
    }

    @Test void admissionAndEveryOrderedUnitCommitTogetherAndCannotBeRebound() throws Exception {
        Accepted a=accept();var claim=plans.claimNext().orElseThrow();assertEquals(a.id(),claim.appJobId());
        PlanAdmission admission=admission(a.reference());
        assertTrue(plans.recordAdmissionIntent(claim));
        assertTrue(plans.bindAdmission(claim,admission));
        assertEquals(2,jdbc.queryForObject("SELECT count(*) FROM analysis_plan_units WHERE plan_id=?",Integer.class,a.reference().planId()));
        assertTrue(plans.bindAdmission(claim,admission));
        for(String change:List.of("plan_digest=repeat('b',64)","service_binding=repeat('b',64)","expected_principal='other'",
                "registered_by='other'","admission_id=NULL,accepted_at=NULL,policy_revision=NULL,policy_digest=NULL,receipt_sha256=NULL,manifest_digest=NULL,manifest=NULL")) {
            assertThrows(DataAccessException.class,()->jdbc.update("UPDATE analysis_plans SET "+change+" WHERE plan_id=?",a.reference().planId()));
        }
        assertThrows(DataAccessException.class,()->jdbc.update("DELETE FROM analysis_plan_units WHERE plan_id=?",a.reference().planId()));
        assertThrows(DataAccessException.class,()->jdbc.update("UPDATE analysis_plan_units SET ordinal=9 WHERE plan_id=? AND ordinal=1",a.reference().planId()));
        assertThrows(DataAccessException.class,()->jdbc.update("UPDATE analysis_jobs SET plan_id=NULL WHERE id=?",a.id()));
        assertThrows(RuntimeException.class,()->new TransactionTemplate(transactions).execute(s->{
            jdbc.update("""
                    INSERT INTO analysis_plan_units SELECT plan_id,3,'extra','extra',s2_approved_request_digest,s2_input_digest,
                    'extra-s3',s2_submit,s3_submit,NULL,s2_checkpoint,s3_checkpoint FROM analysis_plan_units WHERE plan_id=? AND ordinal=1
                    """,a.reference().planId()); return null;
        }));
        assertTrue(plans.finish(claim,new AnalyzePlanTerminal("failed","transient","worker_deadline")));
        String terminal=jobs.adminJob(a.id()).orElseThrow().checkpoint();
        assertFalse(plans.bindAdmission(claim,admission));
        assertEquals(terminal,jobs.adminJob(a.id()).orElseThrow().checkpoint());
    }

    @Test void anIncompleteAdmissionTransactionRollsBackAndCannotExposeAPrefix() throws Exception {
        Accepted a=accept();
        assertThrows(RuntimeException.class,()->new TransactionTemplate(transactions).execute(s->{
            jdbc.update("""
                    UPDATE analysis_plans SET admission_id=?,accepted_at=clock_timestamp(),policy_revision=1,
                    policy_digest=?,receipt_sha256=?,manifest_digest=?,manifest=CAST(? AS jsonb) WHERE plan_id=?
                    """,PlanIdentity.admissionId(BINDING.expectedPrincipal(),a.reference()),DIGEST,DIGEST,DIGEST,
                    "{\"schemaVersion\":\"zoop-ai-plan-manifest-1\",\"planId\":\""+a.reference().planId()+"\",\"planDigest\":\""+DIGEST+"\",\"receiptSha256\":\""+DIGEST+"\",\"principal\":\"queue-test\",\"round\":{},\"provenance\":{},\"units\":[{}],\"manifestDigest\":\""+DIGEST+"\"}",a.reference().planId());return null;
        }));
        assertNull(jdbc.queryForObject("SELECT admission_id FROM analysis_plans WHERE plan_id=?",String.class,a.reference().planId()));
        assertEquals(0,jdbc.queryForObject("SELECT count(*) FROM analysis_plan_units WHERE plan_id=?",Integer.class,a.reference().planId()));
    }

    @Test
    void reclaimExhaustionWithUnansweredSubmitIntentFreezesUnknownAndDeniesRetry() throws Exception {
        Accepted accepted = accept();
        var clock = new MutableClock(Instant.now());
        var bounded = new AnalyzePlanProperties(false, null, properties.pollInterval(), properties.attemptDeadline(),
                properties.lease(), properties.maxConsecutiveFailures(), properties.maxRecoveryDispatches(), 1);
        var repository = new JdbcAnalyzePlanRepository(named, mapper, transactions, clock, bounded);
        var original = repository.claimNext().orElseThrow();
        assertEquals(accepted.id(), original.appJobId());
        assertTrue(repository.bindAdmission(original, admission(accepted.reference())));
        var stage = repository.nextStage(original).orElseThrow();
        assertTrue(repository.recordIntent(original, stage, StageAction.SUBMIT));
        String pendingBefore = jdbc.queryForObject("""
                SELECT s2_checkpoint::text FROM analysis_plan_units WHERE plan_id=? AND ordinal=1
                """, String.class, accepted.reference().planId());
        assertNotNull(mapper.readTree(pendingBefore).get("intentAt").stringValue());
        assertTrue(mapper.readTree(pendingBefore).get("acceptedObservedAt").isNull());
        assertTrue(mapper.readTree(pendingBefore).get("lastStatus").isNull());

        clock.set(original.leaseUntil().plusSeconds(1));
        var reclaimed = repository.claimNext().orElseThrow();
        assertEquals(original.deadline(), reclaimed.deadline());
        assertNotEquals(original.ownerToken(), reclaimed.ownerToken());
        assertFalse(repository.recordIntent(original, stage, StageAction.RECOVER));
        clock.set(reclaimed.leaseUntil().plusSeconds(1));
        assertTrue(repository.claimNext().isEmpty(), "the configured automatic reclaim allowance is exhausted");
        assertEquals("failed", jobs.adminJob(accepted.id()).orElseThrow().status());
        assertEquals(pendingBefore, jdbc.queryForObject("""
                SELECT s2_checkpoint::text FROM analysis_plan_units WHERE plan_id=? AND ordinal=1
                """, String.class, accepted.reference().planId()), "unknown execution evidence must remain intact");
        mvc.perform(get("/api/v1/admin/jobs/{id}", accepted.id()).cookie(accepted.login().cookie()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.error.code").value("outcome_unknown"))
                .andExpect(jsonPath("$.retry.code").value("outcome_unknown"));
        mutate(accepted.login(), accepted.id(), "retry", UUID.randomUUID().toString()).andExpect(status().isConflict());
        assertEquals(0, jdbc.queryForObject("SELECT count(*) FROM analysis_jobs WHERE retry_of=?",
                Integer.class, accepted.id()));
    }

    @Test
    void cancellationAfterPreSubmitReadFailureSelectsNoRemoteWorkAndAllowsContinuation() throws Exception {
        Accepted accepted = accept();
        var claim = plans.claimNext().orElseThrow();
        assertEquals(accepted.id(), claim.appJobId());
        assertTrue(plans.bindAdmission(claim, admission(accepted.reference())));
        var stage = plans.nextStage(claim).orElseThrow();
        assertTrue(plans.recordObservation(claim, stage, StageObservation.failure("transient", "ai_status_unavailable")));
        var failedRead = mapper.readTree(jdbc.queryForObject("""
                SELECT s2_checkpoint::text FROM analysis_plan_units WHERE plan_id=? AND ordinal=1
                """, String.class, accepted.reference().planId()));
        assertTrue(failedRead.get("intentAt").isNull());
        assertTrue(failedRead.get("acceptedObservedAt").isNull());
        assertTrue(failedRead.get("lastStatus").isNull());
        mutate(accepted.login(), accepted.id(), "cancel", UUID.randomUUID().toString())
                .andExpect(status().isOk()).andExpect(jsonPath("$.status").value("running"));
        assertTrue(plans.nextStage(claim).isEmpty(),
                "a failed read with no durable issuance or acceptance evidence must not create remote cancellation work");
        assertTrue(plans.finish(claim, new AnalyzePlanTerminal("cancelled", null, null)));
        String retried = mutate(accepted.login(), accepted.id(), "retry", UUID.randomUUID().toString())
                .andExpect(status().isAccepted()).andReturn().getResponse().getContentAsString();
        String retryId = JsonPath.read(retried, "$.job.id");
        created.add(retryId);
        assertEquals(accepted.reference().planId(), jobs.adminJob(retryId).orElseThrow().planId());
        assertEquals(1, jdbc.queryForObject("SELECT count(*) FROM analysis_plans WHERE plan_id=?",
                Integer.class, accepted.reference().planId()));
        assertTrue(jobs.adminJob(accepted.id()).orElseThrow().error() == null,
                "known pre-send cancellation is not an unknown execution outcome");
    }

    @Test void expiredOwnerCannotRenewIntentObserveDeferOrFinishEvenAfterWaitingForTheRowLock() throws Exception {
        Accepted a=accept();
        var time=new MutableClock(Instant.now());
        var repo=new JdbcAnalyzePlanRepository(named,mapper,transactions,time,properties);
        var claim=repo.claimNext().orElseThrow();assertEquals(a.id(),claim.appJobId());
        assertTrue(repo.bindAdmission(claim,admission(a.reference())));
        StageWork stage=repo.nextStage(claim).orElseThrow();
        var executor=Executors.newSingleThreadExecutor();
        try {
            Future<Boolean> waiting=new TransactionTemplate(transactions).execute(s->{
                jobs.lockAdmin(a.id());
                int holderPid = jdbc.queryForObject("SELECT pg_backend_pid()", Integer.class);
                // Prime the transaction-cached activity snapshot before the waiter can block (PostgreSQL 16 §28.2.2).
                jdbc.queryForObject("SELECT count(*) FROM pg_stat_activity", Integer.class);
                var waiterPid = new CompletableFuture<Integer>();
                Future<Boolean> future = executor.submit(() -> new TransactionTemplate(transactions).execute(waiter -> {
                    waiterPid.complete(jdbc.queryForObject("SELECT pg_backend_pid()", Integer.class));
                    return repo.renew(claim);
                }));
                awaitRowWait(a.id(), holderPid, waiterPid);
                time.set(claim.leaseUntil().plusSeconds(1));
                return future;
            });
            assertFalse(waiting.get(5,TimeUnit.SECONDS),"fresh clock after the lock wait must refuse expired owner");
            assertFalse(repo.recordIntent(claim,stage,StageAction.SUBMIT));
            assertFalse(repo.recordObservation(claim,stage,StageObservation.failure("transient","ai_status_unavailable")));
            assertFalse(repo.defer(claim,time.instant()));
            assertFalse(repo.finish(claim,new AnalyzePlanTerminal("failed","transient","worker_deadline")));
            var replacement=repo.claimNext().orElseThrow();assertEquals(a.id(),replacement.appJobId());
            assertNotEquals(claim.ownerToken(),replacement.ownerToken());assertEquals(claim.deadline(),replacement.deadline());
            assertFalse(repo.renew(claim));
            assertTrue(repo.finish(replacement,new AnalyzePlanTerminal("failed","transient","worker_deadline")));
        } finally {executor.shutdownNow();}
    }

    @Test void runningCancellationBlocksNormalIntentsButAllowsFencedSettlement() throws Exception {
        Accepted a=accept();var claim=plans.claimNext().orElseThrow();assertEquals(a.id(),claim.appJobId());
        assertTrue(plans.bindAdmission(claim,admission(a.reference())));
        var stage=plans.nextStage(claim).orElseThrow();assertTrue(plans.recordIntent(claim,stage,StageAction.SUBMIT));
        mutate(a.login(),a.id(),"cancel",UUID.randomUUID().toString()).andExpect(status().isOk()).andExpect(jsonPath("$.status").value("running"));
        assertFalse(plans.recordAdmissionIntent(claim));assertFalse(plans.recordIntent(claim,stage,StageAction.RECOVER));
        assertTrue(plans.renew(claim));assertTrue(plans.recordIntent(claim,stage,StageAction.CANCEL));
        assertFalse(plans.finish(claim,new AnalyzePlanTerminal("succeeded",null,null)));
        assertTrue(plans.finish(claim,new AnalyzePlanTerminal("cancelled","outcome_unknown","outcome_unknown")));
        mutate(a.login(),a.id(),"retry",UUID.randomUUID().toString()).andExpect(status().isConflict());
        mvc.perform(get("/api/v1/admin/jobs/{id}",a.id()).cookie(a.login().cookie())).andExpect(jsonPath("$.retry.code").value("outcome_unknown"));
    }

    @Test void successfulProcessingPinsS3OnceKeepsHistoryAndDoesNotAdvanceTheIngestBaseline() throws Exception {
        String ingest = "job-" + UUID.randomUUID();
        jdbc.update("""
                INSERT INTO analysis_jobs(id,kind,scope,label,status,reason,requested_by,requested_at,started_at,
                finished_at,command_key,input) VALUES(?,'ingest','admin','기존 수집','succeeded','합성 이력','history',
                clock_timestamp()-interval '3 hours',clock_timestamp()-interval '2 hours',
                clock_timestamp()-interval '1 hour',?,'{}')
                """, ingest, "baseline-" + UUID.randomUUID());
        var before = jobs.latestSucceededIngest().orElseThrow();
        Accepted a = accept();
        Instant afterBaseline = before.finishedAt().plusSeconds(1);
        var time = new MutableClock(afterBaseline.isAfter(Instant.now()) ? afterBaseline : Instant.now());
        var repo = new JdbcAnalyzePlanRepository(named, mapper, transactions, time, properties);
        var claim = repo.claimNext().orElseThrow();
        assertEquals(a.id(), claim.appJobId());
        assertTrue(repo.bindAdmission(claim, admission(a.reference())));
        for (int ordinal = 1; ordinal <= 2; ordinal++) {
            StageWork s2 = repo.nextStage(claim).orElseThrow();
            assertEquals(ordinal, s2.ordinal());
            assertEquals(StageKind.S2, s2.stage());
            var extraction = extractionStatus(s2);
            assertTrue(repo.recordObservation(claim, s2, StageObservation.status(extraction)));
            assertTrue(repo.recordObservation(claim, s2,
                    new StageObservation(new StageStatus(extraction, null), "d".repeat(64), List.of(), null, null)));
            StageWork s3 = repo.nextStage(claim).orElseThrow();
            assertEquals(StageKind.S3, s3.stage());
            var relation = relationStatus(s3, "c".repeat(64));
            assertTrue(repo.recordObservation(claim, s3, StageObservation.status(relation)));
            assertThrows(CustomException.class, () -> repo.recordObservation(claim, s3,
                    StageObservation.status(relationStatus(s3, "e".repeat(64)))));
            assertThrows(DataAccessException.class, () -> jdbc.update(
                    "UPDATE analysis_plan_units SET s3_input_digest=NULL WHERE plan_id=? AND ordinal=?",
                    a.reference().planId(), s3.ordinal()));
            assertTrue(repo.recordObservation(claim, s3,
                    new StageObservation(new StageStatus(null, relation), "f".repeat(64), List.of(), null, null)));
        }
        assertTrue(repo.nextStage(claim).isEmpty());
        assertTrue(repo.finish(claim, new AnalyzePlanTerminal("succeeded", null, null)));
        assertEquals(before.id(), jobs.latestSucceededIngest().orElseThrow().id());
        assertEquals(before.startedAt(), jobs.latestSucceededIngest().orElseThrow().startedAt());
        var references = repo.readyUnits(a.reference().planId(), 0, 1);
        assertEquals(1, references.size());
        assertEquals(1, references.getFirst().ordinal());
        assertEquals(DIGEST, references.getFirst().planDigest());
        assertEquals("c".repeat(64), references.getFirst().relationInputDigest());
        assertNotNull(references.getFirst().s3ResultObservedAt());
        assertEquals(2, repo.readyUnits(a.reference().planId(), 1, 1).getFirst().ordinal());
        var terminal = jobs.adminJob(a.id()).orElseThrow().checkpoint();
        assertFalse(repo.finish(claim, new AnalyzePlanTerminal("failed", "transient", "worker_deadline")));
        assertEquals(terminal, jobs.adminJob(a.id()).orElseThrow().checkpoint());
        mvc.perform(get("/api/v1/admin/jobs/{id}", a.id()).cookie(a.login().cookie()))
                .andExpect(jsonPath("$.planRun.phase").value("ready")).andExpect(jsonPath("$.planRun.readyUnits").value(2))
                .andExpect(jsonPath("$.ingest").isEmpty()).andExpect(jsonPath("$.report").isEmpty());
    }

    @Test void oneGlobalSlotDoesNotClaimOrExposeLegacyInternalProjection() throws Exception {
        String internal = "job-" + UUID.randomUUID();
        jdbc.update("""
                INSERT INTO analysis_jobs(id,kind,scope,label,status,reason,requested_by,requested_at,command_key,input)
                VALUES(?,'project','internal_projection','기존 내부 투영','queued','합성 이력','system',clock_timestamp(),?,'{}')
                """, internal, "internal-" + UUID.randomUUID());
        Accepted first = accept();
        Accepted second = accept();
        var owner = plans.claimNext().orElseThrow();
        assertEquals(first.id(), owner.appJobId());
        assertTrue(plans.claimNext().isEmpty());
        assertEquals("queued", jobs.adminJob(second.id()).orElseThrow().status());
        mvc.perform(get("/api/v1/admin/jobs/{id}", internal).cookie(first.login().cookie())).andExpect(status().isNotFound());
        assertEquals("queued", jdbc.queryForObject("SELECT status FROM analysis_jobs WHERE id=?", String.class, internal));
        assertTrue(plans.finish(owner, new AnalyzePlanTerminal("failed", "transient", "worker_deadline")));
    }

    private com.zoop.ai.extraction.ExtractionJobStatus extractionStatus(StageWork work) {
        Instant at = Instant.now();
        return new com.zoop.ai.extraction.ExtractionJobStatus(work.jobId(), work.extractionInputDigest(),
                work.extractionSubmit().approvedRequestDigest(), PipelineJob.SourceKind.SYNTHETIC, ExecutionMode.REPLAY,
                PipelineJob.State.READY, "ready", PipelineJob.ResumeMode.NONE, Optional.empty(),
                new com.zoop.ai.extraction.ExtractionJobStatus.Usage(1,0,0,0,0,0,Optional.empty(),Optional.empty(),Optional.empty(),Optional.empty(),Optional.empty()),
                List.of(), new PipelineJob.Delivery(PipelineJob.DeliveryState.AVAILABLE, Optional.empty()),
                new PipelineJob.Dispatch(PipelineJob.DispatchState.IDLE,1,Optional.of(PipelineJob.Outcome.EXITED),Optional.empty(),at),
                PipelineJob.Next.FETCH_RESULT, at, at, Optional.empty());
    }

    private RelationJobStatus relationStatus(StageWork work, String inputDigest) {
        Instant at = Instant.now();
        return new RelationJobStatus(work.jobId(), inputDigest, PipelineJob.SourceKind.SYNTHETIC, ExecutionMode.REPLAY,
                work.relationSubmit().upstream(), PipelineJob.State.READY, "ready", PipelineJob.ResumeMode.NONE, Optional.empty(),
                new RelationJobStatus.Usage(1,0,0,0), new PipelineJob.Delivery(PipelineJob.DeliveryState.AVAILABLE, Optional.empty()),
                new PipelineJob.Dispatch(PipelineJob.DispatchState.IDLE,1,Optional.of(PipelineJob.Outcome.EXITED),Optional.empty(),at),
                PipelineJob.Next.FETCH_RESULT, at, at, Optional.empty());
    }

    private void awaitRowWait(String id, int holderPid, CompletableFuture<Integer> waiterPid) {
        long until=System.nanoTime()+TimeUnit.SECONDS.toNanos(5);
        while(System.nanoTime()<until) {
            Integer waitingPid = waiterPid.getNow(null);
            if (waitingPid != null) {
                assertNotEquals(holderPid, waitingPid, "renew must use a separate PostgreSQL session");
                // pg_stat_activity freezes its first query snapshot inside this lock-holder transaction.
                // pg_blocking_pids reads the live lock manager and identifies this exact holder/waiter pair.
                Boolean blocked = jdbc.queryForObject("SELECT ? = ANY(pg_blocking_pids(?))",
                        Boolean.class, holderPid, waitingPid);
                if (Boolean.TRUE.equals(blocked)) return;
            }
            try {Thread.sleep(10);} catch(InterruptedException e){Thread.currentThread().interrupt();throw new AssertionError(e);}
        }
        throw new AssertionError("renew backend " + waiterPid.getNow(null)
                + " never became blocked by holder " + holderPid + " for " + id);
    }
    private Accepted accept() throws Exception {
        Login login=login();
        String seed=UUID.randomUUID().toString().replace("-","");
        PlanReference reference=new PlanReference("s2plan-"+seed+seed,DIGEST);
        String body="{\"kind\":\"analyze_plan\",\"reason\":\"운영 확인\",\"plan\":{\"planId\":\""+reference.planId()+"\",\"planDigest\":\""+DIGEST+"\"}}";
        String key=UUID.randomUUID().toString();
        var response=request(login,key,body).andExpect(status().isAccepted()).andExpect(jsonPath("$.deduplicated").value(false))
                .andExpect(jsonPath("$.job.planRun.completion").value("ai_processing_handoff"))
                .andExpect(jsonPath("$.job.planRun.publicChanged").value(false)).andReturn().getResponse();
        String id=JsonPath.read(response.getContentAsString(),"$.job.id");created.add(id);
        assertEquals("/api/v1/admin/jobs/"+id,response.getHeader("Location"));
        return new Accepted(id,key,body,reference,login,response.getContentAsString());
    }
    private ResultActions request(Login login,String key,String body) throws Exception {return mvc.perform(post("/api/v1/admin/jobs").cookie(login.cookie()).header("Origin",ORIGIN).header("X-CSRF-Token",login.csrf()).header("Idempotency-Key",key).contentType("application/json").content(body));}
    private ResultActions mutate(Login login,String id,String action,String key) throws Exception {return mvc.perform(post("/api/v1/admin/jobs/"+id+"/"+action).cookie(login.cookie()).header("Origin",ORIGIN).header("X-CSRF-Token",login.csrf()).header("Idempotency-Key",key).contentType("application/json").content("{\"reason\":\"운영 확인\"}"));}
    private Login login() throws Exception {
        String suffix=UUID.randomUUID().toString();String email="queue-"+suffix+"@example.com";
        String adminId=provisioning.provision(email,"Queue Test","Secure queue test password 2026","queue-provision-"+suffix);
        var response=mvc.perform(post("/api/v1/admin/auth/login").header("Origin",ORIGIN).contentType("application/json").content("{\"email\":\""+email+"\",\"password\":\"Secure queue test password 2026\"}")).andExpect(status().isOk()).andReturn().getResponse();
        return new Login(response.getCookie(AdminSessionCookie.NAME),JsonPath.read(response.getContentAsString(),"$.csrfToken"),adminId,email);
    }
    private PlanAdmission admission(PlanReference reference) {
        List<PlanManifest.Unit> units=new ArrayList<>();
        for(int i=1;i<=2;i++) {String job="s2-"+UUID.randomUUID();String input=String.valueOf(i).repeat(64);
            units.add(new PlanManifest.Unit(job,new ExtractionSubmission(job,DIGEST,ExecutionMode.REPLAY),input,
                    new RelationSubmission(PlanIdentity.relationJobId(reference,job,input),PipelineJob.SourceKind.SYNTHETIC,ExecutionMode.REPLAY,new RelationUpstream(job,input))));}
        var manifest=new PlanManifest(reference,DIGEST,BINDING.expectedPrincipal(),new PlanManifest.Round("authored-source","authored-round",DIGEST),new PipelineJob.Provenance(PipelineJob.SourceKind.SYNTHETIC,ExecutionMode.REPLAY),units,DIGEST);
        return new PlanAdmission(PlanIdentity.admissionId(BINDING.expectedPrincipal(),reference),Instant.now().truncatedTo(java.time.temporal.ChronoUnit.MICROS),1,DIGEST,manifest,new PlanAdmission.Authority(PlanAdmission.State.ACTIVE,Optional.empty()));
    }
    private static final class MutableClock extends Clock {
        private final AtomicReference<Instant> current;
        MutableClock(Instant now){current=new AtomicReference<>(now);}
        void set(Instant at){current.set(at);}
        @Override public ZoneId getZone(){return ZoneOffset.UTC;}
        @Override public Clock withZone(ZoneId zone){return this;}
        @Override public Instant instant(){return current.get();}
    }
}
