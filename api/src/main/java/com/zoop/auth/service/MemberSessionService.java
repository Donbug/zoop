package com.zoop.auth.service;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.security.SecureRandom;
import java.time.Clock;
import java.time.Instant;
import java.util.Base64;
import java.util.HexFormat;

import com.zoop.auth.dto.SessionResponse;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.auth.repository.MemberSessionRepository;
import com.zoop.auth.repository.MemberSessionRow;
import org.springframework.http.ResponseCookie;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class MemberSessionService {
    private static final SecureRandom RANDOM = new SecureRandom();
    private final MemberSessionRepository repository;
    private final CsrfKeyRing keyRing;
    private final Clock clock;

    public MemberSessionService(MemberSessionRepository repository, CsrfKeyRing keyRing, Clock clock) {
        this.repository = repository;
        this.keyRing = keyRing;
        this.clock = clock;
    }

    /** Called after member creation/authentication; the caller sets the cookie after transaction commit. */
    @Transactional
    public IssuedSession issue(String memberId, String previousCookieToken, String requestId) {
        Instant now = clock.instant();
        String token = randomToken();
        String hash = hashToken(token);
        String id = randomToken();
        repository.insertMemberSession(id, memberId, hash, keyRing.activeKeyId(),
                now, now.plus(SessionCookie.LIFETIME));
        if (validToken(previousCookieToken)) {
            repository.revokeMemberSession(hashToken(previousCookieToken), memberId, now);
        }
        MemberSessionRow row = repository.findByTokenHash(hash).orElseThrow();
        return new IssuedSession(token, memberResponse(row, now, requestId));
    }

    @Transactional(readOnly = true)
    public SessionLookup lookup(String cookieToken, String requestId) {
        Instant now = clock.instant();
        if (cookieToken == null) {
            return new SessionLookup(SessionResponse.anonymous(now, requestId), false);
        }
        if (!validToken(cookieToken)) {
            return new SessionLookup(SessionResponse.anonymous(now, requestId), true);
        }
        var row = repository.findByTokenHash(hashToken(cookieToken));
        if (row.isEmpty() || !isUsable(row.get(), now)
                || keyRing.derive(row.get().csrfKeyId(), row.get().kind(),
                        row.get().id(), row.get().csrfVersion()).isEmpty()) {
            return new SessionLookup(SessionResponse.anonymous(now, requestId), true);
        }
        return new SessionLookup(memberResponse(row.get(), now, requestId), false);
    }

    /** Require an active member session and its exact session-bound CSRF token for a cookie write. */
    @Transactional(readOnly = true)
    public void verifyCsrf(String cookieToken, String suppliedCsrf) {
        if (!validToken(cookieToken) || suppliedCsrf == null
                || !suppliedCsrf.matches("[A-Za-z0-9_-]{43}")) {
            throw new CustomException(ErrorCode.ACCESS_DENIED);
        }
        Instant now = clock.instant();
        var row = repository.findByTokenHash(hashToken(cookieToken));
        if (row.isEmpty() || !isUsable(row.get(), now)) {
            throw new CustomException(ErrorCode.ACCESS_DENIED);
        }
        var expected = keyRing.derive(row.get().csrfKeyId(), row.get().kind(),
                row.get().id(), row.get().csrfVersion());
        if (expected.isEmpty() || !MessageDigest.isEqual(
                expected.get().getBytes(StandardCharsets.US_ASCII),
                suppliedCsrf.getBytes(StandardCharsets.US_ASCII))) {
            throw new CustomException(ErrorCode.ACCESS_DENIED);
        }
    }

    private boolean isUsable(MemberSessionRow row, Instant now) {
        return "member".equals(row.kind()) && "active".equals(row.memberStatus())
                && row.revokedAt() == null && row.expiresAt().isAfter(now)
                && !row.createdAt().isAfter(now) && row.memberId() != null;
    }

    private SessionResponse memberResponse(MemberSessionRow row, Instant now, String requestId) {
        String csrf = keyRing.derive(row.csrfKeyId(), row.kind(), row.id(), row.csrfVersion())
                .orElseThrow(() -> new IllegalStateException("CSRF key unavailable"));
        return new SessionResponse(true, "member",
                new SessionResponse.User(row.memberId(), row.email(), row.displayName()),
                new SessionResponse.Setup(row.completed(), row.tutorialCompleted()),
                SessionResponse.metadata(now, requestId), csrf, row.expiresAt());
    }

    private static boolean validToken(String token) {
        return token != null && token.matches("[A-Za-z0-9_-]{43}");
    }

    private static String randomToken() {
        byte[] bytes = new byte[32];
        RANDOM.nextBytes(bytes);
        return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
    }

    static String hashToken(String token) {
        try {
            byte[] digest = MessageDigest.getInstance("SHA-256")
                    .digest(token.getBytes(StandardCharsets.US_ASCII));
            return HexFormat.of().formatHex(digest);
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException("Session hashing unavailable", exception);
        }
    }

    public record IssuedSession(String token, SessionResponse response) {
        public ResponseCookie cookie() {
            return SessionCookie.issue(token);
        }

        @Override
        public String toString() {
            return "IssuedSession[token=<redacted>]";
        }
    }

    public record SessionLookup(SessionResponse response, boolean clearCookie) {
    }
}
