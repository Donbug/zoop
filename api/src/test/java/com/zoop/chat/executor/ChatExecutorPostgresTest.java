package com.zoop.chat.executor;

import java.sql.Timestamp;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.ArrayList;
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
import com.zoop.chat.service.ChatService;
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
    @Autowired JdbcTemplate jdbc;
    @Autowired ChatService service;
    @Autowired ChatJobExecutor executor;
    @Autowired ScriptedChatEngine engine;
    @Autowired ChatRepository chats;
    @Autowired ChatExecutionRepository runs;
    @Autowired ObjectProvider<ChatEngine> engines;
    @Autowired ObjectMapper mapper;
    @Autowired PlatformTransactionManager transactions;

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
