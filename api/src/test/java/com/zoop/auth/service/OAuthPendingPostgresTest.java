package com.zoop.auth.service;

import java.sql.Timestamp;
import java.time.Instant;
import java.util.UUID;

import com.zoop.auth.repository.JdbcOAuthPendingRepository;
import com.zoop.auth.repository.JdbcMemberAuthRepository;
import com.zoop.auth.repository.JdbcSocialIdentityRepository;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.jdbc.core.JdbcTemplate;

import static org.junit.jupiter.api.Assertions.*;

@SpringBootTest(properties = {
        "ZOOP_AUTH_CSRF_ACTIVE_KEY_ID=test",
        "ZOOP_AUTH_CSRF_KEYS=test=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
})
@EnabledIfEnvironmentVariable(named = "DB_URL", matches = "jdbc:postgresql:.*")
@Tag("auth-postgres")
class OAuthPendingPostgresTest {
    private static final String HASH_A = "a".repeat(64);
    private static final String HASH_B = "b".repeat(64);

    @Autowired JdbcOAuthPendingRepository pending;
    @Autowired JdbcSocialIdentityRepository identities;
    @Autowired JdbcMemberAuthRepository members;
    @Autowired JdbcTemplate jdbc;

    @Test
    void socialProviderSubjectIsUniqueAndLookupReturnsTheLinkedMember() {
        String memberId = insertMember("social-identity");
        String identityId = "identity-" + UUID.randomUUID();
        try {
            identities.insert(identityId, memberId, "google", "google-subject-1", Instant.now());

            var found = identities.findByProviderSubject("google", "google-subject-1");
            assertTrue(found.isPresent());
            assertEquals(memberId, found.orElseThrow().memberId());
            assertEquals("google", found.orElseThrow().provider());
            assertThrows(DataIntegrityViolationException.class,
                    () -> identities.insert("identity-duplicate-" + UUID.randomUUID(), memberId,
                            "google", "google-subject-1", Instant.now()));
        } finally {
            jdbc.update("DELETE FROM social_identities WHERE member_id = ?", memberId);
            jdbc.update("DELETE FROM members WHERE id = ?", memberId);
        }
    }

    @Test
    void socialMemberIsCreatedWithoutPasswordAndEmailConflictIsReportedAsNoInsert() {
        String memberId = "social-signup-" + UUID.randomUUID();
        String email = memberId + "@example.invalid";
        try {
            assertTrue(members.insertSocialMember(memberId, "analytics-" + memberId,
                    email, email, "Synthetic", "google", Instant.now()));
            assertFalse(members.insertSocialMember("duplicate-" + memberId, "analytics-duplicate",
                    email, email, "Duplicate", "google", Instant.now()));
            var row = members.findById(memberId).orElseThrow();
            assertEquals("active", row.status());
            assertNull(row.passwordHash());
            assertEquals(email, members.findLinkTargetById(memberId).orElseThrow().emailKey());
            assertEquals("google", jdbc.queryForObject(
                    "SELECT signup_method FROM members WHERE id = ?", String.class, memberId));
        } finally {
            jdbc.update("DELETE FROM members WHERE id = ?", memberId);
        }
    }

    @Test
    void callbackClaimBindsBrowserStateAndProviderAndCanOnlyBeClaimedOnce() {
        Instant now = Instant.now();
        String id = "oauth-" + UUID.randomUUID();
        pending.insert(id, HASH_A, authorizationFlow("google", HASH_B), now, now.plusSeconds(300));
        try {
            assertTrue(pending.claimAuthorization(HASH_A, HASH_B, "kakao", now).isEmpty());
            assertTrue(pending.claimAuthorization(HASH_A, "c".repeat(64), "google", now).isEmpty());
            assertTrue(pending.claimAuthorization("d".repeat(64), HASH_B, "google", now).isEmpty());

            var claimed = pending.claimAuthorization(HASH_A, HASH_B, "google", now).orElseThrow();
            assertTrue(claimed.authFlow().contains("callback_processing"));
            assertTrue(pending.claimAuthorization(HASH_A, HASH_B, "google", now).isEmpty());
            assertTrue(pending.consumeClaimedCallback(id, HASH_A, now));
            assertFalse(pending.consumeClaimedCallback(id, HASH_A, now));
        } finally {
            jdbc.update("DELETE FROM member_sessions WHERE id = ?", id);
        }
    }

    @Test
    void signupConsentRotatesCookieAndIsConsumedOnce() {
        Instant now = Instant.now();
        String id = "oauth-" + UUID.randomUUID();
        pending.insert(id, HASH_A, authorizationFlow("kakao", HASH_B), now, now.plusSeconds(300));
        try {
            assertTrue(pending.claimAuthorization(HASH_A, HASH_B, "kakao", now).isPresent());
            var verified = pending.completeVerification(id, HASH_A,
                    identityFlow("kakao", HASH_B), now).orElseThrow();
            assertTrue(verified.authFlow().contains("identity_verified"));
            var consent = pending.rotateToConsent(id, HASH_A, HASH_B,
                    consentFlow("kakao", HASH_B), now, now.plusSeconds(600)).orElseThrow();
            assertEquals(HASH_B, consent.tokenHash());
            assertTrue(pending.consumeConsent(HASH_A, now).isEmpty());
            assertTrue(pending.consumeConsent(HASH_B, now).isPresent());
            assertTrue(pending.consumeConsent(HASH_B, now).isEmpty());
        } finally {
            jdbc.update("DELETE FROM member_sessions WHERE id = ?", id);
        }
    }

    @Test
    void expiredPendingCannotBeClaimedAndCanBePurged() {
        Instant now = Instant.now();
        String id = "oauth-" + UUID.randomUUID();
        pending.insert(id, HASH_A, authorizationFlow("google", HASH_B),
                now.minusSeconds(600), now.minusSeconds(1));

        assertTrue(pending.claimAuthorization(HASH_A, HASH_B, "google", now).isEmpty());
        assertEquals(1, pending.purgeExpired(now));
        assertEquals(0, pending.purgeExpired(now));
    }

    private String insertMember(String prefix) {
        String memberId = prefix + "-" + UUID.randomUUID();
        Instant now = Instant.now();
        jdbc.update("""
                INSERT INTO members (id, analytics_key, email, email_key, display_name,
                                     password_hash, signup_method, status, mode, investor,
                                     completed, tutorial_completed, settings_version,
                                     created_at, updated_at, blocked_at)
                VALUES (?, ?, ?, ?, 'Synthetic', NULL, 'google', 'active', NULL, NULL,
                        false, false, 1, ?, ?, NULL)
                """, memberId, "analytics-" + memberId, memberId + "@example.invalid",
                memberId + "@example.invalid", Timestamp.from(now), Timestamp.from(now));
        return memberId;
    }

    private static String authorizationFlow(String provider, String stateHash) {
        return """
                {"schemaVersion":1,"phase":"authorization_pending","provider":"%s","stateHash":"%s"}
                """.formatted(provider, stateHash).strip();
    }

    private static String consentFlow(String provider, String stateHash) {
        return """
                {"schemaVersion":1,"phase":"consent_pending","provider":"%s","stateHash":"%s","subject":"synthetic-subject","email":"synthetic@example.invalid"}
                """.formatted(provider, stateHash).strip();
    }

    private static String identityFlow(String provider, String stateHash) {
        return """
                {"schemaVersion":1,"phase":"identity_verified","provider":"%s","stateHash":"%s","providerSubject":"synthetic-subject","email":"synthetic@example.invalid","emailVerified":true}
                """.formatted(provider, stateHash).strip();
    }
}
