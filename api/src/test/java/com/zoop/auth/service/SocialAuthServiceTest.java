package com.zoop.auth.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneOffset;

import com.zoop.auth.config.SocialAuthSettings;
import com.zoop.auth.dto.SocialProvidersResponse;
import com.zoop.auth.repository.OAuthPendingRepository;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.http.HttpHeaders;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.json.JsonMapper;

class SocialAuthServiceTest {
    private static final Instant NOW = Instant.parse("2026-10-15T00:00:00Z");
    private OAuthPendingRepository pending;
    private AuthRateLimiter rates;
    private SocialAuthService service;
    private ObjectMapper mapper;
    private MemberSessionService sessions;

    @BeforeEach
    void setUp() {
        pending = mock(OAuthPendingRepository.class);
        rates = mock(AuthRateLimiter.class);
        mapper = JsonMapper.builder().build();
        sessions = mock(MemberSessionService.class);
        SocialAuthSettings settings = new SocialAuthSettings(Duration.ofMinutes(10), 30, 10,
                "/login,/signup,/", false, "https://web.example.com", "google-client", "google-secret",
                "https://api.example.com/api/v1/auth/social/google/callback",
                "kakao-client", "kakao-secret", "https://api.example.com/api/v1/auth/social/kakao/callback");
        service = new SocialAuthService(pending, settings, rates, mapper,
                Clock.fixed(NOW, ZoneOffset.UTC), sessions);
    }

    @Test
    void providerListUsesOpaqueCursorAndStablePages() {
        SocialProvidersResponse first = service.listProviders(null, 1);
        assertEquals("google", first.items().getFirst().id());
        assertNotNull(first.nextCursor());

        SocialProvidersResponse second = service.listProviders(first.nextCursor(), null);
        assertEquals("kakao", second.items().getFirst().id());
        assertEquals(null, second.nextCursor());
    }

    @Test
    void authorizePersistsOneTimeStateAndRedirectsWithSecureBrowserCookie() throws Exception {
        var response = service.authorize("google", "/signup", "203.0.113.4", null);

        assertEquals(302, response.getStatusCode().value());
        String location = response.getHeaders().getFirst(HttpHeaders.LOCATION);
        assertTrue(location.startsWith("https://accounts.google.com/o/oauth2/v2/auth?"));
        assertTrue(location.contains("code_challenge_method=S256"));
        assertTrue(location.contains("scope=openid%20email"));
        String setCookie = response.getHeaders().getFirst(HttpHeaders.SET_COOKIE);
        assertTrue(setCookie.contains("Secure"));
        assertTrue(setCookie.contains("HttpOnly"));
        assertTrue(setCookie.contains("SameSite=Lax"));
        assertTrue(setCookie.contains("Path=/api/v1/auth/social"));
        assertFalse(setCookie.contains("Domain="));

        ArgumentCaptor<String> tokenHash = ArgumentCaptor.forClass(String.class);
        ArgumentCaptor<String> flowJson = ArgumentCaptor.forClass(String.class);
        verify(pending).insert(anyString(), tokenHash.capture(), flowJson.capture(), any(Instant.class), any(Instant.class));
        var flow = mapper.readTree(flowJson.getValue());
        assertEquals("authorization_pending", flow.path("phase").asString());
        assertEquals("google", flow.path("provider").asString());
        assertEquals("login", flow.path("intent").asString());
        assertEquals(64, flow.path("stateHash").asString().length());
        assertEquals(64, flow.path("nonceHash").asString().length());
        assertEquals(43, flow.path("codeVerifier").asString().length());
        assertEquals("https://api.example.com/api/v1/auth/social/google/callback",
                flow.path("redirectUri").asString());
        assertEquals(NOW.plus(Duration.ofMinutes(10)),
                pendingExpiry(pending, tokenHash.getValue()));
    }

    @Test
    void aSubsequentStartKeepsTheBrowserRateKeyAndReplacesItsPendingFlow() {
        String cookieToken = "A".repeat(43);
        var response = service.authorize("kakao", null, "203.0.113.4", cookieToken);

        verify(rates).recordSocialStartBrowserAttempt(anyString(), anyInt());
        verify(pending).deleteByTokenHash(anyString());
        String setCookie = response.getHeaders().getFirst(HttpHeaders.SET_COOKIE);
        assertTrue(setCookie.contains("zoop_oauth_pending=" + cookieToken));
    }

    @Test
    void explicitLinkStartBindsTheAuthenticatedMemberAndSessionToPending() throws Exception {
        when(sessions.currentBinding("M".repeat(43)))
                .thenReturn(new MemberSessionService.SessionBinding("member-42", "session-99"));

        var response = service.authorizeLink("google", "/", "203.0.113.4", null,
                "M".repeat(43), "C".repeat(43));

        assertEquals(200, response.getStatusCode().value());
        assertTrue(response.getBody().authorizationUrl().startsWith("https://accounts.google.com/"));
        assertTrue(response.getHeaders().getFirst(HttpHeaders.SET_COOKIE).contains("zoop_oauth_pending="));
        ArgumentCaptor<String> flowJson = ArgumentCaptor.forClass(String.class);
        verify(pending).insert(anyString(), anyString(), flowJson.capture(), any(Instant.class), any(Instant.class));
        var flow = mapper.readTree(flowJson.getValue());
        assertEquals("link", flow.path("intent").asString());
        assertEquals("member-42", flow.path("memberId").asString());
        assertEquals("session-99", flow.path("sessionId").asString());
        verify(sessions).verifyCsrf("M".repeat(43), "C".repeat(43));
    }

    @Test
    void rejectsExternalReturnPathsAndInvalidCursors() {
        CustomException external = assertThrows(CustomException.class,
                () -> service.authorize("google", "//evil.example", "203.0.113.4", null));
        assertEquals(ErrorCode.INVALID_REQUEST, external.getErrorCode());
        CustomException cursor = assertThrows(CustomException.class,
                () -> service.listProviders("bogus", null));
        assertEquals(ErrorCode.INVALID_CURSOR, cursor.getErrorCode());
        verifyNoInteractions(rates);
    }

    @Test
    void insecureRedirectsAreOptInAndRestrictedToLoopbackHosts() {
        SocialAuthSettings local = new SocialAuthSettings(Duration.ofMinutes(10), 30, 10,
                "/login,/signup,/", true, "http://localhost:5173", "google-client", "google-secret",
                "http://localhost:8080/api/v1/auth/social/google/callback",
                "kakao-client", "kakao-secret", "http://127.0.0.1:8080/api/v1/auth/social/kakao/callback");
        assertTrue(local.providerConfigured(local.provider("google")));
        assertTrue(local.providerConfigured(local.provider("kakao")));
        assertFalse(local.pendingCookieSecure(local.provider("google")));

        SocialAuthSettings secureOnly = new SocialAuthSettings(Duration.ofMinutes(10), 30, 10,
                "/login,/signup,/", false, "https://web.example.com", "google-client", "google-secret",
                "http://localhost:8080/api/v1/auth/social/google/callback",
                "kakao-client", "kakao-secret", "http://127.0.0.1:8080/api/v1/auth/social/kakao/callback");
        assertFalse(secureOnly.providerConfigured(secureOnly.provider("google")));

        SocialAuthSettings notLoopback = new SocialAuthSettings(Duration.ofMinutes(10), 30, 10,
                "/login,/signup,/", true, "http://localhost:5173", "google-client", "google-secret",
                "http://dev.example.com/api/v1/auth/social/google/callback",
                "kakao-client", "kakao-secret", "https://api.example.com/api/v1/auth/social/kakao/callback");
        assertFalse(notLoopback.providerConfigured(notLoopback.provider("google")));
        assertTrue(notLoopback.pendingCookieSecure(notLoopback.provider("kakao")));
    }

    private Instant pendingExpiry(OAuthPendingRepository repository, String ignoredTokenHash) {
        // TTL is also asserted at the repository boundary in the insertion capture below.
        ArgumentCaptor<Instant> expires = ArgumentCaptor.forClass(Instant.class);
        verify(repository).insert(anyString(), anyString(), anyString(), any(Instant.class), expires.capture());
        return expires.getValue();
    }
}
