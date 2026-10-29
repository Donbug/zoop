package com.zoop.graph.importer;

import static com.zoop.graph.importer.HandoffFixtures.COMPANY_A;
import static com.zoop.graph.importer.HandoffFixtures.COMPANY_B;
import static com.zoop.graph.importer.HandoffFixtures.TEXT;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Optional;

import com.zoop.artifact.storage.ArtifactFileStore;
import com.zoop.document.importer.IngestionExportParser;
import com.zoop.document.service.InMemoryDocumentRegistry;
import com.zoop.graph.importer.HandoffFixtures.Built;
import com.zoop.graph.importer.HandoffFixtures.FakeHandoffRead;
import com.zoop.graph.importer.HandoffFixtures.FakeIngestion;
import com.zoop.graph.round.GraphRound;
import com.zoop.graph.round.GraphRoundEvent;
import com.zoop.graph.round.GraphRoundEvent.Outcome;
import com.zoop.graph.round.GraphRoundImportBridge;
import com.zoop.graph.round.GraphRoundImportLock;
import com.zoop.graph.round.GraphRoundStage;
import com.zoop.graph.round.InMemoryGraphRoundRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.transaction.TransactionStatus;
import org.springframework.transaction.support.TransactionCallback;
import org.springframework.transaction.support.TransactionOperations;

/**
 * R7 through the bridge: the same importer as the operator command, fed by the claimed round row's pins, with the outcome
 * recorded on the row and its timeline under the row's lease token. Lives in the importer package for its fixtures.
 */
class GraphRoundImportBridgeTest {
    private static final Instant NOW = Instant.parse("2026-10-30T00:35:10Z");
    private static final Instant SLOT_1 = Instant.parse("2026-10-30T00:05:00Z");
    private static final Instant SLOT_2 = Instant.parse("2026-10-30T00:35:00Z");
    private static final String ROUND_1 = "round-20261030T0905";
    private static final String ROUND_2 = "round-20261030T0935";
    private static final Duration LEASE = Duration.ofMinutes(10);

    @TempDir
    Path temp;
    private InMemoryDocumentRegistry registry;
    private InMemoryGraphHandoffRepository graph;
    private ArtifactFileStore store;
    private FakeIngestion ingestion;
    private FakeHandoffRead reads;
    private Built built;
    private InMemoryGraphRoundRepository rounds;
    private boolean lockFree = true;
    private int lockAcquired;
    /** Runs at the start of the import transaction: what another instance does while this one imports. */
    private Runnable duringImport = () -> {
    };

    @BeforeEach
    void setUp() throws IOException {
        store = ArtifactFileStore.at(Files.createDirectory(temp.toRealPath().resolve("artifacts")));
        registry = new InMemoryDocumentRegistry();
        graph = new InMemoryGraphHandoffRepository("fixture-active", 2);
        graph.seedCompany(COMPANY_A, "합성기업");
        graph.seedCompany(COMPANY_B, "합성부품");
        HandoffFixtures.seedApp(store, registry, TEXT);
        ingestion = new FakeIngestion();
        built = HandoffFixtures.build();
        reads = new FakeHandoffRead(HandoffFixtures.read(built));
        rounds = new InMemoryGraphRoundRepository();
    }

    private GraphRoundImportBridge bridge(int maxAttempts) {
        TransactionOperations transaction = new TransactionOperations() {
            @Override
            public <T> T execute(TransactionCallback<T> action) {
                duringImport.run();
                return registry.transactionally(() -> graph.transactionally(() -> action.doInTransaction((TransactionStatus) null)));
            }
        };
        GraphHandoffImporter importer = new GraphHandoffImporter(new HttpHandoffSource(reads), ingestion,
                new IngestionExportParser(), store, registry, graph, transaction, Clock.fixed(NOW, ZoneOffset.UTC));
        GraphRoundImportLock lock = () -> {
            if (!lockFree) return Optional.empty();
            lockAcquired++;
            return Optional.of(() -> lockAcquired--);
        };
        return new GraphRoundImportBridge(importer, rounds, lock, "scheduler", Duration.ofMinutes(1), Duration.ofMinutes(5),
                maxAttempts, Clock.fixed(NOW, ZoneOffset.UTC));
    }

    /** A row at handoff_ready with the fixture's pins, claimed by {@code task-a} as the worker would have it. */
    private GraphRound ready(String roundId, Instant slot, int attempts) {
        rounds.seed(roundId, slot, GraphRoundStage.HANDOFF_READY, built.spec().handoffId(), built.manifestDigest(),
                built.bundleDigest(), attempts);
        return claim(roundId);
    }

    private GraphRound claim(String roundId) {
        return rounds.claim(roundId, "task-a", LEASE, NOW).orElseThrow();
    }

    @Test
    void aReadyRoundIsImportedAsAnInactiveVersionAndTheRowRecordsTheVersionAndOutcome() {
        GraphRound claimed = ready(ROUND_2, SLOT_2, 0);

        GraphRound imported = bridge(20).importRound(claimed);

        assertEquals(GraphRoundStage.IMPORTED, imported.stage());
        assertEquals(Optional.of(built.versionId()), imported.graphVersionId());
        assertEquals(0, imported.attempts());
        assertTrue(imported.lease().isEmpty(), "a finished round keeps no lease");
        assertTrue(graph.state().versions().containsKey(built.versionId()));
        List<GraphRoundEvent> events = rounds.events(ROUND_2);
        assertEquals(1, events.size());
        assertEquals(Outcome.ADVANCED, events.get(0).outcome());
        assertEquals(Optional.of("staged"), events.get(0).code());
        assertEquals(built.versionId(), events.get(0).detail().orElseThrow().get("versionId").stringValue());
        assertEquals(1, reads.bundleCalls.get());
        assertEquals(0, lockAcquired, "the import lock is released with the import");

        // The same pins again (a retry after a lost outcome) are unchanged, still an import.
        rounds.seed(ROUND_2, SLOT_2, GraphRoundStage.HANDOFF_READY, built.spec().handoffId(), built.manifestDigest(),
                built.bundleDigest(), 0);
        GraphRound again = bridge(20).importRound(claim(ROUND_2));
        assertEquals(GraphRoundStage.IMPORTED, again.stage());
        assertEquals(Optional.of("unchanged"), rounds.events(ROUND_2).get(1).code());
    }

    @Test
    void anOlderRoundIsNeverImportedAfterANewerOne() {
        GraphRound older = ready(ROUND_1, SLOT_1, 0);
        rounds.seed(ROUND_2, SLOT_2, GraphRoundStage.IMPORTED, "round-20261030T0935", built.manifestDigest(),
                built.bundleDigest(), 0);

        GraphRound skipped = bridge(20).importRound(older);

        assertEquals(GraphRoundStage.SKIPPED, skipped.stage());
        assertEquals(0, reads.bundleCalls.get(), "nothing is read for a superseded round");
        GraphRoundEvent event = rounds.events(ROUND_1).get(0);
        assertEquals(Outcome.SKIPPED, event.outcome());
        assertEquals(Optional.of("skipped_superseded"), event.code());
        assertEquals(ROUND_2, event.detail().orElseThrow().get("supersededBy").stringValue());
    }

    /**
     * The newest round's import committed (its version is registered and linked to the row in the same transaction) but the
     * process stopped before the row reached {@code imported}. The guard reads the link, so the older round is still skipped;
     * the newest round's next attempt completes with {@code unchanged}.
     */
    @Test
    void aVersionCommittedBeforeTheStageChangeStillSupersedesOlderRoundsAndCompletesOnTheNextAttempt() {
        // The newest round as a crash before advance() leaves it: version registered, link in the row, stage still handoff_ready.
        GraphRound newest = ready(ROUND_2, SLOT_2, 0);
        bridge(20).importRound(newest);
        int versions = graph.state().versions().size();
        rounds.seed(ROUND_2, SLOT_2, GraphRoundStage.HANDOFF_READY, built.spec().handoffId(), built.manifestDigest(),
                built.bundleDigest(), built.versionId(), 0);
        assertTrue(graph.state().versions().containsKey(built.versionId()));
        reads.bundleCalls.set(0);

        GraphRound older = ready(ROUND_1, SLOT_1, 0);
        GraphRound skipped = bridge(20).importRound(older);
        assertEquals(GraphRoundStage.SKIPPED, skipped.stage());
        assertEquals(ROUND_2, rounds.events(ROUND_1).get(0).detail().orElseThrow().get("supersededBy").stringValue());
        assertEquals(0, reads.bundleCalls.get(), "the older round's bundle is never read");

        GraphRound completed = bridge(20).importRound(claim(ROUND_2));
        assertEquals(GraphRoundStage.IMPORTED, completed.stage());
        assertEquals(Optional.of(built.versionId()), completed.graphVersionId());
        assertEquals(Optional.of("unchanged"), rounds.events(ROUND_2).get(1).code());
        assertEquals(versions, graph.state().versions().size(), "no second version");
    }

    /** The round's own import committed (version linked) and a newer round was imported meanwhile: it completes, not skips. */
    @Test
    void aRoundWhoseOwnImportCommittedCompletesEvenAfterANewerRoundWasImported() {
        bridge(20).importRound(ready(ROUND_1, SLOT_1, 0));
        int versions = graph.state().versions().size();
        rounds.seed(ROUND_1, SLOT_1, GraphRoundStage.HANDOFF_READY, built.spec().handoffId(), built.manifestDigest(),
                built.bundleDigest(), built.versionId(), 0);
        rounds.seed(ROUND_2, SLOT_2, GraphRoundStage.IMPORTED, "round-20261030T0935", built.manifestDigest(),
                built.bundleDigest(), "gv-other", 0);

        GraphRound completed = bridge(20).importRound(claim(ROUND_1));

        assertEquals(GraphRoundStage.IMPORTED, completed.stage());
        assertEquals(Optional.of(built.versionId()), completed.graphVersionId());
        assertEquals(Optional.of("unchanged"), rounds.events(ROUND_1).get(1).code());
        assertEquals(versions, graph.state().versions().size());
    }

    /** A linked version that is not the one the round's handoff produces: failed before anything is read, no trigger loop. */
    @Test
    void aRoundLinkedToAnotherVersionFailsWithVersionConflictBeforeReading() {
        rounds.seed(ROUND_2, SLOT_2, GraphRoundStage.HANDOFF_READY, built.spec().handoffId(), built.manifestDigest(),
                built.bundleDigest(), "gv-" + "0".repeat(64), 0);

        GraphRound failed = bridge(20).importRound(claim(ROUND_2));

        assertEquals(GraphRoundStage.FAILED, failed.stage());
        assertEquals(Optional.of("import:version_conflict"), failed.failureCode());
        assertEquals(Optional.of("gv-" + "0".repeat(64)), failed.graphVersionId(), "the link is kept for the admin view");
        assertEquals(0, reads.bundleCalls.get());
        GraphRoundEvent event = rounds.events(ROUND_2).get(0);
        assertEquals(built.versionId(), event.detail().orElseThrow().get("versionId").stringValue());
        assertFalse(graph.state().versions().containsKey(built.versionId()));
    }

    /**
     * The lease expired during a long import and another instance took the row. The first instance's link is fenced, so its
     * import rolls back (no version, no file) and it records nothing; the row is returned as the new holder left it. A late
     * wait() of a fenced worker is not recorded either.
     */
    @Test
    void anOutcomeArrivingAfterTheLeaseWasTakenOverIsNotRecordedAndAnImportInFlightRollsBack() throws IOException {
        GraphRound claimed = ready(ROUND_2, SLOT_2, 0);
        long filesBefore = files();
        duringImport = () -> rounds.claim(ROUND_2, "task-b", LEASE, NOW.plus(LEASE).plusSeconds(1)).orElseThrow();

        GraphRound afterwards = bridge(20).importRound(claimed);

        assertEquals(GraphRoundStage.HANDOFF_READY, afterwards.stage());
        assertEquals("task-b", afterwards.lease().orElseThrow().owner());
        assertTrue(afterwards.graphVersionId().isEmpty());
        assertFalse(graph.state().versions().containsKey(built.versionId()), "the import rolled back");
        assertEquals(filesBefore, files(), "the files the import created are removed again");
        assertTrue(rounds.events(ROUND_2).isEmpty(), "nothing is recorded by the fenced worker");

        // The same for the wait path: the lock is held elsewhere, and the row was taken over before the wait is recorded.
        duringImport = () -> {
        };
        lockFree = false;
        GraphRound stale = bridge(20).importRound(claimed);
        assertEquals("task-b", stale.lease().orElseThrow().owner());
        assertEquals(0, stale.attempts());
        assertTrue(rounds.events(ROUND_2).isEmpty());

        // The new holder imports normally.
        lockFree = true;
        GraphRound imported = bridge(20).importRound(rounds.find(ROUND_2).orElseThrow());
        assertEquals(GraphRoundStage.IMPORTED, imported.stage());
        assertTrue(graph.state().versions().containsKey(built.versionId()));
    }

    @Test
    void aWithheldHandoffFailsTheRoundWithTheImportCodeAndTheRoundKeepsItsId() {
        GraphRound claimed = ready(ROUND_2, SLOT_2, 0);
        reads.withholdFrom(1);

        GraphRound failed = bridge(20).importRound(claimed);

        assertEquals(GraphRoundStage.FAILED, failed.stage());
        assertEquals(Optional.of("import:handoff_withheld"), failed.failureCode());
        assertTrue(failed.graphVersionId().isEmpty());
        GraphRoundEvent event = rounds.events(ROUND_2).get(0);
        assertEquals(Outcome.FAILED, event.outcome());
        assertEquals("source_unauthorized", event.detail().orElseThrow().get("code").stringValue());
    }

    @Test
    void aTransientFailureWaitsAndGivesUpAfterTheAttemptBound() throws IOException {
        GraphRound claimed = ready(ROUND_2, SLOT_2, 0);
        // Another operator command holds the artifact store: import_busy, retried after busy-retry-after.
        try (ArtifactFileStore.Session held = store.open()) {
            GraphRound waiting = bridge(20).importRound(claimed);
            assertEquals(GraphRoundStage.HANDOFF_READY, waiting.stage());
            assertEquals(1, waiting.attempts());
            assertEquals(Optional.of(NOW.plus(Duration.ofMinutes(5))), waiting.nextAttemptAt());
            assertEquals("task-a", waiting.lease().orElseThrow().owner(), "a waiting round keeps its lease");
            GraphRoundEvent event = rounds.events(ROUND_2).get(0);
            assertEquals(Outcome.WAITING, event.outcome());
            assertEquals(Optional.of("import:import_busy"), event.code());

            // At the attempt bound the round fails with import_timeout instead of waiting again.
            rounds.seed(ROUND_2, SLOT_2, GraphRoundStage.HANDOFF_READY, built.spec().handoffId(), built.manifestDigest(),
                    built.bundleDigest(), 19);
            GraphRound gaveUp = bridge(20).importRound(claim(ROUND_2));
            assertEquals(GraphRoundStage.FAILED, gaveUp.stage());
            assertEquals(Optional.of("import_timeout"), gaveUp.failureCode());
            assertEquals(20, gaveUp.attempts(), "the exhausted bound stays visible");
        }
    }

    @Test
    void anImportLockHeldElsewhereMakesTheRoundWaitWithoutReadingAnything() {
        GraphRound claimed = ready(ROUND_2, SLOT_2, 0);
        lockFree = false;

        GraphRound waiting = bridge(20).importRound(claimed);

        assertEquals(GraphRoundStage.HANDOFF_READY, waiting.stage());
        assertEquals(1, waiting.attempts());
        assertEquals(Optional.of(NOW.plus(Duration.ofMinutes(5))), waiting.nextAttemptAt());
        assertEquals(Optional.of("import:round_import_busy"), rounds.events(ROUND_2).get(0).code());
        assertEquals(0, reads.bundleCalls.get());
    }

    @Test
    void theBridgeRefusesARoundThatIsNotReadyForImportOrNotClaimed() {
        GraphRound unclaimed = rounds.seed(ROUND_2, SLOT_2, GraphRoundStage.HANDOFF_READY, built.spec().handoffId(),
                built.manifestDigest(), built.bundleDigest(), 0);
        assertThrows(IllegalArgumentException.class, () -> bridge(20).importRound(unclaimed));
        rounds.seed(ROUND_2, SLOT_2, GraphRoundStage.PLAN_READY, null, null, null, 0);
        assertThrows(IllegalStateException.class, () -> bridge(20).importRound(claim(ROUND_2)));
        rounds.seed(ROUND_1, SLOT_1, GraphRoundStage.HANDOFF_READY, null, null, null, 0);
        assertThrows(IllegalStateException.class, () -> bridge(20).importRound(claim(ROUND_1)));
        assertTrue(rounds.events(ROUND_2).isEmpty());
        assertEquals(0, reads.bundleCalls.get());
    }

    private long files() throws IOException {
        try (var walk = Files.walk(temp)) {
            return walk.filter(Files::isRegularFile).filter(path -> !path.getFileName().toString().startsWith(".")).count();
        }
    }
}
