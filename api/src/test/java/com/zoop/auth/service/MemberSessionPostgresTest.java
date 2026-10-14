package com.zoop.auth.service;

import java.sql.Timestamp;
import java.time.Instant;
import java.util.UUID;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.annotation.Transactional;

import static org.junit.jupiter.api.Assertions.*;

@SpringBootTest(properties = {
        "ZOOP_AUTH_CSRF_ACTIVE_KEY_ID=test",
        "ZOOP_AUTH_CSRF_KEYS=test=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
})
@EnabledIfEnvironmentVariable(named = "DB_URL", matches = "jdbc:postgresql:.*")
class MemberSessionPostgresTest {
    @Autowired
    MemberSessionService service;

    @Autowired
    JdbcTemplate jdbc;

    @Test
    @Transactional
    void issuedSessionPersistsOnlyHashAndReadsThroughRealSchema() {
        String memberId = "session-test-" + UUID.randomUUID();
        Instant now = Instant.now();
        jdbc.update("""
                INSERT INTO members (id, analytics_key, email, email_key, display_name,
                                     password_hash, signup_method, status, mode, investor,
                                     completed, tutorial_completed, settings_version,
                                     created_at, updated_at, blocked_at)
                VALUES (?, ?, ?, ?, ?, ?, 'email', 'active', NULL, NULL,
                        false, false, 1, ?, ?, NULL)
                """, memberId, memberId, memberId + "@example.com",
                memberId + "@example.com", "Session Test", "test-hash",
                Timestamp.from(now), Timestamp.from(now));

        var issued = service.issue(memberId, null, "postgres-test");
        String stored = jdbc.queryForObject("SELECT token_hash FROM member_sessions WHERE member_id = ?",
                String.class, memberId);
        assertEquals(MemberSessionService.hashToken(issued.token()), stored);
        assertNotEquals(issued.token(), stored);
        assertTrue(service.lookup(issued.token(), "postgres-read").response().authenticated());

        var replacement = service.issue(memberId, issued.token(), "postgres-reissue");
        assertTrue(service.lookup(issued.token(), "postgres-revoked").clearCookie());
        assertTrue(service.lookup(replacement.token(), "postgres-replacement").response().authenticated());

        jdbc.update("UPDATE member_sessions SET expires_at = ? WHERE token_hash = ?",
                Timestamp.from(now.minusSeconds(1)), MemberSessionService.hashToken(replacement.token()));
        assertTrue(service.lookup(replacement.token(), "postgres-expired").clearCookie());
    }
}
