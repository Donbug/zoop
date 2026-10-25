package com.zoop.admin.auth;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.HexFormat;
import java.util.UUID;

import com.zoop.admin.auth.provision.AdminProvisioningService;
import com.zoop.admin.auth.service.AdminSessionCookie;
import com.zoop.common.request.RequestIdFilter;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.context.WebApplicationContext;

import static org.hamcrest.Matchers.containsString;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

@SpringBootTest(properties = {
        "ZOOP_AUTH_CSRF_ACTIVE_KEY_ID=test",
        "ZOOP_AUTH_CSRF_KEYS=test=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        "ZOOP_AUTH_ALLOWED_ORIGINS=https://zoop.example"
})
@EnabledIfEnvironmentVariable(named = "DB_URL", matches = "jdbc:postgresql:.*")
@Tag("auth-postgres")
class AdminAuthPostgresTest {
    private static final String ORIGIN = "https://zoop.example";
    private static final String PASSWORD = "Secure admin password 2026";

    @Autowired WebApplicationContext context;
    @Autowired RequestIdFilter requestIds;
    @Autowired JdbcTemplate jdbc;
    @Autowired AdminProvisioningService provisioning;

    private MockMvc mvc;

    @BeforeEach
    void setUp() {
        mvc = MockMvcBuilders.webAppContextSetup(context).addFilters(requestIds).build();
    }

    @Test
    void loginSessionAndLogoutUseAnIsolatedAdminCookieAndAuditTrail() throws Exception {
        String suffix = UUID.randomUUID().toString();
        String email = "login-" + suffix + "@example.com";
        String adminId = provisioning.provision(email, "Login Admin", PASSWORD, "provision-" + suffix);
        String[] sessionToken = new String[1];

        mvc.perform(post("/api/v1/admin/auth/login")
                        .header("Origin", ORIGIN)
                        .header("X-Request-ID", "admin-login-" + suffix)
                        .contentType("application/json")
                        .content("{\"email\":\"" + email + "\",\"password\":\"" + PASSWORD + "\"}"))
                .andExpect(status().isOk())
                .andExpect(header().string("X-Request-ID", "admin-login-" + suffix))
                .andExpect(header().string("Set-Cookie", containsString(AdminSessionCookie.NAME + "=")))
                .andExpect(header().string("Set-Cookie", containsString("HttpOnly")))
                .andExpect(header().string("Set-Cookie", containsString("SameSite=Lax")))
                .andExpect(jsonPath("$.authenticated").value(true))
                .andExpect(jsonPath("$.admin.id").value(adminId))
                .andExpect(jsonPath("$.admin.role").value("admin"))
                .andExpect(jsonPath("$.idleTimeoutSeconds").value(1800))
                .andExpect(jsonPath("$.absoluteTimeoutSeconds").value(28800))
                .andDo(result -> {
                    var cookie = result.getResponse().getCookie(AdminSessionCookie.NAME);
                    org.junit.jupiter.api.Assertions.assertNotNull(cookie);
                    sessionToken[0] = cookie.getValue();
                    String persistedHash = jdbc.queryForObject("""
                            SELECT token_hash FROM admin_sessions WHERE admin_id = ?
                            """, String.class, adminId);
                    assertNotEquals(sessionToken[0], persistedHash);
                    assertTrue(persistedHash.matches("[0-9a-f]{64}"));
                    mvc.perform(get("/api/v1/admin/auth/session").cookie(cookie))
                            .andExpect(status().isOk())
                            .andExpect(jsonPath("$.authenticated").value(true))
                            .andExpect(jsonPath("$.admin.email").value(email));
                    String csrf = com.jayway.jsonpath.JsonPath.read(
                            result.getResponse().getContentAsString(), "$.csrfToken");
                    mvc.perform(post("/api/v1/admin/auth/logout").cookie(cookie)
                                    .header("Origin", ORIGIN).header("X-CSRF-Token", csrf)
                                    .header("X-Request-ID", "admin-logout-" + suffix))
                            .andExpect(status().isNoContent())
                            .andExpect(header().string("Set-Cookie", containsString("Max-Age=0")));
                    mvc.perform(get("/api/v1/admin/auth/session").cookie(cookie))
                            .andExpect(status().isOk())
                            .andExpect(jsonPath("$.authenticated").value(false));
                });

        assertEquals(1, jdbc.queryForObject("""
                SELECT count(*) FROM audit_logs
                WHERE admin_id = ? AND action = 'auth.login' AND outcome = 'succeeded'
                """, Integer.class, adminId));
        assertEquals(1, jdbc.queryForObject("""
                SELECT count(*) FROM audit_logs
                WHERE admin_id = ? AND action = 'auth.logout' AND outcome = 'succeeded'
                """, Integer.class, adminId));
        assertEquals(1, jdbc.queryForObject("""
                SELECT count(*) FROM admin_sessions
                WHERE admin_id = ? AND revoked_at IS NOT NULL
                """, Integer.class, adminId));
        assertEquals(0, jdbc.queryForObject("""
                SELECT count(*) FROM admin_sessions
                WHERE admin_id = ? AND token_hash = ?
                """, Integer.class, adminId, sessionToken[0]));
    }

    @Test
    void invalidCredentialsAreGenericAndAuditedWithoutThePassword() throws Exception {
        String suffix = UUID.randomUUID().toString();
        String password = "wrong admin password 2026";
        mvc.perform(post("/api/v1/admin/auth/login")
                        .header("Origin", ORIGIN)
                        .header("X-Request-ID", "admin-failed-" + suffix)
                        .contentType("application/json")
                        .content("{\"email\":\"missing-" + suffix + "@example.com\",\"password\":\"" + password + "\"}"))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.error.code").value("INVALID_CREDENTIALS"))
                .andExpect(header().doesNotExist("Set-Cookie"));

        assertEquals(1, jdbc.queryForObject("""
                SELECT count(*) FROM audit_logs
                WHERE request_id = ? AND action = 'auth.login_failed' AND outcome = 'denied'
                  AND reason = 'invalid_credentials'
                """, Integer.class, "admin-failed-" + suffix));
        assertEquals(1, jdbc.queryForObject("""
                SELECT count(*) FROM auth_rate_events
                WHERE scope = 'admin_login_email_failure' AND subject_hash = ?
                """, Integer.class, rateSubjectHash("admin_login_email_failure",
                "missing-" + suffix + "@example.com")));
    }

    @Test
    void blockedAdminLoginFailuresAreCountedAndEventuallyRateLimited() throws Exception {
        String suffix = UUID.randomUUID().toString();
        String email = "blocked-" + suffix + "@example.com";
        String adminId = provisioning.provision(email, "Blocked Admin", PASSWORD,
                "provision-blocked-" + suffix);
        jdbc.update("UPDATE admins SET status = 'blocked' WHERE id = ?", adminId);

        for (int attempt = 1; attempt <= 20; attempt++) {
            mvc.perform(post("/api/v1/admin/auth/login")
                            .header("Origin", ORIGIN)
                            .header("X-Request-ID", "admin-blocked-" + suffix + "-" + attempt)
                            .contentType("application/json")
                            .content("{\"email\":\"" + email + "\",\"password\":\"" + PASSWORD + "\"}"))
                    .andExpect(status().isForbidden())
                    .andExpect(jsonPath("$.error.code").value("MEMBER_BLOCKED"));
        }

        mvc.perform(post("/api/v1/admin/auth/login")
                        .header("Origin", ORIGIN)
                        .header("X-Request-ID", "admin-blocked-" + suffix + "-limited")
                        .contentType("application/json")
                        .content("{\"email\":\"" + email + "\",\"password\":\"" + PASSWORD + "\"}"))
                .andExpect(status().isTooManyRequests())
                .andExpect(jsonPath("$.error.code").value("RATE_LIMITED"));

        String rateHash = rateSubjectHash("admin_login_email_failure", email);
        assertEquals(20, jdbc.queryForObject("""
                SELECT count(*) FROM auth_rate_events
                WHERE scope = 'admin_login_email_failure' AND subject_hash = ?
                """, Integer.class, rateHash));
        assertEquals(20, jdbc.queryForObject("""
                SELECT count(*) FROM audit_logs
                WHERE request_id LIKE ? AND action = 'auth.login_failed'
                  AND outcome = 'denied' AND reason = 'account_blocked'
                """, Integer.class, "admin-blocked-" + suffix + "-%"));
    }

    @Test
    void activeLogoutRequiresOriginAndSameSessionCsrfButAnonymousLogoutIsIdempotent() throws Exception {
        String suffix = UUID.randomUUID().toString();
        String email = "logout-" + suffix + "@example.com";
        provisioning.provision(email, "Logout Admin", PASSWORD, "provision-logout-" + suffix);
        var login = mvc.perform(post("/api/v1/admin/auth/login").header("Origin", ORIGIN)
                        .contentType("application/json")
                        .content("{\"email\":\"" + email + "\",\"password\":\"" + PASSWORD + "\"}"))
                .andReturn();
        var cookie = login.getResponse().getCookie(AdminSessionCookie.NAME);
        String csrf = com.jayway.jsonpath.JsonPath.read(login.getResponse().getContentAsString(), "$.csrfToken");

        mvc.perform(post("/api/v1/admin/auth/logout").cookie(cookie)
                        .header("Origin", ORIGIN).header("X-CSRF-Token", "x".repeat(43)))
                .andExpect(status().isForbidden())
                .andExpect(jsonPath("$.error.code").value("ACCESS_DENIED"));
        mvc.perform(post("/api/v1/admin/auth/logout").cookie(cookie).header("X-CSRF-Token", csrf))
                .andExpect(status().isForbidden());
        mvc.perform(post("/api/v1/admin/auth/logout").cookie(cookie)
                        .header("Origin", ORIGIN).header("X-CSRF-Token", csrf))
                .andExpect(status().isNoContent());
        mvc.perform(post("/api/v1/admin/auth/logout")).andExpect(status().isNoContent());
    }

    @Test
    void dashboardRequiresAdminSessionAndReturnsAConsistentPartialSnapshot() throws Exception {
        mvc.perform(get("/api/v1/admin/dashboard"))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.error.code").value("AUTH_REQUIRED"));

        String suffix = UUID.randomUUID().toString();
        String email = "dashboard-" + suffix + "@example.com";
        String adminId = provisioning.provision(email, "Dashboard Admin", PASSWORD, "provision-dashboard-" + suffix);
        var login = mvc.perform(post("/api/v1/admin/auth/login").header("Origin", ORIGIN)
                        .contentType("application/json")
                        .content("{\"email\":\"" + email + "\",\"password\":\"" + PASSWORD + "\"}"))
                .andExpect(status().isOk())
                .andReturn();
        var cookie = login.getResponse().getCookie(AdminSessionCookie.NAME);

        Instant fixtureAt = Instant.now().minusSeconds(30);
        String activeMemberId = "dashboard-active-" + suffix;
        String blockedMemberId = "dashboard-blocked-" + suffix;
        insertDashboardMember(activeMemberId, "active-" + suffix, "active", fixtureAt);
        insertDashboardMember(blockedMemberId, "blocked-" + suffix, "blocked", fixtureAt);
        insertDashboardMemberSession("dashboard-member-session-" + suffix, activeMemberId,
                "member", null, fixtureAt);
        insertDashboardMemberSession("dashboard-guest-session-" + suffix, null,
                "guest", "guest-analytics-" + suffix, fixtureAt);
        jdbc.update("""
                INSERT INTO audit_logs
                  (actor_kind, admin_id, actor_id, actor_email_snapshot, action, target_type, target_id,
                   outcome, request_id, detail, occurred_at)
                VALUES ('admin', ?, ?, ?, 'dashboard.fixture', 'dashboard-fixture', ?,
                        'succeeded', ?, '{}'::jsonb, ?)
                """, adminId, adminId, email, suffix, "dashboard-fixture-" + suffix,
                java.sql.Timestamp.from(fixtureAt));

        var dashboard = mvc.perform(get("/api/v1/admin/dashboard").cookie(cookie)
                        .header("X-Request-ID", "dashboard-read-" + suffix))
                .andExpect(status().isOk())
                .andExpect(header().string("X-Request-ID", "dashboard-read-" + suffix))
                .andExpect(jsonPath("$.metadata.requestId").value("dashboard-read-" + suffix))
                .andExpect(jsonPath("$.metadata.partial").value(true))
                .andExpect(jsonPath("$.metadata.asOf").isNotEmpty())
                .andExpect(jsonPath("$.members.source").value("zoop-db"))
                .andExpect(jsonPath("$.audit.last24h").isNumber())
                .andExpect(jsonPath("$.jobs.running").isNumber())
                .andExpect(jsonPath("$.jobs.queued").isNumber())
                .andExpect(jsonPath("$.jobs.failed24h").isNumber())
                .andExpect(jsonPath("$.jobs.recent").isArray())
                .andExpect(jsonPath("$.candidates").value(org.hamcrest.Matchers.nullValue()))
                .andExpect(jsonPath("$.ai").value(org.hamcrest.Matchers.nullValue()))
                .andExpect(jsonPath("$.briefings").value(org.hamcrest.Matchers.nullValue()))
                .andReturn();

        Instant asOf = Instant.parse(com.jayway.jsonpath.JsonPath.read(
                dashboard.getResponse().getContentAsString(), "$.generatedAt"));
        String dashboardBody = dashboard.getResponse().getContentAsString();
        assertEquals(asOf.toString(), com.jayway.jsonpath.JsonPath.read(dashboardBody, "$.metadata.asOf"));
        assertEquals(jdbc.queryForObject("SELECT count(*) FROM members", Long.class),
                jsonLong(dashboardBody, "$.members.registered"));
        assertEquals(jdbc.queryForObject("""
                SELECT count(*) FROM member_sessions s JOIN members m ON m.id = s.member_id
                WHERE s.kind = 'member' AND m.status = 'active' AND s.revoked_at IS NULL
                  AND s.created_at <= ? AND s.expires_at > ?
                """, Long.class, java.sql.Timestamp.from(asOf), java.sql.Timestamp.from(asOf)),
                jsonLong(dashboardBody, "$.members.activeMemberSessions"));
        assertEquals(jdbc.queryForObject("""
                SELECT count(*) FROM member_sessions
                WHERE kind = 'guest' AND revoked_at IS NULL AND created_at <= ? AND expires_at > ?
                """, Long.class, java.sql.Timestamp.from(asOf), java.sql.Timestamp.from(asOf)),
                jsonLong(dashboardBody, "$.members.activeGuestSessions"));
        assertEquals(jdbc.queryForObject("""
                SELECT count(*) FROM audit_logs WHERE occurred_at >= ? AND occurred_at < ?
                """, Long.class, java.sql.Timestamp.from(asOf.minus(24, ChronoUnit.HOURS)), java.sql.Timestamp.from(asOf)),
                jsonLong(dashboardBody, "$.audit.last24h"));

        assertEquals(0, jdbc.queryForObject("""
                SELECT count(*) FROM audit_logs
                WHERE admin_id = ? AND action = 'admin.dashboard.read'
                """, Integer.class, adminId));
    }

    @Test
    void auditLogRequiresAdminSessionAndReturnsFilteredRecords() throws Exception {
        mvc.perform(get("/api/v1/admin/audit-log"))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.error.code").value("AUTH_REQUIRED"));

        String suffix = UUID.randomUUID().toString();
        String email = "audit-http-" + suffix + "@example.com";
        String adminId = provisioning.provision(email, "Audit Admin", PASSWORD,
                "provision-audit-http-" + suffix);
        var login = mvc.perform(post("/api/v1/admin/auth/login").header("Origin", ORIGIN)
                        .contentType("application/json")
                        .content("{\"email\":\"" + email + "\",\"password\":\"" + PASSWORD + "\"}"))
                .andExpect(status().isOk()).andReturn();
        var cookie = login.getResponse().getCookie(AdminSessionCookie.NAME);

        mvc.perform(get("/api/v1/admin/audit-log").cookie(cookie)
                        .param("action", "auth.login").param("actor", adminId)
                        .header("X-Request-ID", "audit-read-" + suffix))
                .andExpect(status().isOk())
                .andExpect(header().string("X-Request-ID", "audit-read-" + suffix))
                .andExpect(jsonPath("$.items.length()").value(1))
                .andExpect(jsonPath("$.items[0].actorKind").value("admin"))
                .andExpect(jsonPath("$.items[0].outcome").value("ok"))
                .andExpect(jsonPath("$.items[0].action").value("auth.login"))
                .andExpect(jsonPath("$.nextCursor").value(org.hamcrest.Matchers.nullValue()));
        mvc.perform(get("/api/v1/admin/audit-log").cookie(cookie)
                        .param("action", "auth.login").param("actor", adminId)
                        .param("q", "unmatched-value-" + suffix))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.items.length()").value(0));
        mvc.perform(get("/api/v1/admin/audit-log").cookie(cookie).param("limit", "101"))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.error.code").value("INVALID_REQUEST"));
        mvc.perform(get("/api/v1/admin/audit-log").cookie(cookie).param("cursor", "tampered"))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.error.code").value("INVALID_CURSOR"));
    }

    private void insertDashboardMember(String id, String suffix, String status, Instant createdAt) {
        String email = suffix + "@example.test";
        jdbc.update("""
                INSERT INTO members
                  (id, analytics_key, email, email_key, display_name, signup_method, status, created_at, blocked_at,
                   password_hash, mode, investor, completed, tutorial_completed, settings_version, updated_at)
                VALUES (?, ?, ?, ?, 'Dashboard fixture', 'google', ?, ?, ?, NULL, 'watchlist', NULL,
                        false, false, 1, ?)
                """, id, "analytics-" + id, email, email, status, java.sql.Timestamp.from(createdAt),
                "blocked".equals(status) ? java.sql.Timestamp.from(createdAt) : null,
                java.sql.Timestamp.from(createdAt));
    }

    private static long jsonLong(String document, String path) {
        return ((Number) com.jayway.jsonpath.JsonPath.read(document, path)).longValue();
    }

    private void insertDashboardMemberSession(String id, String memberId, String kind,
            String analyticsKey, Instant createdAt) {
        jdbc.update("""
                INSERT INTO member_sessions
                  (id, member_id, kind, analytics_key, token_hash, csrf_key_id, csrf_version,
                   tutorial_completed, created_at, expires_at, revoked_at, auth_flow)
                VALUES (?, ?, ?, ?, ?, 'test', 1, false, ?, ?, NULL, NULL)
                """, id, memberId, kind, analyticsKey, java.util.UUID.randomUUID().toString().replace("-", "").repeat(2),
                java.sql.Timestamp.from(createdAt), java.sql.Timestamp.from(createdAt.plus(2, ChronoUnit.HOURS)));
    }

    private static String rateSubjectHash(String scope, String subject) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256")
                    .digest((scope + "\0" + subject).getBytes(StandardCharsets.UTF_8)));
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException(exception);
        }
    }
}
