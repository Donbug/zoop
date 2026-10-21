package com.zoop.admin.members;

import java.sql.Timestamp;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;

import com.jayway.jsonpath.JsonPath;
import com.zoop.admin.auth.provision.AdminProvisioningService;
import com.zoop.admin.auth.service.AdminSessionCookie;
import com.zoop.admin.auth.service.AdminPrincipal;
import com.zoop.admin.members.dto.MemberStatusRequest;
import com.zoop.admin.members.service.AdminMemberStatusService;
import com.zoop.common.exception.CustomException;
import com.zoop.common.request.RequestIdFilter;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.mock.web.MockHttpServletResponse;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.context.WebApplicationContext;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest(properties = {
        "ZOOP_AUTH_CSRF_ACTIVE_KEY_ID=test",
        "ZOOP_AUTH_CSRF_KEYS=test=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        "ZOOP_AUTH_ALLOWED_ORIGINS=https://zoop.example"
})
@EnabledIfEnvironmentVariable(named = "DB_URL", matches = "jdbc:postgresql:.*")
@Tag("auth-postgres")
class AdminMemberPostgresTest {
    private static final String ORIGIN = "https://zoop.example";
    private static final String PASSWORD = "Secure admin password 2026";

    @Autowired WebApplicationContext context;
    @Autowired RequestIdFilter requestIds;
    @Autowired JdbcTemplate jdbc;
    @Autowired AdminProvisioningService provisioning;
    @Autowired AdminMemberStatusService statuses;

    private MockMvc mvc;

    @BeforeEach
    void setUp() {
        mvc = MockMvcBuilders.webAppContextSetup(context).addFilters(requestIds).build();
    }

    @Test
    void listAndDetailExposeOnlyApprovedActivityWithExplicitUnavailableFields() throws Exception {
        mvc.perform(get("/api/v1/admin/members"))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.error.code").value("AUTH_REQUIRED"));

        String suffix = UUID.randomUUID().toString();
        var login = loginAdmin(suffix);
        String memberId = "member-list-" + suffix;
        String email = "member-list-" + suffix + "@example.com";
        insertMember(memberId, email, "active");
        insertMemberSession(memberId, "member-session-list-" + suffix);

        var list = mvc.perform(get("/api/v1/admin/members")
                        .cookie(login.cookie()).param("q", email).param("limit", "10")
                        .header("X-Request-ID", "member-list-request-" + suffix))
                .andExpect(status().isOk())
                .andExpect(header().string("X-Request-ID", "member-list-request-" + suffix))
                .andExpect(jsonPath("$.items.length()").value(1))
                .andExpect(jsonPath("$.items[0].id").value(memberId))
                .andExpect(jsonPath("$.items[0].emailMasked").value("m***@example.com"))
                .andExpect(jsonPath("$.items[0].activity.sessions").value(1))
                .andExpect(jsonPath("$.items[0].activity.aiQuestions").value(org.hamcrest.Matchers.nullValue()))
                .andExpect(jsonPath("$.metadata.partial").value(true))
                .andReturn();
        org.junit.jupiter.api.Assertions.assertFalse(
                list.getResponse().getContentAsString().contains(email));

        mvc.perform(get("/api/v1/admin/members/{memberId}", memberId).cookie(login.cookie()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.member.statusRevision").value(1))
                .andExpect(jsonPath("$.watchlistCount").value(0))
                .andExpect(jsonPath("$.holdingCount").value(org.hamcrest.Matchers.nullValue()))
                .andExpect(jsonPath("$.history.length()").value(0));

        assertEquals("active", jdbc.queryForObject("SELECT status FROM members WHERE id = ?", String.class, memberId));
        assertEquals(0, jdbc.queryForObject("SELECT count(*) FROM audit_logs WHERE target_id = ?",
                Integer.class, memberId));
    }

    @Test
    void sessionActivityIncludesMemberCreationBoundaryButExcludesEarlierSessions() throws Exception {
        String suffix = UUID.randomUUID().toString();
        var login = loginAdmin(suffix);
        String memberId = "member-period-" + suffix;
        String email = "period-" + suffix + "@example.com";
        Instant memberCreatedAt = insertMember(memberId, email, "active");
        insertMemberSessionAt(memberId, "session-before-" + suffix, memberCreatedAt.minusSeconds(1));
        insertMemberSessionAt(memberId, "session-at-boundary-" + suffix, memberCreatedAt);
        insertMemberSessionAt(memberId, "session-after-" + suffix, memberCreatedAt.plusSeconds(1));
        String expectedLastActiveAt = memberCreatedAt.plusSeconds(1)
                .truncatedTo(ChronoUnit.MICROS).toString();

        mvc.perform(get("/api/v1/admin/members").cookie(login.cookie())
                        .param("q", email).param("limit", "10"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.items[0].activity.sessions").value(2))
                .andExpect(jsonPath("$.items[0].lastActiveAt")
                        .value(expectedLastActiveAt));

        mvc.perform(get("/api/v1/admin/members/{memberId}", memberId).cookie(login.cookie()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.member.activity.sessions").value(2))
                .andExpect(jsonPath("$.member.lastActiveAt")
                        .value(expectedLastActiveAt));
    }

    @Test
    void blockReplayConflictAndUnblockPreserveRevisionSessionAndAuditRules() throws Exception {
        String suffix = UUID.randomUUID().toString();
        var login = loginAdmin(suffix);
        String memberId = "member-status-" + suffix;
        String memberSessionId = "member-session-status-" + suffix;
        insertMember(memberId, "status-" + suffix + "@example.com", "active");
        insertMemberSession(memberId, memberSessionId);

        String blockBody = "{\"expectedRevision\":1,\"reason\":\"confirmed abuse\"}";
        mvc.perform(post("/api/v1/admin/members/{memberId}/block", memberId)
                        .cookie(login.cookie()).header("Origin", ORIGIN)
                        .header("Idempotency-Key", "missing-csrf-" + suffix)
                        .contentType("application/json").content(blockBody))
                .andExpect(status().isForbidden())
                .andExpect(jsonPath("$.error.code").value("ACCESS_DENIED"));
        assertEquals("active", jdbc.queryForObject("SELECT status FROM members WHERE id = ?", String.class, memberId));

        mvc.perform(post("/api/v1/admin/members/{memberId}/block", memberId)
                        .cookie(login.cookie()).header("Origin", ORIGIN)
                        .header("X-CSRF-Token", login.csrf()).header("Idempotency-Key", "block-" + suffix)
                        .contentType("application/json").content(blockBody))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.changed").value(true))
                .andExpect(jsonPath("$.detail.member.status").value("blocked"))
                .andExpect(jsonPath("$.detail.member.statusRevision").value(2));

        assertEquals("blocked", jdbc.queryForObject("SELECT status FROM members WHERE id = ?", String.class, memberId));
        assertEquals(2L, jdbc.queryForObject("SELECT status_revision FROM members WHERE id = ?", Long.class, memberId));
        assertNotNull(jdbc.queryForObject("SELECT revoked_at FROM member_sessions WHERE id = ?",
                Timestamp.class, memberSessionId));
        assertEquals(1, auditCount(memberId));

        mvc.perform(post("/api/v1/admin/members/{memberId}/block", memberId)
                        .cookie(login.cookie()).header("Origin", ORIGIN)
                        .header("X-CSRF-Token", login.csrf()).header("Idempotency-Key", "block-" + suffix)
                        .contentType("application/json").content(blockBody))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.changed").value(true))
                .andExpect(jsonPath("$.detail.member.statusRevision").value(2));
        assertEquals(1, auditCount(memberId));

        mvc.perform(post("/api/v1/admin/members/{memberId}/block", memberId)
                        .cookie(login.cookie()).header("Origin", ORIGIN)
                        .header("X-CSRF-Token", login.csrf()).header("Idempotency-Key", "block-" + suffix)
                        .contentType("application/json")
                        .content("{\"expectedRevision\":2,\"reason\":\"different\"}"))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.error.code").value("IDEMPOTENCY_CONFLICT"));

        mvc.perform(post("/api/v1/admin/members/{memberId}/unblock", memberId)
                        .cookie(login.cookie()).header("Origin", ORIGIN)
                        .header("X-CSRF-Token", login.csrf()).header("Idempotency-Key", "unblock-" + suffix)
                        .contentType("application/json")
                        .content("{\"expectedRevision\":2,\"reason\":\"appeal accepted\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.changed").value(true))
                .andExpect(jsonPath("$.detail.member.status").value("active"))
                .andExpect(jsonPath("$.detail.member.statusRevision").value(3));

        assertEquals(2, auditCount(memberId));
        assertNotNull(jdbc.queryForObject("SELECT revoked_at FROM member_sessions WHERE id = ?",
                Timestamp.class, memberSessionId));

        mvc.perform(post("/api/v1/admin/members/{memberId}/unblock", memberId)
                        .cookie(login.cookie()).header("Origin", ORIGIN)
                        .header("X-CSRF-Token", login.csrf()).header("Idempotency-Key", "unblock-noop-" + suffix)
                        .contentType("application/json")
                        .content("{\"expectedRevision\":3,\"reason\":\"confirm active\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.changed").value(false))
                .andExpect(jsonPath("$.detail.member.statusRevision").value(3));
        assertEquals(2, auditCount(memberId));

        mvc.perform(post("/api/v1/admin/members/{memberId}/block", memberId)
                        .cookie(login.cookie()).header("Origin", ORIGIN)
                        .header("X-CSRF-Token", login.csrf()).header("Idempotency-Key", "stale-" + suffix)
                        .contentType("application/json")
                        .content("{\"expectedRevision\":1,\"reason\":\"stale screen\"}"))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.error.code").value("REVISION_CONFLICT"));
    }

    @Test
    void concurrentAdministratorsCannotApplyTheSameRevisionTwice() throws Exception {
        String suffix = UUID.randomUUID().toString();
        String memberId = "member-concurrent-" + suffix;
        insertMember(memberId, "concurrent-" + suffix + "@example.com", "active");
        String emailA = "admin-a-" + suffix + "@example.com";
        String emailB = "admin-b-" + suffix + "@example.com";
        String adminA = provisioning.provision(emailA, "Admin A", PASSWORD, "provision-a-" + suffix);
        String adminB = provisioning.provision(emailB, "Admin B", PASSWORD, "provision-b-" + suffix);
        var principalA = new AdminPrincipal(adminA, emailA, "Admin A", "admin", "session-a");
        var principalB = new AdminPrincipal(adminB, emailB, "Admin B", "admin", "session-b");
        var ready = new CountDownLatch(2);
        var start = new CountDownLatch(1);
        var executor = Executors.newFixedThreadPool(2);
        try {
            var first = executor.submit(() -> concurrentBlock(memberId, "concurrent-a-" + suffix,
                    principalA, ready, start));
            var second = executor.submit(() -> concurrentBlock(memberId, "concurrent-b-" + suffix,
                    principalB, ready, start));
            assertTrue(ready.await(10, TimeUnit.SECONDS));
            start.countDown();
            var outcomes = java.util.Set.of(first.get(20, TimeUnit.SECONDS), second.get(20, TimeUnit.SECONDS));
            assertEquals(java.util.Set.of("changed", "REVISION_CONFLICT"), outcomes);
        } finally {
            executor.shutdownNow();
        }

        assertEquals(2L, jdbc.queryForObject("SELECT status_revision FROM members WHERE id = ?",
                Long.class, memberId));
        assertEquals(1, auditCount(memberId));
    }

    private Login loginAdmin(String suffix) throws Exception {
        String email = "member-admin-" + suffix + "@example.com";
        provisioning.provision(email, "Member Admin", PASSWORD, "member-admin-provision-" + suffix);
        MockHttpServletResponse response = mvc.perform(post("/api/v1/admin/auth/login")
                        .header("Origin", ORIGIN).contentType("application/json")
                        .content("{\"email\":\"" + email + "\",\"password\":\"" + PASSWORD + "\"}"))
                .andExpect(status().isOk()).andReturn().getResponse();
        var cookie = response.getCookie(AdminSessionCookie.NAME);
        assertNotNull(cookie);
        String csrf = JsonPath.read(response.getContentAsString(), "$.csrfToken");
        return new Login(cookie, csrf);
    }

    private Instant insertMember(String memberId, String email, String status) {
        Instant now = Instant.now().minusSeconds(120);
        jdbc.update("""
                INSERT INTO members (id, analytics_key, email, email_key, display_name,
                                     password_hash, signup_method, status, mode, investor,
                                     completed, tutorial_completed, settings_version,
                                     created_at, updated_at, blocked_at)
                VALUES (?, ?, ?, ?, 'Synthetic Member', 'test-hash', 'email', ?, NULL, NULL,
                        false, false, 1, ?, ?, NULL)
                """, memberId, "analytics-" + memberId, email, email.toLowerCase(), status,
                Timestamp.from(now), Timestamp.from(now));
        return now;
    }

    private void insertMemberSession(String memberId, String sessionId) {
        Instant now = Instant.now().minusSeconds(60);
        insertMemberSessionAt(memberId, sessionId, now);
    }

    private void insertMemberSessionAt(String memberId, String sessionId, Instant createdAt) {
        jdbc.update("""
                INSERT INTO member_sessions
                  (id, member_id, kind, analytics_key, token_hash, csrf_key_id, csrf_version,
                   tutorial_completed, auth_flow, created_at, expires_at, revoked_at)
                VALUES (?, ?, 'member', NULL, ?, 'test', 1, false, NULL, ?, ?, NULL)
                """, sessionId, memberId, "hash-" + sessionId,
                Timestamp.from(createdAt), Timestamp.from(createdAt.plusSeconds(3600)));
    }

    private int auditCount(String memberId) {
        return jdbc.queryForObject("""
                SELECT count(*) FROM audit_logs
                WHERE target_type = 'member' AND target_id = ?
                  AND action IN ('member.block', 'member.unblock') AND outcome = 'succeeded'
                """, Integer.class, memberId);
    }

    private String concurrentBlock(String memberId, String key, AdminPrincipal principal,
            CountDownLatch ready, CountDownLatch start) throws Exception {
        ready.countDown();
        if (!start.await(10, TimeUnit.SECONDS)) throw new IllegalStateException("concurrent start timeout");
        try {
            return statuses.block(memberId, new MemberStatusRequest(1, "concurrent decision"),
                    key, principal, "request-" + key).changed() ? "changed" : "unchanged";
        } catch (CustomException exception) {
            return exception.getErrorCode().name();
        }
    }

    private record Login(jakarta.servlet.http.Cookie cookie, String csrf) { }
}
