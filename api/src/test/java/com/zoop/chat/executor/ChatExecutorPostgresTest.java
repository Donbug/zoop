package com.zoop.chat.executor;

import java.sql.Timestamp;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;

import com.zoop.auth.service.MemberSessionService.MemberPrincipal;
import com.zoop.chat.dto.ChatJobRequest;
import com.zoop.chat.repository.ChatExecutionRepository;
import com.zoop.chat.repository.ChatRepository;
import com.zoop.chat.repository.ChatToolCallEnd;
import com.zoop.chat.service.ChatService;
import com.zoop.chat.tool.ChatToolRegistry;
import com.zoop.chat.tool.ChatToolRequest;
import com.zoop.chat.tool.ChatToolRunner;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.PlatformTransactionManager;
import tools.jackson.databind.ObjectMapper;

import static org.junit.jupiter.api.Assertions.*;

/**
 * D-AI-02 against PostgreSQL: claiming skips locked jobs, every run write is fenced by owner token and lease, an expired
 * lease is recovered and a rerun starts a new attempt. The engine is the test-only scripted fake; the scheduler is off so
 * each test drives the executor itself.
 */
@SpringBootTest(properties = {
        "ZOOP_AUTH_CSRF_ACTIVE_KEY_ID=test",
        "ZOOP_AUTH_CSRF_KEYS=test=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        "zoop.chat.questions-enabled=true",
        "zoop.chat.executor.enabled=false"
})
@EnabledIfEnvironmentVariable(named = "DB_URL", matches = "jdbc:postgresql:.*")
@Tag("auth-postgres")
class ChatExecutorPostgresTest {
    private static final String EVIDENCE = "ev-" + "a".repeat(64);
    @Autowired JdbcTemplate jdbc;
    @Autowired ChatService service;
    @Autowired ChatJobExecutor executor;
    @Autowired ScriptedChatEngine engine;
    @Autowired ChatRepository chats;
    @Autowired ChatExecutionRepository runs;
    @Autowired ObjectProvider<ChatEngine> engines;
    @Autowired ObjectMapper mapper;
    @Autowired PlatformTransactionManager transactions;
    @Autowired ChatToolRunner tools;

    private String memberId;
    private MemberPrincipal member;
    private String session;

    @TestConfiguration
    static class Engine {
        @Bean
        ScriptedChatEngine chatEngine() {
            return new ScriptedChatEngine((run, control) -> ScriptedChatEngine.generalAnswer("기본 답"));
        }
    }

    @BeforeEach
    void setUp() {
        // Other test classes may leave queued jobs behind; the executor claims the oldest, so start from none.
        jdbc.update("UPDATE chat_jobs SET status = 'cancelled', phase = NULL, owner_token = NULL, lease_until = NULL, "
                + "finished_at = now() WHERE status IN ('queued', 'running')");
        memberId = insertMember();
        member = new MemberPrincipal(memberId, "chat-executor");
        session = "conv-" + suffix();
        service.createSession(member, session);
    }

    @AfterEach
    void tearDown() {
        jdbc.update("DELETE FROM members WHERE id = ?", memberId);
    }

    @Test
    void aQueuedQuestionRunsToAStoredResultTheMemberCanRead() {
        engine.script((run, control) -> {
            control.beforeModelCall();
            control.phase("writing");
            assertEquals("writing", jdbc.queryForObject("SELECT phase FROM chat_jobs WHERE id = ?", String.class, run.jobId()));
            control.phase("verifying");
            return ScriptedChatEngine.generalAnswer("HBM은 고대역폭 메모리입니다.");
        });
        String jobId = submit("HBM이 뭐야?");

        assertTrue(executor.runOnce());
        var job = service.getJob(member, jobId);
        assertEquals("completed", job.status());
        assertEquals("answered", job.outcome());
        assertNull(job.phase());
        assertEquals(1, job.runs());
        assertEquals("msg-" + jobId, job.result().messageId());
        assertEquals("general_knowledge", job.result().answerBasis());
        assertEquals("chat-result/v1", jdbc.queryForObject("SELECT result_schema_version FROM chat_jobs WHERE id = ?",
                String.class, jobId));
        assertFalse(executor.runOnce());
    }

    @Test
    void aModelStageIsRecordedAsAChatbotExecutionOwnedByTheJob() {
        String jobId = submit("기록");
        var recorder = new com.zoop.chat.model.ChatModelRecorder(
                new org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate(jdbc), Clock.systemUTC());
        String id = recorder.start(jobId, 2, "chat-router", "replay");
        assertEquals("running", jdbc.queryForObject("SELECT status FROM ai_executions WHERE id = ?", String.class, id));
        recorder.finish(id, "succeeded", "sent", new com.zoop.ai.chat.ChatStageReply.Receipt("typesafe", "systemone-v1", "jev",
                "chat-router-1", "replay", 12L, null, Instant.now(), Instant.now()), null);
        recorder.finish(id, "failed", "not_sent", null, "late");
        var row = jdbc.queryForMap("SELECT feature, execution_mode, status, chat_job_id, stage, model, input_tokens, "
                + "output_tokens, error_code, finished_at, attempt_no, provider_send_state, provider_revision, "
                + "receipt_execution_mode, provider_sent_at, provider_received_at FROM ai_executions WHERE id = ?", id);
        assertEquals("chatbot", row.get("feature"));
        assertEquals("replay", row.get("execution_mode"));
        assertEquals("succeeded", row.get("status"), "an ended execution is not rewritten");
        assertEquals(jobId, row.get("chat_job_id"));
        assertEquals("chat-router", row.get("stage"));
        assertEquals(2, ((Number) row.get("attempt_no")).intValue());
        assertEquals("sent", row.get("provider_send_state"));
        assertEquals("systemone-v1", row.get("provider_revision"));
        assertEquals("replay", row.get("receipt_execution_mode"));
        assertNotNull(row.get("provider_sent_at"));
        assertNotNull(row.get("provider_received_at"));
        assertEquals("jev", row.get("model"));
        assertEquals(12L, ((Number) row.get("input_tokens")).longValue());
        assertNull(row.get("output_tokens"));
        assertNull(row.get("error_code"));
        assertTrue(row.get("finished_at") != null);
        // ai_executions keeps its chat job (ON DELETE RESTRICT): remove the record before the member cascade.
        jdbc.update("DELETE FROM ai_executions WHERE id = ?", id);
    }

    @Test
    void concurrentExecutorsClaimAQueuedJobOnce() throws Exception {
        String jobId = submit("동시 실행");
        int threads = 4;
        CountDownLatch start = new CountDownLatch(1);
        ExecutorService pool = Executors.newFixedThreadPool(threads);
        List<Future<Optional<ChatJobExecutor.Claim>>> claims = new ArrayList<>();
        for (int i = 0; i < threads; i++) {
            claims.add(pool.submit(() -> {
                start.await();
                return executor.claimNext();
            }));
        }
        start.countDown();
        List<ChatJobExecutor.Claim> won = new ArrayList<>();
        for (var claim : claims) claim.get(30, TimeUnit.SECONDS).ifPresent(won::add);
        pool.shutdown();
        assertEquals(1, won.size());
        assertEquals(jobId, won.getFirst().job().id());
        assertEquals(won.getFirst().ownerToken(),
                jdbc.queryForObject("SELECT owner_token FROM chat_jobs WHERE id = ?", String.class, jobId));
    }

    @Test
    void aCancelledRunStoresNothing() {
        String jobId = submit("취소될 질문");
        var claim = executor.claimNext().orElseThrow();
        assertEquals("running", service.getJob(member, jobId).status());
        engine.script((run, control) -> {
            service.cancel(member, run.jobId(), "cancel-" + suffix());
            assertThrows(ChatRunSuperseded.class, () -> control.phase("writing"));
            return ScriptedChatEngine.generalAnswer("늦은 답");
        });
        executor.execute(claim);

        var job = service.getJob(member, jobId);
        assertEquals("cancelled", job.status());
        assertNull(job.result());
        assertNull(jdbc.queryForObject("SELECT owner_token FROM chat_jobs WHERE id = ?", String.class, jobId));
    }

    @Test
    void aRunningAttemptCanBeAttachedFromOutsideItsThreadUnderTheSameFences() {
        String jobId = submit("MCP로 붙을 질문");
        var claim = executor.claimNext().orElseThrow();

        var attached = executor.attach(jobId, 1).orElseThrow();
        assertEquals(jobId, attached.run().jobId());
        assertEquals(1, attached.run().attemptNo());
        // The stored deadline is the claim's, rounded to the database's microseconds.
        assertTrue(Duration.between(claim.deadline(), attached.run().deadline()).abs().toMillis() < 1);
        assertTrue(attached.control().owned());
        assertEquals(List.of("tc-0"), attached.control().reserveToolCalls(1, List.of(reservation("company.read"))));
        // An approved (reserved) call is found by its exact capability and digest, and only while still reserved.
        String digest = "0".repeat(64);
        assertEquals(Optional.of("tc-0"), executor.reservedToolCall(jobId, 1, "company.read", digest));
        assertTrue(executor.reservedToolCall(jobId, 1, "issue.read", digest).isEmpty());
        assertTrue(executor.reservedToolCall(jobId, 1, "company.read", "1".repeat(64)).isEmpty());
        assertTrue(executor.reservedToolCall(jobId, 2, "company.read", digest).isEmpty());
        assertTrue(executor.attach(jobId, 2).isEmpty(), "another attempt");
        assertTrue(executor.attach("job-missing", 1).isEmpty());

        assertEquals(List.of("tc-1"), attached.control().reserveToolCalls(1, List.of(reservation("issue.read"))));
        attached.control().toolCallStarted("tc-1");
        assertTrue(executor.reservedToolCall(jobId, 1, "issue.read", digest).isEmpty(), "a started call is spent");

        service.cancel(member, jobId, "cancel-" + suffix());
        assertTrue(executor.attach(jobId, 1).isEmpty());
        assertThrows(ChatRunSuperseded.class, () -> attached.control().toolCallStarted("tc-0"));
        assertEquals("cancelled", jdbc.queryForObject(
                "SELECT status FROM chat_tool_calls WHERE chat_job_id = ? AND tool_call_id = 'tc-0'", String.class, jobId));
    }

    @Test
    void anExpiredLeaseIsRecoveredTheLateRunIsDiscardedAndARerunStartsANewAttempt() {
        String jobId = submit("오래 걸린 질문");
        var claim = executor.claimNext().orElseThrow();
        var later = new ChatJobExecutor(chats, runs, engines, mapper,
                Clock.fixed(Instant.now().plus(Duration.ofMinutes(5)), ZoneOffset.UTC), transactions);
        assertEquals(1, later.recoverExpired());

        var failed = service.getJob(member, jobId);
        assertEquals("failed", failed.status());
        assertEquals("deadline_guard", failed.failure().reason());
        assertEquals("rerun", failed.failure().retry());

        engine.script((run, control) -> ScriptedChatEngine.generalAnswer("너무 늦은 답"));
        executor.execute(claim);
        assertEquals("failed", service.getJob(member, jobId).status());

        assertEquals("queued", service.retry(member, jobId, "retry-" + suffix()).job().status());
        engine.script((run, control) -> {
            assertEquals(2, run.attemptNo());
            assertEquals("rerun", run.mode());
            return ScriptedChatEngine.generalAnswer("다시 처리한 답");
        });
        assertTrue(executor.runOnce());
        var done = service.getJob(member, jobId);
        assertEquals("completed", done.status());
        String attempts = jdbc.queryForObject("SELECT attempts::text FROM chat_jobs WHERE id = ?", String.class, jobId);
        assertTrue(attempts.contains("\"mode\": \"rerun\"") && attempts.contains("\"status\": \"succeeded\""), attempts);
    }

    @Test
    void aRunThatCalledAModelIsNeverRerunAfterItsLeaseExpires() {
        String jobId = submit("모델을 부른 뒤 멈춘 질문");
        var claim = executor.claimNext().orElseThrow();
        engine.script((run, control) -> {
            control.beforeModelCall();
            throw new ChatRunSuperseded();
        });
        executor.execute(claim);
        var later = new ChatJobExecutor(chats, runs, engines, mapper,
                Clock.fixed(Instant.now().plus(Duration.ofMinutes(5)), ZoneOffset.UTC), transactions);
        later.recoverExpired();

        var failed = service.getJob(member, jobId);
        assertEquals("response_unknown", failed.failure().reason());
        assertNull(failed.failure().retry());
        assertEquals(1, failed.runs());
    }

    @Test
    void toolCallsAreRecordedUnderTheRunAndClosedWithTheJob() {
        engine.script((run, control) -> {
            assertEquals(List.of("tc-0", "tc-1", "tc-2"), control.reserveToolCalls(1,
                    List.of(reservation("company.read"), reservation("issue.read"), reservation("evidence.resolve"))));
            control.toolCallStarted("tc-0");
            control.toolCallFinished("tc-0", new ChatToolCallEnd("succeeded", null, "fixture-2026-10-08",
                    List.of(EVIDENCE), true, false));
            control.toolCallStarted("tc-1");
            assertThrows(IllegalArgumentException.class,
                    () -> control.reserveToolCalls(2, Collections.nCopies(10, reservation("company.read"))));
            return ScriptedChatEngine.generalAnswer("도구를 부른 답");
        });
        String jobId = submit("도구 호출 기록");
        assertTrue(executor.runOnce());

        var rows = jdbc.queryForList("""
                SELECT tool_call_id, call_index, plan_revision, attempt_no, registry_version, registry_group, capability_id,
                       tool_id, schema_version, request_meta->>'limit' AS meta_limit, status, error_code, data_version,
                       array_to_string(evidence_ids, ',') AS evidence, truncated, next_allowed, finished_at
                  FROM chat_tool_calls WHERE chat_job_id = ? ORDER BY call_index
                """, jobId);
        assertEquals(3, rows.size(), "the refused plan reserved nothing");
        assertEquals(List.of("succeeded", "unknown", "cancelled"), rows.stream().map(r -> r.get("status")).toList());
        var first = rows.getFirst();
        assertEquals("tc-0", first.get("tool_call_id"));
        assertEquals(1, first.get("attempt_no"));
        assertEquals(ChatToolRegistry.VERSION, first.get("registry_version"));
        assertEquals("zoop-core-read", first.get("registry_group"));
        assertEquals("app:company.read", first.get("tool_id"));
        assertEquals("20", first.get("meta_limit"));
        assertEquals("fixture-2026-10-08", first.get("data_version"));
        assertEquals(EVIDENCE, first.get("evidence"));
        assertEquals(true, first.get("truncated"));
        assertEquals(false, first.get("next_allowed"));
        assertTrue(rows.stream().allMatch(r -> r.get("finished_at") != null));
    }

    @Test
    void aCancelClosesTheRunsToolCallsAndFencesItsLaterWrites() {
        String jobId = submit("도구 호출 중 취소");
        var claim = executor.claimNext().orElseThrow();
        engine.script((run, control) -> {
            control.reserveToolCalls(1, List.of(reservation("company.read"), reservation("issue.read")));
            control.toolCallStarted("tc-0");
            service.cancel(member, run.jobId(), "cancel-" + suffix());
            assertThrows(ChatRunSuperseded.class, () -> control.toolCallFinished("tc-0",
                    new ChatToolCallEnd("succeeded", null, "v1", List.of(), false, false)));
            assertThrows(ChatRunSuperseded.class, () -> control.toolCallStarted("tc-1"));
            throw new ChatRunSuperseded();
        });
        executor.execute(claim);

        assertEquals(List.of("unknown", "cancelled"), jdbc.queryForList(
                "SELECT status FROM chat_tool_calls WHERE chat_job_id = ? ORDER BY call_index", String.class, jobId));
    }

    @Test
    void theToolRunnerRecordsAnUnreadableGraphAsAFailedCallNotAnEmptyResult() {
        engine.script((run, control) -> {
            // The test context has no snapshot source: with or without a frozen version, the graph cannot be read.
            var results = tools.runStage(run, control, 1,
                    List.of(new ChatToolRequest("company.read", List.of("KRX:000660"), 20)));
            assertEquals(ChatToolRunner.UNAVAILABLE, results.getFirst().error());
            var path = tools.runStage(run, control, 1,
                    List.of(new ChatToolRequest("graph.path.read", List.of("KRX:000660", "NASDAQ:NVDA"), 20)));
            assertEquals(ChatToolRunner.UNAVAILABLE, path.getFirst().error());
            return new ChatEngineOutcome.Failed("transient", "provider_error", true);
        });
        String jobId = submit("그래프 없이 도구 호출");
        assertTrue(executor.runOnce());

        assertEquals(List.of("company.read failed:tool_unavailable", "graph.path.read failed:tool_unavailable"),
                jdbc.queryForList("SELECT capability_id || ' ' || status || ':' || error_code FROM chat_tool_calls "
                        + "WHERE chat_job_id = ? ORDER BY call_index", String.class, jobId));
    }

    private static ChatToolCallReservation reservation(String capability) {
        return new ChatToolCallReservation(ChatToolRegistry.VERSION, "zoop-core-read", capability, "app:" + capability,
                "chat-tool/v1", "0".repeat(64), "{\"limit\":20}");
    }

    private String submit(String question) {
        String jobId = "job-" + suffix();
        service.submit(member, session, jobId, new ChatJobRequest(jobId, question, null, null), "req-test");
        return jobId;
    }

    private String insertMember() {
        String id = "chat-exec-" + UUID.randomUUID();
        Instant now = Instant.now();
        String email = id + "@example.com";
        jdbc.update("""
                INSERT INTO members (id, analytics_key, email, email_key, display_name,
                                     password_hash, signup_method, status, mode, investor,
                                     completed, tutorial_completed, settings_version,
                                     created_at, updated_at, blocked_at)
                VALUES (?, ?, ?, ?, 'Chat Executor Test', 'test-hash', 'email', 'active', NULL, NULL,
                        false, false, 1, ?, ?, NULL)
                """, id, id, email, email, Timestamp.from(now), Timestamp.from(now));
        return id;
    }

    private static String suffix() {
        return UUID.randomUUID().toString().substring(0, 12);
    }
}
