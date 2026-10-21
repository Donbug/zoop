package com.zoop.admin.graph;

import java.io.IOException;
import java.io.InputStream;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Map;
import java.util.Optional;

import com.zoop.admin.auth.repository.AdminAuditRepository;
import com.zoop.admin.auth.service.AdminPrincipal;
import com.zoop.admin.graph.GraphVersionAdminResponse.GraphDbVersionState;
import com.zoop.admin.graph.GraphVersionAdminResponse.GraphVersionOut;
import com.zoop.admin.graph.JdbcAdminGraphVersionRepository.IdempotencyRow;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.common.json.Canonical;
import com.zoop.document.evidence.graph.GraphEvidence;
import com.zoop.document.evidence.service.EvidenceService;
import com.zoop.graph.read.DisclosureExclusionReader;
import com.zoop.graph.read.DisclosureExclusions;
import com.zoop.graph.snapshot.GraphSnapshotCodec;
import com.zoop.graph.snapshot.GraphSnapshotStore;
import com.zoop.graph.snapshot.GraphSnapshotUnavailableException;
import com.zoop.graph.snapshot.PublicGraphSnapshot;
import com.zoop.graph.version.GraphVersionRecord;
import com.zoop.graph.version.JdbcGraphVersionRepository;
import com.zoop.graph.version.JdbcGraphVersionRepository.Activation;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import tools.jackson.databind.json.JsonMapper;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class AdminGraphVersionServiceTest {
    private static final Instant NOW = Instant.parse("2026-10-21T00:00:00Z");
    private static final Instant LATER = Instant.parse("2026-10-21T00:00:07Z");
    private static final String ACTIVE = "fixture-2026-10-08";
    private static final AdminPrincipal ADMIN = new AdminPrincipal(
            "admin-1", "admin@example.com", "Admin", "admin", "session-1");
    private static final GraphVersionRecord IMPORTED = new GraphVersionRecord(
            "gv-1", 3, "snapshot", "artifact-1", "artifact://gv-1.json", "a".repeat(64), false);
    private static final GraphVersionRecord FIXTURE = new GraphVersionRecord(
            "fixture-2026-10-01", 1, "fixture", "artifact-fixture-1", "classpath:x", "b".repeat(64), false);

    @Mock JdbcAdminGraphVersionRepository repository;
    @Mock JdbcGraphVersionRepository versions;
    @Mock GraphSnapshotStore snapshots;
    @Mock EvidenceService evidence;
    @Mock AdminAuditRepository audit;

    @Test
    void importedVersionIsCheckedUnderTheLockAndAuditedAtTheActivationTime() {
        claim("gv-1", ACTIVE, "go live");
        when(versions.find("gv-1")).thenReturn(Optional.of(IMPORTED));
        when(snapshots.load(IMPORTED)).thenReturn(fixtureSnapshot());
        activating("gv-1", ACTIVE, "go live", new Activation(ACTIVE, true, LATER));

        var result = service(storeExists(), false).activate("gv-1", request(" go live ", ACTIVE), "key-1", ADMIN,
                "request-1");

        assertEquals("gv-1", result.activeVersionId());
        assertEquals(ACTIVE, result.previousActiveVersionId());
        assertFalse(result.idempotent());
        @SuppressWarnings("unchecked")
        ArgumentCaptor<Map<String, GraphEvidence>> visible = ArgumentCaptor.forClass(Map.class);
        verify(evidence).requireGraphEvidenceServable(eq("gv-1"), visible.capture(), eq("request-1"));
        assertFalse(visible.getValue().isEmpty());
        verify(repository).shareLockArticles(argThat(ids -> !ids.isEmpty()));
        // The audit carries the time the pointer moved, not the time the request arrived (review 2).
        verify(audit).recordGraphActivation("admin-1", "admin@example.com", "gv-1", ACTIVE, true, "go live",
                "request-1", LATER);
        verify(repository).claimIdempotency(anyString(), eq("admin-1"), anyString(), eq("key-1"), eq("gv-1"),
                anyString(), eq(NOW));
        verify(repository).completeIdempotency(eq("idem-1"), anyString());
    }

    @Test
    void importedVersionIsRefusedWithoutAnExclusionStoreUnlessTheOperatorOptedIn() {
        claim("gv-1", ACTIVE, "go live");
        when(versions.find("gv-1")).thenReturn(Optional.of(IMPORTED));
        when(snapshots.load(IMPORTED)).thenReturn(fixtureSnapshot());
        activating("gv-1", ACTIVE, "go live", new Activation(ACTIVE, true, LATER));

        var error = assertThrows(CustomException.class, () -> service(noStore(), false).activate("gv-1",
                request("go live", ACTIVE), "key-1", ADMIN, "r"));

        assertEquals(ErrorCode.SOURCE_UNAVAILABLE, error.getErrorCode());
        verifyNoInteractions(evidence, audit);
        verify(repository, never()).completeIdempotency(any(), any());
    }

    @Test
    void operatorOptInAllowsAnImportedVersionWithoutAnExclusionStoreButStillChecksRights() {
        claim("gv-1", ACTIVE, "go live");
        when(versions.find("gv-1")).thenReturn(Optional.of(IMPORTED));
        when(snapshots.load(IMPORTED)).thenReturn(fixtureSnapshot());
        activating("gv-1", ACTIVE, "go live", new Activation(ACTIVE, true, LATER));

        service(noStore(), true).activate("gv-1", request("go live", ACTIVE), "key-1", ADMIN, "r");

        verify(evidence).requireGraphEvidenceServable(eq("gv-1"), anyMap(), eq("r"));
    }

    @Test
    void withheldEvidenceKeepsThePointerAndWritesNoAudit() {
        claim("gv-1", ACTIVE, "go live");
        when(versions.find("gv-1")).thenReturn(Optional.of(IMPORTED));
        when(snapshots.load(IMPORTED)).thenReturn(fixtureSnapshot());
        activating("gv-1", ACTIVE, "go live", new Activation(ACTIVE, true, LATER));
        doThrow(new CustomException(ErrorCode.REVISION_CONFLICT))
                .when(evidence).requireGraphEvidenceServable(eq("gv-1"), anyMap(), eq("r"));

        var error = assertThrows(CustomException.class, () -> service(storeExists(), false).activate("gv-1",
                request("go live", ACTIVE), "key-1", ADMIN, "r"));

        assertEquals(ErrorCode.REVISION_CONFLICT, error.getErrorCode());
        verifyNoInteractions(audit);
        verify(repository, never()).completeIdempotency(any(), any());
    }

    @Test
    void syntheticFixturesSkipTheRightsGate() {
        claim("fixture-2026-10-01", ACTIVE, "rollback");
        when(versions.find("fixture-2026-10-01")).thenReturn(Optional.of(FIXTURE));
        when(snapshots.load(FIXTURE)).thenReturn(fixtureSnapshot());
        activating("fixture-2026-10-01", ACTIVE, "rollback", new Activation(ACTIVE, true, LATER));

        service(noStore(), false).activate("fixture-2026-10-01", request("rollback", ACTIVE), "key-1", ADMIN, "r");

        verifyNoInteractions(evidence);
        verify(repository, never()).shareLockArticles(any());
    }

    @Test
    void reactivatingTheActiveVersionIsReportedIdempotent() {
        claim("fixture-2026-10-01", "fixture-2026-10-01", "again");
        when(versions.find("fixture-2026-10-01")).thenReturn(Optional.of(FIXTURE));
        activating("fixture-2026-10-01", "fixture-2026-10-01", "again",
                new Activation("fixture-2026-10-01", false, LATER));

        var result = service(noStore(), false).activate("fixture-2026-10-01",
                request("again", "fixture-2026-10-01"), "key-1", ADMIN, "r");

        assertTrue(result.idempotent());
    }

    @Test
    void unreadableSnapshotLeavesThePointerAlone() {
        claim("gv-1", ACTIVE, "go live");
        when(versions.find("gv-1")).thenReturn(Optional.of(IMPORTED));
        when(snapshots.load(IMPORTED)).thenThrow(new GraphSnapshotUnavailableException("sha256_mismatch"));

        var error = assertThrows(CustomException.class, () -> service(storeExists(), false).activate("gv-1",
                request("go live", ACTIVE), "key-1", ADMIN, "r"));

        assertEquals(ErrorCode.SOURCE_UNAVAILABLE, error.getErrorCode());
        verify(versions, never()).activateByAdmin(any(), any(), any(), any(), any(), any());
        verifyNoInteractions(audit);
    }

    @Test
    void staleExpectedActiveVersionIsAConflictWithoutAudit() {
        claim("gv-1", ACTIVE, "go live");
        when(versions.find("gv-1")).thenReturn(Optional.of(IMPORTED));
        when(snapshots.load(IMPORTED)).thenReturn(fixtureSnapshot());
        when(versions.activateByAdmin(eq("gv-1"), eq(ACTIVE), eq("admin-1"), eq("admin@example.com"), eq("go live"),
                any())).thenThrow(new CustomException(ErrorCode.REVISION_CONFLICT));

        var error = assertThrows(CustomException.class, () -> service(storeExists(), false).activate("gv-1",
                request("go live", ACTIVE), "key-1", ADMIN, "r"));

        assertEquals(ErrorCode.REVISION_CONFLICT, error.getErrorCode());
        verifyNoInteractions(audit, evidence);
        verify(repository, never()).completeIdempotency(any(), any());
    }

    @Test
    void unknownVersionIsNotFound() {
        claim("gv-x", ACTIVE, "go live");
        when(versions.find("gv-x")).thenReturn(Optional.empty());

        var error = assertThrows(CustomException.class, () -> service(storeExists(), false).activate("gv-x",
                request("go live", ACTIVE), "key-1", ADMIN, "r"));

        assertEquals(ErrorCode.RESOURCE_NOT_FOUND, error.getErrorCode());
        verifyNoInteractions(snapshots, audit);
    }

    @Test
    void replayReturnsTheStoredResultWithoutMovingThePointer() {
        when(repository.claimIdempotency(anyString(), eq("admin-1"), anyString(), eq("key-1"), eq("gv-1"),
                anyString(), eq(NOW))).thenReturn(false);
        when(repository.findIdempotencyForUpdate(eq("admin-1"), anyString(), eq("key-1")))
                .thenReturn(Optional.of(new IdempotencyRow("idem-1", hash("gv-1", ACTIVE, "go live"), "completed",
                        "{\"activeVersionId\":\"gv-1\",\"previousActiveVersionId\":null,\"idempotent\":false}")));

        var result = service(storeExists(), false).activate("gv-1", request("go live", ACTIVE), "key-1", ADMIN, "r");

        assertNull(result.previousActiveVersionId());
        verifyNoInteractions(versions, snapshots, audit, evidence);
    }

    @Test
    void sameKeyWithAnotherReasonIsAConflict() {
        when(repository.claimIdempotency(anyString(), eq("admin-1"),
                eq("/api/v1/admin/graph/versions/gv-1/activate"), eq("key-1"), eq("gv-1"), anyString(), eq(NOW)))
                .thenReturn(false);
        when(repository.findIdempotencyForUpdate("admin-1", "/api/v1/admin/graph/versions/gv-1/activate", "key-1"))
                .thenReturn(Optional.of(new IdempotencyRow("idem-1", hash("gv-1", ACTIVE, "go live"), "completed",
                        "{}")));

        var error = assertThrows(CustomException.class, () -> service(storeExists(), false).activate("gv-1",
                request("another reason", ACTIVE), "key-1", ADMIN, "r"));

        assertEquals(ErrorCode.IDEMPOTENCY_CONFLICT, error.getErrorCode());
        verifyNoInteractions(versions, snapshots, audit);
    }

    @Test
    void explicitNullAndAnIdHashDifferently() {
        assertFalse(hash("gv-1", null, "go").equals(hash("gv-1", "gv-0", "go")));
    }

    @Test
    void sensitiveReasonOrBadKeyIsRejectedBeforeAnyWrite() {
        var service = service(storeExists(), false);
        assertThrows(CustomException.class, () -> service.activate("gv-1",
                request("token=abc", ACTIVE), "key-1", ADMIN, "r"));
        assertThrows(CustomException.class, () -> service.activate("gv-1",
                request("go live", ACTIVE), " ", ADMIN, "r"));
        verifyNoInteractions(repository, versions, snapshots, audit, evidence);
    }

    @Test
    void listPagesBySequenceAndReportsTheActiveVersionOffPage() {
        when(repository.versions(null, 2)).thenReturn(List.of(version("gv-3", 3), version("gv-2", 2)));
        when(repository.versions(3L, 2)).thenReturn(List.of(version("gv-1", 1)));
        when(repository.activations()).thenReturn(List.of());
        when(versions.active()).thenReturn(Optional.of(IMPORTED));

        var first = service(storeExists(), false).list(null, 1);
        var second = service(storeExists(), false).list(first.nextCursor(), 1);

        assertEquals("gv-1", first.activeVersionId());
        assertEquals(List.of("gv-3"), first.items().stream().map(GraphVersionOut::id).toList());
        assertEquals(List.of("gv-1"), second.items().stream().map(GraphVersionOut::id).toList());
        assertNull(second.nextCursor());
    }

    @Test
    void badLimitOrCursorIsRejected() {
        var service = service(storeExists(), false);
        assertEquals(ErrorCode.INVALID_REQUEST, assertThrows(CustomException.class,
                () -> service.list(null, 101)).getErrorCode());
        assertEquals(ErrorCode.INVALID_CURSOR, assertThrows(CustomException.class,
                () -> service.list("not-a-cursor!", null)).getErrorCode());
        assertEquals(ErrorCode.INVALID_CURSOR, assertThrows(CustomException.class,
                () -> service.list("Z3YxOjA", null)).getErrorCode());
        verifyNoInteractions(repository);
    }

    /** The repository mock runs the caller's checks where the real one does: under the lock, before the pointer moves. */
    private void activating(String versionId, String expected, String reason, Activation activation) {
        when(versions.activateByAdmin(eq(versionId), eq(expected), eq("admin-1"), eq("admin@example.com"), eq(reason),
                any())).thenAnswer(invocation -> {
                    invocation.<Runnable>getArgument(5).run();
                    return activation;
                });
    }

    private void claim(String versionId, String expected, String reason) {
        when(repository.claimIdempotency(anyString(), eq("admin-1"), anyString(), eq("key-1"), eq(versionId),
                anyString(), eq(NOW))).thenReturn(true);
        when(repository.findIdempotencyForUpdate(eq("admin-1"), anyString(), eq("key-1")))
                .thenReturn(Optional.of(new IdempotencyRow("idem-1", hash(versionId, expected, reason), "processing",
                        null)));
    }

    private static GraphVersionActivateRequest request(String reason, String expected) {
        return new GraphVersionActivateRequest(reason, expected);
    }

    private static String hash(String versionId, String expected, String reason) {
        return Canonical.sha256(versionId + "\n" + (expected == null ? "" : expected) + "\n" + reason);
    }

    private static PublicGraphSnapshot fixtureSnapshot() {
        try (InputStream in = AdminGraphVersionServiceTest.class.getResourceAsStream(
                "/graph-fixtures/fixture-2026-10-08.json")) {
            return GraphSnapshotCodec.read(in.readAllBytes(), "fixture-2026-10-08");
        } catch (IOException exception) {
            throw new IllegalStateException(exception);
        }
    }

    private static DisclosureExclusionReader storeExists() {
        return () -> DisclosureExclusions.NONE;
    }

    private static DisclosureExclusionReader noStore() {
        return new DisclosureExclusionReader() {
            @Override
            public DisclosureExclusions current() {
                return DisclosureExclusions.NONE;
            }

            @Override
            public boolean authoritative() {
                return false;
            }
        };
    }

    private static GraphVersionOut version(String id, long sequence) {
        return new GraphVersionOut(id, sequence, "snapshot", NOW, "operator:test", null, "label", null, 0, 0, 0,
                null, "a".repeat(64), 1, false, null, new GraphDbVersionState("unknown", null, null));
    }

    private AdminGraphVersionService service(DisclosureExclusionReader exclusions, boolean allowWithoutStore) {
        return new AdminGraphVersionService(repository, versions, snapshots, exclusions, evidence, audit,
                JsonMapper.builder().build(), Clock.fixed(NOW, ZoneOffset.UTC), allowWithoutStore);
    }
}
