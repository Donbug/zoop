package com.zoop.auth.service;

import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import com.zoop.auth.repository.AuthRateEventStore;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

class AuthRateLimiterTest {
    private static final Instant START = Instant.parse("2026-10-14T00:00:00Z");
    private final MemoryEvents events = new MemoryEvents();

    @Test
    void signupLimitsBothIpAndEmailAndUsesRollingHour() {
        var limit = at(START);
        for (int i = 0; i < 5; i++) {
            limit.recordSignupIpAttempt("192.0.2.1");
            limit.recordSignupEmailAttempt("a@example.com");
        }
        var emailLimit = assertThrows(RateLimitedException.class,
                () -> limit.recordSignupEmailAttempt("a@example.com"));
        assertEquals(3600, emailLimit.retryAfterSeconds());
        for (int i = 0; i < 5; i++) {
            limit.recordSignupIpAttempt("192.0.2.1");
            limit.recordSignupEmailAttempt("b" + i + "@example.com");
        }
        assertEquals(3600, assertThrows(RateLimitedException.class,
                () -> limit.recordSignupIpAttempt("192.0.2.1")).retryAfterSeconds());
        at(START.plusSeconds(3600)).recordSignupIpAttempt("192.0.2.1");
        at(START.plusSeconds(3600)).recordSignupEmailAttempt("a@example.com");
    }

    @Test
    void loginCountsEveryIpAttemptOnlyEmailFailuresAndSuccessClearsThem() {
        var limit = at(START);
        for (int i = 0; i < 20; i++) {
            limit.recordLoginIpAttempt("192.0.2.1");
            limit.checkLoginEmailFailures("a@example.com");
            limit.recordLoginFailure("a@example.com");
        }
        assertEquals(900, assertThrows(RateLimitedException.class,
                () -> limit.checkLoginEmailFailures("a@example.com")).retryAfterSeconds());
        limit.clearLoginFailures("a@example.com");
        limit.checkLoginEmailFailures("a@example.com");
        for (int i = 20; i < 100; i++) {
            limit.recordLoginIpAttempt("192.0.2.1");
        }
        assertEquals(900, assertThrows(RateLimitedException.class,
                () -> limit.recordLoginIpAttempt("192.0.2.1")).retryAfterSeconds());
        at(START.plusSeconds(900)).recordLoginIpAttempt("192.0.2.1");
    }

    @Test
    void malformedEmailAttemptsStillConsumeIpBudget() {
        var limit = at(START);
        for (int i = 0; i < 10; i++) {
            limit.recordSignupIpAttempt("192.0.2.3");
        }
        assertThrows(RateLimitedException.class,
                () -> limit.recordSignupIpAttempt("192.0.2.3"));
        for (int i = 0; i < 100; i++) {
            limit.recordLoginIpAttempt("192.0.2.4");
        }
        assertThrows(RateLimitedException.class,
                () -> limit.recordLoginIpAttempt("192.0.2.4"));
    }

    private AuthRateLimiter at(Instant instant) {
        return new AuthRateLimiter(events, Clock.fixed(instant, ZoneOffset.UTC));
    }

    private static class MemoryEvents implements AuthRateEventStore {
        private final Map<String, List<Instant>> rows = new HashMap<>();

        @Override
        public void lock(String scope, String subjectHash) {
        }

        @Override
        public List<Instant> recent(String scope, String subjectHash, Instant after, int limit) {
            return rows.getOrDefault(scope + subjectHash, List.of()).stream()
                    .filter(time -> time.isAfter(after)).sorted().limit(limit).toList();
        }

        @Override
        public void add(String scope, String subjectHash, Instant at) {
            rows.computeIfAbsent(scope + subjectHash, ignored -> new ArrayList<>()).add(at);
        }

        @Override
        public void clear(String scope, String subjectHash) {
            rows.remove(scope + subjectHash);
        }

        @Override
        public void purgeBefore(Instant before) {
            rows.values().forEach(times -> times.removeIf(time -> !time.isAfter(before)));
        }
    }
}
