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
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
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
                .andExpect(jsonPath("$.retry.code").value("allowed"))
                .andExpect(jsonPath("$.report").isEmpty())
                .andExpect(jsonPath("$.error.code").value("provider_error"));
        mvc.perform(get("/api/v1/admin/jobs/{id}", projection).cookie(login.cookie()))
                .andExpect(status().isNotFound());
        mvc.perform(get("/api/v1/admin/jobs").param("status", "failed").cookie(login.cookie()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.items[?(@.id == '" + failed + "')]").exists())
                .andExpect(jsonPath("$.items[?(@.id == '" + projection + "')]").doesNotExist())
                .andExpect(jsonPath("$.retryRule").isNotEmpty())
                .andExpect(jsonPath("$.nextCursor").isEmpty());
        mvc.perform(get("/api/v1/admin/jobs").param("status", "paused").cookie(login.cookie()))
                .andExpect(status().isUnprocessableContent());
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
    void retryQueuesOneNewJobWithRetryOfAndThenBlocksTheSameJob() throws Exception {
        String suffix = UUID.randomUUID().toString();
        Login login = login(suffix);
        String failed = insertJob("failed", "admin", "ingest", null, suffix + "-retry");

        MockHttpServletResponse created = retry(login, failed, "retry-" + suffix, "일시 장애 후 재시도")
                .andExpect(status().isAccepted())
                .andExpect(jsonPath("$.job.retryOf").value(failed))
                .andExpect(jsonPath("$.job.status").value("queued"))
                .andExpect(jsonPath("$.deduplicated").value(false))
                .andReturn().getResponse();
        String newId = JsonPath.read(created.getContentAsString(), "$.job.id");
        assertEquals(failed, jdbc.queryForObject("SELECT retry_of FROM analysis_jobs WHERE id = ?", String.class, newId));
        assertEquals(1, auditCount("analysis.job.retry", failed));

        // The same request replays; a new key is refused because the retry is waiting.
        retry(login, failed, "retry-" + suffix, "일시 장애 후 재시도").andExpect(status().isAccepted())
                .andExpect(jsonPath("$.job.id").value(newId));
        retry(login, failed, "retry-again-" + suffix, "한 번 더").andExpect(status().isConflict())
                .andExpect(jsonPath("$.error.code").value("REVISION_CONFLICT"));
        mvc.perform(get("/api/v1/admin/jobs/{id}", failed).cookie(login.cookie()))
                .andExpect(jsonPath("$.retry.code").value("duplicate_running"))
                .andExpect(jsonPath("$.retry.blockedBy").value(newId));
        assertEquals(1, jdbc.queryForObject("SELECT count(*) FROM analysis_jobs WHERE retry_of = ?", Integer.class, failed));

        // Writes need the admin CSRF token.
        mvc.perform(post("/api/v1/admin/jobs/{id}/retry", failed).cookie(login.cookie()).header("Origin", ORIGIN)
                        .header("Idempotency-Key", "no-csrf-" + suffix).contentType("application/json")
                        .content("{\"reason\":\"x\"}"))
                .andExpect(status().isForbidden());
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

    private void finish(String id) {
        jdbc.update("UPDATE analysis_jobs SET status = 'failed', finished_at = now() WHERE id = ? AND status = 'running'", id);
    }

    private int auditCount(String action, String jobId) {
        return jdbc.queryForObject("SELECT count(*) FROM audit_logs WHERE action = ? AND target_id = ?", Integer.class,
                action, jobId);
    }
}
