package com.zoop.auth.service;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.security.SecureRandom;
import java.time.Clock;
import java.time.Instant;
import java.util.Base64;
import java.util.HexFormat;
import java.util.Optional;

import com.zoop.auth.dto.SessionResponse;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.auth.repository.MemberSessionRepository;
import com.zoop.auth.repository.MemberSessionRow;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.ResponseCookie;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class MemberSessionService {
    private static final SecureRandom RANDOM = new SecureRandom();
    private final MemberSessionRepository repository;
    private final CsrfKeyRing keyRing;
    private final Clock clock;
    private final boolean sessionCookieSecure;

    public MemberSessionService(MemberSessionRepository repository, CsrfKeyRing keyRing, Clock clock) {
        this(repository, keyRing, clock, true);
    }

    @Autowired
    public MemberSessionService(MemberSessionRepository repository, CsrfKeyRing keyRing, Clock clock,
            @Value("${zoop.auth.session-cookie-secure:true}") boolean sessionCookieSecure) {
        this.repository = repository;
        this.keyRing = keyRing;
        this.clock = clock;
        this.sessionCookieSecure = sessionCookieSecure;
    }

    /** Called after member creation/authentication; the caller sets the cookie after transaction commit. */
    @Transactional
    public IssuedSession issue(String memberId, String previousCookieToken, String requestId) {
        Instant now = clock.instant();
        String token = randomToken();
        String hash = hashToken(token);
        String id = randomToken();
        boolean inserted = repository.insertMemberSession(id, memberId, hash, keyRing.activeKeyId(),
                now, now.plus(SessionCookie.LIFETIME));
        if (!inserted) throw new CustomException(ErrorCode.MEMBER_BLOCKED);
        if (validToken(previousCookieToken)) {
            repository.revokeMemberSession(hashToken(previousCookieToken), memberId, now);
        }
        MemberSessionRow row = repository.findByTokenHash(hash).orElseThrow();
        return new IssuedSession(token, memberResponse(row, now, requestId), sessionCookieSecure);
    }

    /** Creates an unowned guest session; a prior guest token is rotated without revoking member sessions. */
    @Transactional
    public IssuedSession issueGuest(String previousCookieToken, String requestId) {
        Instant now = clock.instant();
        String token = randomToken();
        String hash = hashToken(token);
        repository.insertGuestSession(randomToken(), randomToken(), hash, keyRing.activeKeyId(),
                now, now.plus(SessionCookie.LIFETIME));
        if (validToken(previousCookieToken)) {
            repository.revokeGuestSession(hashToken(previousCookieToken), now);
        }
        MemberSessionRow row = repository.findByTokenHash(hash).orElseThrow();
        return new IssuedSession(token, guestResponse(row, now, requestId), sessionCookieSecure);
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
        SessionResponse response = "guest".equals(row.get().kind())
                ? guestResponse(row.get(), now, requestId)
                : memberResponse(row.get(), now, requestId);
        return new SessionLookup(response, false);
    }

    /** True only when this cookie identifies a currently usable member or guest session. */
    @Transactional(readOnly = true)
    public boolean isActiveSession(String cookieToken) {
        if (!validToken(cookieToken)) return false;
        Instant now = clock.instant();
        var row = repository.findByTokenHash(hashToken(cookieToken));
        return row.filter(value -> isUsable(value, now)
                && keyRing.derive(value.csrfKeyId(), value.kind(), value.id(), value.csrfVersion()).isPresent())
                .isPresent();
    }

    /** Revokes only the current member session; guest sessions are outside member logout scope. */
    @Transactional
    public void logoutMember(String cookieToken) {
        if (!validToken(cookieToken)) return;
        Instant now = clock.instant();
        String tokenHash = hashToken(cookieToken);
        var row = repository.findByTokenHash(tokenHash);
        if (row.isPresent() && "member".equals(row.get().kind()) && isUsable(row.get(), now)
                && keyRing.derive(row.get().csrfKeyId(), row.get().kind(),
                        row.get().id(), row.get().csrfVersion()).isPresent()) {
            repository.revokeMemberSession(tokenHash, row.get().memberId(), now);
        }
    }

    /** Returns the active member and exact session binding for a privileged OAuth link flow. */
    @Transactional(readOnly = true)
    public SessionBinding currentBinding(String cookieToken) {
        return currentBindingIfActive(cookieToken).orElseThrow(() -> new CustomException(ErrorCode.ACCESS_DENIED));
    }

    @Transactional(readOnly = true)
    public Optional<SessionBinding> currentBindingIfActive(String cookieToken) {
        if (!validToken(cookieToken)) return Optional.empty();
        Instant now = clock.instant();
        var row = repository.findByTokenHash(hashToken(cookieToken));
        if (row.isEmpty() || !"member".equals(row.get().kind()) || !isUsable(row.get(), now)
                || keyRing.derive(row.get().csrfKeyId(), row.get().kind(),
                        row.get().id(), row.get().csrfVersion()).isEmpty()) {
            return Optional.empty();
        }
        return Optional.of(new SessionBinding(row.get().memberId(), row.get().id()));
    }

    /** Resolves the authenticated member for a member-only API. Never trusts an ID from request data. */
    @Transactional(readOnly = true)
    public MemberPrincipal requireMember(String cookieToken) {
        if (!validToken(cookieToken)) {
            throw new CustomException(ErrorCode.AUTH_REQUIRED);
        }
        Instant now = clock.instant();
        var row = repository.findByTokenHash(hashToken(cookieToken));
        if (row.isEmpty() || !isUsable(row.get(), now)
                || keyRing.derive(row.get().csrfKeyId(), row.get().kind(),
                        row.get().id(), row.get().csrfVersion()).isEmpty()) {
            throw new CustomException(ErrorCode.AUTH_REQUIRED);
        }
        if (!"member".equals(row.get().kind())) {
            throw new CustomException(ErrorCode.MEMBER_REQUIRED);
        }
        return new MemberPrincipal(row.get().memberId(), row.get().id());
    }

    /** Call after loading a personal resource; ownership must match the authenticated member. */
    public void requireOwner(MemberPrincipal principal, String resourceMemberId) {
        if (principal == null || resourceMemberId == null
                || !MessageDigest.isEqual(principal.memberId().getBytes(StandardCharsets.UTF_8),
                        resourceMemberId.getBytes(StandardCharsets.UTF_8))) {
            throw new CustomException(ErrorCode.ACCESS_DENIED);
        }
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
        boolean ownerValid = "member".equals(row.kind())
                ? row.memberId() != null && "active".equals(row.memberStatus())
                : "guest".equals(row.kind()) && row.memberId() == null;
        return ownerValid && row.revokedAt() == null && row.expiresAt().isAfter(now)
                && !row.createdAt().isAfter(now);
    }

    private SessionResponse memberResponse(MemberSessionRow row, Instant now, String requestId) {
        String csrf = keyRing.derive(row.csrfKeyId(), row.kind(), row.id(), row.csrfVersion())
                .orElseThrow(() -> new IllegalStateException("CSRF key unavailable"));
        return new SessionResponse(true, "member",
                new SessionResponse.User(row.memberId(), row.email(), row.displayName()),
                new SessionResponse.Setup(row.completed(), row.tutorialCompleted()),
                SessionResponse.metadata(now, requestId), csrf, row.expiresAt());
    }

    private SessionResponse guestResponse(MemberSessionRow row, Instant now, String requestId) {
        String csrf = keyRing.derive(row.csrfKeyId(), row.kind(), row.id(), row.csrfVersion())
                .orElseThrow(() -> new IllegalStateException("CSRF key unavailable"));
        return new SessionResponse(true, "guest", null,
                new SessionResponse.Setup(false, false),
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

    public record IssuedSession(String token, SessionResponse response, boolean secureCookie) {
        public IssuedSession(String token, SessionResponse response) {
            this(token, response, true);
        }

        public ResponseCookie cookie() {
            return SessionCookie.issue(token, secureCookie);
        }

        @Override
        public String toString() {
            return "IssuedSession[token=<redacted>]";
        }
    }

    public record SessionLookup(SessionResponse response, boolean clearCookie) {
    }

    public ResponseCookie clearCookie() {
        return SessionCookie.clear(sessionCookieSecure);
    }

    public record SessionBinding(String memberId, String sessionId) {
    }

    public record MemberPrincipal(String memberId, String sessionId) {
    }
}
