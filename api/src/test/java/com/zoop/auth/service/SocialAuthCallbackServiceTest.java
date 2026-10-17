package com.zoop.auth.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.HexFormat;
import java.util.Optional;

import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.json.JsonMapper;
import com.zoop.auth.config.SocialAuthSettings;
import com.zoop.auth.repository.OAuthPendingRepository;
import com.zoop.auth.repository.OAuthPendingRow;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.http.HttpHeaders;
import org.springframework.http.ResponseEntity;

class SocialAuthCallbackServiceTest {
    private static final Instant NOW = Instant.parse("2026-10-15T00:00:00Z");
    private static final String COOKIE = "C".repeat(43);
    private static final String STATE = "S".repeat(43);
    private OAuthPendingRepository pending;
    private SocialProviderGateway gateway;
    private OidcIdTokenVerifier verifier;
    private ObjectMapper mapper;
    private SocialAuthCompletionService completion;
    private SocialAuthCallbackService service;

    @BeforeEach
    void setUp() {
        pending = mock(OAuthPendingRepository.class);
        gateway = mock(SocialProviderGateway.class);
        verifier = mock(OidcIdTokenVerifier.class);
        completion = mock(SocialAuthCompletionService.class);
        mapper = JsonMapper.builder().build();
        SocialAuthSettings settings = new SocialAuthSettings(Duration.ofMinutes(10), 30, 10,
                "/login,/signup,/", false, "https://web.example.com", "google-client", "google-secret",
                "https://api.example.com/api/v1/auth/social/google/callback",
                "kakao-client", "kakao-secret", "https://api.example.com/api/v1/auth/social/kakao/callback");
        service = new SocialAuthCallbackService(pending, settings, gateway, verifier, mapper,
                Clock.fixed(NOW, ZoneOffset.UTC), completion);
    }

    @Test
    void validGoogleCallbackClaimsOnceAndStoresOnlyVerifiedIdentity() throws Exception {
        OAuthPendingRow row = pendingRow("google", "/signup");
        when(pending.claimAuthorization(anyString(), anyString(), anyString(), any(Instant.class)))
                .thenReturn(Optional.of(row));
        when(gateway.exchange("google", "provider-code",
                "https://api.example.com/api/v1/auth/social/google/callback", "V".repeat(43)))
                .thenReturn(new SocialProviderGateway.TokenSet("access-secret", "id-token-secret"));
        when(verifier.verify(anyString(), any(), anyString(), anyString()))
                .thenReturn(new OidcIdTokenVerifier.VerifiedClaims("subject-123", "member@example.com", true));
        when(pending.completeVerification(anyString(), anyString(), anyString(), any(Instant.class)))
                .thenAnswer(call -> Optional.of(new OAuthPendingRow("flow-id", hash(COOKIE),
                        call.getArgument(2), NOW, NOW.plusSeconds(600))));
        when(completion.complete(any(), anyString(), any(), anyString()))
                .thenReturn(ResponseEntity.status(302).header(HttpHeaders.LOCATION, "https://web.example.com/login").build());

        var response = service.callback("google", STATE, "provider-code", null, COOKIE, null, "request-1");

        assertEquals(302, response.getStatusCode().value());
        assertEquals("https://web.example.com/login", response.getHeaders().getFirst(HttpHeaders.LOCATION));
        verify(completion).complete(any(), org.mockito.ArgumentMatchers.eq(COOKIE),
                org.mockito.ArgumentMatchers.isNull(), org.mockito.ArgumentMatchers.eq("request-1"));
        verify(pending).claimAuthorization(anyString(), anyString(), org.mockito.ArgumentMatchers.eq("google"), any(Instant.class));
        verify(pending, never()).consumeClaimedCallback(anyString(), anyString(), any(Instant.class));
        ArgumentCaptor<String> flowJson = ArgumentCaptor.forClass(String.class);
        verify(pending).completeVerification(anyString(), anyString(), flowJson.capture(), any(Instant.class));
        var flow = mapper.readTree(flowJson.getValue());
        assertEquals("identity_verified", flow.path("phase").asString());
        assertEquals("subject-123", flow.path("providerSubject").asString());
        assertEquals("member@example.com", flow.path("email").asString());
        assertTrue(flow.path("emailVerified").asBoolean());
        assertFalse(flow.has("codeVerifier"));
        assertFalse(flowJson.getValue().contains("access-secret"));
        assertFalse(flowJson.getValue().contains("id-token-secret"));
    }

    @Test
    void linkCallbackPreservesTheBoundMemberAndSessionForAtomicLinkCompletion() throws Exception {
        OAuthPendingRow row = pendingLinkRow("google", "/login");
        when(pending.claimAuthorization(anyString(), anyString(), anyString(), any(Instant.class)))
                .thenReturn(Optional.of(row));
        when(gateway.exchange("google", "provider-code",
                "https://api.example.com/api/v1/auth/social/google/callback", "V".repeat(43)))
                .thenReturn(new SocialProviderGateway.TokenSet("access-secret", "id-token-secret"));
        when(verifier.verify(anyString(), any(), anyString(), anyString()))
                .thenReturn(new OidcIdTokenVerifier.VerifiedClaims("subject-123", "member@example.com", true));
        when(pending.completeVerification(anyString(), anyString(), anyString(), any(Instant.class)))
                .thenAnswer(call -> Optional.of(new OAuthPendingRow("flow-id", hash(COOKIE),
                        call.getArgument(2), NOW, NOW.plusSeconds(600))));
        when(completion.complete(any(), anyString(), any(), anyString()))
                .thenReturn(ResponseEntity.status(302)
                        .header(HttpHeaders.LOCATION, "https://web.example.com/login?social=linked").build());

        var response = service.callback("google", STATE, "provider-code", null, COOKIE,
                "M".repeat(43), "request-link");

        assertEquals("https://web.example.com/login?social=linked", response.getHeaders().getFirst(HttpHeaders.LOCATION));
        ArgumentCaptor<OAuthPendingRow> verifiedRow = ArgumentCaptor.forClass(OAuthPendingRow.class);
        verify(completion).complete(verifiedRow.capture(), org.mockito.ArgumentMatchers.eq(COOKIE),
                org.mockito.ArgumentMatchers.eq("M".repeat(43)), org.mockito.ArgumentMatchers.eq("request-link"));
        var flow = mapper.readTree(verifiedRow.getValue().authFlow());
        assertEquals("link", flow.path("intent").asString());
        assertEquals("member-42", flow.path("memberId").asString());
        assertEquals("session-99", flow.path("sessionId").asString());
    }

    @Test
    void callbackStateMismatchDoesNotExchangeAuthorizationCodeAndClearsPending() {
        var response = service.callback("google", "X".repeat(43), "provider-code", null, COOKIE, null, "request-1");

        assertEquals("https://web.example.com/login?social=failed", response.getHeaders().getFirst(HttpHeaders.LOCATION));
        assertTrue(response.getHeaders().getFirst(HttpHeaders.SET_COOKIE).contains("Max-Age=0"));
        verify(gateway, never()).exchange(anyString(), anyString(), anyString(), anyString());
        verify(pending).deleteByTokenHash(anyString());
    }

    @Test
    void kakaoSubjectMustMatchAccessTokenUserInfoId() throws Exception {
        OAuthPendingRow row = pendingRow("kakao", "/login");
        when(pending.claimAuthorization(anyString(), anyString(), anyString(), any(Instant.class)))
                .thenReturn(Optional.of(row));
        when(gateway.exchange(anyString(), anyString(), anyString(), anyString()))
                .thenReturn(new SocialProviderGateway.TokenSet("access-token", "id-token"));
        when(verifier.verify(anyString(), any(), anyString(), anyString()))
                .thenReturn(new OidcIdTokenVerifier.VerifiedClaims("1234567", "user@example.com", true));
        when(gateway.kakaoUserInfo("access-token")).thenReturn(mapper.readTree("""
                {"id": 7654321, "kakao_account":{"email":"user@example.com","is_email_valid":true,"is_email_verified":true}}
                """));

        var response = service.callback("kakao", STATE, "provider-code", null, COOKIE, null, "request-1");

        assertEquals("https://web.example.com/login?social=failed", response.getHeaders().getFirst(HttpHeaders.LOCATION));
        verify(pending).consumeClaimedCallback(anyString(), anyString(), any(Instant.class));
        verify(pending, never()).completeVerification(anyString(), anyString(), anyString(), any(Instant.class));
    }

    @Test
    void providerCancellationConsumesPendingWithoutExchangingCode() {
        OAuthPendingRow row = pendingRow("google", "/login");
        when(pending.claimAuthorization(anyString(), anyString(), anyString(), any(Instant.class)))
                .thenReturn(Optional.of(row));

        var response = service.callback("google", STATE, null, "access_denied", COOKIE, null, "request-1");

        assertEquals("https://web.example.com/login?social=cancelled", response.getHeaders().getFirst(HttpHeaders.LOCATION));
        verify(pending).consumeClaimedCallback(anyString(), anyString(), any(Instant.class));
        verify(gateway, never()).exchange(anyString(), anyString(), anyString(), anyString());
    }

    private OAuthPendingRow pendingRow(String provider, String returnTo) {
        String stateHash = hash(STATE);
        var flow = mapper.createObjectNode()
                .put("schemaVersion", 1)
                .put("phase", "callback_processing")
                .put("provider", provider)
                .put("stateHash", stateHash)
                .put("nonceHash", "a".repeat(64))
                .put("codeVerifier", "V".repeat(43))
                .put("redirectUri", "https://api.example.com/api/v1/auth/social/" + provider + "/callback")
                .put("returnTo", returnTo)
                .put("intent", "login");
        return new OAuthPendingRow("flow-id", hash(COOKIE), mapper.writeValueAsString(flow), NOW, NOW.plusSeconds(600));
    }

    private OAuthPendingRow pendingLinkRow(String provider, String returnTo) {
        var flow = mapper.createObjectNode()
                .put("schemaVersion", 1)
                .put("phase", "callback_processing")
                .put("provider", provider)
                .put("stateHash", hash(STATE))
                .put("nonceHash", "a".repeat(64))
                .put("codeVerifier", "V".repeat(43))
                .put("redirectUri", "https://api.example.com/api/v1/auth/social/" + provider + "/callback")
                .put("returnTo", returnTo)
                .put("intent", "link")
                .put("memberId", "member-42")
                .put("sessionId", "session-99");
        return new OAuthPendingRow("flow-id", hash(COOKIE), mapper.writeValueAsString(flow), NOW,
                NOW.plusSeconds(600));
    }

    private static String hash(String value) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256")
                    .digest(value.getBytes(StandardCharsets.US_ASCII)));
        } catch (Exception exception) {
            throw new AssertionError(exception);
        }
    }
}
