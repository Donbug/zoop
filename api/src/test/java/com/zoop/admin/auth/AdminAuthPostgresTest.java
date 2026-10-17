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

    private static String rateSubjectHash(String scope, String subject) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256")
                    .digest((scope + "\0" + subject).getBytes(StandardCharsets.UTF_8)));
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException(exception);
        }
    }
}
