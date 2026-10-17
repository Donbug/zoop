package com.zoop.auth.service;

import java.sql.Timestamp;
import java.time.Instant;
import java.util.UUID;

import tools.jackson.databind.ObjectMapper;
import com.zoop.auth.config.MemberAuthorizationInterceptor;
import com.zoop.auth.config.MemberCsrfInterceptor;
import com.zoop.auth.controller.MemberWatchlistController;
import com.zoop.auth.service.SessionCookie;
import com.zoop.common.exception.GlobalExceptionHandler;
import com.zoop.auth.service.MemberSessionService.MemberPrincipal;
import com.zoop.common.json.StrictJson;
import com.zoop.common.request.RequestIdFilter;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.transaction.annotation.Transactional;

import static org.junit.jupiter.api.Assertions.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest(properties = {
        "ZOOP_AUTH_CSRF_ACTIVE_KEY_ID=test",
        "ZOOP_AUTH_CSRF_KEYS=test=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
})
@EnabledIfEnvironmentVariable(named = "DB_URL", matches = "jdbc:postgresql:.*")
@Tag("auth-postgres")
class MemberSettingsPostgresTest {
    private static final String ORIGIN = "https://zoop.example";
    @Autowired JdbcTemplate jdbc;
    @Autowired MemberSettingsService service;
    @Autowired MemberSessionService sessions;
    @Autowired MemberWatchlistController watchlistController;
    @Autowired ObjectMapper mapper;

    @Test
    @Transactional
    void readsAndAtomicallyPersistsMemberSetupAndWatchlist() {
        String memberId = "settings-test-" + UUID.randomUUID();
        Instant now = Instant.now();
        jdbc.update("""
                INSERT INTO members (id, analytics_key, email, email_key, display_name,
                                     password_hash, signup_method, status, mode, investor,
                                     completed, tutorial_completed, settings_version,
                                     created_at, updated_at, blocked_at)
                VALUES (?, ?, ?, ?, 'Settings Test', 'test-hash', 'email', 'active', NULL, NULL,
                        false, false, 1, ?, ?, NULL)
                """, memberId, memberId, memberId + "@example.com", memberId + "@example.com",
                Timestamp.from(now), Timestamp.from(now));
        var member = new MemberPrincipal(memberId, "settings-session");

        var initial = service.get(member, "settings-get");
        assertNull(initial.investor());
        assertTrue(initial.watchlistIds().isEmpty());
        assertFalse(initial.completed());

        var saved = service.update(member, StrictJson.parseObject("""
                {"version":1,"investor":false,"mode":"watchlist",
                 "watchlistIds":["NASDAQ:NVDA"],"completed":true}
                """.getBytes(java.nio.charset.StandardCharsets.UTF_8)).node(), "settings-put");

        assertFalse(saved.investor());
        assertEquals("watchlist", saved.mode());
        assertEquals(java.util.List.of("NASDAQ:NVDA"), saved.watchlistIds());
        assertTrue(saved.completed());
        assertFalse(saved.tutorialCompleted());
        assertEquals(2, saved.version());
        assertEquals(1L, jdbc.queryForObject("SELECT count(*) FROM member_watchlist WHERE member_id = ?",
                Long.class, memberId));

        var replay = service.update(member, StrictJson.parseObject("""
                {"version":1,"investor":false,"mode":"watchlist",
                 "watchlistIds":["NASDAQ:NVDA"],"completed":true}
                """.getBytes(java.nio.charset.StandardCharsets.UTF_8)).node(), "settings-retry");
        assertEquals(2, replay.version());
    }

    @Test
    @Transactional
    void watchlistRouteRequiresMemberAndCsrfAndPersistsIdempotentTargetState() throws Exception {
        String memberId = insertMember();
        var issued = sessions.issue(memberId, null, "watchlist-http");
        var guest = sessions.issueGuest(null, "watchlist-guest");
        MockMvc mvc = MockMvcBuilders.standaloneSetup(watchlistController)
                .setControllerAdvice(new GlobalExceptionHandler())
                .addInterceptors(new MemberCsrfInterceptor(new AuthOriginPolicy(ORIGIN), sessions),
                        new MemberAuthorizationInterceptor(sessions))
                .addFilters(new RequestIdFilter()).build();

        mvc.perform(put("/api/v1/me/watchlist/{id}", "NASDAQ:NVDA")
                        .cookie(new jakarta.servlet.http.Cookie(SessionCookie.NAME, guest.token()))
                        .header("Origin", ORIGIN).contentType("application/json")
                        .content("{\"watched\":true}"))
                .andExpect(status().isForbidden());

        mvc.perform(put("/api/v1/me/watchlist/{id}", "NASDAQ:NVDA")
                        .cookie(new jakarta.servlet.http.Cookie(SessionCookie.NAME, issued.token()))
                        .header("Origin", ORIGIN).contentType("application/json")
                        .content("{\"watched\":true}"))
                .andExpect(status().isForbidden());

        var added = mvc.perform(put("/api/v1/me/watchlist/{id}", "NASDAQ:NVDA")
                        .cookie(new jakarta.servlet.http.Cookie(SessionCookie.NAME, issued.token()))
                        .header("Origin", ORIGIN).header("X-CSRF-Token", issued.response().csrfToken())
                        .contentType("application/json").content("{\"watched\":true}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.watchlistIds[0]").value("NASDAQ:NVDA"))
                .andExpect(jsonPath("$.version").value(2)).andReturn();
        assertEquals(2, mapper.readTree(added.getResponse().getContentAsString()).path("version").asLong());

        mvc.perform(put("/api/v1/me/watchlist/{id}", "NASDAQ:NVDA")
                        .cookie(new jakarta.servlet.http.Cookie(SessionCookie.NAME, issued.token()))
                        .header("Origin", ORIGIN).header("X-CSRF-Token", issued.response().csrfToken())
                        .contentType("application/json").content("{\"watched\":true}"))
                .andExpect(status().isOk()).andExpect(jsonPath("$.version").value(2));

        String otherMemberId = insertMember();
        var other = sessions.issue(otherMemberId, null, "watchlist-other");
        mvc.perform(put("/api/v1/me/watchlist/{id}", "NASDAQ:NVDA")
                        .cookie(new jakarta.servlet.http.Cookie(SessionCookie.NAME, other.token()))
                        .header("Origin", ORIGIN).header("X-CSRF-Token", other.response().csrfToken())
                        .contentType("application/json").content("{\"watched\":false}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.watchlistIds.length()").value(0))
                .andExpect(jsonPath("$.version").value(1));
        assertEquals(java.util.List.of("NASDAQ:NVDA"),
                service.get(new MemberPrincipal(memberId, "owner-check"), "owner-check").watchlistIds());

        mvc.perform(put("/api/v1/me/watchlist/{id}", "NOPE")
                        .cookie(new jakarta.servlet.http.Cookie(SessionCookie.NAME, issued.token()))
                        .header("Origin", ORIGIN).header("X-CSRF-Token", issued.response().csrfToken())
                        .contentType("application/json").content("{\"watched\":true}"))
                .andExpect(status().isNotFound());
        mvc.perform(put("/api/v1/me/watchlist/{id}", "NASDAQ:NVDA")
                        .cookie(new jakarta.servlet.http.Cookie(SessionCookie.NAME, issued.token()))
                        .header("Origin", ORIGIN).header("X-CSRF-Token", issued.response().csrfToken())
                        .contentType("application/json").content("{\"watched\":true,\"extra\":1}"))
                .andExpect(status().isUnprocessableContent());

        mvc.perform(put("/api/v1/me/watchlist/{id}", "NASDAQ:NVDA")
                        .cookie(new jakarta.servlet.http.Cookie(SessionCookie.NAME, issued.token()))
                        .header("Origin", ORIGIN).header("X-CSRF-Token", issued.response().csrfToken())
                        .contentType("application/json").content("{\"watched\":false}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.watchlistIds.length()").value(0))
                .andExpect(jsonPath("$.version").value(3));
    }

    private String insertMember() {
        String memberId = "watchlist-test-" + UUID.randomUUID();
        Instant now = Instant.now();
        String email = memberId + "@example.com";
        jdbc.update("""
                INSERT INTO members (id, analytics_key, email, email_key, display_name,
                                     password_hash, signup_method, status, mode, investor,
                                     completed, tutorial_completed, settings_version,
                                     created_at, updated_at, blocked_at)
                VALUES (?, ?, ?, ?, 'Watchlist Test', 'test-hash', 'email', 'active', 'watchlist', false,
                        true, false, 1, ?, ?, NULL)
                """, memberId, memberId, email, email, Timestamp.from(now), Timestamp.from(now));
        return memberId;
    }
}
