package com.zoop.admin.transcripts;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;
import com.zoop.admin.auth.service.AdminSessionCookie;
import com.zoop.admin.auth.service.AdminSessionService;
import com.zoop.common.request.RequestIdFilter;
import com.zoop.auth.service.CsrfKeyRing;
import com.zoop.auth.service.SignedCursor;
import com.zaxxer.hikari.HikariDataSource;
import jakarta.servlet.http.Cookie;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.List;
import java.util.UUID;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.bean.override.mockito.MockitoSpyBean;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.context.WebApplicationContext;
import tools.jackson.databind.ObjectMapper;
import javax.sql.DataSource;
import org.springframework.transaction.support.TransactionSynchronizationManager;

/** FS066-03 / A-ADM-02b: real authorization, snapshot queries and committed audits, synthetic data only. */
@SpringBootTest(properties = {
        "ZOOP_AUTH_CSRF_ACTIVE_KEY_ID=test",
        "ZOOP_AUTH_CSRF_KEYS=test=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        "ZOOP_AUTH_ALLOWED_ORIGINS=https://zoop.example",
        "zoop.admin.transcript-readers=transcript-admin-allowed",
        "spring.datasource.hikari.maximum-pool-size=1",
        "spring.datasource.hikari.connection-timeout=1000",
        // Flyway itself opens two migration connections; keep it off the one-connection application pool.
        "spring.flyway.url=${DB_URL}",
        "spring.flyway.user=${DB_USERNAME}",
        "spring.flyway.password=${DB_PASSWORD}"
})
@Tag("auth-postgres")
@EnabledIfEnvironmentVariable(named = "DB_URL", matches = "jdbc:postgresql:.*")
class TranscriptPostgresTest {
    private static final String ALLOWED = "transcript-admin-allowed", DENIED = "transcript-admin-denied";
    private static final String EMAIL = "synthetic-private@example.test", PHONE = "010-2345-6789";
    @Autowired WebApplicationContext context;
    @Autowired RequestIdFilter requestIds;
    @Autowired JdbcTemplate jdbc;
    @Autowired AdminSessionService sessions;
    @Autowired ObjectMapper mapper;
    @Autowired CsrfKeyRing keys;
    @Autowired DataSource dataSource;
    @Autowired TranscriptRepository repository;
    @MockitoSpyBean TranscriptMasker masker;
    @MockitoSpyBean TranscriptAudit audit;
    @MockitoSpyBean TranscriptReadPolicy policy;
    private MockMvc mvc;
    private String member, session, job;
    private Cookie allowed, denied;

    @BeforeEach void seed() {
        mvc = MockMvcBuilders.webAppContextSetup(context).addFilters(requestIds).build();
        for (String admin : List.of(ALLOWED, DENIED)) {
            jdbc.update("INSERT INTO admins(id,email,email_key,display_name,password_hash,role,status,created_at) VALUES(?,?,?,'합성 관리자','synthetic-hash','admin','active',now())",
                    admin, admin + "@example.test", admin + "@example.test");
        }
        allowed = cookie(ALLOWED); denied = cookie(DENIED);
        member = "transcript-member-" + UUID.randomUUID();
        jdbc.update("""
                INSERT INTO members(id,analytics_key,email,email_key,display_name,password_hash,signup_method,status,
                    completed,tutorial_completed,settings_version,created_at,updated_at)
                VALUES(?,?,?,?,'합성 질문자','synthetic-hash','email','active',true,true,1,now(),now())
                """, member, member, EMAIL, EMAIL);
        session = session(Instant.now().minusMillis(2));
        job = job(session, 1, "질문 " + EMAIL + " " + member + " 합성 질문자", "답변 " + PHONE);
        vote(job, "down", "검토 사유 " + EMAIL);
    }

    private Cookie cookie(String id) {
        var issued = sessions.issue(id, id + "@example.test", "합성 관리자", null, "fixture-session",
                (a, b, c, d, e, f) -> { });
        return new Cookie(AdminSessionCookie.NAME, issued.token());
    }

    private String session(Instant at) {
        String id = "session-" + UUID.randomUUID();
        jdbc.update("INSERT INTO chat_sessions(id,member_id,created_at,updated_at) VALUES(?,?,?,?)",
                id, member, Timestamp.from(at), Timestamp.from(at));
        return id;
    }

    private String job(String conversation, int seq, String question, String answer) {
        return job(conversation, seq, question, answer, Instant.now());
    }

    private String job(String conversation, int seq, String question, String answer, Instant askedAt) {
        String id = "job-" + UUID.randomUUID();
        var result = mapper.createObjectNode().put("answer", answer); result.putArray("citations").addObject().put("evidenceId", "synthetic-evidence");
        jdbc.update("""
                INSERT INTO chat_jobs(id,session_id,seq,question,request_hash,asked_at,frozen_context,frozen_selection,
                    status,outcome,message_id,result,result_schema_version,created_at,updated_at,finished_at)
                VALUES(?,?,?,?,repeat('a',64),?,'{"items":[{"kind":"company","id":"synthetic-company","label":"합성 기업"}]}',
                    '{"contextIds":[],"evidenceIds":[],"evidencePool":[]}', 'completed','answered',?,?::jsonb,'synthetic-v1',?,?,?)
                """, id, conversation, seq, question, Timestamp.from(askedAt), "message-" + UUID.randomUUID(), result.toString(),
                Timestamp.from(askedAt), Timestamp.from(askedAt), Timestamp.from(askedAt));
        return id;
    }

    private void vote(String target, String value, String reason) {
        String message = jdbc.queryForObject("SELECT message_id FROM chat_jobs WHERE id=?", String.class, target);
        jdbc.update("""
                INSERT INTO ai_result_feedback(id,member_id,feature,target_id,target_version,chat_job_id,value,reason,created_at,updated_at)
                VALUES(?,?,'chatbot_answer',?,'synthetic-v1',?,?,?,now(),now())
                """, "feedback-" + UUID.randomUUID(), member, message, target, value, reason);
    }

    @AfterEach void clean() {
        // Each test commits its own fixture: REQUIRES_NEW audit writes must see the administrator row.
        jdbc.update("DELETE FROM audit_logs WHERE admin_id IN (?,?)", ALLOWED, DENIED);
        if (member != null) {
            jdbc.update("DELETE FROM chat_sessions WHERE member_id=?", member);
            jdbc.update("DELETE FROM members WHERE id=?", member);
        }
        jdbc.update("DELETE FROM admins WHERE id IN (?,?)", ALLOWED, DENIED);
    }

    @Test void unauthenticatedAndAdminAllOnlyNeverReceiveConversationContent() throws Exception {
        mvc.perform(get("/api/v1/admin/transcripts").param("purpose", "품질 점검"))
                .andExpect(status().isUnauthorized());
        var response = mvc.perform(get("/api/v1/admin/transcripts/" + session).cookie(denied))
                .andExpect(status().isForbidden()).andExpect(jsonPath("$.error.code").value("ACCESS_DENIED"))
                .andReturn().getResponse().getContentAsString();
        assertFalse(response.contains(EMAIL)); assertFalse(response.contains("messages"));
        assertEquals(1L, jdbc.queryForObject("SELECT count(*) FROM audit_logs WHERE admin_id=? AND action='transcript.view' AND outcome='denied'", Long.class, DENIED));
    }

    @Test void invalidPurposeIs422AndItsPersonalDataIsNotAudited() throws Exception {
        for (String purpose : List.of("", " ", EMAIL, PHONE, "연락처 " + PHONE, "검토\n목적"))
            mvc.perform(get("/api/v1/admin/transcripts/" + session).cookie(allowed).param("purpose", purpose))
                    .andExpect(status().isUnprocessableContent()).andExpect(jsonPath("$.error.code").value("INVALID_REQUEST"));
        mvc.perform(get("/api/v1/admin/transcripts/" + session).cookie(allowed))
                .andExpect(status().isUnprocessableContent());
        assertEquals(0L, jdbc.queryForObject("SELECT count(*) FROM audit_logs WHERE admin_id=? AND purpose IS NOT NULL", Long.class, ALLOWED));
    }

    @Test void succeedsOnlyAfterAuditCommitAndDoesNotMutateOrExposeOriginals() throws Exception {
        String request = "transcript-read-" + UUID.randomUUID();
        var response = mvc.perform(get("/api/v1/admin/transcripts/" + session).cookie(allowed)
                        .param("purpose", "  응답 품질 점검  ").header("X-Request-ID", request))
                .andExpect(status().isOk()).andExpect(header().string("Cache-Control", "no-store"))
                .andExpect(jsonPath("$.masking.completed").value(true))
                .andExpect(jsonPath("$.masking.counts.email").value(2))
                .andExpect(jsonPath("$.masking.counts.phone").value(1))
                .andExpect(jsonPath("$.masking.counts.userId").value(1))
                .andExpect(jsonPath("$.masking.counts.name").value(1))
                .andExpect(jsonPath("$.messages[0].seq").value(1))
                .andExpect(jsonPath("$.messages[0].citationCount").value(1))
                .andExpect(jsonPath("$.messages[0].feedback.down").value(1))
                .andReturn().getResponse().getContentAsString();
        for (String secret : List.of(EMAIL, PHONE, member)) assertFalse(response.contains(secret));
        var savedAudit = jdbc.queryForMap("SELECT purpose,detail::text,outcome FROM audit_logs WHERE request_id=? AND action='transcript.view'", request);
        assertEquals("succeeded", savedAudit.get("outcome")); assertEquals("응답 품질 점검", savedAudit.get("purpose"));
        String detail = savedAudit.get("detail").toString();
        for (String secret : List.of(EMAIL, PHONE, member, "질문", "답변")) assertFalse(detail.contains(secret));
        assertTrue(jdbc.queryForObject("SELECT question FROM chat_jobs WHERE id=?", String.class, job).contains(EMAIL));
    }

    @Test void maskingAndAuditFailuresReturn503WithoutAnyPartialOrOriginalBody() throws Exception {
        doThrow(new IllegalArgumentException("synthetic-private@example.test")).when(masker).mask(anyString(), any());
        mvc.perform(get("/api/v1/admin/transcripts/" + session).cookie(allowed).param("purpose", "품질 점검"))
                .andExpect(status().isServiceUnavailable()).andExpect(jsonPath("$.error.code").value("MASKING_FAILED"))
                .andExpect(jsonPath("$.messages").doesNotExist());
        reset(masker);
        doThrow(new IllegalStateException("audit unavailable")).when(audit)
                .record(any(), any(), any(), any(), any(), any(), any(), anyInt(), any());
        mvc.perform(get("/api/v1/admin/transcripts/" + session).cookie(allowed).param("purpose", "품질 점검"))
                .andExpect(status().isServiceUnavailable()).andExpect(jsonPath("$.error.code").value("AUDIT_UNAVAILABLE"))
                .andExpect(jsonPath("$.messages").doesNotExist());
    }

    @Test void listsDislikedOnlyAndUsesBoundCursorWithoutReplacingMissingSessions() throws Exception {
        String another = session(Instant.now().minusMillis(1));
        String positive = job(another, 1, "일반 합성 질문", "일반 합성 답변"); vote(positive, "up", null);
        var disliked = mapper.readTree(mvc.perform(get("/api/v1/admin/transcripts").cookie(allowed)
                        .param("purpose", "품질 점검").param("only", "disliked").param("limit", "100"))
                .andExpect(status().isOk()).andReturn().getResponse().getContentAsString());
        assertTrue(disliked.path("items").valueStream().anyMatch(n -> session.equals(n.path("id").asText())));
        assertFalse(disliked.path("items").valueStream().anyMatch(n -> another.equals(n.path("id").asText())));
        var first = mapper.readTree(mvc.perform(get("/api/v1/admin/transcripts").cookie(allowed)
                        .param("purpose", "품질 점검").param("limit", "1"))
                .andExpect(status().isOk()).andReturn().getResponse().getContentAsString());
        String cursor = first.path("nextCursor").asText(); assertFalse(cursor.isBlank());
        var next = mapper.readTree(mvc.perform(get("/api/v1/admin/transcripts").cookie(allowed)
                        .param("purpose", "품질 점검").param("limit", "1").param("cursor", cursor))
                .andExpect(status().isOk()).andReturn().getResponse().getContentAsString());
        assertNotEquals(first.at("/items/0/id").asText(), next.at("/items/0/id").asText());
        assertEquals(first.path("total").asLong(), next.path("total").asLong());
        mvc.perform(get("/api/v1/admin/transcripts").cookie(allowed).param("purpose", "다른 목적").param("cursor", cursor))
                .andExpect(status().isUnprocessableContent()).andExpect(jsonPath("$.error.code").value("INVALID_CURSOR"));
        mvc.perform(get("/api/v1/admin/transcripts/missing-session").cookie(allowed).param("purpose", "품질 점검"))
                .andExpect(status().isNotFound());
    }

    @Test void rechecksPermissionForTheSameSessionOnEveryRequest() throws Exception {
        mvc.perform(get("/api/v1/admin/transcripts/" + session).cookie(allowed).param("purpose", "품질 점검"))
                .andExpect(status().isOk());
        doReturn(false).when(policy).allows(any());
        mvc.perform(get("/api/v1/admin/transcripts/" + session).cookie(allowed).param("purpose", "품질 점검"))
                .andExpect(status().isForbidden()).andExpect(jsonPath("$.messages").doesNotExist());
    }

    @Test void oneConnectionPoolCompletesReadsAndDeniedAuditsAfterReleasingTheReadTransaction() throws Exception {
        assertEquals(1, assertInstanceOf(HikariDataSource.class, dataSource).getMaximumPoolSize());
        doAnswer(call -> {
            assertFalse(TransactionSynchronizationManager.isActualTransactionActive(), "masking must follow read commit");
            return call.callRealMethod();
        }).when(masker).mask(anyString(), any());
        mvc.perform(get("/api/v1/admin/transcripts").cookie(allowed).param("purpose", "품질 점검"))
                .andExpect(status().isOk());
        mvc.perform(get("/api/v1/admin/transcripts/" + session).cookie(allowed).param("purpose", "품질 점검"))
                .andExpect(status().isOk());
        mvc.perform(get("/api/v1/admin/transcripts/" + session).cookie(denied))
                .andExpect(status().isForbidden());
        mvc.perform(get("/api/v1/admin/transcripts/" + session).cookie(allowed))
                .andExpect(status().isUnprocessableContent());
        assertEquals(4L, jdbc.queryForObject("SELECT count(*) FROM audit_logs WHERE admin_id IN (?,?) AND action='transcript.view'", Long.class, ALLOWED, DENIED));
    }

    private tools.jackson.databind.JsonNode page(String only, String cursor) throws Exception {
        var request = get("/api/v1/admin/transcripts").cookie(allowed).param("purpose", "품질 점검")
                .param("only", only).param("limit", "1");
        if (cursor != null) request.param("cursor", cursor);
        return mapper.readTree(mvc.perform(request).andExpect(status().isOk()).andReturn().getResponse().getContentAsString());
    }

    @Test void cursorPagesAndDislikedFilterExcludeVotesAddedOrChangedAfterTheirAsOf() throws Exception {
        String changedSession = session(Instant.now().minusSeconds(60));
        String changedJob = job(changedSession, 1, "변경 전 질문", "답변"); vote(changedJob, "down", null);
        String addedSession = session(Instant.now().minusSeconds(120));
        String addedJob = job(addedSession, 1, "추가 전 질문", "답변"); vote(addedJob, "down", null);
        var first = page("all", null);
        var dislikedFirst = page("disliked", null);
        String cursor = first.path("nextCursor").asText();
        var position = SignedCursor.decode(mapper, keys, "admin-transcript-cursor-v1", cursor, TranscriptService.Position.class);
        var after = Timestamp.from(position.asOf().plusSeconds(60));
        jdbc.update("UPDATE ai_result_feedback SET value='up',updated_at=? WHERE chat_job_id=?", after, changedJob);
        String lateJob = job(addedSession, 2, "늦은 질문", "답변"); vote(lateJob, "down", null);
        jdbc.update("UPDATE ai_result_feedback SET updated_at=? WHERE chat_job_id=?", after, lateJob);
        var changed = page("all", cursor);
        assertEquals(changedSession, changed.at("/items/0/id").asText());
        assertEquals(0, changed.at("/items/0/up").asInt());
        assertEquals(0, changed.at("/items/0/down").asInt());
        var added = page("all", changed.path("nextCursor").asText());
        assertEquals(addedSession, added.at("/items/0/id").asText());
        assertEquals(1, added.at("/items/0/down").asInt());
        var disliked = page("disliked", dislikedFirst.path("nextCursor").asText());
        assertEquals(addedSession, disliked.at("/items/0/id").asText());
        assertEquals(1, disliked.at("/items/0/down").asInt());
    }

    @Test void voteCountsAlsoExcludeJobsAskedAfterTheSnapshotEvenWhenTheVoteTimestampIsEarlier() {
        Instant asOf = Instant.now().plusSeconds(60);
        String futureJob = job(session, 2, "미래 시각 질문", "답변", asOf.plusSeconds(60)); vote(futureJob, "down", null);
        var row = repository.list("all", asOf, null, null, 100).stream()
                .filter(item -> item.session().id().equals(session)).findFirst().orElseThrow();
        assertEquals(1, row.down());
        assertEquals(1, row.messages());
    }
}
