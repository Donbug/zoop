package com.zoop.admin.members.service;

import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.List;

import com.zoop.admin.auth.repository.AdminAuditRepository;
import com.zoop.admin.auth.service.AdminPrincipal;
import com.zoop.admin.members.dto.MemberAdminResponse.MemberActivity;
import com.zoop.admin.members.dto.MemberAdminResponse.MemberDetail;
import com.zoop.admin.members.dto.MemberAdminResponse.MemberRow;
import com.zoop.admin.members.dto.MemberAdminResponse.MemberStatusResult;
import com.zoop.admin.members.dto.MemberStatusRequest;
import com.zoop.admin.members.repository.AdminMemberRepository;
import com.zoop.admin.members.repository.AdminMemberRepository.IdempotencyRow;
import com.zoop.admin.members.repository.AdminMemberRepository.MemberStatusRow;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.common.response.Metadata;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import tools.jackson.databind.json.JsonMapper;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class AdminMemberStatusServiceTest {
    private static final Instant NOW = Instant.parse("2026-10-20T00:00:00Z");
    private static final AdminPrincipal ADMIN = new AdminPrincipal(
            "admin-1", "admin@example.com", "Admin", "admin", "session-1");

    @Mock AdminMemberRepository repository;
    @Mock AdminAuditRepository audit;
    @Mock AdminMemberQueryService queries;

    @Test
    void blocksAtExpectedRevisionAndRevokesSessionsAtomically() {
        when(repository.claimIdempotency(anyString(), eq("admin-1"), anyString(), eq("key-1"),
                anyString(), eq(NOW))).thenReturn(true);
        when(repository.findIdempotencyForUpdate(eq("admin-1"), anyString(), eq("key-1")))
                .thenAnswer(invocation -> java.util.Optional.of(new IdempotencyRow(
                        "idem-1", hash("member-1", "blocked", 1, "abuse"), "processing", null, null)));
        when(repository.findStatusForUpdate("member-1"))
                .thenReturn(java.util.Optional.of(new MemberStatusRow("member-1", "active", 1)));
        when(repository.updateStatus("member-1", 1, "blocked", NOW, NOW)).thenReturn(true);
        when(queries.detailAt("member-1", NOW, "request-1")).thenReturn(detail("blocked", 2));

        var result = service().block("member-1", new MemberStatusRequest(1, "abuse"),
                "key-1", ADMIN, "request-1");

        assertTrue(result.changed());
        verify(repository).revokeActiveSessions("member-1", NOW);
        verify(audit).recordMemberStatusAction("admin-1", "admin@example.com", "member.block",
                "member-1", "abuse", "active", "blocked", 1, 2, "request-1", NOW);
        verify(repository).completeIdempotency(eq("idem-1"), eq(200), anyString());
    }

    @Test
    void staleRevisionDoesNotChangeMember() {
        when(repository.claimIdempotency(anyString(), eq("admin-1"), anyString(), eq("key-2"),
                anyString(), eq(NOW))).thenReturn(true);
        when(repository.findIdempotencyForUpdate(eq("admin-1"), anyString(), eq("key-2")))
                .thenReturn(java.util.Optional.of(new IdempotencyRow(
                        "idem-2", hash("member-1", "blocked", 1, "stale"), "processing", null, null)));
        when(repository.findStatusForUpdate("member-1"))
                .thenReturn(java.util.Optional.of(new MemberStatusRow("member-1", "active", 2)));

        CustomException failure = assertThrows(CustomException.class, () -> service().block(
                "member-1", new MemberStatusRequest(1, "stale"), "key-2", ADMIN, "request-2"));

        assertEquals(ErrorCode.REVISION_CONFLICT, failure.getErrorCode());
        verify(repository, never()).updateStatus(anyString(), anyLong(), anyString(), any(), any());
        verify(audit, never()).recordMemberStatusAction(anyString(), anyString(), anyString(),
                anyString(), anyString(), anyString(), anyString(), anyLong(), anyLong(), anyString(), any());
    }

    @Test
    void rejectsCredentialOrPersonalDataInAuditReasonBeforeChangingMember() {
        var failure = assertThrows(CustomException.class, () -> service().block("member-1",
                new MemberStatusRequest(1, "Contact person@example.com with password"),
                "key", ADMIN, "request"));
        assertEquals(ErrorCode.INVALID_REQUEST, failure.getErrorCode());
        verifyNoInteractions(repository, audit);
    }

    @Test
    void auditWriteFailureNeverCompletesTheMemberChangeResult() {
        when(repository.claimIdempotency(anyString(), eq("admin-1"), anyString(), eq("key-4"),
                anyString(), eq(NOW))).thenReturn(true);
        when(repository.findIdempotencyForUpdate(eq("admin-1"), anyString(), eq("key-4")))
                .thenReturn(java.util.Optional.of(new IdempotencyRow(
                        "idem-4", hash("member-1", "blocked", 1, "abuse"), "processing", null, null)));
        when(repository.findStatusForUpdate("member-1"))
                .thenReturn(java.util.Optional.of(new MemberStatusRow("member-1", "active", 1)));
        when(repository.updateStatus("member-1", 1, "blocked", NOW, NOW)).thenReturn(true);
        org.mockito.Mockito.doThrow(new org.springframework.dao.DataAccessResourceFailureException("audit unavailable"))
                .when(audit).recordMemberStatusAction(anyString(), anyString(), anyString(),
                        anyString(), anyString(), anyString(), anyString(), anyLong(), anyLong(),
                        anyString(), any());

        var failure = assertThrows(CustomException.class, () -> service().block("member-1",
                new MemberStatusRequest(1, "abuse"), "key-4", ADMIN, "request-4"));

        assertEquals(ErrorCode.SOURCE_UNAVAILABLE, failure.getErrorCode());
        verify(repository, never()).completeIdempotency(anyString(), anyInt(), anyString());
    }

    @Test
    void aFreshNoOpIsChangedFalseButStillGetsAReplayableResult() {
        when(repository.claimIdempotency(anyString(), eq("admin-1"), anyString(), eq("key-3"),
                anyString(), eq(NOW))).thenReturn(true);
        when(repository.findIdempotencyForUpdate(eq("admin-1"), anyString(), eq("key-3")))
                .thenReturn(java.util.Optional.of(new IdempotencyRow(
                        "idem-3", hash("member-1", "active", 3, "confirm"), "processing", null, null)));
        when(repository.findStatusForUpdate("member-1"))
                .thenReturn(java.util.Optional.of(new MemberStatusRow("member-1", "active", 3)));
        when(queries.detailAt("member-1", NOW, "request-3")).thenReturn(detail("active", 3));

        var result = service().unblock("member-1", new MemberStatusRequest(3, "confirm"),
                "key-3", ADMIN, "request-3");

        assertFalse(result.changed());
        verify(repository, never()).updateStatus(anyString(), anyLong(), anyString(), any(), any());
        verify(repository).completeIdempotency(eq("idem-3"), eq(200), anyString());
    }

    private AdminMemberStatusService service() {
        return new AdminMemberStatusService(repository, audit, queries, JsonMapper.builder().build(),
                Clock.fixed(NOW, ZoneOffset.UTC));
    }

    private static String hash(String memberId, String status, long revision, String reason) {
        return com.zoop.common.json.Canonical.sha256(
                memberId + "\n" + status + "\n" + revision + "\n" + reason);
    }

    private static MemberDetail detail(String status, long revision) {
        var row = new MemberRow("member-1", "m***@example.com", "email", NOW.minusSeconds(100),
                NOW.minusSeconds(50), status, revision, new MemberActivity(1L, null, null, null));
        return new MemberDetail(row, true, true, 0, null, false, null, null, List.of(),
                new Metadata("zoop-db", NOW, null, "request", true, List.of()));
    }
}
