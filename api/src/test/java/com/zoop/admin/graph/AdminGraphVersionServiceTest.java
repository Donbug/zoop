package com.zoop.admin.graph;

import java.io.IOException;
import java.io.InputStream;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.function.Consumer;
import java.util.function.Supplier;

import com.zoop.admin.auth.repository.AdminAuditRepository;
import com.zoop.admin.auth.service.AdminPrincipal;
import com.zoop.admin.graph.GraphVersionAdminResponse.GraphDbVersionState;
import com.zoop.admin.graph.GraphVersionAdminResponse.GraphVersionOut;
import com.zoop.admin.graph.JdbcAdminGraphVersionRepository.IdempotencyRow;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.document.evidence.graph.GraphEvidence;
import com.zoop.document.evidence.service.EvidenceService;
import com.zoop.graph.exclusion.DisclosureExclusionCarry;
import com.zoop.graph.publication.GraphPublicationAuthority;
import com.zoop.graph.publication.GraphPublicationReader;
import com.zoop.graph.publication.GraphPublicationReader.Contribution;
import com.zoop.graph.publication.GraphPublicationReader.Publication;
import com.zoop.graph.publication.PublicationException;
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
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
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
    @Mock GraphPublicationReader publications;
    @Mock GraphPublicationAuthority authority;
    @Mock AdminAuditRepository audit;
    @Mock DisclosureExclusionCarry carry;

    @Test
    void importedVersionIsCheckedUnderTheLockAndAuditedAtTheActivationTime() {
        claim("gv-1", ACTIVE, "go live");
        when(versions.find("gv-1")).thenReturn(Optional.of(IMPORTED));
        when(snapshots.load(IMPORTED)).thenReturn(fixtureSnapshot());
        activating("gv-1", ACTIVE, "go live", new Activation(ACTIVE, true, LATER));
        List<Instant> judgedAt = new java.util.ArrayList<>();
        when(evidence.prepareGraphActivation(eq("gv-1"), anyMap(), eq("request-1"))).thenReturn(judgedAt::add);

        var result = service(storeExists(), false).activate("gv-1", request(" go live ", ACTIVE), "key-1", ADMIN,
                "request-1");

        assertEquals("gv-1", result.activeVersionId());
        assertEquals(ACTIVE, result.previousActiveVersionId());
        assertFalse(result.idempotent());
        assertEquals(List.of(LATER), judgedAt, "grants are judged at the activation time, not when the checks began");
        @SuppressWarnings("unchecked")
        ArgumentCaptor<Map<String, GraphEvidence>> visible = ArgumentCaptor.forClass(Map.class);
        verify(evidence).prepareGraphActivation(eq("gv-1"), visible.capture(), eq("request-1"));
        assertFalse(visible.getValue().isEmpty());
        verify(repository).shareLockArticles(argThat(ids -> !ids.isEmpty()));
        // The audit carries the time the pointer moved, not the time the request arrived (review 2).
        verify(audit).recordGraphActivation("admin-1", "admin@example.com", "gv-1", ACTIVE, true, "go live",
                "forward", "request-1", LATER);
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
        when(evidence.prepareGraphActivation(eq("gv-1"), anyMap(), eq("r"))).thenReturn(at -> { });

        service(noStore(), true).activate("gv-1", request("go live", ACTIVE), "key-1", ADMIN, "r");

        verify(evidence).prepareGraphActivation(eq("gv-1"), anyMap(), eq("r"));
    }

    @Test
    void withheldEvidenceKeepsThePointerAndWritesNoAudit() {
        claim("gv-1", ACTIVE, "go live");
        when(versions.find("gv-1")).thenReturn(Optional.of(IMPORTED));
        when(snapshots.load(IMPORTED)).thenReturn(fixtureSnapshot());
        activating("gv-1", ACTIVE, "go live", new Activation(ACTIVE, true, LATER));
        when(evidence.prepareGraphActivation(eq("gv-1"), anyMap(), eq("r")))
                .thenThrow(new CustomException(ErrorCode.REVISION_CONFLICT));

        var error = assertThrows(CustomException.class, () -> service(storeExists(), false).activate("gv-1",
                request("go live", ACTIVE), "key-1", ADMIN, "r"));

        assertEquals(ErrorCode.REVISION_CONFLICT, error.getErrorCode());
        verifyNoInteractions(audit);
        verify(repository, never()).completeIdempotency(any(), any());
    }

    @Test
    void aGrantThatExpiresWhileTheChecksRunIsRefusedAtTheActivationTime() {
        claim("gv-1", ACTIVE, "go live");
        when(versions.find("gv-1")).thenReturn(Optional.of(IMPORTED));
        when(snapshots.load(IMPORTED)).thenReturn(fixtureSnapshot());
        activating("gv-1", ACTIVE, "go live", new Activation(ACTIVE, true, LATER));
        // The slow step passes (it judges nothing by time); the grant ends between NOW and LATER.
        Instant expiry = NOW.plusSeconds(3);
        when(evidence.prepareGraphActivation(eq("gv-1"), anyMap(), eq("r"))).thenReturn(at -> {
            if (!at.isBefore(expiry)) throw new CustomException(ErrorCode.REVISION_CONFLICT);
        });

        var error = assertThrows(CustomException.class, () -> service(storeExists(), false).activate("gv-1",
                request("go live", ACTIVE), "key-1", ADMIN, "r"));

        assertEquals(ErrorCode.REVISION_CONFLICT, error.getErrorCode());
        verifyNoInteractions(audit);
        verify(repository, never()).completeIdempotency(any(), any());
    }

    @Test
    void syntheticFixturesSkipTheRightsGateUnderTheFixtureSource() {
        claim("fixture-2026-10-01", ACTIVE, "rollback");
        when(versions.find("fixture-2026-10-01")).thenReturn(Optional.of(FIXTURE));
        when(snapshots.load(FIXTURE)).thenReturn(fixtureSnapshot());
        activating("fixture-2026-10-01", ACTIVE, "rollback", new Activation(ACTIVE, true, LATER));

        service(noStore(), false).activate("fixture-2026-10-01", request("rollback", ACTIVE), "key-1", ADMIN, "r");

        verifyNoInteractions(evidence);
        verify(repository, never()).shareLockArticles(any());
    }

    @Test
    void aSyntheticFixtureIsNeverActivatedOutsideTheFixtureSource() {
        for (String source : new String[] {"artifact", "none"}) {
            org.mockito.Mockito.reset(repository, versions, snapshots);
            claim("fixture-2026-10-01", ACTIVE, "rollback", "rollback");
            when(versions.find("fixture-2026-10-01")).thenReturn(Optional.of(FIXTURE));
            // Like the real source=none store (GraphSnapshotConfiguration): every read fails, which would surface as 503.
            org.mockito.Mockito.lenient().when(snapshots.load(FIXTURE))
                    .thenThrow(new GraphSnapshotUnavailableException("snapshot_source_disabled"));

            var error = assertThrows(CustomException.class, () -> service(storeExists(), true, source)
                    .activate("fixture-2026-10-01", new GraphVersionActivateRequest("rollback", ACTIVE, "rollback"),
                            "key-1", ADMIN, "r"));

            // 422 from the contract, decided before the snapshot is read and before the pointer could move.
            assertEquals(ErrorCode.INVALID_REQUEST, error.getErrorCode(), source);
            verify(snapshots, never()).load(any());
            verify(versions, never()).activateByAdmin(any(), any(), any(), any(), any(), any(), any());
            verify(repository, never()).completeIdempotency(any(), any());
        }
        verifyNoInteractions(audit, evidence);
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
        verify(versions, never()).activateByAdmin(any(), any(), any(), any(), any(), any(), any());
        verifyNoInteractions(audit);
    }

    @Test
    void staleExpectedActiveVersionIsAConflictWithoutAudit() {
        claim("gv-1", ACTIVE, "go live");
        when(versions.find("gv-1")).thenReturn(Optional.of(IMPORTED));
        when(snapshots.load(IMPORTED)).thenReturn(fixtureSnapshot());
        when(versions.activateByAdmin(eq("gv-1"), eq(ACTIVE), eq("admin-1"), eq("admin@example.com"), eq("go live"),
                eq("forward"), any())).thenThrow(new CustomException(ErrorCode.REVISION_CONFLICT));

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
    void sameKeyCannotChangeForwardIntoRollback() {
        when(repository.claimIdempotency(anyString(), eq("admin-1"), anyString(), eq("key-1"), eq("gv-1"),
                anyString(), eq(NOW))).thenReturn(false);
        when(repository.findIdempotencyForUpdate(eq("admin-1"), anyString(), eq("key-1")))
                .thenReturn(Optional.of(new IdempotencyRow("idem-1", hash("gv-1", ACTIVE, "go live"), "completed",
                        "{\"activeVersionId\":\"gv-1\",\"previousActiveVersionId\":null,\"idempotent\":false}")));

        var error = assertThrows(CustomException.class, () -> service(storeExists(), false).activate("gv-1",
                new GraphVersionActivateRequest("go live", ACTIVE, "rollback"), "key-1", ADMIN, "r"));

        assertEquals(ErrorCode.IDEMPOTENCY_CONFLICT, error.getErrorCode());
        verifyNoInteractions(versions, snapshots, audit, evidence);
    }

    @Test
    void explicitForwardReplaysARequestWhoseModeWasOmitted() {
        when(repository.claimIdempotency(anyString(), eq("admin-1"), anyString(), eq("key-1"), eq("gv-1"),
                anyString(), eq(NOW))).thenReturn(false);
        var omitted = JsonMapper.builder().build().readValue(
                "{\"reason\":\"go live\",\"expectedActiveVersionId\":\"" + ACTIVE + "\"}",
                GraphVersionActivateRequest.class);
        String originalHash = AdminGraphVersionService.requestHash("gv-1", ACTIVE, omitted.reason(), omitted.mode());
        when(repository.findIdempotencyForUpdate(eq("admin-1"), anyString(), eq("key-1")))
                .thenReturn(Optional.of(new IdempotencyRow("idem-1", originalHash, "completed",
                        "{\"activeVersionId\":\"gv-1\",\"previousActiveVersionId\":null,\"idempotent\":false}")));

        var result = service(storeExists(), false).activate("gv-1", request("go live", ACTIVE), "key-1", ADMIN, "r");

        assertEquals("gv-1", result.activeVersionId());
        verifyNoInteractions(versions, snapshots, audit, evidence);
    }

    @Test
    void rollbackStillChecksFullPublicationRightsAtTheActivationTime() {
        claim("gv-1", ACTIVE, "restore", "rollback");
        when(versions.find("gv-1")).thenReturn(Optional.of(IMPORTED));
        when(snapshots.load(IMPORTED)).thenReturn(fixtureSnapshot());
        activating("gv-1", ACTIVE, "restore", "rollback", new Activation(ACTIVE, true, LATER));
        when(evidence.prepareGraphActivation(eq("gv-1"), anyMap(), eq("r"))).thenReturn(at -> { });
        org.mockito.Mockito.doThrow(new PublicationException("rights_denied")).when(authority)
                .requireFullRights(any(), eq("r"), eq(LATER));

        var error = assertThrows(CustomException.class, () -> service(storeExists(), false).activate("gv-1",
                new GraphVersionActivateRequest("restore", ACTIVE, "rollback"), "key-1", ADMIN, "r"));

        assertEquals(ErrorCode.REVISION_CONFLICT, error.getErrorCode());
        verifyNoInteractions(audit);
        verify(repository, never()).completeIdempotency(any(), any());
    }

    @Test
    void missingOriginalProofRefusesActivationAsSourceUnavailable() {
        claim("gv-1", ACTIVE, "go live");
        when(versions.find("gv-1")).thenReturn(Optional.of(IMPORTED));
        when(snapshots.load(IMPORTED)).thenReturn(fixtureSnapshot());
        activating("gv-1", ACTIVE, "go live", new Activation(ACTIVE, true, LATER));
        var service = service(storeExists(), false);
        when(publications.read("gv-1")).thenThrow(new PublicationException("basis_unavailable"));

        var error = assertThrows(CustomException.class, () -> service.activate("gv-1", request("go live", ACTIVE),
                "key-1", ADMIN, "r"));

        assertEquals(ErrorCode.SOURCE_UNAVAILABLE, error.getErrorCode());
        verifyNoInteractions(audit, evidence);
        verify(repository, never()).completeIdempotency(any(), any());
    }

    @Test
    void alreadyActiveImportedVersionStillRequiresCurrentRights() {
        claim("gv-1", "gv-1", "again");
        when(versions.find("gv-1")).thenReturn(Optional.of(IMPORTED));
        when(snapshots.load(IMPORTED)).thenReturn(fixtureSnapshot());
        activating("gv-1", "gv-1", "again", new Activation("gv-1", false, LATER));
        when(evidence.prepareGraphActivation(eq("gv-1"), anyMap(), eq("r"))).thenReturn(at -> {
            throw new CustomException(ErrorCode.REVISION_CONFLICT);
        });

        var error = assertThrows(CustomException.class, () -> service(storeExists(), false).activate("gv-1",
                request("again", "gv-1"), "key-1", ADMIN, "r"));

        assertEquals(ErrorCode.REVISION_CONFLICT, error.getErrorCode());
        verifyNoInteractions(audit);
        verify(repository, never()).completeIdempotency(any(), any());
    }

    @Test
    void explicitNullAnEmptyStringAndAnIdHashDifferently() {
        assertFalse(hash("gv-1", null, "go").equals(hash("gv-1", "gv-0", "go")));
        assertFalse(hash("gv-1", null, "go").equals(hash("gv-1", "", "go")),
                "a sentinel string must not make null and \"\" the same request");
    }

    @Test
    void anEmptyExpectedVersionAfterANullSuccessWithTheSameKeyIsAConflict() {
        when(repository.claimIdempotency(anyString(), eq("admin-1"), anyString(), eq("key-1"), eq("gv-1"),
                anyString(), eq(NOW))).thenReturn(false);
        when(repository.findIdempotencyForUpdate(eq("admin-1"), anyString(), eq("key-1")))
                .thenReturn(Optional.of(new IdempotencyRow("idem-1", hash("gv-1", null, "go live"), "completed",
                        "{\"activeVersionId\":\"gv-1\",\"previousActiveVersionId\":null,\"idempotent\":false}")));

        var error = assertThrows(CustomException.class, () -> service(storeExists(), false).activate("gv-1",
                request("go live", ""), "key-1", ADMIN, "r"));

        assertEquals(ErrorCode.IDEMPOTENCY_CONFLICT, error.getErrorCode(), "\"\" is not the null that succeeded");
        verifyNoInteractions(versions, snapshots, audit);
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

    /**
     * The repository mock runs the caller's checks where the real one does: the slow part under the lock, then the last part at
     * the activation time it reports, before the pointer moves.
     */
    @Test
    void anImportedCandidateGetsTheSameChecksAndBecomesPublicForTheSystemActor() {
        when(versions.active()).thenReturn(Optional.of(new GraphVersionRecord(ACTIVE, 2, "fixture", "artifact-active",
                "classpath:a", "c".repeat(64), true)));
        when(snapshots.load(IMPORTED)).thenReturn(fixtureSnapshot());
        List<Instant> judgedAt = new java.util.ArrayList<>();
        when(evidence.prepareGraphActivation(eq("gv-1"), anyMap(), eq("auto-1"))).thenReturn(judgedAt::add);
        when(versions.activateBySystem(eq("gv-1"), eq(ACTIVE), eq(NOW), eq(AdminGraphVersionService.AUTO_REASON), any()))
                .thenAnswer(invocation -> {
                    invocation.<Supplier<Consumer<Instant>>>getArgument(4).get().accept(LATER);
                    return Optional.of(new Activation(ACTIVE, true, LATER));
                });

        var activation = service(storeExists(), false, "artifact").activateImported(IMPORTED, NOW, "auto-1");

        assertEquals(Optional.of(new Activation(ACTIVE, true, LATER)), activation);
        assertEquals(List.of(LATER), judgedAt, "grants are judged at the activation time");
        verify(repository).shareLockArticles(argThat(ids -> !ids.isEmpty()));
        verifyNoInteractions(audit);
    }

    @Test
    void anImportedCandidateThatFailsTheChecksIsRefusedLikeAnAdminActivation() {
        when(versions.active()).thenReturn(Optional.empty());
        when(snapshots.load(IMPORTED)).thenReturn(fixtureSnapshot());
        when(evidence.prepareGraphActivation(eq("gv-1"), anyMap(), eq("auto-1")))
                .thenThrow(new CustomException(ErrorCode.REVISION_CONFLICT));
        when(versions.activateBySystem(eq("gv-1"), isNull(), eq(NOW), anyString(), any())).thenAnswer(invocation -> {
            invocation.<Supplier<Consumer<Instant>>>getArgument(4).get();
            return Optional.of(new Activation(null, true, LATER));
        });

        var error = assertThrows(CustomException.class,
                () -> service(storeExists(), false, "artifact").activateImported(IMPORTED, NOW, "auto-1"));

        assertEquals(ErrorCode.REVISION_CONFLICT, error.getErrorCode());
    }

    private void activating(String versionId, String expected, String reason, Activation activation) {
        activating(versionId, expected, reason, "forward", activation);
    }

    private void activating(String versionId, String expected, String reason, String mode, Activation activation) {
        when(versions.activateByAdmin(eq(versionId), eq(expected), eq("admin-1"), eq("admin@example.com"), eq(reason),
                eq(mode), any())).thenAnswer(invocation -> {
                    invocation.<Supplier<Consumer<Instant>>>getArgument(6).get().accept(activation.activatedAt());
                    return activation;
                });
    }

    private void claim(String versionId, String expected, String reason) {
        claim(versionId, expected, reason, "forward");
    }

    private void claim(String versionId, String expected, String reason, String mode) {
        when(repository.claimIdempotency(anyString(), eq("admin-1"), anyString(), eq("key-1"), eq(versionId),
                anyString(), eq(NOW))).thenReturn(true);
        when(repository.findIdempotencyForUpdate(eq("admin-1"), anyString(), eq("key-1")))
                .thenReturn(Optional.of(new IdempotencyRow("idem-1",
                        AdminGraphVersionService.requestHash(versionId, expected, reason, mode), "processing", null)));
    }

    private static GraphVersionActivateRequest request(String reason, String expected) {
        return new GraphVersionActivateRequest(reason, expected, "forward");
    }

    private static String hash(String versionId, String expected, String reason) {
        return AdminGraphVersionService.requestHash(versionId, expected, reason, "forward");
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
        return pinned -> DisclosureExclusions.NONE;
    }

    private static DisclosureExclusionReader noStore() {
        return new DisclosureExclusionReader() {
            @Override
            public DisclosureExclusions current(String versionId) {
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

    /** The local/dev fixture source, where synthetic fixtures may be activated. */
    private AdminGraphVersionService service(DisclosureExclusionReader exclusions, boolean allowWithoutStore) {
        return service(exclusions, allowWithoutStore, "fixture");
    }

    private AdminGraphVersionService service(DisclosureExclusionReader exclusions, boolean allowWithoutStore,
            String snapshotSource) {
        org.mockito.Mockito.lenient().when(publications.read(anyString())).thenAnswer(invocation -> {
            var snapshot = fixtureSnapshot();
            String versionId = invocation.getArgument(0);
            return new Publication(versionId, null, null, null, null, null, null, snapshot,
                    List.of(new Contribution(versionId, "source-1", "native", null, null, snapshot, null)),
                    null, Map.of(), Map.of());
        });
        org.mockito.Mockito.lenient()
                .doAnswer(invocation -> exclusions.current(invocation.<Publication>getArgument(0).versionId()))
                .when(authority).current(any(), anyString());
        return new AdminGraphVersionService(repository, versions, snapshots, exclusions, carry, evidence, publications,
                authority, audit, JsonMapper.builder().build(), Clock.fixed(NOW, ZoneOffset.UTC), allowWithoutStore,
                snapshotSource);
    }

    // ---- the carry of the public version's exclusions (#55 A-14) -----------------------------------------------------------

    @Test
    void anActivationCarriesThePublicVersionsExclusionsBeforeItReadsTheNewOverlay() {
        claim("gv-1", ACTIVE, "go live");
        when(versions.find("gv-1")).thenReturn(Optional.of(IMPORTED));
        when(versions.active()).thenReturn(Optional.of(new GraphVersionRecord(ACTIVE, 2, "snapshot", "artifact-active",
                "artifact://active.json", "c".repeat(64), true)));
        when(snapshots.load(IMPORTED)).thenReturn(fixtureSnapshot());
        activating("gv-1", ACTIVE, "go live", new Activation(ACTIVE, true, LATER));
        when(evidence.prepareGraphActivation(eq("gv-1"), anyMap(), eq("r"))).thenReturn(at -> { });
        List<String> order = new java.util.ArrayList<>();
        when(carry.carry(List.of(ACTIVE), List.of("gv-1"), "admin:admin-1")).thenAnswer(invocation -> {
            order.add("carry");
            return 3;
        });
        DisclosureExclusionReader reads = pinned -> {
            order.add("read " + pinned);
            return DisclosureExclusions.NONE;
        };

        service(reads, false).activate("gv-1", request("go live", ACTIVE), "key-1", ADMIN, "r");

        assertEquals(List.of("carry", "read gv-1"), order, "carried first, so the pre-activation checks see the carried targets");
    }

    @Test
    void aFixtureInBetweenDoesNotCutTheChainTheLastPublicImportedVersionIsTheBaseThen() {
        when(versions.active()).thenReturn(Optional.of(new GraphVersionRecord(ACTIVE, 2, "fixture", "artifact-active",
                "classpath:a", "c".repeat(64), true)));
        when(versions.lastActivatedImported()).thenReturn(Optional.of("gv-0"));
        when(snapshots.load(IMPORTED)).thenReturn(fixtureSnapshot());
        when(evidence.prepareGraphActivation(eq("gv-1"), anyMap(), eq("auto-1"))).thenReturn(at -> { });
        when(versions.activateBySystem(eq("gv-1"), eq(ACTIVE), eq(NOW), eq(AdminGraphVersionService.AUTO_REASON), any()))
                .thenAnswer(invocation -> {
                    invocation.<Supplier<Consumer<Instant>>>getArgument(4).get().accept(LATER);
                    return Optional.of(new Activation(ACTIVE, true, LATER));
                });

        service(storeExists(), false, "artifact").activateImported(IMPORTED, NOW, "auto-1");

        verify(carry).carry(List.of("gv-0"), List.of("gv-1"), "system");
    }

    @Test
    void aCumulativePublicationCarriesBetweenOriginalVersionsNeverToItsOwnId() {
        when(versions.active()).thenReturn(Optional.of(new GraphVersionRecord(ACTIVE, 2, "snapshot", "artifact-active",
                "artifact://active.json", "c".repeat(64), true)));
        when(snapshots.load(IMPORTED)).thenReturn(fixtureSnapshot());
        when(evidence.prepareGraphActivation(eq("gv-1"), anyMap(), eq("auto-1"))).thenReturn(at -> { });
        when(versions.activateBySystem(eq("gv-1"), eq(ACTIVE), eq(NOW), eq(AdminGraphVersionService.AUTO_REASON), any()))
                .thenAnswer(invocation -> {
                    invocation.<Supplier<Consumer<Instant>>>getArgument(4).get().accept(LATER);
                    return Optional.of(new Activation(ACTIVE, true, LATER));
                });
        AdminGraphVersionService service = service(storeExists(), false, "artifact");
        when(publications.read(ACTIVE)).thenReturn(composed(ACTIVE, "gv-legacy", "gv-native-1"));
        when(publications.read("gv-1")).thenReturn(composed("gv-1", "gv-legacy", "gv-native-1", "gv-native-2"));

        service.activateImported(IMPORTED, NOW, "auto-1");

        // The base's sources and the target's sources, as original versions: the carry writes only to gv-native-2.
        verify(carry).carry(List.of("gv-legacy", "gv-native-1"), List.of("gv-legacy", "gv-native-1", "gv-native-2"), "system");
    }

    private static Publication composed(String versionId, String... sources) {
        var snapshot = fixtureSnapshot();
        List<Contribution> contributions = java.util.Arrays.stream(sources)
                .map(source -> new Contribution(source, "source-" + source, "native", null, null, snapshot, null)).toList();
        return new Publication(versionId, "pub-" + versionId, null, null, null, null, null, snapshot, contributions, null,
                Map.of(), Map.of());
    }

    @Test
    void theSystemActivationCarriesUnderItsOwnActorAndAFixtureOrAMissingStoreCarriesNothing() {
        when(versions.active()).thenReturn(Optional.of(new GraphVersionRecord(ACTIVE, 2, "snapshot", "artifact-active",
                "artifact://active.json", "c".repeat(64), true)));
        when(snapshots.load(IMPORTED)).thenReturn(fixtureSnapshot());
        when(evidence.prepareGraphActivation(eq("gv-1"), anyMap(), eq("auto-1"))).thenReturn(at -> { });
        when(versions.activateBySystem(eq("gv-1"), eq(ACTIVE), eq(NOW), eq(AdminGraphVersionService.AUTO_REASON), any()))
                .thenAnswer(invocation -> {
                    invocation.<Supplier<Consumer<Instant>>>getArgument(4).get().accept(LATER);
                    return Optional.of(new Activation(ACTIVE, true, LATER));
                });
        service(storeExists(), false, "artifact").activateImported(IMPORTED, NOW, "auto-1");
        verify(carry).carry(List.of(ACTIVE), List.of("gv-1"), "system");

        // Without a store (operator opt-in) there is nothing to carry from or to.
        service(noStore(), true, "artifact").activateImported(IMPORTED, NOW, "auto-1");
        verify(carry, times(1)).carry(any(), any(), any());

        // A fixture gets no rights checks and no carry.
        claim("fixture-2026-10-01", ACTIVE, "rollback");
        when(versions.find("fixture-2026-10-01")).thenReturn(Optional.of(FIXTURE));
        when(snapshots.load(FIXTURE)).thenReturn(fixtureSnapshot());
        activating("fixture-2026-10-01", ACTIVE, "rollback", new Activation(ACTIVE, true, LATER));
        service(storeExists(), false).activate("fixture-2026-10-01", request("rollback", ACTIVE), "key-1", ADMIN, "r");
        verify(carry, times(1)).carry(any(), any(), any());
    }
}
