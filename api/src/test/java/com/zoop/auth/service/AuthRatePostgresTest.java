package com.zoop.auth.service;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.HexFormat;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;

import static org.junit.jupiter.api.Assertions.*;

@SpringBootTest(properties = {
        "ZOOP_AUTH_CSRF_ACTIVE_KEY_ID=test",
        "ZOOP_AUTH_CSRF_KEYS=test=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
})
@EnabledIfEnvironmentVariable(named = "DB_URL", matches = "jdbc:postgresql:.*")
class AuthRatePostgresTest {
    @Autowired
    AuthRateLimiter limiter;

    @Autowired
    JdbcTemplate jdbc;

    @Test
    void concurrentSignupCannotPassIpBoundary() throws Exception {
        String suffix = UUID.randomUUID().toString();
        String hex = suffix.replace("-", "");
        String ip = "2001:db8::" + hex.substring(0, 4) + ":" + hex.substring(4, 8)
                + ":" + hex.substring(8, 12) + ":" + hex.substring(12, 16);
        try {
            int accepted = race(11, index -> limiter.recordSignupIpAttempt(ip));
            assertEquals(10, accepted);
        } finally {
            clear("signup_ip", ip);
        }
    }

    @Test
    void concurrentLoginFailuresCannotPassEmailBoundary() throws Exception {
        String email = "failure-" + UUID.randomUUID() + "@example.com";
        try {
            assertEquals(20, race(21, index -> limiter.recordLoginFailure(email)));
        } finally {
            clear("login_email_failure", email);
        }
    }

    private int race(int count, Attempt attempt) throws Exception {
        var start = new CountDownLatch(1);
        try (var executor = Executors.newFixedThreadPool(count)) {
            List<Future<Boolean>> futures = new ArrayList<>();
            for (int i = 0; i < count; i++) {
                int index = i;
                futures.add(executor.submit(() -> {
                    start.await();
                    try {
                        attempt.run(index);
                        return true;
                    } catch (RateLimitedException exception) {
                        assertTrue(exception.retryAfterSeconds() > 0);
                        return false;
                    }
                }));
            }
            start.countDown();
            int accepted = 0;
            for (Future<Boolean> future : futures) {
                if (future.get()) {
                    accepted++;
                }
            }
            return accepted;
        }
    }

    private void clear(String scope, String subject) throws Exception {
        byte[] digest = MessageDigest.getInstance("SHA-256")
                .digest((scope + "\0" + subject).getBytes(StandardCharsets.UTF_8));
        jdbc.update("DELETE FROM auth_rate_events WHERE scope = ? AND subject_hash = ?",
                scope, HexFormat.of().formatHex(digest));
    }

    @FunctionalInterface
    private interface Attempt {
        void run(int index);
    }
}
