package com.zoop.portfolio.controller;

import java.sql.Timestamp;
import java.time.Instant;
import java.util.UUID;

import com.zoop.auth.service.PasswordHashService;
import com.zoop.auth.service.MemberSessionService;
import com.zoop.auth.service.SessionCookie;
import com.zoop.common.request.RequestIdFilter;
import com.zoop.portfolio.service.PortfolioQuoteProvider;
import jakarta.servlet.http.Cookie;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Timeout;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;
import org.springframework.context.annotation.Primary;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;
import org.springframework.test.web.servlet.request.MockHttpServletRequestBuilder;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.context.WebApplicationContext;
import tools.jackson.databind.ObjectMapper;

import static org.junit.jupiter.api.Assertions.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

/** #51 / WBS 6.4.8 / D-MY-01·01b / FS027·FS054·FS062.
 * Real MVC routing, auth/CSRF, services and PostgreSQL. Only members and market quotes are synthetic.
 */
@SpringBootTest(properties = {
        "ZOOP_AUTH_CSRF_ACTIVE_KEY_ID=test",
        "ZOOP_AUTH_CSRF_KEYS=test=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        "ZOOP_AUTH_ALLOWED_ORIGINS=https://zoop.example"
})
@Import(MyStocksJourneyPostgresTest.MarketFixture.class)
@EnabledIfEnvironmentVariable(named = "DB_URL", matches = "jdbc:postgresql:.*")
@Tag("auth-postgres")
@Timeout(60)
class MyStocksJourneyPostgresTest {
    private static final String ORIGIN = "https://zoop.example";
    private static final String PASSWORD = "MyStocks51-local-test!9";
    private static final String COMPANY = "NASDAQ:NVDA";
    @Autowired WebApplicationContext context;
    @Autowired RequestIdFilter requestIds;
    @Autowired JdbcTemplate jdbc;
    @Autowired ObjectMapper json;
    @Autowired PasswordHashService passwords;
    @Autowired MemberSessionService sessions;
    private MockMvc mvc;

    @BeforeEach
    void setup() {
        mvc = MockMvcBuilders.webAppContextSetup(context).addFilters(requestIds).build();
    }

    @Test
    void anonymousAndGuestCannotReadOrWriteMemberStocks() throws Exception {
        mvc.perform(get("/api/v1/me/settings"))
                .andExpect(status().isUnauthorized()).andExpect(jsonPath("$.error.code").value("AUTH_REQUIRED"));
        mvc.perform(get("/api/v1/portfolio"))
                .andExpect(status().isUnauthorized()).andExpect(jsonPath("$.error.code").value("AUTH_REQUIRED"));
        var issued = sessions.issueGuest(null, "my-stocks-guest");
        var guest = new Login(issued.token(), issued.response().csrfToken());
        mvc.perform(read(get("/api/v1/me/settings"), guest))
                .andExpect(status().isForbidden()).andExpect(jsonPath("$.error.code").value("MEMBER_REQUIRED"));
        mvc.perform(read(get("/api/v1/portfolio"), guest))
                .andExpect(status().isForbidden()).andExpect(jsonPath("$.error.code").value("MEMBER_REQUIRED"));
        mvc.perform(write(put("/api/v1/me/watchlist/{id}", COMPANY), guest).content("{\"watched\":true}"))
                .andExpect(status().isForbidden()).andExpect(jsonPath("$.error.code").value("MEMBER_REQUIRED"));
    }

    @Test
    void loginWatchConnectLogoutReloginAndDisconnectPreserveIndependentSettings() throws Exception {
        String email = insertMember();
        Login first = login(email);
        watch(first, true).andExpect(jsonPath("$.watchlistIds[0]").value(COMPANY));
        var connected = mvc.perform(write(post("/api/v1/portfolio/connections"), first)
                        .header("Idempotency-Key", UUID.randomUUID().toString())
                        .content("{\"mockPortfolioId\":\"demo-balanced\"}"))
                .andExpect(status().isCreated()).andReturn();
        String connectionId = json.readTree(connected.getResponse().getContentAsString()).path("id").asText();
        mvc.perform(read(get("/api/v1/portfolio"), first))
                .andExpect(status().isOk()).andExpect(jsonPath("$.connected").value(true));
        mvc.perform(write(post("/api/v1/auth/logout"), first)).andExpect(status().isNoContent());
        mvc.perform(read(get("/api/v1/me/settings"), first)).andExpect(status().isUnauthorized());

        Login second = login(email);
        assertTrue(!first.token().equals(second.token()), "A new login must rotate the session");
        mvc.perform(read(get("/api/v1/me/settings"), second))
                .andExpect(status().isOk()).andExpect(jsonPath("$.watchlistIds[0]").value(COMPANY))
                .andExpect(jsonPath("$.completed").value(true)).andExpect(jsonPath("$.tutorialCompleted").value(true));
        mvc.perform(read(get("/api/v1/portfolio"), second))
                .andExpect(status().isOk()).andExpect(jsonPath("$.connection.id").value(connectionId));
        mvc.perform(write(delete("/api/v1/portfolio/connections/{id}", connectionId), second))
                .andExpect(status().isNoContent());
        mvc.perform(read(get("/api/v1/portfolio"), second))
                .andExpect(status().isOk()).andExpect(jsonPath("$.connected").value(false))
                .andExpect(jsonPath("$.holdings").isEmpty());
        mvc.perform(read(get("/api/v1/me/settings"), second))
                .andExpect(status().isOk()).andExpect(jsonPath("$.watchlistIds[0]").value(COMPANY))
                .andExpect(jsonPath("$.completed").value(true)).andExpect(jsonPath("$.tutorialCompleted").value(true));
    }

    @Test
    void anotherMemberAndRejectedWritesCannotAlterTheOwnersWatchlistOrConnection() throws Exception {
        Login owner = login(insertMember());
        Login other = login(insertMember());
        watch(owner, true).andExpect(jsonPath("$.version").value(2));
        // A target-state retry is idempotent; the saved settings version does not advance twice.
        watch(owner, true).andExpect(jsonPath("$.version").value(2));
        var connected = mvc.perform(write(post("/api/v1/portfolio/connections"), owner)
                        .header("Idempotency-Key", "my-stocks-connection")
                        .content("{\"mockPortfolioId\":\"demo-growth\"}"))
                .andExpect(status().isCreated()).andReturn();
        String id = json.readTree(connected.getResponse().getContentAsString()).path("id").asText();
        mvc.perform(read(get("/api/v1/me/settings"), other))
                .andExpect(status().isOk()).andExpect(jsonPath("$.watchlistIds").isEmpty());
        mvc.perform(read(get("/api/v1/portfolio"), other))
                .andExpect(status().isOk()).andExpect(jsonPath("$.connected").value(false));
        mvc.perform(write(delete("/api/v1/portfolio/connections/{id}", id), other))
                .andExpect(status().isNotFound());
        mvc.perform(read(put("/api/v1/me/watchlist/{id}", COMPANY), owner)
                        .header("Origin", ORIGIN).contentType("application/json").content("{\"watched\":false}"))
                .andExpect(status().isForbidden());
        mvc.perform(read(put("/api/v1/me/watchlist/{id}", COMPANY), other)
                        .header("Origin", ORIGIN).header("X-CSRF-Token", owner.csrf())
                        .contentType("application/json").content("{\"watched\":true}"))
                .andExpect(status().isForbidden());
        mvc.perform(read(get("/api/v1/me/settings"), owner))
                .andExpect(status().isOk()).andExpect(jsonPath("$.watchlistIds[0]").value(COMPANY))
                .andExpect(jsonPath("$.version").value(2));
        mvc.perform(read(get("/api/v1/portfolio"), owner))
                .andExpect(status().isOk()).andExpect(jsonPath("$.connection.id").value(id));
    }

    private org.springframework.test.web.servlet.ResultActions watch(Login login, boolean watched) throws Exception {
        return mvc.perform(write(put("/api/v1/me/watchlist/{id}", COMPANY), login)
                        .content("{\"watched\":" + watched + "}"))
                .andExpect(status().isOk());
    }

    private Login login(String email) throws Exception {
        MvcResult result = mvc.perform(post("/api/v1/auth/login").header("Origin", ORIGIN)
                        .contentType("application/json")
                        .content(json.writeValueAsString(java.util.Map.of("email", email, "password", PASSWORD))))
                .andExpect(status().isOk()).andExpect(cookie().exists(SessionCookie.NAME)).andReturn();
        String token = result.getResponse().getCookie(SessionCookie.NAME).getValue();
        String csrf = json.readTree(result.getResponse().getContentAsString()).path("csrfToken").asText();
        return new Login(token, csrf);
    }

    private MockHttpServletRequestBuilder read(MockHttpServletRequestBuilder request, Login login) {
        return request.cookie(new Cookie(SessionCookie.NAME, login.token()));
    }

    private MockHttpServletRequestBuilder write(MockHttpServletRequestBuilder request, Login login) {
        return read(request, login).header("Origin", ORIGIN).header("X-CSRF-Token", login.csrf())
                .contentType("application/json");
    }

    private String insertMember() {
        String memberId = "my-stocks-51-" + UUID.randomUUID();
        String email = memberId + "@example.com";
        Timestamp now = Timestamp.from(Instant.now());
        jdbc.update("""
                INSERT INTO members (id, analytics_key, email, email_key, display_name,
                                     password_hash, signup_method, status, mode, investor,
                                     completed, tutorial_completed, settings_version, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'My Stocks Test', ?, 'email', 'active', 'watchlist', false,
                        true, true, 1, ?, ?)
                """, memberId, memberId, email, email, passwords.hashNewPassword(PASSWORD), now, now);
        return email;
    }

    // Never include token/CSRF values in assertion descriptions or record.toString().
    private record Login(String token, String csrf) {
        @Override public String toString() { return "Login[redacted]"; }
    }

    @TestConfiguration(proxyBeanMethods = false)
    static class MarketFixture {
        @Bean @Primary
        PortfolioQuoteProvider noExternalQuotes() {
            return holding -> PortfolioQuoteProvider.QuoteResult.unavailable("synthetic-no-market");
        }
    }
}
