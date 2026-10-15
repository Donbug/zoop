package com.zoop.auth.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Optional;
import java.util.HexFormat;

import tools.jackson.databind.json.JsonMapper;
import com.zoop.auth.dto.SocialSignupRequest;
import com.zoop.auth.dto.SignupRequest;
import com.zoop.auth.repository.MemberAuthRepository;
import com.zoop.auth.repository.OAuthPendingRepository;
import com.zoop.auth.repository.OAuthPendingRow;
import com.zoop.auth.repository.SignupTermsRepository;
import com.zoop.auth.repository.SocialIdentityRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

class SocialSignupServiceTest {
    private static final Instant NOW = Instant.parse("2026-10-15T00:00:00Z");
    private static final String COOKIE = "C".repeat(43);
    private static final String HASH = hash(COOKIE);
    private OAuthPendingRepository pending;
    private SignupAgreementPolicy agreements;
    private SignupTermsRepository terms;
    private MemberAuthRepository members;
    private SocialIdentityRepository identities;
    private CredentialPolicy credentials;
    private MemberSessionService sessions;
    private SocialSignupService service;

    @BeforeEach
    void setUp() {
        pending = mock(OAuthPendingRepository.class);
        agreements = mock(SignupAgreementPolicy.class);
        terms = mock(SignupTermsRepository.class);
        members = mock(MemberAuthRepository.class);
        identities = mock(SocialIdentityRepository.class);
        credentials = mock(CredentialPolicy.class);
        sessions = mock(MemberSessionService.class);
        service = new SocialSignupService(pending, agreements, terms, members, identities,
                credentials, sessions, JsonMapper.builder().build(), Clock.fixed(NOW, ZoneOffset.UTC));
    }

    @Test
    void signupUsesVerifiedPendingIdentityAndAtomicallyPersistsMemberConsentLinkAndSession() {
        var accepted = List.of(new SignupRequest.Agreement("terms-1", "v3", true));
        when(pending.consumeConsent(HASH, NOW)).thenReturn(Optional.of(pendingRow()));
        when(agreements.validate(accepted, NOW)).thenReturn(accepted);
        when(credentials.displayName("  Zoop User ")).thenReturn("Zoop User");
        when(members.findByEmailKey("member@example.com")).thenReturn(Optional.empty());
        when(identities.findByProviderSubject("google", "provider-subject-42")).thenReturn(Optional.empty());
        when(members.insertSocialMember(anyString(), anyString(), anyString(), anyString(), anyString(),
                anyString(), any(Instant.class))).thenReturn(true);
        when(sessions.issue(anyString(), eq("old-session"), eq("req-social-signup")))
                .thenReturn(new MemberSessionService.IssuedSession("S".repeat(43), null));

        var result = service.signup(new SocialSignupRequest("  Zoop User ", accepted), COOKIE,
                "old-session", "req-social-signup");

        assertTrue(result.isPresent());
        verify(members).insertSocialMember(anyString(), anyString(), eq("Member@Example.com"),
                eq("member@example.com"), eq("Zoop User"), eq("google"), eq(NOW));
        ArgumentCaptor<String> memberId = ArgumentCaptor.forClass(String.class);
        verify(terms).recordAgreement(memberId.capture(), eq("terms-1"), eq("v3"), eq(true), eq(NOW));
        verify(identities).insert(anyString(), eq(memberId.getValue()), eq("google"),
                eq("provider-subject-42"), eq(NOW));
        verify(sessions).issue(eq(memberId.getValue()), eq("old-session"), eq("req-social-signup"));
    }

    @Test
    void existingEmailConsumesPendingButCreatesNoAccountOrSession() {
        when(pending.consumeConsent(HASH, NOW)).thenReturn(Optional.of(pendingRow()));
        when(agreements.validate(any(), eq(NOW))).thenReturn(List.of());
        when(credentials.displayName(null)).thenReturn("회원");
        when(members.findByEmailKey("member@example.com")).thenReturn(Optional.of(
                new com.zoop.auth.repository.MemberAuthRow("existing", "active", "hash")));

        var result = service.signup(new SocialSignupRequest(null, List.of()), COOKIE, null, "req-1");

        assertTrue(result.isEmpty());
        verify(pending).consumeConsent(HASH, NOW);
        verify(members, never()).insertSocialMember(anyString(), anyString(), anyString(), anyString(),
                anyString(), anyString(), any(Instant.class));
        verify(terms, never()).recordAgreement(anyString(), anyString(), anyString(), any(Boolean.class), any(Instant.class));
        verify(identities, never()).insert(anyString(), anyString(), anyString(), anyString(), any(Instant.class));
        verify(sessions, never()).issue(anyString(), any(), anyString());
    }

    @Test
    void unverifiedOrMalformedPendingCannotCreateMember() {
        when(pending.consumeConsent(HASH, NOW)).thenReturn(Optional.of(new OAuthPendingRow("flow-id", HASH,
                "{\"schemaVersion\":1,\"phase\":\"consent_pending\",\"provider\":\"google\",\"stateHash\":\"%s\",\"providerSubject\":\"subject\",\"email\":\"member@example.com\",\"emailVerified\":false}".formatted("a".repeat(64)),
                NOW, NOW.plusSeconds(600))));

        var error = org.junit.jupiter.api.Assertions.assertThrows(
                com.zoop.common.exception.CustomException.class,
                () -> service.signup(new SocialSignupRequest(null, List.of()), COOKIE, null, "req-1"));

        assertEquals(com.zoop.common.exception.ErrorCode.ACCESS_DENIED, error.getErrorCode());
        verify(members, never()).findByEmailKey(anyString());
        verify(sessions, never()).issue(anyString(), any(), anyString());
    }

    private OAuthPendingRow pendingRow() {
        return new OAuthPendingRow("flow-id", HASH,
                "{\"schemaVersion\":1,\"phase\":\"consent_pending\",\"provider\":\"google\",\"stateHash\":\"%s\",\"providerSubject\":\"provider-subject-42\",\"email\":\" Member@Example.com \",\"emailVerified\":true}".formatted("a".repeat(64)),
                NOW, NOW.plusSeconds(600));
    }

    private static String hash(String value) {
        try { return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256")
                .digest(value.getBytes(StandardCharsets.US_ASCII))); }
        catch (Exception exception) { throw new AssertionError(exception); }
    }
}
