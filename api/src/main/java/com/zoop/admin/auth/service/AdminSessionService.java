package com.zoop.admin.auth.service;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.security.SecureRandom;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.Base64;
import java.util.HexFormat;
import java.util.Optional;

import com.zoop.admin.auth.dto.AdminInfo;
import com.zoop.admin.auth.dto.AdminSessionResponse;
import com.zoop.admin.auth.repository.AdminAuthRepository;
import com.zoop.admin.auth.repository.AdminSessionRow;
import com.zoop.auth.service.CsrfKeyRing;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.ResponseCookie;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class AdminSessionService {
    private static final SecureRandom RANDOM = new SecureRandom();
    private final AdminAuthRepository repository;
    private final CsrfKeyRing keyRing;
    private final Clock clock;
    private final Duration idleTimeout;
    private final Duration absoluteTimeout;
    private final boolean secureCookie;

    @Autowired
    public AdminSessionService(AdminAuthRepository repository, CsrfKeyRing keyRing, Clock clock,
            @Value("${zoop.admin.session.idle-timeout:30m}") Duration idleTimeout,
            @Value("${zoop.admin.session.absolute-timeout:8h}") Duration absoluteTimeout,
            @Value("${zoop.auth.session-cookie-secure:true}") boolean secureCookie) {
        this.repository = repository;
        this.keyRing = keyRing;
        this.clock = clock;
        if (idleTimeout.isZero() || idleTimeout.isNegative()
                || absoluteTimeout.isZero() || absoluteTimeout.isNegative()
                || idleTimeout.compareTo(absoluteTimeout) > 0) {
            throw new IllegalArgumentException("Invalid administrator session timeout configuration");
        }
        this.idleTimeout = idleTimeout;
        this.absoluteTimeout = absoluteTimeout;
        this.secureCookie = secureCookie;
    }

    @Transactional
    public IssuedSession issue(String adminId, String email, String displayName,
            String previousToken, String requestId, AdminSessionAudit audit) {
        Instant now = clock.instant();
        String token = randomToken();
        String id = randomToken();
        Instant expiresAt = now.plus(absoluteTimeout);
        Instant idleExpiresAt = min(now.plus(idleTimeout), expiresAt);
        if (!repository.insertSession(id, adminId, hashToken(token), keyRing.activeKeyId(),
                now, idleExpiresAt, expiresAt)) {
            throw new CustomException(ErrorCode.ACCESS_DENIED);
        }
        if (validToken(previousToken)) {
            repository.findSessionByTokenHash(hashToken(previousToken))
                    .filter(row -> row.revokedAt() == null)
                    .ifPresent(row -> repository.revokeSession(row.tokenHash(), row.adminId(), now));
        }
        var row = repository.findSessionByTokenHash(hashToken(token)).orElseThrow();
        String csrf = keyRing.derive(row.csrfKeyId(), "admin", row.id(), row.csrfVersion())
                .orElseThrow(() -> new IllegalStateException("CSRF key unavailable"));
        audit.record(adminId, email, "auth.login", row.id(), requestId, now);
        return new IssuedSession(token, response(row, csrf), secureCookie, absoluteTimeout);
    }

    @Transactional(readOnly = true)
    public SessionLookup lookup(String token, String requestId) {
        if (token == null) return new SessionLookup(anonymous(), false);
        if (!validToken(token)) return new SessionLookup(anonymous(), true);
        Optional<AdminSessionRow> found = repository.findSessionByTokenHash(hashToken(token));
        if (found.isEmpty()) return new SessionLookup(anonymous(), true);
        AdminSessionRow row = found.get();
        String reason = unavailableReason(row, clock.instant());
        if (reason != null) {
            boolean expired = "idle".equals(reason) || "absolute".equals(reason);
            return new SessionLookup(AdminSessionResponse.anonymous(
                    expired, expired ? reason : null,
                    idleTimeoutSeconds(), absoluteTimeoutSeconds()), true);
        }
        var csrf = keyRing.derive(row.csrfKeyId(), "admin", row.id(), row.csrfVersion());
        if (csrf.isEmpty()) return new SessionLookup(anonymous(), true);
        return new SessionLookup(response(row, csrf.get()), false);
    }

    @Transactional
    public AdminPrincipal requireAdmin(String token) {
        if (!validToken(token)) throw new CustomException(ErrorCode.AUTH_REQUIRED);
        Instant now = clock.instant();
        var found = repository.findSessionByTokenHash(hashToken(token));
        if (found.isEmpty()) throw new CustomException(ErrorCode.AUTH_REQUIRED);
        AdminSessionRow row = found.get();
        if (unavailableReason(row, now) != null) throw new CustomException(ErrorCode.AUTH_REQUIRED);
        if (keyRing.derive(row.csrfKeyId(), "admin", row.id(), row.csrfVersion()).isEmpty()) {
            throw new CustomException(ErrorCode.AUTH_REQUIRED);
        }
        if (!repository.touchSession(row.id(), now, min(now.plus(idleTimeout), row.expiresAt()))) {
            throw new CustomException(ErrorCode.AUTH_REQUIRED);
        }
        return new AdminPrincipal(row.adminId(), row.email(), row.displayName(), row.role(), row.id());
    }

    @Transactional(readOnly = true)
    public boolean isActiveSession(String token) {
        if (!validToken(token)) return false;
        return repository.findSessionByTokenHash(hashToken(token))
                .filter(row -> unavailableReason(row, clock.instant()) == null
                        && keyRing.derive(row.csrfKeyId(), "admin", row.id(), row.csrfVersion()).isPresent())
                .isPresent();
    }

    @Transactional
    public void verifyCsrf(String token, String suppliedCsrf) {
        if (suppliedCsrf == null || suppliedCsrf.length() > 128 || !validToken(token)) {
            throw new CustomException(ErrorCode.ACCESS_DENIED);
        }
        var row = repository.findSessionByTokenHash(hashToken(token))
                .filter(value -> unavailableReason(value, clock.instant()) == null)
                .orElseThrow(() -> new CustomException(ErrorCode.ACCESS_DENIED));
        var expected = keyRing.derive(row.csrfKeyId(), "admin", row.id(), row.csrfVersion());
        if (expected.isEmpty() || !MessageDigest.isEqual(
                expected.get().getBytes(StandardCharsets.US_ASCII),
                suppliedCsrf.getBytes(StandardCharsets.US_ASCII))) {
            throw new CustomException(ErrorCode.ACCESS_DENIED);
        }
    }

    @Transactional
    public boolean logout(String token, String requestId, AdminSessionAudit audit) {
        if (!validToken(token)) return false;
        Instant now = clock.instant();
        var found = repository.findSessionByTokenHash(hashToken(token));
        if (found.isEmpty()) return false;
        AdminSessionRow row = found.get();
        if (unavailableReason(row, now) != null) return false;
        boolean revoked = repository.revokeSession(row.tokenHash(), row.adminId(), now);
        if (revoked) audit.record(row.adminId(), row.email(), "auth.logout", row.id(), requestId, now);
        return revoked;
    }

    public ResponseCookie clearCookie() {
        return AdminSessionCookie.clear(secureCookie);
    }

    public int idleTimeoutSeconds() { return Math.toIntExact(idleTimeout.toSeconds()); }
    public int absoluteTimeoutSeconds() { return Math.toIntExact(absoluteTimeout.toSeconds()); }

    private AdminSessionResponse anonymous() {
        return AdminSessionResponse.anonymous(false, null, idleTimeoutSeconds(), absoluteTimeoutSeconds());
    }

    private AdminSessionResponse response(AdminSessionRow row, String csrf) {
        return new AdminSessionResponse(true, false, null,
                new AdminInfo(row.adminId(), row.email(), row.displayName(), row.role()),
                row.expiresAt(), row.idleExpiresAt(), idleTimeoutSeconds(), absoluteTimeoutSeconds(), csrf);
    }

    private static String unavailableReason(AdminSessionRow row, Instant now) {
        if (row.revokedAt() != null || !"active".equals(row.adminStatus()) || !"admin".equals(row.role())) {
            return "revoked";
        }
        if (!row.expiresAt().isAfter(now)) return "absolute";
        if (!row.idleExpiresAt().isAfter(now)) return "idle";
        if (row.createdAt().isAfter(now)) return "revoked";
        return null;
    }

    private static Instant min(Instant first, Instant second) {
        return first.isBefore(second) ? first : second;
    }

    private static boolean validToken(String token) {
        return token != null && token.matches("[A-Za-z0-9_-]{43}");
    }

    private static String randomToken() {
        byte[] bytes = new byte[32];
        RANDOM.nextBytes(bytes);
        return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
    }

    private static String hashToken(String token) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256")
                    .digest(token.getBytes(StandardCharsets.US_ASCII)));
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException("Session hashing unavailable", exception);
        }
    }

    public record IssuedSession(String token, AdminSessionResponse response,
            boolean secureCookie, Duration lifetime) {
        public ResponseCookie cookie() {
            return AdminSessionCookie.issue(token, lifetime, secureCookie);
        }

        @Override
        public String toString() { return "IssuedAdminSession[token=<redacted>]"; }
    }

    public record SessionLookup(AdminSessionResponse response, boolean clearCookie) { }

    @FunctionalInterface
    public interface AdminSessionAudit {
        void record(String adminId, String email, String action, String sessionId,
                String requestId, Instant at);
    }
}
