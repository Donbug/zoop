package com.zoop.auth.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.reset;
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
import com.zoop.auth.repository.MemberAuthRepository;
import com.zoop.auth.repository.MemberAuthRow;
import com.zoop.auth.repository.MemberLinkTargetRow;
import com.zoop.auth.repository.OAuthPendingRepository;
import com.zoop.auth.repository.OAuthPendingRow;
import com.zoop.auth.repository.SocialIdentityRepository;
import com.zoop.auth.repository.SocialIdentityRow;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.http.HttpHeaders;

class SocialAuthCompletionServiceTest {
    private static final Instant NOW = Instant.parse("2026-10-15T00:00:00Z");
    private static final String COOKIE = "C".repeat(43);
    private final ObjectMapper mapper = JsonMapper.builder().build();
    private OAuthPendingRepository pending;
    private SocialIdentityRepository identities;
    private MemberAuthRepository members;
    private MemberSessionService sessions;
    private SocialAuthCompletionService service;

    @BeforeEach
    void setUp() {
        pending = mock(OAuthPendingRepository.class);
        identities = mock(SocialIdentityRepository.class);
        members = mock(MemberAuthRepository.class);
        sessions = mock(MemberSessionService.class);
        var settings = new SocialAuthSettings(Duration.ofMinutes(10), 30, 10, "/login,/signup,/", true,
                "google-client", "google-secret", "http://localhost:8080/api/v1/auth/social/google/callback",
                "kakao-client", "kakao-secret", "http://localhost:8080/api/v1/auth/social/kakao/callback");
        service = new SocialAuthCompletionService(pending, identities, members, sessions, settings,
                mapper, Clock.fixed(NOW, ZoneOffset.UTC));
    }

    @Test
    void linkedIdentityIssuesSessionAndConsumesVerifiedPending() {
        var row = row(flow("google", "member@example.com", true));
        when(identities.findByProviderSubject("google", "subject-1")).thenReturn(Optional.of(
                new SocialIdentityRow("link-id", "member-id", "google", "subject-1", NOW)));
        when(members.findById("member-id")).thenReturn(Optional.of(new MemberAuthRow("member-id", "active", null)));
        when(pending.consumeIdentityVerified(eq("flow-id"), anyString(), any(Instant.class))).thenReturn(Optional.of(row));
        when(sessions.issue("member-id", null, "request-1"))
                .thenReturn(new MemberSessionService.IssuedSession("T".repeat(43), null));

        var response = service.complete(row, COOKIE, null, "request-1");

        assertEquals("/login", response.getHeaders().getFirst(HttpHeaders.LOCATION));
        assertTrue(response.getHeaders().get(HttpHeaders.SET_COOKIE).stream().anyMatch(value -> value.startsWith("zoop_session=")));
        assertTrue(response.getHeaders().get(HttpHeaders.SET_COOKIE).stream().anyMatch(value -> value.startsWith("zoop_oauth_pending=")));
        verify(sessions).issue("member-id", null, "request-1");
        verify(pending).consumeIdentityVerified(eq("flow-id"), anyString(), any(Instant.class));
        verify(members, never()).findByEmailKey(anyString());
    }

    @Test
    void existingEmailDoesNotAutoLinkOrLogin() {
        var row = row(flow("kakao", "  MEMBER@example.com ", true));
        when(identities.findByProviderSubject("kakao", "subject-1")).thenReturn(Optional.empty());
        when(members.findByEmailKey("member@example.com"))
                .thenReturn(Optional.of(new MemberAuthRow("existing", "active", "hash")));
        when(pending.consumeIdentityVerified(eq("flow-id"), anyString(), any(Instant.class))).thenReturn(Optional.of(row));

        var response = service.complete(row, COOKIE, null, "request-1");

        assertEquals("/login?social=link_required", response.getHeaders().getFirst(HttpHeaders.LOCATION));
        verify(sessions, never()).issue(anyString(), any(), anyString());
        verify(identities, never()).insert(anyString(), anyString(), anyString(), anyString(), any(Instant.class));
        verify(pending).consumeIdentityVerified(eq("flow-id"), anyString(), any(Instant.class));
    }

    @Test
    void newEmailRotatesCookieAndPreservesOnlyVerifiedSignupClaims() throws Exception {
        var row = row(flow("google", "Member@example.com", true));
        when(identities.findByProviderSubject("google", "subject-1")).thenReturn(Optional.empty());
        when(members.findByEmailKey("member@example.com")).thenReturn(Optional.empty());
        when(pending.rotateToConsent(eq("flow-id"), anyString(), anyString(), anyString(),
                any(Instant.class), any(Instant.class))).thenAnswer(call -> Optional.of(new OAuthPendingRow(
                        "flow-id", call.getArgument(2), call.getArgument(3), NOW, NOW.plusSeconds(600))));

        var response = service.complete(row, COOKIE, null, "request-1");

        assertEquals("/signup?social=pending", response.getHeaders().getFirst(HttpHeaders.LOCATION));
        String cookie = response.getHeaders().getFirst(HttpHeaders.SET_COOKIE);
        assertTrue(cookie.startsWith("zoop_oauth_pending="));
        assertTrue(cookie.contains("HttpOnly"));
        assertTrue(cookie.contains("Max-Age=600"));
        String newValue = cookie.substring("zoop_oauth_pending=".length(), cookie.indexOf(';'));
        assertNotEquals(COOKIE, newValue);
        ArgumentCaptor<String> flowJson = ArgumentCaptor.forClass(String.class);
        verify(pending).rotateToConsent(eq("flow-id"), anyString(), anyString(), flowJson.capture(),
                any(Instant.class), any(Instant.class));
        var savedFlow = mapper.readTree(flowJson.getValue());
        assertEquals("consent_pending", savedFlow.path("phase").asString());
        assertEquals("Member@example.com", savedFlow.path("email").asString());
        assertFalse(savedFlow.has("returnTo"));
        verify(sessions, never()).issue(anyString(), any(), anyString());
    }

    @Test
    void missingOrUnverifiedEmailCannotStartSignup() {
        var row = row(flow("google", null, false));
        when(identities.findByProviderSubject("google", "subject-1")).thenReturn(Optional.empty());
        when(pending.consumeIdentityVerified(eq("flow-id"), anyString(), any(Instant.class))).thenReturn(Optional.of(row));

        var response = service.complete(row, COOKIE, null, "request-1");

        assertEquals("/login?social=email_required", response.getHeaders().getFirst(HttpHeaders.LOCATION));
        verify(members, never()).findByEmailKey(anyString());
        verify(pending, never()).rotateToConsent(anyString(), anyString(), anyString(), anyString(),
                any(Instant.class), any(Instant.class));
    }

    @Test
    void linkCallbackRequiresSameMemberSessionAndMatchingVerifiedEmail() {
        var row = row(linkFlow("member-id", "session-1", "member@example.com"));
        when(pending.consumeIdentityVerified(eq("flow-id"), anyString(), any(Instant.class))).thenReturn(Optional.of(row));
        when(sessions.currentBindingIfActive("S".repeat(43)))
                .thenReturn(Optional.of(new MemberSessionService.SessionBinding("member-id", "session-1")));
        when(members.findLinkTargetById("member-id"))
                .thenReturn(Optional.of(new MemberLinkTargetRow("member-id", "active", "member@example.com")));
        when(identities.findByProviderSubject("google", "subject-1")).thenReturn(Optional.empty());

        var response = service.complete(row, COOKIE, "S".repeat(43), "request-1");

        assertEquals("/login?social=linked", response.getHeaders().getFirst(HttpHeaders.LOCATION));
        verify(identities).insert(anyString(), eq("member-id"), eq("google"), eq("subject-1"), eq(NOW));
        verify(sessions, never()).issue(anyString(), any(), anyString());
    }

    @Test
    void linkCallbackRejectsChangedSessionOrDifferentVerifiedEmail() {
        var changedSession = row(linkFlow("member-id", "session-1", "member@example.com"));
        when(pending.consumeIdentityVerified(eq("flow-id"), anyString(), any(Instant.class)))
                .thenReturn(Optional.of(changedSession));
        when(sessions.currentBindingIfActive("S".repeat(43)))
                .thenReturn(Optional.of(new MemberSessionService.SessionBinding("member-id", "new-session")));

        var changed = service.complete(changedSession, COOKIE, "S".repeat(43), "request-1");

        assertEquals("/login?social=failed", changed.getHeaders().getFirst(HttpHeaders.LOCATION));
        verify(members, never()).findLinkTargetById(anyString());
        verify(identities, never()).insert(anyString(), anyString(), anyString(), anyString(), any(Instant.class));

        reset(pending, sessions, members, identities);
        var mismatch = row(linkFlow("member-id", "session-1", "other@example.com"));
        when(pending.consumeIdentityVerified(eq("flow-id"), anyString(), any(Instant.class))).thenReturn(Optional.of(mismatch));
        when(sessions.currentBindingIfActive("S".repeat(43)))
                .thenReturn(Optional.of(new MemberSessionService.SessionBinding("member-id", "session-1")));
        when(members.findLinkTargetById("member-id"))
                .thenReturn(Optional.of(new MemberLinkTargetRow("member-id", "active", "member@example.com")));
        when(identities.findByProviderSubject("google", "subject-1")).thenReturn(Optional.empty());

        var emailMismatch = service.complete(mismatch, COOKIE, "S".repeat(43), "request-1");

        assertEquals("/login?social=failed", emailMismatch.getHeaders().getFirst(HttpHeaders.LOCATION));
        verify(identities, never()).insert(anyString(), anyString(), anyString(), anyString(), any(Instant.class));
    }

    @Test
    void linkCallbackDoesNotMoveIdentityFromAnotherMemberAndSameMemberRetryIsIdempotent() {
        var row = row(linkFlow("member-id", "session-1", "member@example.com"));
        when(pending.consumeIdentityVerified(eq("flow-id"), anyString(), any(Instant.class))).thenReturn(Optional.of(row));
        when(sessions.currentBindingIfActive("S".repeat(43)))
                .thenReturn(Optional.of(new MemberSessionService.SessionBinding("member-id", "session-1")));
        when(members.findLinkTargetById("member-id"))
                .thenReturn(Optional.of(new MemberLinkTargetRow("member-id", "active", "member@example.com")));
        when(identities.findByProviderSubject("google", "subject-1"))
                .thenReturn(Optional.of(new SocialIdentityRow("link-id", "other-member", "google", "subject-1", NOW)));

        var conflict = service.complete(row, COOKIE, "S".repeat(43), "request-1");

        assertEquals("/login?social=failed", conflict.getHeaders().getFirst(HttpHeaders.LOCATION));
        verify(identities, never()).insert(anyString(), anyString(), anyString(), anyString(), any(Instant.class));

        reset(pending, sessions, members, identities);
        when(pending.consumeIdentityVerified(eq("flow-id"), anyString(), any(Instant.class))).thenReturn(Optional.of(row));
        when(sessions.currentBindingIfActive("S".repeat(43)))
                .thenReturn(Optional.of(new MemberSessionService.SessionBinding("member-id", "session-1")));
        when(members.findLinkTargetById("member-id"))
                .thenReturn(Optional.of(new MemberLinkTargetRow("member-id", "active", "member@example.com")));
        when(identities.findByProviderSubject("google", "subject-1"))
                .thenReturn(Optional.of(new SocialIdentityRow("link-id", "member-id", "google", "subject-1", NOW)));

        var retry = service.complete(row, COOKIE, "S".repeat(43), "request-1");

        assertEquals("/login?social=linked", retry.getHeaders().getFirst(HttpHeaders.LOCATION));
        verify(identities, never()).insert(anyString(), anyString(), anyString(), anyString(), any(Instant.class));
        verify(sessions, never()).issue(anyString(), any(), anyString());
    }

    private OAuthPendingRow row(String flow) {
        return new OAuthPendingRow("flow-id", hash(COOKIE), flow, NOW, NOW.plusSeconds(600));
    }

    private String flow(String provider, String email, boolean verified) {
        var value = mapper.createObjectNode().put("schemaVersion", 1).put("phase", "identity_verified")
                .put("provider", provider).put("stateHash", "a".repeat(64)).put("providerSubject", "subject-1")
                .put("emailVerified", verified).put("intent", "login").put("returnTo", "/login");
        if (email == null) value.putNull("email"); else value.put("email", email);
        return value.toString();
    }

    private String linkFlow(String memberId, String sessionId, String email) {
        return mapper.createObjectNode().put("schemaVersion", 1).put("phase", "identity_verified")
                .put("provider", "google").put("stateHash", "a".repeat(64)).put("providerSubject", "subject-1")
                .put("email", email).put("emailVerified", true).put("intent", "link")
                .put("memberId", memberId).put("sessionId", sessionId).put("returnTo", "/login").toString();
    }

    private static String hash(String value) {
        try { return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256")
                .digest(value.getBytes(StandardCharsets.US_ASCII))); }
        catch (Exception exception) { throw new AssertionError(exception); }
    }
}
