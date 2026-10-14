package com.zoop.auth.service;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.HexFormat;
import java.util.List;

import com.zoop.auth.repository.AuthRateEventStore;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

/** Shared, exact rolling-window limits. Each call commits independently of the auth transaction. */
@Service
public class AuthRateLimiter {
    private static final Duration SIGNUP_WINDOW = Duration.ofHours(1);
    private static final Duration LOGIN_WINDOW = Duration.ofMinutes(15);
    private final AuthRateEventStore store;
    private final Clock clock;

    public AuthRateLimiter(AuthRateEventStore store, Clock clock) {
        this.store = store;
        this.clock = clock;
    }

    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public void recordSignupAttempt(String clientIp, String emailKey) {
        Key ip = key("signup_ip", clientIp);
        Key email = key("signup_email", emailKey);
        Instant now = clock.instant();
        lockBoth(ip, email);
        long retry = Math.max(retryAfter(ip, SIGNUP_WINDOW, 10, now),
                retryAfter(email, SIGNUP_WINDOW, 5, now));
        if (retry > 0) {
            throw new RateLimitedException(retry);
        }
        store.add(ip.scope(), ip.hash(), now);
        store.add(email.scope(), email.hash(), now);
    }

    /** Count malformed-email requests against the IP budget before validation rejects them. */
    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public void recordSignupIpAttempt(String clientIp) {
        recordIpOnly("signup_ip", clientIp, SIGNUP_WINDOW, 10);
    }

    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public void recordLoginAttempt(String clientIp, String emailKey) {
        Key ip = key("login_ip", clientIp);
        Key emailFailures = key("login_email_failure", emailKey);
        Instant now = clock.instant();
        lockBoth(ip, emailFailures);
        long retry = Math.max(retryAfter(ip, LOGIN_WINDOW, 100, now),
                retryAfter(emailFailures, LOGIN_WINDOW, 20, now));
        if (retry > 0) {
            throw new RateLimitedException(retry);
        }
        store.add(ip.scope(), ip.hash(), now);
    }

    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public void recordLoginIpAttempt(String clientIp) {
        recordIpOnly("login_ip", clientIp, LOGIN_WINDOW, 100);
    }

    /** Call only for INVALID_CREDENTIALS, including unknown accounts. */
    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public void recordLoginFailure(String emailKey) {
        Key email = key("login_email_failure", emailKey);
        Instant now = clock.instant();
        store.lock(email.scope(), email.hash());
        long retry = retryAfter(email, LOGIN_WINDOW, 20, now);
        if (retry > 0) {
            throw new RateLimitedException(retry);
        }
        store.add(email.scope(), email.hash(), now);
    }

    /** Joins the successful login transaction so a failed issuance cannot clear failures. */
    @Transactional
    public void clearLoginFailures(String emailKey) {
        Key email = key("login_email_failure", emailKey);
        store.lock(email.scope(), email.hash());
        store.clear(email.scope(), email.hash());
    }

    private void lockBoth(Key first, Key second) {
        if (first.scope().compareTo(second.scope()) <= 0) {
            store.lock(first.scope(), first.hash());
            store.lock(second.scope(), second.hash());
        } else {
            store.lock(second.scope(), second.hash());
            store.lock(first.scope(), first.hash());
        }
    }

    private void recordIpOnly(String scope, String clientIp, Duration window, int limit) {
        Key ip = key(scope, clientIp);
        Instant now = clock.instant();
        store.lock(ip.scope(), ip.hash());
        long retry = retryAfter(ip, window, limit, now);
        if (retry > 0) {
            throw new RateLimitedException(retry);
        }
        store.add(ip.scope(), ip.hash(), now);
    }

    private long retryAfter(Key key, Duration window, int limit, Instant now) {
        List<Instant> recent = store.recent(key.scope(), key.hash(), now.minus(window), limit);
        if (recent.size() < limit) {
            return 0;
        }
        long remainingMillis = Duration.between(now, recent.get(0).plus(window)).toMillis();
        return Math.max(1, (remainingMillis + 999) / 1000);
    }

    private static Key key(String scope, String subject) {
        if (subject == null || subject.isBlank()) {
            throw new IllegalArgumentException("Rate limit subject required");
        }
        try {
            byte[] digest = MessageDigest.getInstance("SHA-256")
                    .digest((scope + "\0" + subject).getBytes(StandardCharsets.UTF_8));
            return new Key(scope, HexFormat.of().formatHex(digest));
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException("Rate key hashing unavailable", exception);
        }
    }

    private record Key(String scope, String hash) {
    }
}
