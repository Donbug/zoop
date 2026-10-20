package com.zoop.graph.importer;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.HexFormat;
import java.util.List;
import java.util.function.Function;
import java.util.stream.Stream;

import com.zoop.artifact.storage.ArtifactFileStore;
import com.zoop.common.json.Canonical;
import com.zoop.document.analysis.repository.EvidenceRow;
import com.zoop.document.importer.IngestionExportParser;
import com.zoop.document.importer.Observation;
import com.zoop.document.repository.ArtifactRow;
import com.zoop.document.service.InMemoryDocumentRegistry;
import com.zoop.graph.importer.GraphHandoffResult.Outcome;
import com.zoop.graph.importer.GraphHandoffResult.Staged;
import com.zoop.graph.importer.HandoffFixtures.Built;
import com.zoop.graph.importer.HandoffFixtures.FakeHandoff;
import com.zoop.graph.importer.HandoffFixtures.FakeIngestion;
import com.zoop.graph.importer.HandoffFixtures.Spec;
import com.zoop.graph.snapshot.GraphSnapshotCodec;
import com.zoop.graph.snapshot.PublicGraphSnapshot;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.transaction.TransactionStatus;
import org.springframework.transaction.TransactionSystemException;
import org.springframework.transaction.support.TransactionCallback;
import org.springframework.transaction.support.TransactionOperations;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.node.ObjectNode;

import static com.zoop.graph.importer.HandoffFixtures.ARTICLE_ID;
import static com.zoop.graph.importer.HandoffFixtures.ARTICLE_VERSION;
import static com.zoop.graph.importer.HandoffFixtures.BASIS;
import static com.zoop.graph.importer.HandoffFixtures.COMPANY_A;
import static com.zoop.graph.importer.HandoffFixtures.COMPANY_B;
import static com.zoop.graph.importer.HandoffFixtures.EVENT;
import static com.zoop.graph.importer.HandoffFixtures.GEO;
import static com.zoop.graph.importer.HandoffFixtures.HANDOFF_ID;
import static com.zoop.graph.importer.HandoffFixtures.ISSUE;
import static com.zoop.graph.importer.HandoffFixtures.SELECTOR;
import static com.zoop.graph.importer.HandoffFixtures.TEXT;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * The whole import with the real strict parsers, the real artifact file store and the real importer; only the two installed
 * CLIs (stand-ins that serve the handoff export and the S2-1 exports) and the database (doubles with relational semantics and a
 * reproduced transaction boundary) are replaced. The real CLIs and PostgreSQL are covered by the operator smoke
 * ({@code api/scripts/graph_handoff_import_smoke.py}) and {@code GraphHandoffImportPostgresIntegrationTest}.
 */
class GraphHandoffImporterTest {
    private static final Instant NOW = Instant.parse("2026-10-17T00:00:00Z");

    @TempDir
    Path temp;
    private Path root;
    private ArtifactFileStore store;
    private InMemoryDocumentRegistry registry;
    private InMemoryGraphHandoffRepository graph;
    private FakeIngestion ingestion;
    private FakeHandoff handoff;
    private Transactions transaction;
    private Built built;
    private GraphHandoffImporter importer;

    /** Spring's transaction boundary for the doubles; {@code failCommitOnce} loses the commit (outcome unknown to the caller). */
    private final class Transactions implements TransactionOperations {
        boolean failCommitOnce;

        @Override
        public <T> T execute(TransactionCallback<T> action) {
            return registry.transactionally(() -> graph.transactionally(() -> {
                T result = action.doInTransaction((TransactionStatus) null);
                if (failCommitOnce) {
                    failCommitOnce = false;
                    throw new TransactionSystemException("commit failed");
                }
                return result;
            }));
        }
    }

    @BeforeEach
    void setUp() throws IOException {
        root = Files.createDirectory(temp.toRealPath().resolve("artifacts"));
        store = ArtifactFileStore.at(root);
        registry = new InMemoryDocumentRegistry();
        graph = new InMemoryGraphHandoffRepository("fixture-active", 2);
        graph.seedCompany(COMPANY_A, "합성기업");
        graph.seedCompany(COMPANY_B, "합성부품");
        HandoffFixtures.seedApp(store, registry, TEXT);
        ingestion = new FakeIngestion();
        built = HandoffFixtures.build();
        handoff = new FakeHandoff(built.envelopeBytes());
        transaction = new Transactions();
        importer = newImporter();
    }

    private GraphHandoffImporter newImporter() {
        return new GraphHandoffImporter(handoff, ingestion, new IngestionExportParser(), store, registry, graph, transaction,
                Clock.fixed(NOW, ZoneOffset.UTC));
    }

    private static GraphHandoffException failure(GraphHandoffResult result) {
        assertFalse(result.succeeded(), "the import should have failed");
        return result.failure();
    }

    private Path snapshotFile(String versionId) {
        return root.resolve("graph_snapshot").resolve(versionId + ".json");
    }

    private Path receiptFile(String versionId) {
        return root.resolve("verification_receipt").resolve(versionId + ".json");
    }

    private static String sha256(byte[] bytes) throws Exception {
        return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes));
    }

    private long fileCount() throws IOException {
        try (Stream<Path> files = Files.walk(root)) {
            return files.filter(Files::isRegularFile).filter(path -> !path.getFileName().toString().startsWith(".")).count();
        }
    }

    /** Nothing the import writes exists: no row, no artifact, no evidence, no file beyond the seeded text. */
    private void assertNothingWritten(InMemoryGraphHandoffRepository.State graphBefore,
            InMemoryDocumentRegistry.State registryBefore, long filesBefore) throws IOException {
        assertEquals(graphBefore, graph.state());
        assertEquals(registryBefore, registry.state());
        assertEquals(filesBefore, fileCount());
        assertFalse(Files.exists(snapshotFile(built.versionId())));
        assertFalse(Files.exists(receiptFile(built.versionId())));
    }

    // ------------------------------------------------------------------------------------------------ the happy path ----

    @Test
    void stagesAnInactiveVersionWithTheRetainedReceiptAndAFormat1Projection() throws Exception {
        GraphHandoffResult result = importer.run(built.request());

        assertTrue(result.succeeded());
        Staged staged = result.staged();
        String versionId = built.versionId();
        assertTrue(versionId.startsWith("gv-") && versionId.length() == 67);
        assertEquals(versionId, "gv-" + sha256(HANDOFF_ID.getBytes(StandardCharsets.UTF_8)));
        assertEquals(Outcome.STAGED, staged.outcome());
        assertEquals(versionId, staged.versionId());
        assertEquals(built.manifestDigest(), staged.manifestDigest());
        assertEquals(built.bundleDigest(), staged.bundleDigest());

        // The version row: a snapshot version, inactive, at app review revision 0, created by the explicit operator.
        var row = graph.findVersion(versionId).orElseThrow();
        assertEquals("snapshot", row.kind());
        assertFalse(row.active());
        assertEquals("operator:operator-a", row.createdBy());
        assertEquals("artifact-" + versionId, row.snapshotArtifactId());
        var inserted = graph.inserted().get(0);
        assertEquals(1, inserted.issueCount());
        assertEquals(2, inserted.relationCount());
        assertEquals(1, inserted.articleCount());
        assertEquals("graph-handoff:" + HANDOFF_ID, inserted.sourceLabel());
        assertEquals(HandoffBundleVerifier.POLICY, inserted.policyVersion());
        assertEquals(NOW, inserted.createdAt());
        // The activation pointer and its history are exactly what they were: the import has no statement that could change them.
        assertEquals("fixture-active", graph.activeVersionId);
        assertEquals(2, graph.activations);
        assertEquals(1, graph.state().versions().size());

        // Both artifacts are registered at their stored files, with the registry's hash and size.
        byte[] snapshotBytes = Files.readAllBytes(snapshotFile(versionId));
        ArtifactRow snapshotRow = registry.findArtifact("artifact-" + versionId).orElseThrow();
        assertEquals("graph_snapshot", snapshotRow.kind());
        assertEquals("artifact-root:graph_snapshot/" + versionId + ".json", snapshotRow.storageUri());
        assertEquals(sha256(snapshotBytes), snapshotRow.sha256());
        assertEquals(snapshotBytes.length, snapshotRow.bytes());
        assertEquals("application/json", snapshotRow.mediaType());
        byte[] receiptBytes = Files.readAllBytes(receiptFile(versionId));
        ArtifactRow receiptRow = registry.findArtifact("artifact-receipt-" + versionId).orElseThrow();
        assertEquals("verification_receipt", receiptRow.kind());
        assertEquals("artifact-root:verification_receipt/" + versionId + ".json", receiptRow.storageUri());
        assertEquals(sha256(receiptBytes), receiptRow.sha256());

        // The receipt retains the COMPLETE original manifest and bundle, and says what the app did not verify.
        JsonNode receipt = HandoffFixtures.parse(receiptBytes);
        assertEquals(built.manifest(), receipt.get("manifest"));
        assertEquals(built.bundle(), receipt.get("bundle"));
        assertEquals(built.manifestDigest(), receipt.get("manifestDigest").stringValue());
        assertEquals(built.bundleDigest(), receipt.get("bundleDigest").stringValue());
        assertEquals("not-verified", receipt.get("appVerification").get("semanticTruth").stringValue());
        assertEquals("none", receipt.get("appVerification").get("activation").stringValue());
        assertEquals("manual-operator-review", receipt.get("appVerification").get("structuralRelations").stringValue());

        // The snapshot uses the current reader's format and preserves the bundle's projected facts.
        PublicGraphSnapshot snapshot = GraphSnapshotCodec.read(snapshotBytes, versionId);
        assertEquals(HANDOFF_ID, snapshot.sourceBundleId());
        assertEquals(2, snapshot.companies().size());
        var company = snapshot.companies().stream().filter(c -> c.companyId().equals(COMPANY_A)).findFirst().orElseThrow();
        assertEquals("합성기업", company.label());
        assertNull(company.brandColor());
        assertNull(company.logoUrl());
        var issue = snapshot.issues().get(0);
        assertEquals(ISSUE, issue.issueId());
        assertEquals("합성 공급 계약", issue.label());
        assertEquals("2026-09-30", issue.eventTime());
        assertEquals("day", issue.timePrecision());
        assertEquals("domestic", issue.geography());
        assertEquals(List.of(ARTICLE_ID), issue.articleIds());
        assertEquals("2026-10-08T00:00:00Z", issue.latestPublishedAt());
        assertEquals(2, issue.evidenceIds().size());
        assertEquals(1, issue.geographyEvidenceIds().size());
        var structural = snapshot.relations().stream().filter(r -> r.relationType().equals("STRUCTURALLY_RELATED_TO"))
                .findFirst().orElseThrow();
        assertEquals(COMPANY_B, structural.target());
        assertEquals("announced", structural.assertionStatus());
        assertEquals(1, structural.basis().size());
        assertEquals("2026-10-16T12:00:00.123456Z", structural.basis().get(0).verifiedAt());
        assertEquals("2026-01-01", structural.basis().get(0).validFrom());
        assertEquals("2026-12-31", structural.basis().get(0).validUntil());
        assertEquals("2026-10-08T00:00:00Z", snapshot.articles().get(0).publishedAt());
        assertEquals(ARTICLE_VERSION, snapshot.articles().get(0).version());
        assertEquals(3, snapshot.evidence().size());

        // The result says in so many words what the version is not.
        JsonNode written = HandoffFixtures.parse(GraphHandoffResultWriter.toBytes(result));
        assertEquals("succeeded", written.get("status").stringValue());
        assertEquals("not-published", written.get("publication").stringValue());
        assertEquals("not-activated", written.get("activation").stringValue());
        assertFalse(written.get("active").booleanValue());
        assertEquals("unsupported", written.get("nextActivation").stringValue());
        assertEquals("quote-integrity-only", written.get("quoteVerification").stringValue());
        assertEquals(1, written.get("provenance").get("relationOrigins").get("manual-operator-review").intValue());
        assertEquals(1, written.get("provenance").get("relationOrigins").get("s3-relation").intValue());
        assertEquals("synthetic", written.get("provenance").get("sourceKind").stringValue());
        assertEquals(3, written.get("evidenceRows").get("registered").intValue());
    }

    @Test
    void theReceiptKeepsTheOriginalMentionsRawWhileTheSnapshotStaysFormat3WithoutMentionValues() throws Exception {
        assertTrue(importer.run(built.request()).succeeded());
        String versionId = built.versionId();

        JsonNode receipt = HandoffFixtures.parse(Files.readAllBytes(receiptFile(versionId)));
        assertEquals("zoop-graph-handoff-bundle-3", receipt.get("bundle").get("schemaVersion").stringValue());
        // The hand-written expectation of the issue's field provenance: the one unanimous mention states every value, and the
        // receipt says so without claiming any value was verified (selection, not fact verification).
        JsonNode provenance = receipt.get("bundle").get("issues").get(0).get("fieldProvenance");
        assertEquals(built.bundle().get("issues").get(0).get("fieldProvenance"), provenance);
        assertEquals("unanimous", provenance.get("selection").stringValue());
        assertEquals("none", provenance.get("verification").stringValue());
        assertEquals(6, provenance.get("sameValueMentions").size());
        for (String field : List.of("title", "action", "target", "eventTime", "period", "assertionStatus")) {
            JsonNode list = provenance.get("sameValueMentions").get(field);
            assertEquals(1, list.size(), field);
            assertEquals(ARTICLE_ID, list.get(0).get("documentId").stringValue(), field);
            assertEquals(ARTICLE_VERSION, list.get(0).get("documentVersion").stringValue(), field);
            assertEquals("m-1", list.get(0).get("mentionId").stringValue(), field);
        }
        JsonNode mentions = receipt.get("bundle").get("issues").get(0).get("mentions");
        assertEquals(built.bundle().get("issues").get(0).get("mentions"), mentions);
        // The hand-written expectation of the fixture's one original mention: its own S2 values, never verified, and the
        // participants exactly as extracted (a mapped company, an unmapped source id, a name without any id).
        assertEquals(1, mentions.size());
        JsonNode mention = mentions.get(0);
        assertEquals("none", mention.get("verification").stringValue());
        assertEquals("m-1", mention.get("mentionId").stringValue());
        assertEquals(ARTICLE_ID, mention.get("documentId").stringValue());
        assertEquals(ARTICLE_VERSION, mention.get("articleVersion").stringValue());
        assertEquals("공급 계약", mention.get("action").stringValue());
        assertEquals("배터리", mention.get("target").stringValue());
        assertEquals("2026-09-30", mention.get("eventTime").stringValue());
        assertEquals("day", mention.get("timePrecision").stringValue());
        assertEquals("announced", mention.get("assertionStatus").stringValue());
        assertFalse(mention.get("background").booleanValue());
        JsonNode participants = mention.get("participants");
        assertEquals(3, participants.size());
        assertEquals(COMPANY_A, participants.get(0).get("companyId").stringValue());
        assertEquals("공급자", participants.get(0).get("role").stringValue());
        assertTrue(participants.get(1).get("companyId").isNull());
        assertEquals("s2-co-unlisted", participants.get(1).get("sourceCompanyId").stringValue());
        assertTrue(participants.get(2).get("sourceCompanyId").isNull() && participants.get(2).get("companyId").isNull());

        // The public read format is unchanged: still format 3, one mention reference per original mention, and not one
        // original mention value (no participant, source company id or role) reached the snapshot.
        byte[] snapshotBytes = Files.readAllBytes(snapshotFile(versionId));
        PublicGraphSnapshot snapshot = GraphSnapshotCodec.read(snapshotBytes, versionId);
        assertEquals(3, snapshot.snapshotFormat());
        assertEquals(PublicGraphSnapshot.FORMAT, snapshot.snapshotFormat());
        assertEquals(1, snapshot.issues().get(0).mentions().size());
        assertEquals(ARTICLE_ID, snapshot.issues().get(0).mentions().get(0).articleId());
        String snapshotText = new String(snapshotBytes, StandardCharsets.UTF_8);
        for (String original : List.of("participants", "sourceCompanyId", "s2-co-a", "미등록 협력사", "이름만 있는 참가자", "공급자",
                "fieldProvenance", "sameValueMentions")) {
            assertFalse(snapshotText.contains(original), original);
        }
    }

    @Test
    void anExportOfAnEarlierBundleSchemaIsAnInvalidBundleAndNothingIsWritten() throws Exception {
        for (String schema : List.of("zoop-graph-handoff-bundle-1", "zoop-graph-handoff-bundle-2")) {
            InMemoryGraphHandoffRepository.State graphBefore = graph.state();
            InMemoryDocumentRegistry.State registryBefore = registry.state();
            long filesBefore = fileCount();
            ObjectNode envelope = built.envelope().deepCopy();
            ObjectNode bundle = (ObjectNode) envelope.get("bundle");
            bundle.put("schemaVersion", schema);
            ObjectNode issue = (ObjectNode) bundle.get("issues").get(0);
            issue.remove("fieldProvenance");
            if (schema.endsWith("-1")) {
                issue.remove("mentions");
            }
            ((ObjectNode) bundle.get("digests")).put("content", HandoffBundleVerifier.contentDigest(bundle));
            ((ObjectNode) envelope.get("receipt")).put("bundleSchema", schema);
            handoff.envelope = Canonical.bytes(envelope);
            GraphHandoffRequest request = new GraphHandoffRequest(HANDOFF_ID, built.manifestDigest(),
                    Canonical.sha256(Canonical.bytes(bundle)), "operator-a");

            GraphHandoffException failure = failure(importer.run(request));

            assertEquals(GraphHandoffFailure.BUNDLE_INVALID, failure.failure(), schema);
            assertEquals(0, ingestion.calls.get(), schema);
            assertEquals(0, graph.writes(), schema);
            assertNothingWritten(graphBefore, registryBefore, filesBefore);
        }
    }

    @Test
    void aHandoffFrozenUnderTheEarlierBundleSchemaIsWithheldAndNothingIsWritten() throws Exception {
        InMemoryGraphHandoffRepository.State graphBefore = graph.state();
        InMemoryDocumentRegistry.State registryBefore = registry.state();
        long filesBefore = fileCount();
        GraphHandoffImporter legacy = new GraphHandoffImporter(handoffId -> {
            throw GraphHandoffException.handoffWithheld("handoff_contract_changed");
        }, ingestion, new IngestionExportParser(), store, registry, graph, transaction, Clock.fixed(NOW, ZoneOffset.UTC));

        GraphHandoffException failure = failure(legacy.run(built.request()));

        assertEquals(GraphHandoffFailure.HANDOFF_WITHHELD, failure.failure());
        assertEquals("handoff_contract_changed", failure.cliCode());
        assertEquals(0, ingestion.calls.get());
        assertNothingWritten(graphBefore, registryBefore, filesBefore);
    }

    @Test
    void evidenceUsesTheAppFormulaCodePointOffsetsAndAnIntegrityOnlyVerification() throws Exception {
        importer.run(built.request());

        String versionId = built.versionId();
        var rows = graph.evidenceRows();
        assertEquals(3, rows.size());
        for (String quote : List.of(EVENT, GEO, BASIS)) {
            int start = TEXT.codePointCount(0, TEXT.indexOf(quote));
            int end = start + quote.codePointCount(0, quote.length());
            // The emoji before the sentences makes UTF-16 offsets differ from code points: the stored offsets are the latter.
            assertNotEquals(TEXT.indexOf(quote), start);
            String id = HandoffBundleVerifier.appEvidenceId(ARTICLE_ID, ARTICLE_VERSION, start, end);
            EvidenceRow row = rows.get(id);
            assertEquals(quote, row.quote());
            assertEquals(start, row.startOffset());
            assertEquals(end, row.endOffset());
            assertEquals(end - start, row.quote().codePointCount(0, row.quote().length()));
            assertEquals(ARTICLE_ID, row.articleId());
            assertEquals(ARTICLE_VERSION, row.articleVersion());
            assertEquals("text-" + ARTICLE_VERSION, row.textArtifactId());
            assertEquals(List.of("loc-1"), row.rawLocatorIds());
            // The verification artifact is the retained receipt, not an AI verdict.
            assertEquals("artifact-receipt-" + versionId, row.verificationArtifactId());
            assertEquals(NOW, row.verifiedAt());
        }
    }

    @Test
    void anIdenticalImportIsAnUnchangedNoOpThatStillChecksRightsAndTheStoredFiles() throws Exception {
        importer.run(built.request());
        InMemoryGraphHandoffRepository.State graphBefore = graph.state();
        InMemoryDocumentRegistry.State registryBefore = registry.state();
        long filesBefore = fileCount();
        Object inode = Files.readAttributes(snapshotFile(built.versionId()), "unix:ino").get("ino");
        int ingestionBefore = ingestion.calls.get();

        GraphHandoffResult again = importer.run(built.request());

        assertTrue(again.succeeded());
        assertEquals(Outcome.UNCHANGED, again.staged().outcome());
        assertEquals("existing", again.staged().snapshot().file());
        assertEquals("existing", again.staged().receipt().file());
        assertEquals(0, again.staged().evidenceRegistered());
        assertEquals(3, again.staged().evidenceExisting());
        assertEquals(graphBefore, graph.state());
        assertEquals(registryBefore, registry.state());
        assertEquals(filesBefore, fileCount());
        assertEquals(inode, Files.readAttributes(snapshotFile(built.versionId()), "unix:ino").get("ino"));
        // Rights are checked again even though nothing is written: a revoked source never "imports" again.
        assertEquals(ingestionBefore + 1, ingestion.calls.get());

        ingestion.refuseAlways("source_unauthorized");
        assertEquals(GraphHandoffFailure.INGESTION_EXPORT_FAILED, failure(importer.run(built.request())).failure());
    }

    @Test
    void anotherHandoffUnderTheSameIdIsAConflictAndNothingIsWritten() throws Exception {
        importer.run(built.request());
        InMemoryGraphHandoffRepository.State graphBefore = graph.state();
        InMemoryDocumentRegistry.State registryBefore = registry.state();
        long filesBefore = fileCount();
        Built other = HandoffFixtures.build(Spec.standard().withCanonicalPin("9".repeat(64)));
        assertNotEquals(built.bundleDigest(), other.bundleDigest());
        handoff.envelope = other.envelopeBytes();

        GraphHandoffResult result = importer.run(other.request());

        assertEquals(GraphHandoffFailure.VERSION_CONFLICT, failure(result).failure());
        assertEquals(graphBefore, graph.state());
        assertEquals(registryBefore, registry.state());
        assertEquals(filesBefore, fileCount());
    }

    // ------------------------------------------------------------------------------------------------ rights -----------

    @Test
    void refusedRightsOfAnyObservationStopTheImportBeforeAnythingIsWritten() throws Exception {
        InMemoryGraphHandoffRepository.State graphBefore = graph.state();
        InMemoryDocumentRegistry.State registryBefore = registry.state();
        long filesBefore = fileCount();
        for (String code : List.of("source_unauthorized", "store_not_allowed", "grant_expired")) {
            ingestion = new FakeIngestion().refuseAlways(code);
            importer = newImporter();

            GraphHandoffException failure = failure(importer.run(built.request()));

            assertEquals(GraphHandoffFailure.INGESTION_EXPORT_FAILED, failure.failure(), code);
            assertEquals(code, failure.cliCode());
            assertEquals(0, failure.observation());
            assertEquals(0, graph.writes());
            assertNothingWritten(graphBefore, registryBefore, filesBefore);
        }
    }

    @Test
    void rightsRevokedAfterTheFirstCheckRollBackEverythingIncludingTheFilesItCreated() throws Exception {
        InMemoryGraphHandoffRepository.State graphBefore = graph.state();
        InMemoryDocumentRegistry.State registryBefore = registry.state();
        long filesBefore = fileCount();
        // One observation: call 1 is the first check, call 2 the recheck before the commit.
        ingestion.refuseFrom(2, "source_unauthorized");

        GraphHandoffResult result = importer.run(built.request());

        GraphHandoffException failure = failure(result);
        assertEquals(GraphHandoffFailure.INGESTION_EXPORT_FAILED, failure.failure());
        assertEquals("source_unauthorized", failure.cliCode());
        assertTrue(graph.writes() > 0, "the rows had been written inside the transaction before the recheck");
        assertNothingWritten(graphBefore, registryBefore, filesBefore);

        // After the rights are back the same import succeeds from a clean slate.
        ingestion = new FakeIngestion();
        importer = newImporter();
        assertEquals(Outcome.STAGED, importer.run(built.request()).staged().outcome());
    }

    @Test
    void aHandoffWithheldBeforeTheCommitRollsBackToo() throws Exception {
        InMemoryGraphHandoffRepository.State graphBefore = graph.state();
        InMemoryDocumentRegistry.State registryBefore = registry.state();
        long filesBefore = fileCount();
        handoff.withholdFrom(2);

        GraphHandoffException failure = failure(importer.run(built.request()));

        assertEquals(GraphHandoffFailure.HANDOFF_WITHHELD, failure.failure());
        assertEquals("source_unauthorized", failure.cliCode());
        assertNothingWritten(graphBefore, registryBefore, filesBefore);
    }

    @Test
    void aWithheldHandoffNeverReachesTheObservationsOrTheDatabase() throws Exception {
        handoff.withholdFrom(1);

        GraphHandoffException failure = failure(importer.run(built.request()));

        assertEquals(GraphHandoffFailure.HANDOFF_WITHHELD, failure.failure());
        assertEquals(0, ingestion.calls.get());
        assertEquals(0, graph.writes());
    }

    @Test
    void theRequestMustPinTheDigestsOfTheCurrentHandoff() throws Exception {
        int seededWrites = registry.writeAttempts();   // the app-side seed (artifact and version rows) counts as writes too
        for (GraphHandoffRequest request : List.of(
                new GraphHandoffRequest(HANDOFF_ID, "0".repeat(64), built.bundleDigest(), "operator-a"),
                new GraphHandoffRequest(HANDOFF_ID, built.manifestDigest(), "0".repeat(64), "operator-a"))) {
            GraphHandoffException failure = failure(importer.run(request));

            assertEquals(GraphHandoffFailure.PIN_MISMATCH, failure.failure());
        }
        assertEquals(0, ingestion.calls.get());
        assertEquals(0, graph.writes());
        assertEquals(seededWrites, registry.writeAttempts());
    }

    @Test
    void anObservationThatTheCliNowExportsDifferentlyIsRefused() throws Exception {
        Function<Observation, byte[]> changedRevision = observation -> HandoffFixtures.ingestionExport(SELECTOR, TEXT,
                "합성 제목", "https://example.invalid/a", HandoffFixtures.PUBLISHED_AT, "operator-grant", "rights-2");
        Function<Observation, byte[]> changedTitle = observation -> HandoffFixtures.ingestionExport(SELECTOR, TEXT,
                "다른 제목", "https://example.invalid/a", HandoffFixtures.PUBLISHED_AT, "operator-grant", "rights-1");
        Function<Observation, byte[]> changedTime = observation -> HandoffFixtures.ingestionExport(SELECTOR, TEXT,
                "합성 제목", "https://example.invalid/a", null, "operator-grant", "rights-1");
        for (Function<Observation, byte[]> serve : List.of(changedRevision, changedTitle, changedTime)) {
            ingestion.serve = serve;

            assertEquals(GraphHandoffFailure.OBSERVATION_MISMATCH, failure(importer.run(built.request())).failure());
        }
        assertEquals(0, graph.writes());
    }

    // ------------------------------------------------------------------------------------------------ app side ----------

    @Test
    void evidenceThatCollidesWithADifferentStoredRowRefusesTheWholeImportAtomically() throws Exception {
        String last = built.evidenceIds().get(built.evidenceIds().size() - 1);
        // The stored row has the app-formula id of the last span but a different quote: nothing may merge with it.
        EvidenceRow squatter = new EvidenceRow(last, ARTICLE_ID, ARTICLE_VERSION, "text-" + ARTICLE_VERSION, "다른 인용",
                0, 5, List.of("loc-1"), "artifact-other", NOW, NOW);
        graph.seedEvidence(squatter);
        InMemoryGraphHandoffRepository.State graphBefore = graph.state();
        InMemoryDocumentRegistry.State registryBefore = registry.state();
        long filesBefore = fileCount();

        GraphHandoffResult result = importer.run(built.request());

        assertEquals(GraphHandoffFailure.EVIDENCE_COLLISION, failure(result).failure());
        // The earlier spans were inserted before the collision was met; the rollback took them out again.
        assertTrue(graph.writes() >= 1, "at least one evidence row was inserted before the collision");
        assertEquals(1, graph.evidenceRows().size());
        assertEquals(squatter, graph.evidenceRows().get(last));
        assertNothingWritten(graphBefore, registryBefore, filesBefore);
    }

    @Test
    void anIdenticalExistingEvidenceRowIsReusedNotDuplicated() throws Exception {
        importer.run(built.request());
        EvidenceRow existing = graph.evidenceRows().values().iterator().next();
        // A second handoff (another id) citing the same spans reuses the rows: same ids, same content.
        Built second = HandoffFixtures.build(Spec.standard().withHandoffId("handoff-unit-2"));
        handoff.envelope = second.envelopeBytes();

        GraphHandoffResult result = importer.run(second.request());

        assertTrue(result.succeeded());
        assertEquals(Outcome.STAGED, result.staged().outcome());
        assertEquals(0, result.staged().evidenceRegistered());
        assertEquals(3, result.staged().evidenceExisting());
        assertEquals(3, graph.evidenceRows().size());
        assertEquals(existing, graph.evidenceRows().get(existing.id()));
        assertEquals(2, graph.state().versions().size());
    }

    @Test
    void evidenceOffsetsAreCodePointsNeverUtf16Units() throws Exception {
        // The producer would have to be wrong for this: it states UTF-16 offsets and the hash of that (different) substring.
        Built wrong = HandoffFixtures.build(Spec.standard().withUtf16Offsets());
        handoff.envelope = wrong.envelopeBytes();

        GraphHandoffResult result = importer.run(wrong.request());

        assertEquals(GraphHandoffFailure.EVIDENCE_INVALID, failure(result).failure());
        assertEquals(0, graph.writes());
    }

    @Test
    void theAppSideMustMatchTheBundle() throws Exception {
        // A different stored text: the app's article is not the document the bundle quotes.
        reseed("다른 본문입니다", "합성 제목", "available");
        assertEquals(GraphHandoffFailure.TEXT_MISMATCH, failure(importer.run(built.request())).failure());

        // A different title on the registered version.
        reseed(TEXT, "다른 제목", "available");
        assertEquals(GraphHandoffFailure.ARTICLE_MISMATCH, failure(importer.run(built.request())).failure());

        // A private or deleted article is never staged.
        for (String access : List.of("private", "deleted")) {
            reseed(TEXT, "합성 제목", access);
            assertEquals(GraphHandoffFailure.ARTICLE_MISMATCH, failure(importer.run(built.request())).failure(), access);
        }

        // An article that was never imported.
        registry = new InMemoryDocumentRegistry();
        importer = newImporter();
        assertEquals(GraphHandoffFailure.ARTICLE_UNREGISTERED, failure(importer.run(built.request())).failure());
        assertEquals(0, graph.writes());
    }

    private void reseed(String text, String title, String access) throws IOException {
        reseed(text, title, access, Instant.parse("2026-10-08T00:00:00Z"), "datetime");
    }

    /** A fresh artifact root and registry holding one article version stored as given (the old ones are left behind). */
    private void reseed(String text, String title, String access, Instant publishedAt, String precision) throws IOException {
        Path other = Files.createTempDirectory(temp, "root");
        store = ArtifactFileStore.at(other.toRealPath());
        root = other.toRealPath();
        registry = new InMemoryDocumentRegistry();
        HandoffFixtures.seedApp(store, registry, text, title, access, publishedAt, precision);
        importer = newImporter();
    }

    @Test
    void companiesMustExistWithTheBundlesLabelAndNeverShareAnIdWithAnIssue() throws Exception {
        graph = new InMemoryGraphHandoffRepository("fixture-active", 2);
        graph.seedCompany(COMPANY_A, "다른 이름");
        graph.seedCompany(COMPANY_B, "합성부품");
        importer = newImporter();
        assertEquals(GraphHandoffFailure.COMPANY_MISMATCH, failure(importer.run(built.request())).failure());

        graph = new InMemoryGraphHandoffRepository("fixture-active", 2);
        graph.seedCompany(COMPANY_A, "합성기업");
        importer = newImporter();
        assertEquals(GraphHandoffFailure.COMPANY_MISMATCH, failure(importer.run(built.request())).failure());

        graph = new InMemoryGraphHandoffRepository("fixture-active", 2);
        graph.seedCompany(COMPANY_A, "합성기업");
        graph.seedCompany(COMPANY_B, "합성부품");
        graph.seedCompany(ISSUE, "이슈와 같은 id");
        importer = newImporter();
        assertEquals(GraphHandoffFailure.COMPANY_MISMATCH, failure(importer.run(built.request())).failure());
        assertEquals(0, graph.writes());
    }

    @Test
    void unknownNullValidityStaysNullAndNeverBecomesForever() throws Exception {
        Built unknown = HandoffFixtures.build(Spec.standard().withValidity(null, null));
        handoff.envelope = unknown.envelopeBytes();

        GraphHandoffResult result = importer.run(unknown.request());

        assertTrue(result.succeeded());
        PublicGraphSnapshot snapshot = GraphSnapshotCodec.read(Files.readAllBytes(snapshotFile(unknown.versionId())),
                unknown.versionId());
        var basis = snapshot.relations().stream().filter(r -> r.relationType().equals("STRUCTURALLY_RELATED_TO"))
                .findFirst().orElseThrow().basis().get(0);
        assertNull(basis.validFrom());
        assertNull(basis.validUntil());
    }

    @Test
    void aTimeThatCannotBeWrittenWithItsStatedPrecisionIsRefusedNotInvented() throws Exception {
        // A month claimed as a day, an hour-only time, a week date: none of them may become a date or a midnight.
        for (Spec spec : List.of(Spec.standard().withEvent("2026-09", "day"), Spec.standard().withEvent("2026-09-30", "year"),
                Spec.standard().withValidity("2026-W40-1", null), Spec.standard().withValidity(null, "2026-12"),
                Spec.standard().withEvent("2026-09-30T09", "datetime"))) {
            Built unsupported = HandoffFixtures.build(spec);
            handoff.envelope = unsupported.envelopeBytes();

            assertEquals(GraphHandoffFailure.TEMPORAL_UNSUPPORTED, failure(importer.run(unsupported.request())).failure(),
                    spec.toString());
        }
        assertEquals(0, graph.writes());
    }

    @Test
    void anUnknownPublicationTimeStaysNullAndTheIssueNeverCountsBeforeAnAsOf() throws Exception {
        ingestion.serve = observation -> HandoffFixtures.ingestionExport(SELECTOR, TEXT, "합성 제목",
                "https://example.invalid/a", null, "operator-grant", "rights-1");
        Built unknown = HandoffFixtures.build(Spec.standard().withPublication(null, "unknown"));
        handoff.envelope = unknown.envelopeBytes();
        reseed(TEXT, "합성 제목", "available", null, "unknown");

        GraphHandoffResult result = importer.run(unknown.request());

        assertTrue(result.succeeded(), () -> String.valueOf(result.failure() == null ? null : result.failure().failure()));
        PublicGraphSnapshot snapshot = GraphSnapshotCodec.read(Files.readAllBytes(snapshotFile(unknown.versionId())),
                unknown.versionId());
        assertNull(snapshot.articles().get(0).publishedAt());
        assertNull(snapshot.issues().get(0).latestPublishedAt());
    }

    // ------------------------------------------------------------------------------------------------ operation ----------

    @Test
    void aHeldArtifactLockIsBusyWithoutAnyCall() throws Exception {
        try (ArtifactFileStore.Session held = store.open()) {
            GraphHandoffResult result = importer.run(built.request());

            assertEquals(GraphHandoffFailure.IMPORT_BUSY, failure(result).failure());
        }
        assertEquals(0, handoff.calls.get());
        assertEquals(0, ingestion.calls.get());
        assertEquals(0, graph.writes());
    }

    @Test
    void anUnknownCommitOutcomeKeepsTheFilesAndTheNextRunAdoptsThem() throws Exception {
        transaction.failCommitOnce = true;

        GraphHandoffResult lost = importer.run(built.request());

        assertEquals(GraphHandoffFailure.DATABASE_UNAVAILABLE, failure(lost).failure());
        // The rows did not commit, but the commit's outcome was unknown to the importer: the files stay (they may belong to
        // committed rows), exactly as in the document import.
        assertTrue(Files.exists(snapshotFile(built.versionId())));
        assertTrue(Files.exists(receiptFile(built.versionId())));
        assertTrue(graph.state().versions().isEmpty());
        assertTrue(registry.state().artifacts().keySet().stream().noneMatch(id -> id.startsWith("artifact-")));

        GraphHandoffResult next = importer.run(built.request());

        assertTrue(next.succeeded());
        assertEquals(Outcome.STAGED, next.staged().outcome());
        assertEquals("existing", next.staged().snapshot().file());
        assertEquals("existing", next.staged().receipt().file());
        assertEquals(1, graph.state().versions().size());
    }

    @Test
    void aDifferentFileAtTheSnapshotNameIsAConflictAndStaysUntouched() throws Exception {
        Files.createDirectory(root.resolve("graph_snapshot"), java.nio.file.attribute.PosixFilePermissions.asFileAttribute(
                java.nio.file.attribute.PosixFilePermissions.fromString("rwx------")));
        Path planted = Files.writeString(snapshotFile(built.versionId()), "tampered");
        Files.setPosixFilePermissions(planted, java.nio.file.attribute.PosixFilePermissions.fromString("rw-------"));
        InMemoryGraphHandoffRepository.State graphBefore = graph.state();
        InMemoryDocumentRegistry.State registryBefore = registry.state();

        GraphHandoffResult result = importer.run(built.request());

        assertEquals(GraphHandoffFailure.ARTIFACT_FILE_CONFLICT, failure(result).failure());
        assertEquals("tampered", Files.readString(planted));
        assertEquals(graphBefore, graph.state());
        assertEquals(registryBefore, registry.state());
        assertFalse(Files.exists(receiptFile(built.versionId())));
    }

    // ------------------------------------------------------------------------------------------------ review regressions --

    /** The evidence row the import would register for one cited sentence, as it could already be stored (verification given). */
    private static EvidenceRow storedFor(String quote, String verificationArtifactId, Instant verifiedAt) {
        int start = TEXT.codePointCount(0, TEXT.indexOf(quote));
        int end = start + quote.codePointCount(0, quote.length());
        return new EvidenceRow(HandoffBundleVerifier.appEvidenceId(ARTICLE_ID, ARTICLE_VERSION, start, end), ARTICLE_ID,
                ARTICLE_VERSION, "text-" + ARTICLE_VERSION, quote, start, end, List.of("loc-1"), verificationArtifactId,
                verifiedAt, NOW);
    }

    @Test
    void anArticleWithdrawnDuringTheFinalRecheckIsRefusedAndRolledBack() throws Exception {
        InMemoryGraphHandoffRepository.State graphBefore = graph.state();
        InMemoryDocumentRegistry.State registryBefore = registry.state();
        long filesBefore = fileCount();
        // Call 1 is the first check, call 2 the recheck inside the transaction: the article becomes private exactly then.
        ingestion.before(2, () -> registry.setAccessStatus(ARTICLE_ID, "private"));

        GraphHandoffResult result = importer.run(built.request());

        assertEquals(GraphHandoffFailure.ARTICLE_MISMATCH, failure(result).failure());
        assertNothingWritten(graphBefore, registryBefore, filesBefore);
    }

    @Test
    void anExistingUnverifiedEvidenceRowWithTheSameContentIsACollisionNotReused() throws Exception {
        // Same id, quote, offsets, text and locators, but no verification at all (valid schema: quote_verified NULL).
        EvidenceRow unverified = storedFor(EVENT, null, null);
        graph.seedEvidence(unverified);
        InMemoryGraphHandoffRepository.State graphBefore = graph.state();
        InMemoryDocumentRegistry.State registryBefore = registry.state();
        long filesBefore = fileCount();

        GraphHandoffResult result = importer.run(built.request());

        assertEquals(GraphHandoffFailure.EVIDENCE_COLLISION, failure(result).failure());
        // The unverified row is neither reused nor repaired by an UPDATE.
        assertEquals(unverified, graph.evidenceRows().get(unverified.id()));
        assertNothingWritten(graphBefore, registryBefore, filesBefore);
    }

    @Test
    void aRetryAfterAnUnknownCommitOutcomeReproducesTheFilesOfTheFirstAttemptByteForByte() throws Exception {
        transaction.failCommitOnce = true;
        assertEquals(GraphHandoffFailure.DATABASE_UNAVAILABLE, failure(importer.run(built.request())).failure());
        byte[] firstSnapshot = Files.readAllBytes(snapshotFile(built.versionId()));
        byte[] firstReceipt = Files.readAllBytes(receiptFile(built.versionId()));
        // The catalog may change between the attempts (same ids and names here; display values are not in the snapshot at all).
        graph.seedCompany(COMPANY_A, "합성기업");

        GraphHandoffResult retry = importer.run(built.request());

        assertTrue(retry.succeeded(), () -> String.valueOf(retry.failure() == null ? null : retry.failure().failure()));
        assertEquals("existing", retry.staged().snapshot().file());
        assertEquals("existing", retry.staged().receipt().file());
        assertEquals(new String(firstSnapshot, StandardCharsets.UTF_8),
                new String(Files.readAllBytes(snapshotFile(built.versionId())), StandardCharsets.UTF_8));
        assertEquals(new String(firstReceipt, StandardCharsets.UTF_8),
                new String(Files.readAllBytes(receiptFile(built.versionId())), StandardCharsets.UTF_8));
        // The snapshot is a function of the verified bundle alone: companies carry their id and label, no catalog appearance.
        for (JsonNode company : HandoffFixtures.parse(firstSnapshot).get("companies").values()) {
            assertEquals(java.util.Set.of("companyId", "label"), java.util.Set.copyOf(company.propertyNames()));
        }
    }

    @Test
    void anExistingEvidenceRowThatIsNotTheVerifiedBodyCitationOfThisSpanIsACollision() throws Exception {
        EvidenceRow content = storedFor(EVENT, "artifact-receipt-gv-earlier", NOW);
        String id = content.id();
        GraphHandoffRepository.StoredEvidence valid = new GraphHandoffRepository.StoredEvidence(content, "unicode_code_point", "body",
                null, Boolean.TRUE, "verification_receipt");
        List<GraphHandoffRepository.StoredEvidence> collisions = List.of(
                new GraphHandoffRepository.StoredEvidence(content, "unicode_code_point", "summary", "analysis-1", Boolean.TRUE,
                        "verification_receipt"),
                new GraphHandoffRepository.StoredEvidence(content, "unicode_code_point", "body", "analysis-1", Boolean.TRUE,
                        "verification_receipt"),
                new GraphHandoffRepository.StoredEvidence(content, "utf16_code_unit", "body", null, Boolean.TRUE, "verification_receipt"),
                new GraphHandoffRepository.StoredEvidence(content, "unicode_code_point", "body", null, null, "verification_receipt"),
                new GraphHandoffRepository.StoredEvidence(content, "unicode_code_point", "body", null, Boolean.FALSE, "verification_receipt"),
                // verified by an S1 exact receipt (the document-analysis convention), not by a graph verification_receipt
                new GraphHandoffRepository.StoredEvidence(content, "unicode_code_point", "body", null, Boolean.TRUE, "exact_receipt"),
                new GraphHandoffRepository.StoredEvidence(content, "unicode_code_point", "body", null, Boolean.TRUE, null),
                new GraphHandoffRepository.StoredEvidence(storedFor(EVENT, "artifact-receipt-gv-earlier", null), "unicode_code_point",
                        "body", null, Boolean.TRUE, "verification_receipt"));
        for (GraphHandoffRepository.StoredEvidence stored : collisions) {
            graph = new InMemoryGraphHandoffRepository("fixture-active", 2);
            graph.seedCompany(COMPANY_A, "합성기업");
            graph.seedCompany(COMPANY_B, "합성부품");
            graph.seedEvidence(stored);
            importer = newImporter();
            InMemoryGraphHandoffRepository.State graphBefore = graph.state();
            InMemoryDocumentRegistry.State registryBefore = registry.state();
            long filesBefore = fileCount();

            GraphHandoffResult result = importer.run(built.request());

            assertEquals(GraphHandoffFailure.EVIDENCE_COLLISION, failure(result).failure(), stored.toString());
            assertEquals(stored, graph.state().evidence().get(id), "a stored row is never repaired");
            assertNothingWritten(graphBefore, registryBefore, filesBefore);
        }

        // The same row, verified body citation of an EARLIER handoff's receipt, is the legitimate reuse.
        graph = new InMemoryGraphHandoffRepository("fixture-active", 2);
        graph.seedCompany(COMPANY_A, "합성기업");
        graph.seedCompany(COMPANY_B, "합성부품");
        graph.seedEvidence(valid);
        importer = newImporter();
        GraphHandoffResult reuse = importer.run(built.request());
        assertTrue(reuse.succeeded());
        assertEquals(1, reuse.staged().evidenceExisting());
        assertEquals(2, reuse.staged().evidenceRegistered());
        assertEquals(valid, graph.state().evidence().get(id));
    }

    @Test
    void anArticleDeletedOrPrivateAtTheLockIsRefusedBeforeAnythingIsWritten() throws Exception {
        for (String access : List.of("private", "deleted")) {
            reseed(TEXT, "합성 제목", access);
            InMemoryGraphHandoffRepository.State graphBefore = graph.state();
            InMemoryDocumentRegistry.State registryBefore = registry.state();

            assertEquals(GraphHandoffFailure.ARTICLE_MISMATCH, failure(importer.run(built.request())).failure(), access);
            assertEquals(graphBefore, graph.state());
            assertEquals(registryBefore, registry.state());
            assertEquals(0, graph.writes());
        }
    }
}
