package com.zoop.admin.jobs;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.jayway.jsonpath.JsonPath;
import com.zoop.admin.auth.provision.AdminProvisioningService;
import com.zoop.admin.auth.service.AdminSessionCookie;
import com.zoop.common.request.RequestIdFilter;
import jakarta.servlet.http.Cookie;
import java.sql.Timestamp;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.List;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.dao.DataAccessException;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.mock.web.MockHttpServletResponse;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.ResultActions;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.context.WebApplicationContext;

/** The admin job API over the real migration, admin session, CSRF, idempotency and audit tables (#132, #133). */
@SpringBootTest(properties = {
        "ZOOP_AUTH_CSRF_ACTIVE_KEY_ID=test",
        "ZOOP_AUTH_CSRF_KEYS=test=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        "ZOOP_AUTH_ALLOWED_ORIGINS=https://zoop.example"
})
@EnabledIfEnvironmentVariable(named = "DB_URL", matches = "jdbc:postgresql:.*")
@Tag("auth-postgres")
class AnalysisJobPostgresTest {
    private static final String ORIGIN = "https://zoop.example";
    private static final String PASSWORD = "Secure admin password 2026";

    @Autowired WebApplicationContext context;
    @Autowired RequestIdFilter requestIds;
    @Autowired JdbcTemplate jdbc;
    @Autowired AdminProvisioningService provisioning;

    private MockMvc mvc;

    private record Login(Cookie cookie, String csrf) {
    }

    @BeforeEach
    void setUp() {
        mvc = MockMvcBuilders.webAppContextSetup(context).addFilters(requestIds).build();
    }

    @Test
    void listAndDetailNeedAnAdminAndNeverShowInternalProjectionJobs() throws Exception {
        mvc.perform(get("/api/v1/admin/jobs")).andExpect(status().isUnauthorized());
        String suffix = UUID.randomUUID().toString();
        Login login = login(suffix);
        String failed = insertJob("failed", "admin", "ingest", null, suffix + "-list");
        String projection = insertJob("queued", "internal_projection", "project", null, suffix + "-projection");

        mvc.perform(get("/api/v1/admin/jobs/{id}", failed).cookie(login.cookie()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.id").value(failed))
                .andExpect(jsonPath("$.retry.code").value("worker_unavailable"))
                .andExpect(jsonPath("$.report").isEmpty())
                .andExpect(jsonPath("$.error.code").value("provider_error"));
        mvc.perform(get("/api/v1/admin/jobs/{id}", projection).cookie(login.cookie()))
                .andExpect(status().isNotFound());
        mvc.perform(get("/api/v1/admin/jobs").param("status", "failed").cookie(login.cookie()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.items[?(@.id == '" + failed + "')]").exists())
                .andExpect(jsonPath("$.items[?(@.id == '" + projection + "')]").doesNotExist())
                .andExpect(jsonPath("$.retryRule").isNotEmpty());
        mvc.perform(get("/api/v1/admin/jobs").param("status", "paused").cookie(login.cookie()))
                .andExpect(status().isUnprocessableContent());
    }

    @Test
    void theListPagesWithASignedCursorAndTheBaselineIsTheNewestNormalIngestStart() throws Exception {
        String suffix = UUID.randomUUID().toString();
        Login login = login(suffix);
        // Requested ten years ahead of now, so these three are the newest succeeded jobs whatever else the shared database
        // holds, including the same rows from earlier runs (whose "now" was earlier; the rows are one second apart).
        Instant base = Instant.now().plus(3_650, ChronoUnit.DAYS).truncatedTo(ChronoUnit.SECONDS);
        String oldest = insertAt("succeeded", "ingest", suffix + "-p1", planInput("p1-" + suffix), base);
        String middle = insertAt("succeeded", "ingest", suffix + "-p2", planInput("p2-" + suffix), base.plusSeconds(1));
        String newest = insertAt("succeeded", "ingest", suffix + "-p3", planInput("p3-" + suffix), base.plusSeconds(2));

        String first = mvc.perform(get("/api/v1/admin/jobs").param("status", "succeeded").param("limit", "1")
                        .cookie(login.cookie()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.items.length()").value(1))
                .andExpect(jsonPath("$.items[0].id").value(newest))
                .andExpect(jsonPath("$.ingest.jobId").value(newest))
                .andExpect(jsonPath("$.ingest.at").value(base.plusSeconds(12).toString()))
                .andExpect(jsonPath("$.ingest.unresolvedFailures").isEmpty())
                .andReturn().getResponse().getContentAsString();
        String cursor = JsonPath.read(first, "$.nextCursor");
        assertNotNull(cursor);
        String second = mvc.perform(get("/api/v1/admin/jobs").param("status", "succeeded").param("cursor", cursor)
                        .cookie(login.cookie()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.items.length()").value(1))
                .andExpect(jsonPath("$.items[0].id").value(middle))
                .andReturn().getResponse().getContentAsString();
        String third = JsonPath.read(second, "$.nextCursor");
        mvc.perform(get("/api/v1/admin/jobs").param("status", "succeeded").param("cursor", third).cookie(login.cookie()))
                .andExpect(jsonPath("$.items[0].id").value(oldest));

        // A cursor is bound to its filter, its limit and the admin it was issued to.
        mvc.perform(get("/api/v1/admin/jobs").param("status", "failed").param("cursor", cursor).cookie(login.cookie()))
                .andExpect(status().isUnprocessableContent());
        mvc.perform(get("/api/v1/admin/jobs").param("status", "succeeded").param("cursor", cursor).param("limit", "2")
                        .cookie(login.cookie()))
                .andExpect(status().isUnprocessableContent());
        mvc.perform(get("/api/v1/admin/jobs").param("status", "succeeded").param("cursor", cursor)
                        .cookie(login(suffix + "-other").cookie()))
                .andExpect(status().isUnprocessableContent());
        mvc.perform(get("/api/v1/admin/jobs").param("limit", "101").cookie(login.cookie()))
                .andExpect(status().isUnprocessableContent());
    }

    @Test
    void aLaterSuccessOnTheSameInputSupersedesAFailedJobInDetailAndRetry() throws Exception {
        String suffix = UUID.randomUUID().toString();
        Login login = login(suffix);
        String input = planInput("same-" + suffix);
        Instant at = Instant.now().minusSeconds(3_600);
        String failed = insertAt("failed", "revalidate", suffix + "-f", input, at);
        String later = insertAt("succeeded", "revalidate", suffix + "-s", input, at.plusSeconds(60));

        mvc.perform(get("/api/v1/admin/jobs/{id}", failed).cookie(login.cookie()))
                .andExpect(jsonPath("$.retry.code").value("superseded"))
                .andExpect(jsonPath("$.retry.blockedBy").value(later));
        retry(login, failed, "retry-sup-" + suffix, "다시").andExpect(status().isConflict());
    }

    @Test
    void cancelEndsAQueuedJobAsksARunningOneAndRefusesAFinishedOne() throws Exception {
        String suffix = UUID.randomUUID().toString();
        Login login = login(suffix);
        String queued = insertJob("queued", "admin", "ingest", null, suffix + "-queued");
        String finished = insertJob("succeeded", "admin", "ingest", null, suffix + "-done");

        cancel(login, queued, "cancel-q-" + suffix, "잘못 접수함").andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("cancelled"))
                .andExpect(jsonPath("$.cancelRequested").value(true));
        // Same key and body: the stored response again, one audit row only.
        cancel(login, queued, "cancel-q-" + suffix, "잘못 접수함").andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("cancelled"));
        cancel(login, queued, "cancel-q-" + suffix, "다른 사유").andExpect(status().isConflict())
                .andExpect(jsonPath("$.error.code").value("IDEMPOTENCY_CONFLICT"));
        assertEquals(1, auditCount("analysis.job.cancel", queued));

        cancel(login, finished, "cancel-s-" + suffix, "취소 시도").andExpect(status().isConflict())
                .andExpect(jsonPath("$.error.code").value("REVISION_CONFLICT"));
        assertEquals("succeeded", jdbc.queryForObject("SELECT status FROM analysis_jobs WHERE id = ?", String.class, finished));

        // The run slot is free here (each test starts its own running job only after the others ended).
        String running = insertJob("running", "admin", "project", null, suffix + "-running");
        try {
            cancel(login, running, "cancel-r-" + suffix, "중단 요청").andExpect(status().isOk())
                    .andExpect(jsonPath("$.status").value("running"))
                    .andExpect(jsonPath("$.cancelRequested").value(true));
        } finally {
            finish(running);
        }
    }

    @Test
    void legacyRetryRefusesAnUnconnectedExecutorWithoutNewRows() throws Exception {
        String suffix = UUID.randomUUID().toString();
        Login login = login(suffix);
        String failed = insertJob("failed", "admin", "ingest", null, suffix + "-retry");
        retry(login, failed, "retry-" + suffix, "일시 장애 후 재시도").andExpect(status().isConflict());
        mvc.perform(get("/api/v1/admin/jobs/{id}", failed).cookie(login.cookie()))
                .andExpect(jsonPath("$.retry.code").value("worker_unavailable"))
                .andExpect(jsonPath("$.planRun").doesNotExist());
        assertEquals(0, jdbc.queryForObject("SELECT count(*) FROM analysis_jobs WHERE retry_of = ?", Integer.class, failed));
        assertEquals(0, auditCount("analysis.job.retry", failed));
        assertEquals(0, jdbc.queryForObject("SELECT count(*) FROM idempotency_records WHERE idem_key = ?",
                Integer.class, "retry-" + suffix));
        mvc.perform(post("/api/v1/admin/jobs/{id}/retry", failed).cookie(login.cookie()).header("Origin", ORIGIN)
                        .header("Idempotency-Key", "no-csrf-" + suffix).contentType("application/json")
                        .content("{\"reason\":\"x\"}"))
                .andExpect(status().isForbidden());
    }

    @Test
    void disabledAndUnsupportedCreateLeaveNoJobPlanIdempotencyOrAuditRows() throws Exception {
        Login login = login(UUID.randomUUID().toString());
        String plan = "s2plan-" + UUID.randomUUID().toString().replace("-", "") + "b".repeat(32);
        for (String kind : List.of("ingest", "revalidate", "project", "analyze_plan")) {
            String key = "disabled-" + UUID.randomUUID();
            String body = "analyze_plan".equals(kind)
                    ? "{\"kind\":\"analyze_plan\",\"reason\":\"시험\",\"plan\":{\"planId\":\"" + plan + "\",\"planDigest\":\"" + "b".repeat(64) + "\"}}"
                    : "{\"kind\":\"" + kind + "\",\"reason\":\"시험\",\"candidateIds\":[],\"unknownLegacyProperty\":true}";
            mvc.perform(post("/api/v1/admin/jobs").cookie(login.cookie()).header("Origin", ORIGIN)
                            .header("X-CSRF-Token", login.csrf()).header("Idempotency-Key", key)
                            .contentType("application/json").content(body))
                    .andExpect(status().isServiceUnavailable())
                    .andExpect(jsonPath("$.error.retryable").value(false));
            assertEquals(0, jdbc.queryForObject("SELECT count(*) FROM idempotency_records WHERE idem_key=?", Integer.class,key));
        }
        assertEquals(0, jdbc.queryForObject("SELECT count(*) FROM analysis_plans WHERE plan_id=?",Integer.class,plan));
        assertEquals(0, jdbc.queryForObject("SELECT count(*) FROM analysis_jobs WHERE plan_id=?",Integer.class,plan));
    }

    @Test
    void theMigrationKeepsOneRunningAdminJobAndProjectionOnlyForProjectKind() {
        String suffix = UUID.randomUUID().toString();
        String running = insertJob("running", "admin", "ingest", null, suffix + "-slot");
        try {
            assertThrows(DataIntegrityViolationException.class,
                    () -> insertJob("running", "admin", "project", null, suffix + "-second"));
        } finally {
            finish(running);
        }
        assertThrows(DataIntegrityViolationException.class,
                () -> insertJob("queued", "internal_projection", "ingest", null, suffix + "-bad-scope"));
        assertThrows(DataIntegrityViolationException.class,
                () -> insertJob("succeeded", "admin", "ingest", null, suffix + "-no-times", false));
    }

    @Test
    void theRequestedCommandIsImmutableAndOnlyARunningJobHoldsALease() {
        String suffix = UUID.randomUUID().toString();
        String queued = insertJob("queued", "admin", "ingest", null, suffix + "-cmd");
        for (String change : List.of("kind = 'project'", "input = '{\"planId\":\"other\"}'::jsonb", "reason = 'other'",
                "command_key = 'other-" + suffix + "'", "requested_at = requested_at + interval '1 second'",
                "requested_by = 'other'", "label = 'other'")) {
            assertThrows(DataAccessException.class,
                    () -> jdbc.update("UPDATE analysis_jobs SET " + change + " WHERE id = ?", queued), change);
        }
        assertThrows(DataIntegrityViolationException.class, () -> jdbc.update(
                "UPDATE analysis_jobs SET owner_token = 'w', lease_until = now() WHERE id = ?", queued), "queued holds no lease");
        String running = insertJob("running", "admin", "ingest", null, suffix + "-lease");
        try {
            assertThrows(DataIntegrityViolationException.class, () -> jdbc.update(
                    "UPDATE analysis_jobs SET owner_token = 'w' WHERE id = ?", running), "owner and deadline together");
            assertEquals(1, jdbc.update("UPDATE analysis_jobs SET owner_token = 'w', lease_until = now() WHERE id = ?",
                    running));
        } finally {
            jdbc.update("UPDATE analysis_jobs SET owner_token = NULL, lease_until = NULL WHERE id = ?", running);
            finish(running);
        }
    }

    @Test
    void documentAndExecutionRecordsCanOnlyNameAnExistingJob() {
        assertEquals(2, jdbc.queryForObject("""
                SELECT count(*) FROM pg_constraint
                WHERE conname IN ('fk_document_analyses_analysis_job', 'fk_ai_executions_analysis_job')
                  AND confrelid = 'analysis_jobs'::regclass AND confdeltype = 'r' AND confupdtype = 'r'
                """, Integer.class), "RESTRICT foreign keys from both job-owned columns");
    }

    private ResultActions cancel(Login login, String id, String key, String reason) throws Exception {
        return mvc.perform(post("/api/v1/admin/jobs/{id}/cancel", id).cookie(login.cookie()).header("Origin", ORIGIN)
                .header("X-CSRF-Token", login.csrf()).header("Idempotency-Key", key)
                .contentType("application/json").content("{\"reason\":\"" + reason + "\"}"));
    }

    private ResultActions retry(Login login, String id, String key, String reason) throws Exception {
        return mvc.perform(post("/api/v1/admin/jobs/{id}/retry", id).cookie(login.cookie()).header("Origin", ORIGIN)
                .header("X-CSRF-Token", login.csrf()).header("Idempotency-Key", key)
                .contentType("application/json").content("{\"reason\":\"" + reason + "\"}"));
    }

    private Login login(String suffix) throws Exception {
        String email = "jobs-admin-" + suffix + "@example.com";
        provisioning.provision(email, "Jobs Admin", PASSWORD, "jobs-admin-provision-" + suffix);
        MockHttpServletResponse response = mvc.perform(post("/api/v1/admin/auth/login")
                        .header("Origin", ORIGIN).contentType("application/json")
                        .content("{\"email\":\"" + email + "\",\"password\":\"" + PASSWORD + "\"}"))
                .andExpect(status().isOk()).andReturn().getResponse();
        Cookie cookie = response.getCookie(AdminSessionCookie.NAME);
        assertNotNull(cookie);
        return new Login(cookie, JsonPath.read(response.getContentAsString(), "$.csrfToken"));
    }

    private String insertJob(String status, String scope, String kind, String retryOf, String key) {
        return insertJob(status, scope, kind, retryOf, key, true);
    }

    /** {@code withTimes=false} leaves a finished status without its times, which the migration must refuse. */
    private String insertJob(String status, String scope, String kind, String retryOf, String key, boolean withTimes) {
        String id = "job-" + UUID.randomUUID();
        Instant requested = Instant.now().minusSeconds(600);
        boolean started = withTimes && !"queued".equals(status);
        boolean finished = withTimes && !"queued".equals(status) && !"running".equals(status);
        jdbc.update("""
                INSERT INTO analysis_jobs (id, kind, scope, label, status, reason, requested_by, requested_at, started_at,
                                           finished_at, retry_of, command_key, input, error)
                VALUES (?, ?, ?, '합성 작업', ?, '시험', 'admin-test', ?, ?, ?, ?, ?, CAST(? AS jsonb), CAST(? AS jsonb))
                """, id, kind, scope, status, Timestamp.from(requested),
                started ? Timestamp.from(requested.plusSeconds(10)) : null,
                finished ? Timestamp.from(requested.plusSeconds(20)) : null, retryOf, "test:" + key,
                "{\"planId\":\"plan-" + key + "\"}", "failed".equals(status) ? "{\"code\":\"provider_error\",\"message\":\"합성 실패\"}" : null);
        return id;
    }

    private static String planInput(String planId) {
        return "{\"planId\":\"" + planId + "\"}";
    }

    /** A finished admin job requested at {@code requested}; it starts 10 s and ends 20 s later. */
    private String insertAt(String status, String kind, String key, String input, Instant requested) {
        String id = "job-" + UUID.randomUUID();
        jdbc.update("""
                INSERT INTO analysis_jobs (id, kind, scope, label, status, reason, requested_by, requested_at, started_at,
                                           finished_at, command_key, input, error)
                VALUES (?, ?, 'admin', '합성 작업', ?, '시험', 'admin-test', ?, ?, ?, ?, CAST(? AS jsonb), CAST(? AS jsonb))
                """, id, kind, status, Timestamp.from(requested), Timestamp.from(requested.plusSeconds(10)),
                Timestamp.from(requested.plusSeconds(20)), "test:" + key, input,
                "failed".equals(status) ? "{\"code\":\"provider_error\",\"message\":\"합성 실패\"}" : null);
        return id;
    }

    private void finish(String id) {
        jdbc.update("UPDATE analysis_jobs SET status = 'failed', finished_at = now() WHERE id = ? AND status = 'running'", id);
    }

    private int auditCount(String action, String jobId) {
        return jdbc.queryForObject("SELECT count(*) FROM audit_logs WHERE action = ? AND target_id = ?", Integer.class,
                action, jobId);
    }
}
