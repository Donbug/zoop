package com.zoop.auth.service;

import java.sql.Timestamp;
import java.time.Instant;
import java.util.UUID;

import com.zoop.auth.controller.SessionController;
import com.zoop.auth.controller.LogoutController;
import com.zoop.auth.config.MemberCsrfInterceptor;
import com.zoop.auth.service.AuthOriginPolicy;
import com.zoop.common.request.RequestIdFilter;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.transaction.annotation.Transactional;
import jakarta.servlet.http.Cookie;

import static org.junit.jupiter.api.Assertions.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest(properties = {
        "ZOOP_AUTH_CSRF_ACTIVE_KEY_ID=test",
        "ZOOP_AUTH_CSRF_KEYS=test=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
})
@EnabledIfEnvironmentVariable(named = "DB_URL", matches = "jdbc:postgresql:.*")
@Tag("auth-postgres")
class MemberSessionPostgresTest {
    @Autowired
    MemberSessionService service;

    @Autowired
    JdbcTemplate jdbc;

    @Test
    @Transactional
    void issuedSessionPersistsOnlyHashAndReadsThroughRealSchema() {
        String memberId = "session-test-" + UUID.randomUUID();
        Instant now = Instant.now();
        jdbc.update("""
                INSERT INTO members (id, analytics_key, email, email_key, display_name,
                                     password_hash, signup_method, status, mode, investor,
                                     completed, tutorial_completed, settings_version,
                                     created_at, updated_at, blocked_at)
                VALUES (?, ?, ?, ?, ?, ?, 'email', 'active', NULL, NULL,
                        false, false, 1, ?, ?, NULL)
                """, memberId, memberId, memberId + "@example.com",
                memberId + "@example.com", "Session Test", "test-hash",
                Timestamp.from(now), Timestamp.from(now));

        var issued = service.issue(memberId, null, "postgres-test");
        String stored = jdbc.queryForObject("SELECT token_hash FROM member_sessions WHERE member_id = ?",
                String.class, memberId);
        assertEquals(MemberSessionService.hashToken(issued.token()), stored);
        assertNotEquals(issued.token(), stored);
        assertTrue(service.lookup(issued.token(), "postgres-read").response().authenticated());

        var replacement = service.issue(memberId, issued.token(), "postgres-reissue");
        assertTrue(service.lookup(issued.token(), "postgres-revoked").clearCookie());
        assertTrue(service.lookup(replacement.token(), "postgres-replacement").response().authenticated());

        jdbc.update("UPDATE member_sessions SET expires_at = ? WHERE token_hash = ?",
                Timestamp.from(now.minusSeconds(1)), MemberSessionService.hashToken(replacement.token()));
        assertTrue(service.lookup(replacement.token(), "postgres-expired").clearCookie());
    }

    @Test
    @Transactional
    void guestSessionPersistsWithoutMemberOrTutorialState() {
        var issued = service.issueGuest(null, "guest-postgres-test");
        var row = jdbc.queryForMap("""
                SELECT kind, member_id, analytics_key, token_hash, tutorial_completed
                FROM member_sessions WHERE token_hash = ?
                """, MemberSessionService.hashToken(issued.token()));
        assertEquals("guest", row.get("kind"));
        assertNull(row.get("member_id"));
        assertNotNull(row.get("analytics_key"));
        assertEquals(MemberSessionService.hashToken(issued.token()), row.get("token_hash"));
        assertEquals(false, row.get("tutorial_completed"));
        assertEquals("guest", service.lookup(issued.token(), "guest-postgres-read").response().kind());

        var replacement = service.issueGuest(issued.token(), "guest-postgres-rotate");
        assertTrue(service.lookup(issued.token(), "guest-postgres-revoked").clearCookie());
        assertTrue(service.lookup(replacement.token(), "guest-postgres-current").response().authenticated());
        assertThrows(org.springframework.dao.DataIntegrityViolationException.class,
                () -> jdbc.update("UPDATE member_sessions SET tutorial_completed = true WHERE token_hash = ?",
                        MemberSessionService.hashToken(replacement.token())));
    }

    @Test
    @Transactional
    void sessionHttpResponseOnlyReturnsTheMemberBoundToTheCookie() throws Exception {
        String memberA = insertMember("owner-a-" + UUID.randomUUID(), "Owner A");
        String memberB = insertMember("owner-b-" + UUID.randomUUID(), "Owner B");
        var sessionA = service.issue(memberA, null, "owner-a-session");
        var sessionB = service.issue(memberB, null, "owner-b-session");
        var guest = service.issueGuest(null, "guest-session");
        // The session token is issued before the setup change; lookup must read the current member row.
        jdbc.update("UPDATE members SET completed = true, tutorial_completed = true WHERE id = ?", memberA);
        MockMvc mvc = MockMvcBuilders.standaloneSetup(new SessionController(service))
                .addFilters(new RequestIdFilter()).build();

        mvc.perform(get("/api/v1/auth/session")
                        .cookie(new Cookie(SessionCookie.NAME, sessionA.token())))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.kind").value("member"))
                .andExpect(jsonPath("$.user.id").value(memberA))
                .andExpect(jsonPath("$.user.displayName").value("Owner A"))
                .andExpect(jsonPath("$.setup.completed").value(true))
                .andExpect(jsonPath("$.setup.tutorialCompleted").value(true));

        mvc.perform(get("/api/v1/auth/session")
                        .cookie(new Cookie(SessionCookie.NAME, sessionB.token())))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.kind").value("member"))
                .andExpect(jsonPath("$.user.id").value(memberB))
                .andExpect(jsonPath("$.user.displayName").value("Owner B"))
                .andExpect(jsonPath("$.setup.completed").value(false))
                .andExpect(jsonPath("$.setup.tutorialCompleted").value(false));

        mvc.perform(get("/api/v1/auth/session")
                        .cookie(new Cookie(SessionCookie.NAME, guest.token())))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.kind").value("guest"))
                .andExpect(jsonPath("$.user").value(org.hamcrest.Matchers.nullValue()))
                .andExpect(jsonPath("$.setup.completed").value(false))
                .andExpect(jsonPath("$.setup.tutorialCompleted").value(false));
    }

    @Test
    @Transactional
    void logoutHttpRevokesOnlyTheCurrentMemberSessionAndClearsItsCookie() throws Exception {
        String memberId = insertMember("logout-" + UUID.randomUUID(), "Logout Member");
        var current = service.issue(memberId, null, "logout-current");
        var other = service.issue(memberId, null, "logout-other");
        var mvc = MockMvcBuilders.standaloneSetup(new LogoutController(service))
                .addInterceptors(new MemberCsrfInterceptor(new AuthOriginPolicy("https://zoop.example"), service))
                .addFilters(new RequestIdFilter()).build();

        mvc.perform(post("/api/v1/auth/logout")
                        .cookie(new Cookie(SessionCookie.NAME, current.token()))
                        .header("Origin", "https://zoop.example")
                        .header("X-CSRF-Token", current.response().csrfToken()))
                .andExpect(status().isNoContent())
                .andExpect(org.springframework.test.web.servlet.result.MockMvcResultMatchers.header()
                        .string("Set-Cookie", org.hamcrest.Matchers.containsString("Max-Age=0")));

        assertTrue(service.lookup(current.token(), "logout-revoked").clearCookie());
        assertTrue(service.lookup(other.token(), "logout-other-active").response().authenticated());
    }

    @Test
    @Transactional
    void logoutWithExpiredCookieReturnsNoContentWithoutCsrf() throws Exception {
        var mvc = MockMvcBuilders.standaloneSetup(new LogoutController(service))
                .addInterceptors(new MemberCsrfInterceptor(new AuthOriginPolicy("https://zoop.example"), service))
                .addFilters(new RequestIdFilter()).build();

        mvc.perform(post("/api/v1/auth/logout")
                        .cookie(new Cookie(SessionCookie.NAME, "x".repeat(43))))
                .andExpect(status().isNoContent())
                .andExpect(org.springframework.test.web.servlet.result.MockMvcResultMatchers.header()
                        .string("Set-Cookie", org.hamcrest.Matchers.containsString("Max-Age=0")));
    }

    private String insertMember(String memberId, String displayName) {
        Instant now = Instant.now();
        String email = memberId + "@example.com";
        jdbc.update("""
                INSERT INTO members (id, analytics_key, email, email_key, display_name,
                                     password_hash, signup_method, status, mode, investor,
                                     completed, tutorial_completed, settings_version,
                                     created_at, updated_at, blocked_at)
                VALUES (?, ?, ?, ?, ?, ?, 'email', 'active', NULL, NULL,
                        false, false, 1, ?, ?, NULL)
                """, memberId, memberId, email, email, displayName, "test-hash",
                Timestamp.from(now), Timestamp.from(now));
        return memberId;
    }
}
