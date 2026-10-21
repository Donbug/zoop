package com.zoop.admin.audit;

import java.sql.Timestamp;
import java.time.Instant;
import java.util.UUID;

import com.zoop.admin.auth.repository.AdminAuditRepository;
import com.zoop.admin.auth.provision.AdminProvisioningWriter;
import com.zoop.admin.auth.service.AdminPrincipal;
import com.zoop.admin.auth.service.AdminSessionService;
import com.zoop.admin.members.dto.MemberStatusRequest;
import com.zoop.admin.members.service.AdminMemberStatusService;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.dao.DataAccessResourceFailureException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.bean.override.mockito.MockitoBean;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.doThrow;

@SpringBootTest(properties = {
        "ZOOP_AUTH_CSRF_ACTIVE_KEY_ID=test",
        "ZOOP_AUTH_CSRF_KEYS=test=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
})
@EnabledIfEnvironmentVariable(named = "DB_URL", matches = "jdbc:postgresql:.*")
@Tag("auth-postgres")
class AdminAuditPostgresTest {
    @Autowired JdbcTemplate jdbc;
    @Autowired AdminAuditQueryService queries;
    @Autowired AdminMemberStatusService statuses;
    @Autowired AdminSessionService sessions;
    @Autowired AdminProvisioningWriter provisioning;
    @MockitoBean AdminAuditRepository audit;

    @Test
    void keysetPaginationAndSearchDoNotExposeHiddenReasons() {
        String suffix = UUID.randomUUID().toString();
        String targetType = "audit-test-" + suffix;
        Instant at = Instant.now().minusSeconds(30);
        long first = insert("member.block", targetType, "target-1", "policy review",
                "{\"beforeStatus\":\"active\",\"afterStatus\":\"blocked\","
                        + "\"beforeRevision\":1,\"afterRevision\":2,\"password\":\"secret\"}", at);
        long second = insert("member.block", targetType, "target-2", "policy review",
                "{}", at);
        insert("member.block", targetType, "target-3", "private@example.com", "{}", at.minusSeconds(1));

        var page1 = queries.list("admin-1", "member.block", null, targetType, null, null, 1);
        assertEquals(second, page1.items().get(0).id());
        assertNotNull(page1.nextCursor());
        var page2 = queries.list("admin-1", "member.block", null, targetType,
                null, page1.nextCursor(), null);
        assertEquals(first, page2.items().get(0).id());
        assertEquals(4, page2.items().get(0).detail().size());
        var page3 = queries.list("admin-1", "member.block", null, targetType,
                null, page2.nextCursor(), null);
        assertNull(page3.items().get(0).reason());
        assertNull(page3.nextCursor());

        assertTrue(queries.list("admin-1", null, null, targetType,
                "private@example.com", null, null).items().isEmpty());
        assertEquals(2, queries.list("admin-1", null, null, targetType,
                "policy review", null, null).items().size());
        assertEquals(1, queries.list("admin-1", null, null, targetType,
                "target-3", null, null).items().size());
        assertTrue(queries.list("admin-1", null, null, targetType,
                "policy%", null, null).items().isEmpty());
    }

    @Test
    void failedAuditWriteRollsBackMemberAndIdempotencyChanges() {
        String suffix = UUID.randomUUID().toString();
        String memberId = "audit-rollback-" + suffix;
        String email = "audit-rollback-" + suffix + "@example.com";
        Instant created = Instant.now().minusSeconds(120);
        jdbc.update("""
                INSERT INTO members (id, analytics_key, email, email_key, display_name,
                                     password_hash, signup_method, status, mode, investor,
                                     completed, tutorial_completed, settings_version,
                                     created_at, updated_at, blocked_at)
                VALUES (?, ?, ?, ?, 'Synthetic Member', 'test-hash', 'email', 'active', NULL, NULL,
                        false, false, 1, ?, ?, NULL)
                """, memberId, "analytics-" + memberId, email, email,
                Timestamp.from(created), Timestamp.from(created));
        doThrow(new DataAccessResourceFailureException("audit unavailable"))
                .when(audit).recordMemberStatusAction(anyString(), anyString(), anyString(),
                        anyString(), anyString(), anyString(), anyString(), anyLong(), anyLong(),
                        anyString(), any());

        var principal = new AdminPrincipal("admin-" + suffix, "operator@example.com",
                "Operator", "admin", "session-" + suffix);
        var failure = assertThrows(CustomException.class, () -> statuses.block(memberId,
                new MemberStatusRequest(1, "policy review"), "key-" + suffix,
                principal, "request-" + suffix));
        assertEquals(ErrorCode.SOURCE_UNAVAILABLE, failure.getErrorCode());
        assertEquals("active", jdbc.queryForObject("SELECT status FROM members WHERE id = ?",
                String.class, memberId));
        assertEquals(1L, jdbc.queryForObject("SELECT status_revision FROM members WHERE id = ?",
                Long.class, memberId));
        assertEquals(0, jdbc.queryForObject("SELECT count(*) FROM idempotency_records WHERE principal_id = ?",
                Integer.class, principal.adminId()));
    }

    @Test
    void failedAuditWriteRollsBackAdminSession() {
        String suffix = UUID.randomUUID().toString();
        String adminId = "audit-session-" + suffix;
        String email = "audit-session-" + suffix + "@example.com";
        jdbc.update("""
                INSERT INTO admins (id, email, email_key, display_name, password_hash,
                                    role, status, created_at)
                VALUES (?, ?, ?, 'Synthetic Admin', 'test-hash', 'admin', 'active', ?)
                """, adminId, email, email, Timestamp.from(Instant.now().minusSeconds(60)));

        assertThrows(DataAccessResourceFailureException.class,
                () -> sessions.issue(adminId, email, "Synthetic Admin", null,
                        "request-" + suffix,
                        (id, actorEmail, action, sessionId, requestId, at) -> {
                            throw new DataAccessResourceFailureException("audit unavailable");
                        }));
        assertEquals(0, jdbc.queryForObject("SELECT count(*) FROM admin_sessions WHERE admin_id = ?",
                Integer.class, adminId));
    }

    @Test
    void failedAuditWriteRollsBackAdminProvisioning() {
        String suffix = UUID.randomUUID().toString();
        String adminId = "audit-provision-" + suffix;
        String email = "audit-provision-" + suffix + "@example.com";
        doThrow(new DataAccessResourceFailureException("audit unavailable"))
                .when(audit).recordProvisioning(eq(adminId), eq("succeeded"), isNull(),
                        anyString(), any());

        assertThrows(DataAccessResourceFailureException.class,
                () -> provisioning.create(adminId, email, email, "Synthetic Admin", "test-hash",
                        "request-" + suffix, Instant.now()));
        assertEquals(0, jdbc.queryForObject("SELECT count(*) FROM admins WHERE id = ?",
                Integer.class, adminId));
    }

    private long insert(String action, String targetType, String targetId,
            String reason, String detail, Instant at) {
        return jdbc.queryForObject("""
                INSERT INTO audit_logs (actor_kind, actor_id, action, target_type, target_id,
                                        outcome, reason, request_id, detail, occurred_at)
                VALUES ('system', 'audit-fixture', ?, ?, ?, 'succeeded', ?, ?, CAST(? AS jsonb), ?)
                RETURNING id
                """, Long.class, action, targetType, targetId, reason,
                "request-" + UUID.randomUUID(), detail, Timestamp.from(at));
    }
}
