package com.zoop.auth.service;

import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.Base64;
import java.util.HashMap;
import java.util.Map;
import java.util.Optional;

import com.zoop.auth.repository.MemberSessionRepository;
import com.zoop.auth.repository.MemberSessionRow;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

class MemberSessionServiceTest {
    private static final Instant NOW = Instant.parse("2026-10-14T00:00:00Z");
    private static final String KEY = Base64.getUrlEncoder().withoutPadding()
            .encodeToString(new byte[32]);
    private final MemoryRepository repository = new MemoryRepository();
    private final CsrfKeyRing keys = new CsrfKeyRing("current", "current=" + KEY);
    private final MemberSessionService service = new MemberSessionService(repository, keys,
            Clock.fixed(NOW, ZoneOffset.UTC));

    @Test
    void issueStoresOnlyHashAndDerivesStableSessionBoundCsrf() {
        var issued = service.issue("member-1", null, "req-1");
        assertEquals(43, issued.token().length());
        assertTrue(issued.cookie().toString().contains("SameSite=Lax"));
        assertFalse(repository.rows.containsKey(issued.token()));
        assertEquals(MemberSessionService.hashToken(issued.token()), repository.rows.keySet().iterator().next());
        assertEquals(NOW.plus(SessionCookie.LIFETIME), issued.response().expiresAt());
        var lookup = service.lookup(issued.token(), "req-2");
        assertTrue(lookup.response().authenticated());
        assertEquals(issued.response().csrfToken(), lookup.response().csrfToken());
        assertEquals("req-2", lookup.response().metadata().requestId());
        assertEquals("member-1", lookup.response().user().id());
        assertFalse(lookup.clearCookie());
    }

    @Test
    void previousSameMemberSessionIsRevokedButOtherMemberSessionSurvives() {
        var first = service.issue("member-1", null, "one");
        var other = service.issue("member-2", null, "other");
        var second = service.issue("member-1", first.token(), "two");
        assertNotEquals(first.token(), second.token());
        assertTrue(service.lookup(first.token(), "one").clearCookie());
        assertTrue(service.lookup(second.token(), "two").response().authenticated());
        assertTrue(service.lookup(other.token(), "other").response().authenticated());
    }

    @Test
    void expiredRevokedAndMissingKeySessionsBecomeAnonymous() {
        var issued = service.issue("member-1", null, "req");
        String hash = MemberSessionService.hashToken(issued.token());
        var row = repository.rows.get(hash);
        repository.rows.put(hash, copy(row, NOW, null, row.csrfKeyId()));
        assertAnonymous(issued.token());
        repository.rows.put(hash, copy(row, row.expiresAt(), NOW, row.csrfKeyId()));
        assertAnonymous(issued.token());
        repository.rows.put(hash, copy(row, row.expiresAt(), null, "retired"));
        assertAnonymous(issued.token());
        assertFalse(service.lookup(null, "req").clearCookie());
        assertAnonymous("invalid");
    }

    @Test
    void csrfUsesExactErdMessageAndVersion() {
        String expected = keys.derive("current", "member", "session_1", 1).orElseThrow();
        assertEquals("pv2h4vOSOpHyi3N-DQl3lx-mkNxhC7hZamyFvLYpIG4", expected);
        assertEquals(expected, keys.derive("current", "member", "session_1", 1).orElseThrow());
        assertNotEquals(expected, keys.derive("current", "member", "session_1", 2).orElseThrow());
        assertNotEquals(expected, keys.derive("current", "member", "session_2", 1).orElseThrow());
        var rotated = new CsrfKeyRing("next", "current=" + KEY + ",next=" + KEY);
        assertEquals(expected, rotated.derive("current", "member", "session_1", 1).orElseThrow());
        assertThrows(IllegalArgumentException.class, () -> new CsrfKeyRing("current", "current=bad"));
        assertThrows(IllegalArgumentException.class, () -> new CsrfKeyRing("missing", "current=" + KEY));
    }

    @Test
    void csrfVerificationRejectsWrongSessionVersionAndRevokedSession() {
        var first = service.issue("member-1", null, "one");
        var second = service.issue("member-2", null, "two");
        service.verifyCsrf(first.token(), first.response().csrfToken());
        assertCsrfDenied(first.token(), second.response().csrfToken());
        assertCsrfDenied(first.token(), null);
        assertCsrfDenied("invalid", first.response().csrfToken());

        String hash = MemberSessionService.hashToken(first.token());
        var row = repository.rows.get(hash);
        repository.rows.put(hash, new MemberSessionRow(row.id(), row.memberId(), row.kind(),
                row.tokenHash(), row.csrfKeyId(), 2, row.createdAt(), row.expiresAt(),
                row.revokedAt(), row.memberStatus(), row.email(), row.displayName(),
                row.completed(), row.tutorialCompleted()));
        assertCsrfDenied(first.token(), first.response().csrfToken());
        repository.rows.put(hash, copy(row, row.expiresAt(), NOW, row.csrfKeyId()));
        assertCsrfDenied(first.token(), first.response().csrfToken());
        repository.rows.put(hash, copy(row, NOW, null, row.csrfKeyId()));
        assertCsrfDenied(first.token(), first.response().csrfToken());
    }

    @Test
    void currentBindingReturnsExactActiveSessionAndRejectsMissingOrExpiredBindings() {
        var issued = service.issue("member-1", null, "req");
        var binding = service.currentBinding(issued.token());
        assertEquals("member-1", binding.memberId());
        assertEquals(repository.rows.get(MemberSessionService.hashToken(issued.token())).id(), binding.sessionId());
        assertTrue(service.currentBindingIfActive("invalid").isEmpty());
        var error = assertThrows(CustomException.class, () -> service.currentBinding("invalid"));
        assertEquals(ErrorCode.ACCESS_DENIED, error.getErrorCode());
    }

    private void assertCsrfDenied(String token, String csrf) {
        var error = assertThrows(CustomException.class, () -> service.verifyCsrf(token, csrf));
        assertEquals(ErrorCode.ACCESS_DENIED, error.getErrorCode());
    }

    private void assertAnonymous(String token) {
        var result = service.lookup(token, "req");
        assertFalse(result.response().authenticated());
        assertEquals("anonymous", result.response().kind());
        assertNull(result.response().csrfToken());
        assertNull(result.response().expiresAt());
        assertTrue(result.clearCookie());
    }

    private static MemberSessionRow copy(MemberSessionRow row, Instant expiry, Instant revoked, String keyId) {
        return new MemberSessionRow(row.id(), row.memberId(), row.kind(), row.tokenHash(), keyId,
                row.csrfVersion(), row.createdAt(), expiry, revoked, row.memberStatus(),
                row.email(), row.displayName(), row.completed(), row.tutorialCompleted());
    }

    private static class MemoryRepository implements MemberSessionRepository {
        private final Map<String, MemberSessionRow> rows = new HashMap<>();

        @Override
        public Optional<MemberSessionRow> findByTokenHash(String hash) {
            return Optional.ofNullable(rows.get(hash));
        }

        @Override
        public void insertMemberSession(String id, String memberId, String hash,
                String keyId, Instant created, Instant expiry) {
            rows.put(hash, new MemberSessionRow(id, memberId, "member", hash, keyId, 1,
                    created, expiry, null, "active", "a@example.com", "User", false, false));
        }

        @Override
        public void revokeMemberSession(String hash, String memberId, Instant at) {
            var row = rows.get(hash);
            if (row != null && memberId.equals(row.memberId()) && row.revokedAt() == null && row.expiresAt().isAfter(at)) {
                rows.put(hash, copy(row, row.expiresAt(), at, row.csrfKeyId()));
            }
        }
    }
}
