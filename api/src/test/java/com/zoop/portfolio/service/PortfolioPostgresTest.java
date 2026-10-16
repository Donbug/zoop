package com.zoop.portfolio.service;

import java.sql.Timestamp;
import java.time.Instant;
import java.util.UUID;

import tools.jackson.databind.ObjectMapper;
import com.zoop.auth.config.MemberAuthorizationInterceptor;
import com.zoop.auth.config.MemberCsrfInterceptor;
import com.zoop.auth.service.AuthOriginPolicy;
import com.zoop.auth.service.MemberSessionService;
import com.zoop.auth.service.SessionCookie;
import com.zoop.common.exception.GlobalExceptionHandler;
import com.zoop.common.request.RequestIdFilter;
import com.zoop.portfolio.controller.PortfolioController;
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
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
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
class PortfolioPostgresTest {
    private static final String ORIGIN = "https://zoop.example";

    @Autowired JdbcTemplate jdbc;
    @Autowired MemberSessionService sessions;
    @Autowired PortfolioService service;
    @Autowired MockPortfolioCatalog catalog;
    @Autowired PortfolioController controller;
    @Autowired ObjectMapper mapper;

    @Test
    @Transactional
    void profileConnectionReplacementAndDisconnectPersistAgainstPostgres() {
        String memberId = insertMember();
        var member = new MemberSessionService.MemberPrincipal(memberId, "portfolio-test");

        var profiles = service.listProfiles(null, 1, "profiles");
        assertEquals(1, profiles.items().size());
        assertNotNull(profiles.nextCursor());
        var secondPage = service.listProfiles(profiles.nextCursor(), 1, "profiles-page-2");
        assertEquals(1, secondPage.items().size());
        assertNull(secondPage.nextCursor());
        assertThrows(com.zoop.common.exception.CustomException.class,
                () -> service.getProfile("demo-empty", "removed-profile"));
        for (var profile : catalog.all()) {
            for (var holding : profile.holdings()) {
                assertEquals(1L, jdbc.queryForObject("SELECT count(*) FROM companies WHERE id = ?",
                        Long.class, holding.companyId()));
            }
        }

        var first = service.connect(member, "demo-growth", "same-key", "connect-1");
        var retry = service.connect(member, "demo-growth", "same-key", "connect-2");
        assertEquals(first.id(), retry.id());
        assertEquals(1L, jdbc.queryForObject("SELECT count(*) FROM member_portfolio_connections WHERE member_id = ?",
                Long.class, memberId));
        assertEquals(1L, jdbc.queryForObject("SELECT count(*) FROM member_portfolio_idempotency WHERE member_id = ?",
                Long.class, memberId));

        assertThrows(com.zoop.common.exception.CustomException.class,
                () -> service.connect(member, "demo-balanced", "same-key", "conflict"));
        var replacement = service.connect(member, "demo-balanced", "new-key", "replace");
        assertNotEquals(first.id(), replacement.id());
        assertEquals("demo-balanced", jdbc.queryForObject(
                "SELECT mock_portfolio_id FROM member_portfolio_connections WHERE member_id = ?",
                String.class, memberId));

        var portfolio = service.getMyPortfolio(member, "read-portfolio");
        assertTrue(portfolio.connected());
        assertEquals(2, portfolio.holdings().size());
        assertEquals("unavailable", portfolio.holdings().getFirst().quote().status());
        assertNull(portfolio.holdings().getFirst().marketValue());

        service.disconnect(member, replacement.id());
        assertFalse(service.getMyPortfolio(member, "after-disconnect").connected());
        assertEquals(2L, jdbc.queryForObject("SELECT count(*) FROM member_portfolio_idempotency WHERE member_id = ?",
                Long.class, memberId));
    }

    @Test
    @Transactional
    void httpRoutesRequireMemberAndCsrfAndExposeMockProfileStates() throws Exception {
        String memberId = insertMember();
        var issued = sessions.issue(memberId, null, "portfolio-http");
        var guest = sessions.issueGuest(null, "portfolio-guest");
        MockMvc mvc = MockMvcBuilders.standaloneSetup(controller)
                .setControllerAdvice(new GlobalExceptionHandler())
                .addInterceptors(new MemberCsrfInterceptor(new AuthOriginPolicy(ORIGIN), sessions),
                        new MemberAuthorizationInterceptor(sessions))
                .addFilters(new RequestIdFilter()).build();

        mvc.perform(get("/api/v1/portfolio/mock-portfolios")
                        .cookie(new jakarta.servlet.http.Cookie(SessionCookie.NAME, issued.token())))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.items.length()").value(2))
                .andExpect(jsonPath("$.items[1].holdingsCount").value(2));

        mvc.perform(get("/api/v1/portfolio/mock-portfolios")
                        .cookie(new jakarta.servlet.http.Cookie(SessionCookie.NAME, guest.token())))
                .andExpect(status().isForbidden());

        mvc.perform(post("/api/v1/portfolio/connections")
                        .cookie(new jakarta.servlet.http.Cookie(SessionCookie.NAME, issued.token()))
                        .header("Origin", ORIGIN)
                        .header("X-CSRF-Token", issued.response().csrfToken())
                        .header("Idempotency-Key", "http-connect-removed-profile")
                        .contentType("application/json")
                        .content("{\"mockPortfolioId\":\"demo-empty\"}"))
                .andExpect(status().isNotFound());

        var connected = mvc.perform(post("/api/v1/portfolio/connections")
                        .cookie(new jakarta.servlet.http.Cookie(SessionCookie.NAME, issued.token()))
                        .header("Origin", ORIGIN)
                        .header("X-CSRF-Token", issued.response().csrfToken())
                        .header("Idempotency-Key", "http-connect-1")
                        .contentType("application/json")
                        .content("{\"mockPortfolioId\":\"demo-growth\"}"))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.status").value("connected"))
                .andExpect(jsonPath("$.holdingsCount").value(2))
                .andReturn();
        String connectionId = mapper.readTree(connected.getResponse().getContentAsString()).path("id").asText();

        mvc.perform(delete("/api/v1/portfolio/connections/{id}", connectionId)
                        .cookie(new jakarta.servlet.http.Cookie(SessionCookie.NAME, issued.token()))
                        .header("Origin", ORIGIN)
                        .header("X-CSRF-Token", issued.response().csrfToken()))
                .andExpect(status().isNoContent());
        mvc.perform(get("/api/v1/portfolio")
                        .cookie(new jakarta.servlet.http.Cookie(SessionCookie.NAME, issued.token())))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.connected").value(false));
    }

    private String insertMember() {
        String memberId = "portfolio-test-" + UUID.randomUUID();
        Instant now = Instant.now();
        String email = memberId + "@example.com";
        jdbc.update("""
                INSERT INTO members (id, analytics_key, email, email_key, display_name,
                                     password_hash, signup_method, status, mode, investor,
                                     completed, tutorial_completed, settings_version,
                                     created_at, updated_at, blocked_at)
                VALUES (?, ?, ?, ?, 'Portfolio Test', 'test-hash', 'email', 'active', NULL, NULL,
                        false, false, 1, ?, ?, NULL)
                """, memberId, memberId, email, email, Timestamp.from(now), Timestamp.from(now));
        return memberId;
    }
}
