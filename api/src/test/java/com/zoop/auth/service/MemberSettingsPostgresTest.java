package com.zoop.auth.service;

import java.sql.Timestamp;
import java.time.Instant;
import java.util.UUID;

import com.zoop.auth.service.MemberSessionService.MemberPrincipal;
import com.zoop.common.json.StrictJson;
import org.junit.jupiter.api.Tag;
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
@Tag("auth-postgres")
class MemberSettingsPostgresTest {
    @Autowired JdbcTemplate jdbc;
    @Autowired MemberSettingsService service;

    @Test
    @Transactional
    void readsAndAtomicallyPersistsMemberSetupAndWatchlist() {
        String memberId = "settings-test-" + UUID.randomUUID();
        Instant now = Instant.now();
        jdbc.update("""
                INSERT INTO members (id, analytics_key, email, email_key, display_name,
                                     password_hash, signup_method, status, mode, investor,
                                     completed, tutorial_completed, settings_version,
                                     created_at, updated_at, blocked_at)
                VALUES (?, ?, ?, ?, 'Settings Test', 'test-hash', 'email', 'active', NULL, NULL,
                        false, false, 1, ?, ?, NULL)
                """, memberId, memberId, memberId + "@example.com", memberId + "@example.com",
                Timestamp.from(now), Timestamp.from(now));
        var member = new MemberPrincipal(memberId, "settings-session");

        var initial = service.get(member, "settings-get");
        assertNull(initial.investor());
        assertTrue(initial.watchlistIds().isEmpty());
        assertFalse(initial.completed());

        var saved = service.update(member, StrictJson.parseObject("""
                {"version":1,"investor":false,"mode":"watchlist",
                 "watchlistIds":["NASDAQ:NVDA"],"completed":true}
                """.getBytes(java.nio.charset.StandardCharsets.UTF_8)).node(), "settings-put");

        assertFalse(saved.investor());
        assertEquals("watchlist", saved.mode());
        assertEquals(java.util.List.of("NASDAQ:NVDA"), saved.watchlistIds());
        assertTrue(saved.completed());
        assertFalse(saved.tutorialCompleted());
        assertEquals(2, saved.version());
        assertEquals(1L, jdbc.queryForObject("SELECT count(*) FROM member_watchlist WHERE member_id = ?",
                Long.class, memberId));

        var replay = service.update(member, StrictJson.parseObject("""
                {"version":1,"investor":false,"mode":"watchlist",
                 "watchlistIds":["NASDAQ:NVDA"],"completed":true}
                """.getBytes(java.nio.charset.StandardCharsets.UTF_8)).node(), "settings-retry");
        assertEquals(2, replay.version());
    }
}
