package com.zoop.admin.graph;

import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Optional;

import com.zoop.admin.auth.repository.AdminAuditRepository;
import com.zoop.admin.auth.service.AdminPrincipal;
import com.zoop.admin.graph.GraphVersionAdminResponse.GraphDbVersionState;
import com.zoop.admin.graph.GraphVersionAdminResponse.GraphVersionOut;
import com.zoop.admin.graph.JdbcAdminGraphVersionRepository.IdempotencyRow;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.common.json.Canonical;
import com.zoop.graph.snapshot.GraphSnapshotStore;
import com.zoop.graph.snapshot.GraphSnapshotUnavailableException;
import com.zoop.graph.version.GraphVersionRecord;
import com.zoop.graph.version.JdbcGraphVersionRepository;
import com.zoop.graph.version.JdbcGraphVersionRepository.Activation;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import tools.jackson.databind.json.JsonMapper;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class AdminGraphVersionServiceTest {
    private static final Instant NOW = Instant.parse("2026-10-21T00:00:00Z");
    private static final String ACTIVE = "fixture-2026-10-08";
    private static final AdminPrincipal ADMIN = new AdminPrincipal(
            "admin-1", "admin@example.com", "Admin", "admin", "session-1");
    private static final GraphVersionRecord VERSION = new GraphVersionRecord(
            "gv-1", 3, "snapshot", "artifact-1", "artifact://gv-1.json", "a".repeat(64), false);

    @Mock JdbcAdminGraphVersionRepository repository;
    @Mock JdbcGraphVersionRepository versions;
    @Mock GraphSnapshotStore snapshots;
    @Mock AdminAuditRepository audit;

    @Test
    void activatesAfterTheSnapshotVerifiesAndRecordsTheAdmin() {
        claim("gv-1", "go live", "processing", null);
        when(versions.find("gv-1")).thenReturn(Optional.of(VERSION));
        when(versions.activateByAdmin("gv-1", ACTIVE, "admin-1", "admin@example.com", "go live", NOW))
                .thenReturn(new Activation("fixture-2026-10-08", true));

        var result = service().activate("gv-1", new GraphVersionActivateRequest(" go live ", ACTIVE), "key-1", ADMIN,
                "request-1");

        assertEquals("gv-1", result.activeVersionId());
        assertEquals("fixture-2026-10-08", result.previousActiveVersionId());
        assertFalse(result.idempotent());
        verify(snapshots).load(VERSION);
        verify(audit).recordGraphActivation("admin-1", "admin@example.com", "gv-1", "fixture-2026-10-08", true,
                "go live", "request-1", NOW);
        verify(repository).completeIdempotency(eq("idem-1"), anyString());
    }

    @Test
    void reactivatingTheActiveVersionIsReportedIdempotent() {
        claim("gv-1", "again", "processing", null);
        when(versions.find("gv-1")).thenReturn(Optional.of(VERSION));
        when(versions.activateByAdmin("gv-1", ACTIVE, "admin-1", "admin@example.com", "again", NOW))
                .thenReturn(new Activation("gv-1", false));

        var result = service().activate("gv-1", new GraphVersionActivateRequest("again", ACTIVE), "key-1", ADMIN, "r");

        assertTrue(result.idempotent());
    }

    @Test
    void unreadableSnapshotLeavesThePointerAlone() {
        claim("gv-1", "go live", "processing", null);
        when(versions.find("gv-1")).thenReturn(Optional.of(VERSION));
        when(snapshots.load(VERSION)).thenThrow(new GraphSnapshotUnavailableException("sha256_mismatch"));

        var error = assertThrows(CustomException.class, () -> service().activate("gv-1",
                new GraphVersionActivateRequest("go live", ACTIVE), "key-1", ADMIN, "r"));

        assertEquals(ErrorCode.SOURCE_UNAVAILABLE, error.getErrorCode());
        verify(versions, never()).activateByAdmin(any(), any(), any(), any(), any(), any());
        verifyNoInteractions(audit);
    }

    @Test
    void staleExpectedActiveVersionIsAConflictWithoutAudit() {
        claim("gv-1", "go live", "processing", null);
        when(versions.find("gv-1")).thenReturn(Optional.of(VERSION));
        when(versions.activateByAdmin("gv-1", ACTIVE, "admin-1", "admin@example.com", "go live", NOW))
                .thenThrow(new CustomException(ErrorCode.REVISION_CONFLICT));

        var error = assertThrows(CustomException.class, () -> service().activate("gv-1",
                new GraphVersionActivateRequest("go live", ACTIVE), "key-1", ADMIN, "r"));

        assertEquals(ErrorCode.REVISION_CONFLICT, error.getErrorCode());
        verifyNoInteractions(audit);
        verify(repository, never()).completeIdempotency(any(), any());
    }

    @Test
    void unknownVersionIsNotFound() {
        claim("gv-x", "go live", "processing", null);
        when(versions.find("gv-x")).thenReturn(Optional.empty());

        var error = assertThrows(CustomException.class, () -> service().activate("gv-x",
                new GraphVersionActivateRequest("go live", ACTIVE), "key-1", ADMIN, "r"));

        assertEquals(ErrorCode.RESOURCE_NOT_FOUND, error.getErrorCode());
        verifyNoInteractions(snapshots, audit);
    }

    @Test
    void replayReturnsTheStoredResultWithoutMovingThePointer() {
        when(repository.claimIdempotency(anyString(), eq("admin-1"), anyString(), eq("key-1"), eq("gv-1"),
                anyString(), eq(NOW))).thenReturn(false);
        when(repository.findIdempotencyForUpdate(eq("admin-1"), anyString(), eq("key-1")))
                .thenReturn(Optional.of(new IdempotencyRow("idem-1", hash("gv-1", "go live"), "completed",
                        "{\"activeVersionId\":\"gv-1\",\"previousActiveVersionId\":null,\"idempotent\":false}")));

        var result = service().activate("gv-1", new GraphVersionActivateRequest("go live", ACTIVE), "key-1", ADMIN, "r");

        assertNull(result.previousActiveVersionId());
        verifyNoInteractions(versions, snapshots, audit);
    }

    @Test
    void sameKeyWithAnotherReasonIsAConflict() {
        when(repository.claimIdempotency(anyString(), eq("admin-1"),
                eq("/api/v1/admin/graph/versions/gv-1/activate"), eq("key-1"), eq("gv-1"), anyString(), eq(NOW)))
                .thenReturn(false);
        when(repository.findIdempotencyForUpdate("admin-1", "/api/v1/admin/graph/versions/gv-1/activate", "key-1"))
                .thenReturn(Optional.of(new IdempotencyRow("idem-1", hash("gv-1", "go live"), "completed", "{}")));

        var error = assertThrows(CustomException.class, () -> service().activate("gv-1",
                new GraphVersionActivateRequest("another reason", ACTIVE), "key-1", ADMIN, "r"));

        assertEquals(ErrorCode.IDEMPOTENCY_CONFLICT, error.getErrorCode());
        verifyNoInteractions(versions, snapshots, audit);
    }

    @Test
    void sensitiveReasonOrBadKeyIsRejectedBeforeAnyWrite() {
        assertThrows(CustomException.class, () -> service().activate("gv-1",
                new GraphVersionActivateRequest("token=abc", ACTIVE), "key-1", ADMIN, "r"));
        assertThrows(CustomException.class, () -> service().activate("gv-1",
                new GraphVersionActivateRequest("go live", ACTIVE), " ", ADMIN, "r"));
        verifyNoInteractions(repository, versions, snapshots, audit);
    }

    @Test
    void listPagesBySequenceAndReportsTheActiveVersionOffPage() {
        when(repository.versions(null, 2)).thenReturn(List.of(version("gv-3", 3), version("gv-2", 2)));
        when(repository.versions(3L, 2)).thenReturn(List.of(version("gv-1", 1)));
        when(repository.activations()).thenReturn(List.of());
        when(versions.active()).thenReturn(Optional.of(VERSION));

        var first = service().list(null, 1);
        var second = service().list(first.nextCursor(), 1);

        assertEquals("gv-1", first.activeVersionId());
        assertEquals(List.of("gv-3"), first.items().stream().map(GraphVersionOut::id).toList());
        assertEquals(List.of("gv-1"), second.items().stream().map(GraphVersionOut::id).toList());
        assertNull(second.nextCursor());
    }

    @Test
    void badLimitOrCursorIsRejected() {
        assertEquals(ErrorCode.INVALID_REQUEST, assertThrows(CustomException.class,
                () -> service().list(null, 101)).getErrorCode());
        assertEquals(ErrorCode.INVALID_CURSOR, assertThrows(CustomException.class,
                () -> service().list("not-a-cursor!", null)).getErrorCode());
        assertEquals(ErrorCode.INVALID_CURSOR, assertThrows(CustomException.class,
                () -> service().list("Z3YxOjA", null)).getErrorCode());
        verifyNoInteractions(repository);
    }

    private void claim(String versionId, String reason, String status, String body) {
        when(repository.claimIdempotency(anyString(), eq("admin-1"), anyString(), eq("key-1"), eq(versionId),
                anyString(), eq(NOW))).thenReturn(true);
        when(repository.findIdempotencyForUpdate(eq("admin-1"), anyString(), eq("key-1")))
                .thenReturn(Optional.of(new IdempotencyRow("idem-1", hash(versionId, reason), status, body)));
    }

    private static String hash(String versionId, String reason) {
        return Canonical.sha256(versionId + "\n" + ACTIVE + "\n" + reason);
    }

    private static GraphVersionOut version(String id, long sequence) {
        return new GraphVersionOut(id, sequence, "snapshot", NOW, "operator:test", null, "label", null, 0, 0, 0,
                null, "a".repeat(64), 1, false, null, new GraphDbVersionState("unknown", null, null));
    }

    private AdminGraphVersionService service() {
        return new AdminGraphVersionService(repository, versions, snapshots, audit, JsonMapper.builder().build(),
                Clock.fixed(NOW, ZoneOffset.UTC));
    }
}
