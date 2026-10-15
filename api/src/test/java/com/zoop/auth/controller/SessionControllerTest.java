package com.zoop.auth.controller;

import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.Base64;
import java.util.Optional;

import com.zoop.auth.repository.MemberSessionRepository;
import com.zoop.auth.repository.MemberSessionRow;
import com.zoop.auth.service.CsrfKeyRing;
import com.zoop.auth.service.MemberSessionService;
import com.zoop.auth.service.SessionCookie;
import com.zoop.common.request.RequestIdFilter;
import jakarta.servlet.http.Cookie;
import org.junit.jupiter.api.Test;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;
import static org.junit.jupiter.api.Assertions.*;

class SessionControllerTest {
    @Test
    void cookieAttributesAndSessionHttpResponsesFollowContract() throws Exception {
        String cookie = SessionCookie.issue("opaque").toString();
        assertTrue(cookie.contains("Path=/api/v1"));
        assertTrue(cookie.contains("Secure"));
        assertTrue(cookie.contains("HttpOnly"));
        assertTrue(cookie.contains("SameSite=Lax"));
        assertTrue(cookie.contains("Max-Age=43200"));
        assertFalse(cookie.contains("Domain="));

        Instant now = Instant.parse("2026-10-14T00:00:00Z");
        MemberSessionRepository repository = new MemberSessionRepository() {
            @Override
            public Optional<MemberSessionRow> findByTokenHash(String hash) {
                return Optional.of(new MemberSessionRow("session_1", "member-1", "member", hash,
                        "key", 1, now, now.plusSeconds(43200), null, "active",
                        "a@example.com", "User", false, false));
            }

            @Override
            public void insertMemberSession(String id, String memberId, String hash,
                    String keyId, Instant created, Instant expiry) {
            }

            @Override
            public void insertGuestSession(String id, String analyticsKey, String hash,
                    String keyId, Instant created, Instant expiry) {
            }

            @Override
            public void revokeMemberSession(String hash, String memberId, Instant at) {
            }

            @Override
            public void revokeGuestSession(String hash, Instant at) {
            }
        };
        String key = Base64.getUrlEncoder().withoutPadding().encodeToString(new byte[32]);
        var service = new MemberSessionService(repository, new CsrfKeyRing("key", "key=" + key),
                Clock.fixed(now, ZoneOffset.UTC));
        var mvc = MockMvcBuilders.standaloneSetup(new SessionController(service))
                .addFilters(new RequestIdFilter()).build();

        mvc.perform(get("/api/v1/auth/session").header("X-Request-ID", "request-1"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.kind").value("anonymous"))
                .andExpect(jsonPath("$.csrfToken").value((Object) null))
                .andExpect(header().doesNotExist("Set-Cookie"));
        mvc.perform(get("/api/v1/auth/session")
                        .cookie(new Cookie(SessionCookie.NAME, "invalid")))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.kind").value("anonymous"))
                .andExpect(header().string("Set-Cookie", org.hamcrest.Matchers.containsString("Max-Age=0")));
        mvc.perform(get("/api/v1/auth/session").header("X-Request-ID", "request-1")
                        .cookie(new Cookie(SessionCookie.NAME, "a".repeat(43))))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.kind").value("member"))
                .andExpect(jsonPath("$.user.id").value("member-1"))
                .andExpect(jsonPath("$.metadata.requestId").value("request-1"))
                .andExpect(jsonPath("$.csrfToken").isString());
    }
}
