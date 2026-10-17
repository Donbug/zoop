package com.zoop.admin.auth;

import java.sql.Timestamp;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.UUID;

import com.zoop.admin.auth.provision.AdminProvisioningException;
import com.zoop.admin.auth.provision.AdminProvisioningService;
import com.zoop.admin.auth.repository.AdminAuthRepository;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.annotation.Transactional;

import static org.junit.jupiter.api.Assertions.*;

@SpringBootTest(properties = {
        "ZOOP_AUTH_CSRF_ACTIVE_KEY_ID=test",
        "ZOOP_AUTH_CSRF_KEYS=test=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
})
@EnabledIfEnvironmentVariable(named = "DB_URL", matches = "jdbc:postgresql:.*")
@Tag("auth-postgres")
class AdminAuthMigrationPostgresTest {
    @Autowired
    AdminAuthRepository repository;

    @Autowired
    AdminProvisioningService provisioning;

    @Autowired
    JdbcTemplate jdbc;

    @Test
    @Transactional
    void repositoryReadsCurrentAuthorityAndPersistsOnlyTokenHash() {
        String suffix = UUID.randomUUID().toString();
        String adminId = "admin-" + suffix;
        String email = suffix + "@example.com";
        Instant createdAt = Instant.now().truncatedTo(ChronoUnit.MILLIS);
        insertAdmin(adminId, email, "active", createdAt);

        var account = repository.findAccountByEmailKey(email).orElseThrow();
        assertEquals(adminId, account.id());
        assertEquals("admin", account.role());
        assertTrue(account.passwordHash().startsWith("{argon2id-v1}"));

        String tokenHash = "a".repeat(64);
        Instant idleExpiresAt = createdAt.plus(30, ChronoUnit.MINUTES);
        Instant expiresAt = createdAt.plus(8, ChronoUnit.HOURS);
        assertTrue(repository.insertSession("session-" + suffix, adminId, tokenHash, "test",
                createdAt, idleExpiresAt, expiresAt));

        var session = repository.findSessionByTokenHash(tokenHash).orElseThrow();
        assertEquals(adminId, session.adminId());
        assertEquals("active", session.adminStatus());
        assertEquals(idleExpiresAt, session.idleExpiresAt());
        assertEquals(expiresAt, session.expiresAt());
        assertFalse(jdbc.queryForObject(
                "SELECT EXISTS (SELECT 1 FROM admin_sessions WHERE token_hash = ?)",
                Boolean.class, "raw-cookie-token"));

        Instant seenAt = createdAt.plus(5, ChronoUnit.MINUTES);
        Instant extendedIdle = createdAt.plus(35, ChronoUnit.MINUTES);
        assertTrue(repository.touchSession(session.id(), seenAt, extendedIdle));
        assertEquals(extendedIdle, repository.findSessionByTokenHash(tokenHash).orElseThrow().idleExpiresAt());

        jdbc.update("UPDATE admins SET status = 'blocked' WHERE id = ?", adminId);
        assertEquals("blocked", repository.findSessionByTokenHash(tokenHash).orElseThrow().adminStatus());
        assertFalse(repository.touchSession(session.id(), seenAt.plusSeconds(1), extendedIdle.plusSeconds(1)));
        assertFalse(repository.insertSession("blocked-session-" + suffix, adminId,
                "b".repeat(64), "test", createdAt, idleExpiresAt, expiresAt));
        assertTrue(repository.revokeSession(tokenHash, adminId, seenAt.plusSeconds(2)));
        assertNotNull(repository.findSessionByTokenHash(tokenHash).orElseThrow().revokedAt());
        assertFalse(repository.revokeSession(tokenHash, adminId, seenAt.plusSeconds(3)));
    }

    @Test
    @Transactional
    void schemaRejectsUnknownAuthority() {
        String suffix = UUID.randomUUID().toString();
        Instant now = Instant.now().truncatedTo(ChronoUnit.MILLIS);

        assertThrows(DataIntegrityViolationException.class, () -> jdbc.update("""
                INSERT INTO admins
                  (id, email, email_key, display_name, password_hash, external_subject,
                   role, status, created_at)
                VALUES (?, ?, ?, 'Unknown Role', 'hash', NULL, 'operator', 'active', ?)
                """, "unknown-role-" + suffix, suffix + "@example.com",
                suffix + "@example.com", Timestamp.from(now)));
    }

    @Test
    @Transactional
    void schemaRejectsInvalidSessionLifecycle() {
        String suffix = UUID.randomUUID().toString();
        Instant now = Instant.now().truncatedTo(ChronoUnit.MILLIS);

        String adminId = "invalid-session-admin-" + suffix;
        insertAdmin(adminId, "invalid-" + suffix + "@example.com", "active", now);
        assertThrows(DataIntegrityViolationException.class, () -> jdbc.update("""
                INSERT INTO admin_sessions
                  (id, admin_id, token_hash, csrf_key_id, csrf_version, created_at,
                   last_seen_at, idle_expires_at, expires_at, revoked_at)
                VALUES (?, ?, ?, 'test', 1, ?, ?, ?, ?, NULL)
                """, "invalid-session-" + suffix, adminId, "c".repeat(64),
                Timestamp.from(now), Timestamp.from(now),
                Timestamp.from(now.plus(9, ChronoUnit.HOURS)),
                Timestamp.from(now.plus(8, ChronoUnit.HOURS))));
    }

    @Test
    @Transactional
    void auditSchemaSupportsKnownAndAnonymousAdminAuthEvents() {
        String suffix = UUID.randomUUID().toString();
        Instant now = Instant.now().truncatedTo(ChronoUnit.MILLIS);
        String adminId = "audit-admin-" + suffix;
        insertAdmin(adminId, "audit-" + suffix + "@example.com", "active", now);

        jdbc.update("""
                INSERT INTO audit_logs
                  (actor_kind, admin_id, actor_id, actor_email_snapshot, action,
                   target_type, target_id, outcome, purpose, reason, request_id, detail, occurred_at)
                VALUES ('admin', ?, ?, ?, 'auth.login', 'admin_session', ?,
                        'succeeded', NULL, NULL, ?, '{}'::jsonb, ?)
                """, adminId, adminId, "audit-" + suffix + "@example.com",
                "session-" + suffix, "request-" + suffix, Timestamp.from(now));
        jdbc.update("""
                INSERT INTO audit_logs
                  (actor_kind, admin_id, actor_id, actor_email_snapshot, action,
                   target_type, target_id, outcome, purpose, reason, request_id, detail, occurred_at)
                VALUES ('anonymous', NULL, 'unknown', NULL, 'auth.login_failed',
                        'admin_session', NULL, 'denied', NULL, 'invalid_credentials',
                        ?, '{}'::jsonb, ?)
                """, "request-failed-" + suffix, Timestamp.from(now));

        assertEquals(2, jdbc.queryForObject(
                "SELECT count(*) FROM audit_logs WHERE request_id IN (?, ?)", Integer.class,
                "request-" + suffix, "request-failed-" + suffix));
    }

    @Test
    @Transactional
    void operatorProvisioningCreatesHashedAdminAndAuditsSuccessAndDuplicate() {
        String suffix = UUID.randomUUID().toString();
        String email = "provision-" + suffix + "@example.com";

        String adminId = provisioning.provision(email, "Provisioned Admin",
                "Safe admin password 2026", "provision-success-" + suffix);
        var account = repository.findAccountByEmailKey(email).orElseThrow();
        assertEquals(adminId, account.id());
        assertEquals("active", account.status());
        assertEquals("admin", account.role());
        assertTrue(account.passwordHash().startsWith("{argon2id-v1}$argon2id$"));
        assertFalse(account.passwordHash().contains("Safe admin password 2026"));

        assertThrows(AdminProvisioningException.class,
                () -> provisioning.provision(email, "Other Admin",
                        "Another safe password 2026", "provision-denied-" + suffix));
        var outcomes = jdbc.queryForList("""
                SELECT outcome FROM audit_logs
                WHERE request_id IN (?, ?) ORDER BY request_id
                """, String.class, "provision-denied-" + suffix, "provision-success-" + suffix);
        assertEquals(java.util.List.of("denied", "succeeded"), outcomes);
        assertEquals(1, jdbc.queryForObject(
                "SELECT count(*) FROM admins WHERE email_key = ?", Integer.class, email));
    }

    private void insertAdmin(String id, String email, String status, Instant createdAt) {
        jdbc.update("""
                INSERT INTO admins
                  (id, email, email_key, display_name, password_hash, external_subject,
                   role, status, created_at)
                VALUES (?, ?, ?, 'Admin Test', '{argon2id-v1}synthetic-test-hash', NULL,
                        'admin', ?, ?)
                """, id, email, email, status, Timestamp.from(createdAt));
    }
}
