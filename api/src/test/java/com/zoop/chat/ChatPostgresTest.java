package com.zoop.chat;

import java.sql.Timestamp;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;

import com.zoop.auth.config.MemberAuthorizationInterceptor;
import com.zoop.auth.config.MemberCsrfInterceptor;
import com.zoop.auth.service.AuthOriginPolicy;
import com.zoop.auth.service.MemberSessionService;
import com.zoop.auth.service.MemberSessionService.MemberPrincipal;
import com.zoop.auth.service.SessionCookie;
import com.zoop.chat.controller.ChatController;
import com.zoop.chat.dto.ChatAnswerSection;
import com.zoop.chat.dto.ChatApplied;
import com.zoop.chat.dto.ChatJobRequest;
import com.zoop.chat.dto.ChatResult;
import com.zoop.chat.dto.Citation;
import com.zoop.chat.dto.GraphTarget;
import com.zoop.chat.executor.ChatEngine;
import com.zoop.chat.service.ChatResponseGuard;
import com.zoop.chat.service.ChatService;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.common.exception.GlobalExceptionHandler;
import com.zoop.common.request.RequestIdFilter;
import com.zoop.common.response.Metadata;
import jakarta.servlet.http.Cookie;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.dao.DataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.transaction.annotation.Transactional;
import tools.jackson.databind.ObjectMapper;

import static org.junit.jupiter.api.Assertions.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/** ERD v6 sections 22, 23 and 36 against PostgreSQL: constraints, the single active job under concurrency, and the HTTP routes. */
@SpringBootTest(properties = {
        "ZOOP_AUTH_CSRF_ACTIVE_KEY_ID=test",
        "ZOOP_AUTH_CSRF_KEYS=test=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        "zoop.chat.questions-enabled=true",
        "zoop.chat.executor.enabled=false"
})
@EnabledIfEnvironmentVariable(named = "DB_URL", matches = "jdbc:postgresql:.*")
@Tag("auth-postgres")
class ChatPostgresTest {
    private static final String ORIGIN = "https://zoop.example";
    private static final String SELECTION = "{\"contextIds\":[],\"evidenceIds\":[],\"evidencePool\":[]}";

    @Autowired JdbcTemplate jdbc;
    @Autowired MemberSessionService sessions;
    @Autowired ChatService service;
    @Autowired ChatController controller;
    @Autowired ObjectMapper mapper;

    /** Intake needs a registered engine; the scheduler is off, so these tests only see queued jobs. */
    @TestConfiguration
    static class NoRunEngine {
        @Bean
        ChatEngine chatEngine() {
            return (run, control) -> {
                throw new IllegalStateException("no job runs in this test");
            };
        }
    }

    @Test
    @Transactional
    void tableConstraintsHoldTheJobContract() {
        String memberId = insertMember();
        String session = "conv-" + suffix();
        jdbc.update("INSERT INTO chat_sessions (id, member_id, created_at, updated_at) VALUES (?, ?, now(), now())",
                session, memberId);
        String root = insertJob(session, 1, "queued", null, 0);

        // One queued or running job per conversation.
        assertConstraint(() -> insertJob(session, 2, "queued", null, 0));
        // A clarification reply has a depth, a root question has none, and depth 2 never stores a clarification.
        assertConstraint(() -> insertJob(session, 2, "cancelled", root, 0));
        assertConstraint(() -> insertJob(session, 2, "cancelled", null, 1));
        assertConstraint(() -> jdbc.update("""
                INSERT INTO chat_jobs (id, session_id, seq, question, request_hash, asked_at, frozen_context,
                    frozen_selection, status, outcome, result, result_schema_version, message_id, resolves_job_id,
                    clarification_depth, created_at, updated_at, finished_at)
                VALUES (?, ?, 3, 'q', repeat('a', 64), now(), '{}', ?::jsonb, 'completed', 'clarification', '{}', 'v1', ?,
                    ?, 2, now(), now(), now())
                """, "job-" + suffix(), session, SELECTION, "message-" + suffix(), root));
        // Status and stored outcome go together.
        assertConstraint(() -> jdbc.update("UPDATE chat_jobs SET outcome = 'answered' WHERE id = ?", root));
        assertConstraint(() -> jdbc.update("UPDATE chat_jobs SET phase = 'planning' WHERE id = ?", root));
        assertConstraint(() -> jdbc.update("UPDATE chat_jobs SET runs = 4 WHERE id = ?", root));

        // The frozen request never changes; a completed job never changes.
        assertImmutable(() -> jdbc.update("UPDATE chat_jobs SET question = 'changed' WHERE id = ?", root));
        assertImmutable(() -> jdbc.update("UPDATE chat_jobs SET frozen_selection = "
                + "'{\"contextIds\":[\"x\"],\"evidenceIds\":[],\"evidencePool\":[]}' WHERE id = ?", root));
        // The selection keeps all three lists.
        assertConstraint(() -> jdbc.update("""
                INSERT INTO chat_jobs (id, session_id, seq, question, request_hash, asked_at, frozen_context,
                    frozen_selection, status, created_at, updated_at, finished_at)
                VALUES (?, ?, 9, 'q', repeat('a', 64), now(), '{}', '{"contextIds":[]}', 'cancelled', now(), now(), now())
                """, "job-" + suffix(), session));
        assertImmutable(() -> jdbc.update("UPDATE chat_jobs SET frozen_context = '{\"items\":[],\"evidenceCount\":1}' WHERE id = ?", root));
        jdbc.update("""
                UPDATE chat_jobs SET status = 'completed', outcome = 'clarification', result = '{"choices":[]}',
                    result_schema_version = 'v1', message_id = ?, finished_at = now() WHERE id = ?
                """, "message-" + suffix(), root);
        assertImmutable(() -> jdbc.update("UPDATE chat_jobs SET result = '{}' WHERE id = ?", root));
        assertImmutable(() -> jdbc.update("UPDATE chat_sessions SET member_id = ? WHERE id = ?", insertMember(), session));

        String reply = insertJob(session, 2, "queued", root, 1);
        assertEquals(1, jdbc.queryForObject("SELECT clarification_depth FROM chat_jobs WHERE id = ?", Integer.class, reply));
        assertEquals(1, jdbc.queryForObject("""
                SELECT count(*) FROM information_schema.table_constraints
                 WHERE table_schema = current_schema() AND table_name = 'ai_executions'
                   AND constraint_name = 'fk_ai_executions_chat_job'
                """, Integer.class));
    }

    @Test
    @Transactional
    void serviceStoresAndReturnsTheFrozenJobAgainstPostgres() {
        var member = new MemberPrincipal(insertMember(), "chat-test");
        String session = "conv-" + suffix();
        assertTrue(service.createSession(member, session).created());
        assertFalse(service.createSession(member, session).created());

        String jobId = "job-" + suffix();
        var request = new ChatJobRequest(jobId, "HBM이 뭐야?", null, null);
        var accepted = service.submit(member, session, jobId, request, "req-test");
        assertTrue(accepted.accepted());
        assertEquals("queued", accepted.job().status());
        assertEquals(List.of(), accepted.job().context().items());
        assertEquals("{\"contextIds\": [], \"evidenceIds\": [], \"evidencePool\": []}", jdbc.queryForObject(
                "SELECT frozen_selection::text FROM chat_jobs WHERE id = ?", String.class, jobId));
        var replay = service.submit(member, session, jobId, request, "req-test");
        assertFalse(replay.accepted());
        assertEquals(accepted.job(), replay.job());

        var cancelled = service.cancel(member, jobId, "cancel-" + suffix());
        assertEquals("cancelled", cancelled.status());
        assertNotNull(cancelled.finishedAt());
        var conversation = service.getCurrentConversation(member).conversation();
        assertEquals(session, conversation.session().id());
        assertEquals(1, conversation.jobs().size());
        assertEquals("cancelled", conversation.jobs().getFirst().status());
    }

    @Test
    void concurrentSubmissionsToOneConversationAcceptExactlyOne() throws Exception {
        String memberId = insertMember();
        try {
            var member = new MemberPrincipal(memberId, "chat-race");
            String session = "conv-" + suffix();
            service.createSession(member, session);
            int threads = 6;
            CountDownLatch start = new CountDownLatch(1);
            ExecutorService pool = Executors.newFixedThreadPool(threads);
            List<Future<String>> results = new ArrayList<>();
            for (int i = 0; i < threads; i++) {
                String jobId = "job-race-" + i + "-" + suffix();
                results.add(pool.submit(() -> {
                    start.await();
                    try {
                        service.submit(member, session, jobId, new ChatJobRequest(jobId, "동시 질문", null, null), "req-test");
                        return "accepted";
                    } catch (CustomException refused) {
                        return refused.getErrorCode().name();
                    }
                }));
            }
            start.countDown();
            List<String> outcomes = new ArrayList<>();
            for (var result : results) outcomes.add(result.get(30, TimeUnit.SECONDS));
            pool.shutdown();
            assertEquals(1, outcomes.stream().filter("accepted"::equals).count(), outcomes.toString());
            assertEquals(threads - 1, outcomes.stream().filter(ErrorCode.JOB_IN_PROGRESS.name()::equals).count(),
                    outcomes.toString());
            assertEquals(1, jdbc.queryForObject("SELECT count(*) FROM chat_jobs WHERE session_id = ?", Integer.class,
                    session));
        } finally {
            jdbc.update("DELETE FROM members WHERE id = ?", memberId);
        }
    }

    @Test
    @Transactional
    void httpRoutesRequireAMemberAndCsrfAndNeverRunAJobOnRead() throws Exception {
        String memberId = insertMember();
        var issued = sessions.issue(memberId, null, "chat-http");
        var guest = sessions.issueGuest(null, "chat-guest");
        MockMvc mvc = MockMvcBuilders.standaloneSetup(controller)
                .setControllerAdvice(new GlobalExceptionHandler())
                .addInterceptors(new MemberCsrfInterceptor(new AuthOriginPolicy(ORIGIN), sessions),
                        new MemberAuthorizationInterceptor(sessions))
                .addFilters(new RequestIdFilter()).build();
        Cookie cookie = new Cookie(SessionCookie.NAME, issued.token());
        String session = "conv-" + suffix();
        String jobId = "job-" + suffix();

        mvc.perform(get("/api/v1/chat/sessions/current")).andExpect(status().isUnauthorized());
        mvc.perform(get("/api/v1/chat/sessions/current").cookie(new Cookie(SessionCookie.NAME, guest.token())))
                .andExpect(status().isForbidden());
        mvc.perform(get("/api/v1/chat/sessions/current").cookie(cookie))
                .andExpect(status().isOk()).andExpect(jsonPath("$.conversation").isEmpty());

        mvc.perform(put("/api/v1/chat/sessions/{id}", session).cookie(cookie))
                .andExpect(status().isForbidden());
        mvc.perform(put("/api/v1/chat/sessions/{id}", session).cookie(cookie).header("Origin", ORIGIN)
                        .header("X-CSRF-Token", issued.response().csrfToken()))
                .andExpect(status().isCreated()).andExpect(jsonPath("$.jobs").value(0));
        mvc.perform(put("/api/v1/chat/sessions/{id}", session).cookie(cookie).header("Origin", ORIGIN)
                        .header("X-CSRF-Token", issued.response().csrfToken()))
                .andExpect(status().isOk());

        String body = "{\"jobId\":\"" + jobId + "\",\"question\":\"HBM이 뭐야?\"}";
        mvc.perform(post("/api/v1/chat/sessions/{id}/jobs", session).cookie(cookie).header("Origin", ORIGIN)
                        .header("X-CSRF-Token", issued.response().csrfToken()).contentType("application/json")
                        .content(body))
                .andExpect(status().isUnprocessableContent());
        mvc.perform(post("/api/v1/chat/sessions/{id}/jobs", session).cookie(cookie).header("Origin", ORIGIN)
                        .header("X-CSRF-Token", issued.response().csrfToken()).header("Idempotency-Key", jobId)
                        .contentType("application/json").content(body))
                .andExpect(status().isAccepted())
                .andExpect(jsonPath("$.status").value("queued"))
                .andExpect(jsonPath("$.result").isEmpty())
                .andExpect(jsonPath("$.resolves").isEmpty())
                .andExpect(jsonPath("$.context.items").isArray());
        mvc.perform(post("/api/v1/chat/sessions/{id}/jobs", session).cookie(cookie).header("Origin", ORIGIN)
                        .header("X-CSRF-Token", issued.response().csrfToken()).header("Idempotency-Key", jobId)
                        .contentType("application/json").content(body))
                .andExpect(status().isOk());

        String before = jdbc.queryForObject("SELECT updated_at::text FROM chat_jobs WHERE id = ?", String.class, jobId);
        mvc.perform(get("/api/v1/chat/jobs/{id}", jobId).cookie(cookie))
                .andExpect(status().isOk()).andExpect(jsonPath("$.runs").value(0));
        mvc.perform(get("/api/v1/chat/sessions/{id}", session).cookie(cookie))
                .andExpect(status().isOk()).andExpect(jsonPath("$.jobs.length()").value(1));
        assertEquals(before, jdbc.queryForObject("SELECT updated_at::text FROM chat_jobs WHERE id = ?", String.class, jobId));

        mvc.perform(post("/api/v1/chat/jobs/{id}/retry", jobId).cookie(cookie).header("Origin", ORIGIN)
                        .header("X-CSRF-Token", issued.response().csrfToken()).header("Idempotency-Key", "retry-1"))
                .andExpect(status().isConflict()).andExpect(jsonPath("$.error.code").value("JOB_IN_PROGRESS"));
        mvc.perform(post("/api/v1/chat/jobs/{id}/cancel", jobId).cookie(cookie).header("Origin", ORIGIN)
                        .header("X-CSRF-Token", issued.response().csrfToken()).header("Idempotency-Key", "cancel-1"))
                .andExpect(status().isOk()).andExpect(jsonPath("$.status").value("cancelled"));
    }

    @Test
    void everyReturnPathReChecksAStoredCitationWithTheRealEvidenceReadAndLeavesItStored() throws Exception {
        // The cited evidence id is unknown to the evidence registry, so the real EvidenceService cannot read it now: the
        // same outcome as a withdrawn or unverifiable document. Not transactional: the evidence read has its own transaction.
        String memberId = insertMember();
        try {
            var member = new MemberPrincipal(memberId, "chat-guard");
            var issued = sessions.issue(memberId, null, "chat-guard");
            MockMvc mvc = MockMvcBuilders.standaloneSetup(controller)
                    .setControllerAdvice(new GlobalExceptionHandler())
                    .addInterceptors(new MemberCsrfInterceptor(new AuthOriginPolicy(ORIGIN), sessions),
                            new MemberAuthorizationInterceptor(sessions))
                    .addFilters(new RequestIdFilter()).build();
            Cookie cookie = new Cookie(SessionCookie.NAME, issued.token());
            String session = "conv-" + suffix();
            service.createSession(member, session);
            String jobId = "job-" + suffix();
            String evidenceId = "ev-" + "c".repeat(64);
            String question = "근거 기반 질문";
            var result = new ChatResult("answered", "msg-" + jobId, "보호된 답변",
                    List.of(new ChatAnswerSection("evidence_grounded", "보호된 답변", List.of(evidenceId))), "evidence_grounded",
                    null, List.of("art-1"), List.of(new Citation("article", evidenceId, "인용", "art-1", "v1", null, null, 0, 2,
                            "보호된 기사 제목", "언론사", Instant.now(), "https://example.invalid/a")),
                    List.of(new GraphTarget("KRX:000660", "company")),
                    new ChatApplied(List.of(), List.of(), null, null, Instant.now(), false), List.of(), null, List.of(),
                    new Metadata("zoop", Instant.now(), null, "req-0", false, List.of()));
            jdbc.update("""
                    INSERT INTO chat_jobs (id, session_id, seq, question, request_hash, asked_at, frozen_context,
                        frozen_selection, status, outcome, message_id, result, result_schema_version, runs,
                        created_at, updated_at, finished_at)
                    VALUES (?, ?, 1, ?, ?, now(), ?::jsonb, ?::jsonb, 'completed', 'answered', ?, ?::jsonb, 'chat-result/v1',
                        1, now(), now(), now())
                    """, jobId, session, question,
                    ChatService.requestHash(session, new ChatJobRequest(jobId, question, null, null)),
                    "{\"items\":[{\"id\":\"" + evidenceId + "\",\"kind\":\"evidence\",\"label\":\"보호된 기사 제목\"}],"
                            + "\"evidenceCount\":1,\"period\":null,\"asOf\":null,\"graphVersion\":null}",
                    SELECTION, "msg-" + jobId, mapper.writeValueAsString(result));

            mvc.perform(get("/api/v1/chat/jobs/{id}", jobId).cookie(cookie))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.result.answer").value(ChatResponseGuard.WITHHELD_ANSWER))
                    .andExpect(jsonPath("$.result.answerBasis").value("none"))
                    .andExpect(jsonPath("$.result.citations.length()").value(0))
                    .andExpect(jsonPath("$.result.sections.length()").value(0))
                    .andExpect(jsonPath("$.result.graphTargets.length()").value(0))
                    .andExpect(jsonPath("$.context.items[0].label").value(ChatResponseGuard.WITHHELD_EVIDENCE_LABEL));
            mvc.perform(get("/api/v1/chat/sessions/{id}", session).cookie(cookie))
                    .andExpect(jsonPath("$.jobs[0].result.answer").value(ChatResponseGuard.WITHHELD_ANSWER));
            mvc.perform(get("/api/v1/chat/sessions/current").cookie(cookie))
                    .andExpect(jsonPath("$.conversation.jobs[0].result.answer").value(ChatResponseGuard.WITHHELD_ANSWER));
            mvc.perform(post("/api/v1/chat/sessions/{id}/jobs", session).cookie(cookie).header("Origin", ORIGIN)
                            .header("X-CSRF-Token", issued.response().csrfToken()).header("Idempotency-Key", jobId)
                            .contentType("application/json")
                            .content("{\"jobId\":\"" + jobId + "\",\"question\":\"" + question + "\"}"))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.result.answer").value(ChatResponseGuard.WITHHELD_ANSWER));

            assertEquals("보호된 답변", jdbc.queryForObject("SELECT result->>'answer' FROM chat_jobs WHERE id = ?",
                    String.class, jobId), "the stored result never changes");
            assertEquals(1, jdbc.queryForObject("SELECT jsonb_array_length(result->'citations') FROM chat_jobs WHERE id = ?",
                    Integer.class, jobId));
        } finally {
            jdbc.update("DELETE FROM members WHERE id = ?", memberId);
        }
    }

    private String insertJob(String session, int seq, String status, String resolves, int depth) {
        String id = "job-" + suffix();
        boolean finished = !status.equals("queued") && !status.equals("running");
        jdbc.update("""
                INSERT INTO chat_jobs (id, session_id, seq, question, request_hash, asked_at, frozen_context,
                    frozen_selection, status, resolves_job_id, clarification_depth, created_at, updated_at, finished_at)
                VALUES (?, ?, ?, 'q', repeat('a', 64), now(), '{"items":[]}', ?::jsonb, ?, ?, ?, now(), now(), ?)
                """, id, session, seq, SELECTION, status, resolves, depth,
                finished ? Timestamp.from(Instant.now()) : null);
        return id;
    }

    /** A refused write aborts the PostgreSQL transaction, so each one runs inside its own savepoint. */
    private void assertConstraint(Runnable write) {
        jdbc.execute("SAVEPOINT refused_write");
        try {
            assertThrows(DataIntegrityViolationException.class, write::run);
        } finally {
            jdbc.execute("ROLLBACK TO SAVEPOINT refused_write");
        }
    }

    private void assertImmutable(Runnable write) {
        jdbc.execute("SAVEPOINT refused_write");
        try {
            var error = assertThrows(DataAccessException.class, write::run);
            assertTrue(String.valueOf(error.getMostSpecificCause().getMessage()).contains("immutable"), error.toString());
        } finally {
            jdbc.execute("ROLLBACK TO SAVEPOINT refused_write");
        }
    }

    private String insertMember() {
        String memberId = "chat-test-" + UUID.randomUUID();
        Instant now = Instant.now();
        String email = memberId + "@example.com";
        jdbc.update("""
                INSERT INTO members (id, analytics_key, email, email_key, display_name,
                                     password_hash, signup_method, status, mode, investor,
                                     completed, tutorial_completed, settings_version,
                                     created_at, updated_at, blocked_at)
                VALUES (?, ?, ?, ?, 'Chat Test', 'test-hash', 'email', 'active', NULL, NULL,
                        false, false, 1, ?, ?, NULL)
                """, memberId, memberId, email, email, Timestamp.from(now), Timestamp.from(now));
        return memberId;
    }

    private static String suffix() {
        return UUID.randomUUID().toString().substring(0, 12);
    }
}
