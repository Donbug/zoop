package com.zoop.graph.importer;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.Comparator;
import java.util.HexFormat;
import java.util.List;
import java.util.function.Function;
import java.util.stream.Stream;

import java.util.Optional;
import com.zoop.artifact.storage.ArtifactFileStore;
import com.zoop.common.json.Canonical;
import com.zoop.document.analysis.repository.EvidenceRow;
import com.zoop.document.importer.IngestionExportParser;
import com.zoop.document.importer.Observation;
import com.zoop.document.repository.ArtifactRow;
import com.zoop.document.service.InMemoryDocumentRegistry;
import com.zoop.graph.importer.GraphHandoffRepository.PublicationState;
import com.zoop.graph.importer.GraphHandoffRepository.RuleRow;
import com.zoop.graph.importer.GraphHandoffResult.Outcome;
import com.zoop.document.evidence.repository.EvidenceReadRepository;
import com.zoop.document.evidence.repository.EvidenceView;
import com.zoop.document.evidence.service.DocumentReadSources;
import com.zoop.document.evidence.service.EvidenceArtifactReader;
import com.zoop.document.evidence.service.EvidenceService;
import com.zoop.graph.importer.GraphHandoffResult.Staged;
import com.zoop.graph.importer.HandoffFixtures.Built;
import com.zoop.ai.handoff.HandoffReadClient.HandoffRead;
import com.zoop.ai.handoff.HandoffReadClient;
import com.zoop.graph.importer.HandoffFixtures.FakeHandoff;
import com.zoop.graph.importer.HandoffFixtures.FakeIngestion;
import com.zoop.graph.importer.HandoffFixtures.Shape;
import com.zoop.graph.importer.HandoffFixtures.Spec;
import com.zoop.graph.snapshot.GraphSnapshotCodec;
import com.zoop.graph.read.DisclosureExclusions;
import com.zoop.graph.read.EventController;
import com.zoop.graph.read.EventDetailService;
import com.zoop.graph.read.GraphEvidenceSnapshotReader;
import com.zoop.graph.read.PublicGraphReader;
import com.zoop.graph.snapshot.ArtifactGraphSnapshotStore;
import com.zoop.graph.version.GraphVersionRecord;
import com.zoop.graph.version.GraphVersionRepository;
import com.zoop.graph.version.GraphVersionSelector;
import com.zoop.graph.snapshot.PublicGraphSnapshot;
import com.zoop.graph.publication.GraphPublicationAuthority;
import com.zoop.graph.publication.GraphPublicationReader;
import com.zoop.graph.publication.JdbcGraphPublicationRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.transaction.TransactionStatus;
import org.springframework.transaction.TransactionSystemException;
import org.springframework.transaction.support.TransactionCallback;
import org.springframework.transaction.support.TransactionOperations;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.node.ArrayNode;
import tools.jackson.databind.node.ObjectNode;

import static com.zoop.graph.importer.HandoffFixtures.ARTICLE_ID;
import static com.zoop.graph.importer.HandoffFixtures.ARTICLE_VERSION;
import static com.zoop.graph.importer.HandoffFixtures.BASIS;
import static com.zoop.graph.importer.HandoffFixtures.COMPANY_A;
import static com.zoop.graph.importer.HandoffFixtures.COMPANY_B;
import static com.zoop.graph.importer.HandoffFixtures.COMPANY_M;
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
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

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

    /** {@link #setUp()} again within one test: a new store, registry and database, as if nothing had been imported. */
    private void freshSetUp() throws IOException {
        try (Stream<Path> files = Files.walk(root)) {
            files.sorted(Comparator.reverseOrder()).forEach(path -> path.toFile().delete());
        }
        setUp();
    }

    private GraphHandoffImporter newImporter() {
        return new GraphHandoffImporter(handoff, ingestion, new IngestionExportParser(), store, registry, graph, transaction,
                Clock.fixed(NOW, ZoneOffset.UTC));
    }

    /** The {@code publicationRules} object of the written result file. */
    private static JsonNode rules(GraphHandoffResult result) {
        return HandoffFixtures.parse(GraphHandoffResultWriter.toBytes(result)).get("publicationRules");
    }

    private static GraphHandoffException failure(GraphHandoffResult result) {
        assertFalse(result.succeeded(), "the import should have failed");
        return result.failure();
    }

    private Path snapshotFile(String versionId) {
        return root.resolve("graph_snapshot").resolve(versionId + ".json");
    }

    /** The snapshot file the version registered, found through the registry as the public read finds it (the name carries the rules). */
    private Path storedSnapshotFile(String versionId) {
        String uri = registry.findArtifact("artifact-" + versionId).orElseThrow().storageUri();
        return root.resolve(uri.substring(uri.indexOf(':') + 1));
    }

    private Path receiptFile(String versionId) {
        return root.resolve("verification_receipt").resolve(versionId + ".json");
    }

    /** The bundle's rule-free projection (#55 composition): named by the version alone, whatever the rules. */
    private Path bundleFile(String versionId) {
        return root.resolve("graph_bundle").resolve(versionId + ".json");
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
        assertFalse(Files.exists(bundleFile(built.versionId())));
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
        // The composition (#55): this one bundle, its receipt and its rule-free projection. With no rule enabled the stored
        // snapshot IS that projection, so the composition points at the snapshot artifact and no second file is written.
        assertFalse(Files.exists(bundleFile(versionId)));
        assertTrue(registry.findArtifact("artifact-bundle-" + versionId).isEmpty());
        assertEquals(List.of(new GraphHandoffRepository.Source(0, HANDOFF_ID, "artifact-receipt-" + versionId,
                "artifact-" + versionId)), graph.sources(versionId));
        assertEquals("artifact-" + versionId, staged.bundleSnapshot().artifactId());
        assertEquals("created", staged.bundleSnapshot().file());
        assertEquals(List.of(HANDOFF_ID), staged.sources());

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
        assertEquals("replay", written.get("provenance").get("executionMode").stringValue());
        assertEquals("authored-test", written.get("provenance").get("recordingKind").stringValue());
        assertEquals(1, written.get("provenance").get("approvalBases").get("automatic-verifier").intValue());
        assertFalse(written.get("provenance").get("approvalBases").has("operator-final-approval"));
        assertEquals(3, written.get("evidenceRows").get("registered").intValue());
        assertEquals("artifact-" + versionId, written.get("bundleSnapshot").get("artifactId").stringValue());
        assertEquals("created", written.get("bundleSnapshot").get("file").stringValue());
        assertEquals("[\"" + HANDOFF_ID + "\"]", written.get("composition").get("sources").toString());
        assertEquals(HANDOFF_ID, written.get("composition").get("newSource").stringValue());
    }

    // ------------------------------------------------------------------------------------------------ publication rules ----

    /** Hides the fixture's INVOLVES (one article) and keeps its structural relation, so the issue stays. */
    private static final RuleRow INVOLVES_SINGLE = new RuleRow("involves-single@1",
            "{\"kind\": \"single_source\", \"minSources\": 2, \"relationTypes\": [\"INVOLVES\"]}");
    /** Enabled, readable, and matches nothing in the fixture (its issue is announced). */
    private static final RuleRow CANCELLED_ONLY = new RuleRow("cancelled-only@1",
            "{\"kind\": \"assertion_status\", \"hide\": [\"cancelled\"]}");

    @Test
    void theVersionFixesBothRevisionsAndARuleThatMatchesNothingLeavesTheWritersBytes() throws Exception {
        GraphHandoffResult plainResult = importer.run(built.request());
        assertTrue(plainResult.succeeded());
        assertEquals(HandoffFixtures.parse("""
                {"ruleRevision":0,"reviewRevision":0,"applied":[],"stored":{"issues":1,"relations":2,"articles":1,"evidence":3},
                 "hidden":{"issues":0,"relations":0},"byRule":{}}
                """.getBytes(StandardCharsets.UTF_8)), rules(plainResult), "no rule: what is stored is the bundle");
        byte[] unfiltered = Files.readAllBytes(storedSnapshotFile(built.versionId()));
        var plain = graph.inserted().get(0);
        assertEquals(0, plain.ruleRevision());
        assertEquals(0, plain.reviewRevision());
        assertEquals(List.of(), plain.ruleIds());
        assertEquals(List.of(), graph.versionRules(built.versionId()));

        freshSetUp();
        graph.publication = new PublicationState(7, 4, List.of(CANCELLED_ONLY));
        GraphHandoffResult matchedNothing = importer.run(built.request());
        assertTrue(matchedNothing.succeeded());
        assertEquals(HandoffFixtures.parse("""
                {"ruleRevision":7,"reviewRevision":4,"applied":["cancelled-only@1"],
                 "stored":{"issues":1,"relations":2,"articles":1,"evidence":3},"hidden":{"issues":0,"relations":0},
                 "byRule":{"cancelled-only@1":{"issues":0,"relations":0}}}
                """.getBytes(StandardCharsets.UTF_8)), rules(matchedNothing));

        var inserted = graph.inserted().get(0);
        assertEquals(7, inserted.ruleRevision());
        assertEquals(4, inserted.reviewRevision());
        assertEquals(List.of("cancelled-only@1"), inserted.ruleIds(), "an enabled rule is recorded whether or not it hid anything");
        assertEquals(List.of(CANCELLED_ONLY), graph.versionRules(built.versionId()));
        assertEquals(List.of(1L, 2L, 1L), List.of(inserted.issueCount(), inserted.relationCount(), inserted.articleCount()));
        assertEquals(sha256(unfiltered), sha256(Files.readAllBytes(storedSnapshotFile(built.versionId()))),
                "the same bytes as with no rule at all");
    }

    @Test
    void anEnabledRuleFiltersTheStoredSnapshotWhileTheReceiptAndTheEvidenceRowsKeepTheWholeBundle() throws Exception {
        graph.publication = new PublicationState(3, 0, List.of(INVOLVES_SINGLE));

        GraphHandoffResult result = importer.run(built.request());

        assertTrue(result.succeeded());
        String versionId = built.versionId();
        PublicGraphSnapshot snapshot = GraphSnapshotCodec.read(Files.readAllBytes(storedSnapshotFile(versionId)), versionId);
        assertEquals(List.of("STRUCTURALLY_RELATED_TO"), snapshot.relations().stream().map(r -> r.relationType()).toList());
        assertEquals(List.of(ISSUE), snapshot.issues().stream().map(i -> i.issueId()).toList(),
                "the issue keeps its structural company relation");
        assertEquals(2, snapshot.companies().size(), "companies are the catalogue and always stay");
        // The bundle's rule-free projection keeps both relations in its own artifact: a composition re-filters it under the
        // rules of its own day. (With no rule hiding anything it would be the snapshot artifact itself.)
        byte[] projectionBytes = Files.readAllBytes(bundleFile(versionId));
        PublicGraphSnapshot projection = GraphSnapshotCodec.read(projectionBytes, versionId);
        assertEquals(2, projection.relations().size());
        assertEquals(HANDOFF_ID, projection.sourceBundleId());
        ArtifactRow bundleRow = registry.findArtifact("artifact-bundle-" + versionId).orElseThrow();
        assertEquals("graph_bundle_snapshot", bundleRow.kind());
        assertEquals("artifact-root:graph_bundle/" + versionId + ".json", bundleRow.storageUri());
        assertEquals(sha256(projectionBytes), bundleRow.sha256());
        assertEquals(List.of(new GraphHandoffRepository.Source(0, HANDOFF_ID, "artifact-receipt-" + versionId,
                "artifact-bundle-" + versionId)), graph.sources(versionId));
        assertEquals("artifact-bundle-" + versionId, result.staged().bundleSnapshot().artifactId());
        var inserted = graph.inserted().get(0);
        assertEquals(List.of(1L, 1L, 1L), List.of(inserted.issueCount(), inserted.relationCount(), inserted.articleCount()),
                "the version counts what the stored snapshot holds");
        assertEquals(List.of("involves-single@1"), inserted.ruleIds());
        assertEquals(3, inserted.ruleRevision());
        // The result file says what the rules did; its counts stay the bundle's.
        JsonNode written = HandoffFixtures.parse(GraphHandoffResultWriter.toBytes(result));
        assertEquals(2, written.get("counts").get("relations").intValue());
        JsonNode rules = rules(result);
        assertEquals(3, rules.get("ruleRevision").intValue());
        assertEquals("[\"involves-single@1\"]", rules.get("applied").toString());
        assertEquals(1, rules.get("stored").get("relations").intValue());
        assertEquals(1, rules.get("stored").get("issues").intValue());
        assertEquals(snapshot.evidence().size(), rules.get("stored").get("evidence").intValue());
        assertEquals(1, rules.get("hidden").get("relations").intValue());
        assertEquals(0, rules.get("hidden").get("issues").intValue());
        assertEquals(1, rules.get("byRule").get("involves-single@1").get("relations").intValue());

        // The receipt is the complete bundle and every span is registered: a rule changes the public projection only.
        assertEquals(built.bundle(), HandoffFixtures.parse(Files.readAllBytes(receiptFile(versionId))).get("bundle"));
        assertEquals(3, graph.evidenceRows().size());
        assertEquals(3, HandoffFixtures.parse(GraphHandoffResultWriter.toBytes(result)).get("evidenceRows").get("registered")
                .intValue());
    }

    @Test
    void aRepeatedImportFiltersWithTheRulesItsVersionWasStagedWithWhateverWasSwitchedSince() throws Exception {
        for (List<RuleRow> first : List.of(List.of(INVOLVES_SINGLE), List.<RuleRow>of())) {
            freshSetUp();
            graph.publication = new PublicationState(3, 0, first);
            GraphHandoffResult staged = importer.run(built.request());
            assertTrue(staged.succeeded());
            byte[] stored = Files.readAllBytes(storedSnapshotFile(built.versionId()));

            // The switch flips the rule; the staged version is not this import's to change, only the next version's.
            graph.publication = new PublicationState(4, 0, first.isEmpty() ? List.of(INVOLVES_SINGLE) : List.of());
            GraphHandoffResult again = importer.run(built.request());

            assertTrue(again.succeeded(), first.toString());
            assertEquals(Outcome.UNCHANGED, again.staged().outcome(), first.toString());
            assertEquals(rules(staged), rules(again), "the version's own rules and revisions, never the switched ones");
            assertEquals(1, graph.inserted().size());
            assertEquals(sha256(stored), sha256(Files.readAllBytes(storedSnapshotFile(built.versionId()))));
        }
    }

    @Test
    void anEnabledRuleThisAppCannotReadFailsTheImportBeforeAnythingIsWritten() throws Exception {
        InMemoryGraphHandoffRepository.State graphBefore = graph.state();
        InMemoryDocumentRegistry.State registryBefore = registry.state();
        long filesBefore = fileCount();
        for (RuleRow unreadable : List.of(
                new RuleRow("regex@1", "{\"kind\": \"regex\", \"pattern\": \".*\"}"),
                new RuleRow("too-small@1", "{\"kind\": \"single_source\", \"minSources\": 1, \"relationTypes\": [\"INVOLVES\"]}"),
                new RuleRow("not-a-rule-id", CANCELLED_ONLY.definition()))) {
            graph.publication = new PublicationState(1, 0, List.of(CANCELLED_ONLY, unreadable));

            GraphHandoffException failure = failure(importer.run(built.request()));

            assertEquals(GraphHandoffFailure.RULE_DEFINITION_INVALID, failure.failure(), unreadable.id());
            assertEquals(0, graph.writes(), unreadable.id());
            assertNothingWritten(graphBefore, registryBefore, filesBefore);
        }
    }

    @Test
    void theReceiptKeepsTheOriginalMentionsRawWhileTheSnapshotStaysFormat3WithoutMentionValues() throws Exception {
        assertTrue(importer.run(built.request()).succeeded());
        String versionId = built.versionId();

        JsonNode receipt = HandoffFixtures.parse(Files.readAllBytes(receiptFile(versionId)));
        assertEquals("zoop-graph-handoff-bundle-8", receipt.get("bundle").get("schemaVersion").stringValue());
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
                "fieldProvenance", "sameValueMentions", "fieldVerdicts", "withheld", "operator-field-verdict")) {
            assertFalse(snapshotText.contains(original), original);
        }
        // No operator verdict exists for this issue: nothing was withheld, and "no verdict" is not "verified".
        assertEquals(0, receipt.get("bundle").get("issues").get(0).get("fieldVerdicts").size());
        assertEquals(0, provenance.get("withheld").size());
        assertEquals("2026-09-30", snapshot.issues().get(0).eventTime());
        assertEquals("2026Q3", snapshot.issues().get(0).period());
    }

    @Test
    void importedSupplyScopeReachesRelationHttpOnlyWhileItsBasisIsReadable() throws Exception {
        assertTrue(importer.run(built.request()).succeeded());
        String versionId = built.versionId();
        ReadSide side = readSide(versionId);
        PublicGraphReader publicReader = side.reader();
        EvidenceService evidenceService = side.receipts();
        Path sourceFile = side.sources();
        String sources = side.sourceRegistry();
        // Resolve the display ID using its stable public formula, not the producer's full source relation ID.
        String edgeId = "edge-" + sha256(("STRUCTURALLY_RELATED_TO|" + ISSUE + "|" + COMPANY_B).getBytes(StandardCharsets.UTF_8)).substring(0, 16);
        var service = new com.zoop.graph.read.GraphRelationService(publicReader,
                org.mockito.Mockito.mock(org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate.class),
                new com.zoop.graph.read.GraphStructuralDetailReader(evidenceService));
        var mvc = org.springframework.test.web.servlet.setup.MockMvcBuilders.standaloneSetup(
                new com.zoop.graph.read.GraphRelationController(service))
                .setControllerAdvice(new com.zoop.common.exception.GlobalExceptionHandler())
                .addFilters(new com.zoop.common.request.RequestIdFilter()).build();
        var request = org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get("/api/v1/graph/edges/" + edgeId)
                .param("graphVersion", versionId);
        var response = mvc.perform(request).andExpect(org.springframework.test.web.servlet.result.MockMvcResultMatchers.status().isOk())
                .andExpect(org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath("$.structuralDetails.status").value("available"))
                .andExpect(org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath("$.metadata.partial").value(false))
                .andReturn();
        JsonNode body = HandoffFixtures.parse(response.getResponse().getContentAsByteArray());
        JsonNode sourceRelation = built.bundle().get("relations").values().stream()
                .filter(r -> r.get("type").stringValue().equals("STRUCTURALLY_RELATED_TO")).findFirst().orElseThrow();
        JsonNode link = body.get("structuralDetails").get("paths").get(0).get("links").get(0);
        assertEquals(sourceRelation.get("basis").get(0).get("businessScope"), link.get("businessScope"));
        assertEquals(sourceRelation.get("structuralPath").get("links").get(0).get("supplierCompanyId"), link.get("supplierCompanyId"));
        assertEquals(sourceRelation.get("basis").get(0).get("evidenceIds"), link.get("evidenceIds"));
        // A source grant is checked now, not only when the bundle was imported.
        Files.writeString(sourceFile, sources.replace("\"enabled\":true", "\"enabled\":false"));
        mvc.perform(request).andExpect(status().isNotFound())
                .andExpect(jsonPath("$.error.code").value("RESOURCE_NOT_FOUND"));
        Files.writeString(sourceFile, sources);
        mvc.perform(request).andExpect(org.springframework.test.web.servlet.result.MockMvcResultMatchers.status().isOk())
                .andExpect(org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath("$.structuralDetails.status").value("available"));
        Files.writeString(receiptFile(versionId), "{}");
        mvc.perform(request).andExpect(status().isServiceUnavailable())
                .andExpect(jsonPath("$.error.code").value("SOURCE_UNAVAILABLE"));
    }



    /** The public read side over one imported version, as activated: real snapshot store, receipts and source registry. */
    private record ReadSide(PublicGraphReader reader, EvidenceService receipts, GraphVersionSelector selector, Path sources,
            String sourceRegistry) { }

    private ReadSide readSide(String versionId) throws Exception {
        ArtifactRow snapshot = registry.findArtifact("artifact-" + versionId).orElseThrow();
        GraphVersionRecord version = new GraphVersionRecord(versionId, 3, "snapshot", snapshot.id(),
                snapshot.storageUri(), snapshot.sha256(), true);
        // Only the read-side version port models an activated version; the importer never activates anything.
        GraphVersionRepository versions = mock(GraphVersionRepository.class);
        when(versions.find(versionId)).thenReturn(Optional.of(version));
        when(versions.everActivated(versionId)).thenReturn(true);
        when(versions.firstActivatedAt(versionId)).thenReturn(Optional.of(NOW));
        Clock clock = Clock.fixed(NOW, ZoneOffset.UTC);
        when(versions.active()).thenReturn(Optional.of(version));
        GraphVersionSelector selector = new GraphVersionSelector(versions, clock);
        EvidenceReadRepository evidence = mock(EvidenceReadRepository.class);
        for (EvidenceRow row : graph.evidenceRows().values()) {
            when(evidence.findEvidence(row.id())).thenReturn(Optional.of(new EvidenceView(row.id(), row.articleId(),
                    row.articleVersion(), row.textArtifactId(), row.quote(), row.startOffset(), row.endOffset(),
                    "body", true, row.verificationArtifactId())));
        }
        Path sources = temp.toRealPath().resolve("event-read-sources.json");
        String sourceRegistry = """
                {"schemaVersion":"zoop-ingestion-s2-1","revision":"event-read-1","sources":[{
                  "sourceId":"synthetic-source","adapter":"authored-files","inputRoot":"/synthetic",
                  "allowedHosts":["example.invalid"],"scopes":[{"scopeId":"body","selection":"authored fixture",
                    "initialCursor":null,"articleXPath":null,"timestampLimitations":["authored fixture"]}],
                  "grant":{"grantId":"operator-grant","revision":"rights-1","sourceId":"synthetic-source",
                    "enabled":true,"rights":"known","allowedOperations":["read","store","quote-display"],
                    "recipients":[],"purposes":[],"evidence":["authored synthetic fixture"],"expiresAt":null}}]}
                """;
        Files.writeString(sources, sourceRegistry);
        GraphPublicationReader publications = new GraphPublicationReader(graph, registry, store,
                mock(JdbcGraphPublicationRepository.class));
        PublicGraphReader reader = new PublicGraphReader(selector,
                new ArtifactGraphSnapshotStore(store, registry, null), ignoredVersion -> DisclosureExclusions.NONE,
                publications, new GraphPublicationAuthority(registry, new DocumentReadSources(sources),
                        ignoredVersion -> DisclosureExclusions.NONE, clock));
        EvidenceService receipts = new EvidenceService(evidence, registry, null, new DocumentReadSources(sources),
                new GraphEvidenceSnapshotReader(reader), new EvidenceArtifactReader(store), clock, transaction, publications);
        return new ReadSide(reader, receipts, selector, sources, sourceRegistry);
    }

    @Test
    void aCurrentBundle7ImportIsPublishedForTheCandidateLists() throws Exception {
        // #349 review: the candidate publication state reads the importer's own bundle-7 receipt through the same head gate.
        handoff.envelope = built.envelopeBytes();
        assertTrue(importer.run(built.request()).succeeded());
        String versionId = built.versionId();
        ReadSide side = readSide(versionId);
        var published = new com.zoop.admin.review.PublishedCandidates(side.reader(), side.receipts());

        var shown = published.current("req-published").orElseThrow(() -> new AssertionError("publication state unknown"));

        assertEquals(versionId, shown.versionId());
        assertFalse(shown.events().isEmpty(), "the imported issue's S2 event candidate is published");
        assertTrue(shown.excludedEvents().isEmpty());
        assertFalse(shown.relations().isEmpty(), "the imported relation's S3 candidate is published");

        // Rights withdrawn now: the same receipt's items are hidden, never unknown.
        Files.writeString(side.sources(), side.sourceRegistry().replace("\"enabled\":true", "\"enabled\":false"));
        var withdrawn = new com.zoop.admin.review.PublishedCandidates(side.reader(), side.receipts()).current("req-withdrawn")
                .orElseThrow();
        assertTrue(withdrawn.events().isEmpty());
        assertEquals(shown.events(), withdrawn.excludedEvents());
    }

    @Test
    void aCurrentImportReceiptServesEventMetadataOverTheConsumerRouteWithoutExposingItsSummary() throws Exception {
        Built summarized = HandoffFixtures.withSummary(built, HandoffFixtures::availableSummary);
        handoff.envelope = summarized.envelopeBytes();
        assertTrue(importer.run(summarized.request()).succeeded());
        String versionId = summarized.versionId();
        ReadSide side = readSide(versionId);
        PublicGraphReader reader = side.reader();
        EvidenceService receipts = side.receipts();
        Path sources = side.sources();
        String sourceRegistry = side.sourceRegistry();
        var mvc = org.springframework.test.web.servlet.setup.MockMvcBuilders.standaloneSetup(
                new EventController(null, new EventDetailService(reader, receipts, registry)))
                .setControllerAdvice(new com.zoop.common.exception.GlobalExceptionHandler())
                .addFilters(new com.zoop.common.request.RequestIdFilter()).build();

        mvc.perform(get("/api/v1/events/" + ISSUE).param("graphVersion", versionId))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.id").value(ISSUE))
                .andExpect(jsonPath("$.mentions[0].title").value("합성 공급 계약"))
                .andExpect(jsonPath("$.mentions[0].eventTime").value("2026-09-30"))
                .andExpect(jsonPath("$.sourceSupport.articleCount").value(1))
                .andExpect(jsonPath("$.metadata.graphVersion").value(versionId))
                .andExpect(jsonPath("$.metadata.source").value("public_graph_snapshot"))
                .andExpect(jsonPath("$.metadata.partial").value(true))
                .andExpect(jsonPath("$.metadata.failures[0].code").value("SUMMARY_NOT_PRODUCED"))
                .andExpect(jsonPath("$.summary.status").value("unavailable"))
                .andExpect(jsonPath("$.summary.text").doesNotExist())
                .andExpect(jsonPath("$.approval").isEmpty());

        // The same supported receipt still cannot bypass current source rights or its registry-pinned bytes.
        Files.writeString(sources, sourceRegistry.replace("\"enabled\":true", "\"enabled\":false"));
        mvc.perform(get("/api/v1/events/" + ISSUE).param("graphVersion", versionId))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.error.code").value("RESOURCE_NOT_FOUND"));
        Files.writeString(sources, sourceRegistry);
        Files.writeString(receiptFile(versionId), "{}");
        mvc.perform(get("/api/v1/events/" + ISSUE).param("graphVersion", versionId))
                .andExpect(status().isServiceUnavailable())
                .andExpect(jsonPath("$.error.code").value("SOURCE_UNAVAILABLE"));
    }



    @Test
    void anAvailableSummaryIsRetainedExactlyInTheReceiptAndNeverReachesTheSnapshotOrTheResult() throws Exception {
        Built summarized = HandoffFixtures.withSummary(built, HandoffFixtures::availableSummary);
        handoff.envelope = summarized.envelopeBytes();

        GraphHandoffResult result = importer.run(summarized.request());

        assertTrue(result.succeeded(), () -> String.valueOf(result.failure() == null ? null : result.failure().failure()));
        String versionId = summarized.versionId();
        // The receipt keeps the producer's exact object: every claim, id, digest, identity and the job pin.
        JsonNode retained = HandoffFixtures.parse(Files.readAllBytes(receiptFile(versionId))).get("bundle").get("issues").get(0).get("summary");
        assertEquals(summarized.bundle().get("issues").get(0).get("summary"), retained);
        assertEquals("available", retained.get("status").stringValue());
        assertEquals(HandoffFixtures.SUMMARY_CLAIM, retained.get("text").stringValue());
        assertEquals(HandoffFixtures.SUMMARY_JOB, retained.get("source").get("jobId").stringValue());
        // It is a receipt-only record, not a public snapshot projection: nothing of it is in the snapshot or in the written result.
        byte[] snapshotBytes = Files.readAllBytes(snapshotFile(versionId));
        assertEquals(PublicGraphSnapshot.FORMAT, GraphSnapshotCodec.read(snapshotBytes, versionId).snapshotFormat());
        String snapshotText = new String(snapshotBytes, StandardCharsets.UTF_8);
        String resultText = new String(GraphHandoffResultWriter.toBytes(result), StandardCharsets.UTF_8);
        for (String summaryOnly : List.of(HandoffFixtures.SUMMARY_CLAIM, "resultVersion", "isr-", HandoffFixtures.SUMMARY_JOB, "authored-replay",
                "claims", "basisDigest", "issueSummary")) {
            assertFalse(snapshotText.contains(summaryOnly), "snapshot: " + summaryOnly);
            assertFalse(resultText.contains(summaryOnly), "result: " + summaryOnly);
        }

        // The same pins again: a no-op with the same retained summary.
        assertEquals(Outcome.UNCHANGED, importer.run(summarized.request()).staged().outcome());
    }

    @Test
    void aTemporalPendingOrJobCodedSummaryIsRetainedAsStatedAndANotRequestedOneNeverBecomesAnAvailableOne() throws Exception {
        Built held = HandoffFixtures.build(Spec.standard().withVerdicts());
        handoff.envelope = held.envelopeBytes();

        assertTrue(importer.run(held.request()).succeeded());
        JsonNode retained = HandoffFixtures.parse(Files.readAllBytes(receiptFile(held.versionId()))).get("bundle").get("issues").get(0).get("summary");
        assertEquals("temporal-review-pending", retained.get("code").stringValue());
        assertTrue(retained.get("source").isNull());
        assertFalse(Files.readString(receiptFile(held.versionId())).contains(HandoffFixtures.SUMMARY_CLAIM));
    }

    @Test
    void aTamperedSummaryIsRefusedBeforeAnythingIsWrittenWhateverItsDigestsSay() throws Exception {
        InMemoryGraphHandoffRepository.State graphBefore = graph.state();
        InMemoryDocumentRegistry.State registryBefore = registry.state();
        long filesBefore = fileCount();
        Built summarized = HandoffFixtures.withSummary(built, HandoffFixtures::availableSummary);
        Built held = HandoffFixtures.build(Spec.standard().withVerdicts());
        record Forgery(String rule, Built forged) {
        }
        List<Forgery> forgeries = List.of(
                new Forgery("a claim text edited behind the digests", HandoffFixtures.repinned(summarized,
                        b -> ((ObjectNode) b.get("issues").get(0).get("summary").get("claims").get(0)).put("text", "합성기업이 계약을 취소했다."))),
                new Forgery("a summary text that is not the claims", HandoffFixtures.repinned(summarized,
                        b -> ((ObjectNode) b.get("issues").get(0).get("summary")).put("text", "다른 문장이다."))),
                new Forgery("an evidence id outside the issue's mention quotes", HandoffFixtures.repinned(summarized,
                        b -> ((ObjectNode) b.get("issues").get(0).get("summary").get("claims").get(0)).putArray("evidenceIds")
                                .add("ev-" + "0".repeat(64)))),
                new Forgery("a basis digest of another basis", HandoffFixtures.repinned(summarized,
                        b -> ((ObjectNode) b.get("issues").get(0).get("summary").get("source")).put("basisDigest", "0".repeat(64)))),
                new Forgery("an available summary on an issue whose time field is held", HandoffFixtures.repinned(held,
                        b -> ((ObjectNode) b.get("issues").get(0)).set("summary", HandoffFixtures.availableSummary(b)))),
                new Forgery("not-requested on an issue whose time field is held", HandoffFixtures.repinned(held,
                        b -> ((ObjectNode) b.get("issues").get(0)).set("summary", HandoffFixtures.unavailable("not-requested")))),
                new Forgery("temporal-review-pending on an issue nobody held", HandoffFixtures.repinned(built,
                        b -> ((ObjectNode) b.get("issues").get(0)).set("summary", HandoffFixtures.unavailable("temporal-review-pending")))),
                new Forgery("a replay summary relabelled as a provider's", HandoffFixtures.repinned(summarized,
                        b -> ((ObjectNode) b.get("issues").get(0).get("summary").get("producer")).put("kind", "provider"))));
        for (Forgery forgery : forgeries) {
            handoff.envelope = forgery.forged().envelopeBytes();

            GraphHandoffException failure = failure(importer.run(forgery.forged().request()));

            assertEquals(GraphHandoffFailure.BUNDLE_INVALID, failure.failure(), forgery.rule());
            assertEquals(0, graph.writes(), forgery.rule());
            assertNothingWritten(graphBefore, registryBefore, filesBefore);
        }
    }

    @Test
    void aWithheldEventTimeAndPeriodAreNullInTheSnapshotWhileTheReceiptKeepsTheOriginalsAndTheVerdictEvidence() throws Exception {
        Built reviewed = HandoffFixtures.build(Spec.standard().withVerdicts());
        handoff.envelope = reviewed.envelopeBytes();

        GraphHandoffResult result = importer.run(reviewed.request());

        assertTrue(result.succeeded(), () -> String.valueOf(result.failure() == null ? null : result.failure().failure()));
        String versionId = reviewed.versionId();
        PublicGraphSnapshot snapshot = GraphSnapshotCodec.read(Files.readAllBytes(snapshotFile(versionId)), versionId);
        // The public projection carries the producer's withheld headline: no event time (unknown precision), no period; the other
        // values and the mention reference are untouched.
        var issue = snapshot.issues().get(0);
        assertNull(issue.eventTime());
        assertEquals("unknown", issue.timePrecision());
        assertNull(issue.period());
        assertEquals("합성 공급 계약", issue.label());
        assertEquals("announced", issue.assertionStatus());
        assertEquals(1, issue.mentions().size());
        // The period verdict's evidence is part of the issue's evidence (the basis sentence no mention cites), so the public
        // evidence read finds it through the issue exactly like geography evidence.
        assertEquals(3, issue.evidenceIds().size());
        assertTrue(issue.evidenceIds().containsAll(reviewed.evidenceIds()));

        // The receipt retains the complete original: the mention's values, both verdicts and the withheld list.
        JsonNode receiptIssue = HandoffFixtures.parse(Files.readAllBytes(receiptFile(versionId))).get("bundle").get("issues").get(0);
        assertEquals(reviewed.bundle().get("issues").get(0), receiptIssue);
        JsonNode mention = receiptIssue.get("mentions").get(0);
        assertEquals("2026-09-30", mention.get("eventTime").stringValue());
        assertEquals("day", mention.get("timePrecision").stringValue());
        assertEquals("2026Q3", mention.get("period").stringValue());
        assertEquals(List.of("eventTime", "period"),
                List.of(receiptIssue.get("fieldProvenance").get("withheld").get(0).stringValue(),
                        receiptIssue.get("fieldProvenance").get("withheld").get(1).stringValue()));
        // sameValueMentions still compares the ORIGINAL selected values, never the redacted null.
        assertEquals(1, receiptIssue.get("fieldProvenance").get("sameValueMentions").get("eventTime").size());
        assertEquals(1, receiptIssue.get("fieldProvenance").get("sameValueMentions").get("period").size());
        JsonNode verdicts = receiptIssue.get("fieldVerdicts");
        assertEquals(2, verdicts.size());
        assertEquals("eventTime", verdicts.get(0).get("field").stringValue());
        assertEquals("REJECT", verdicts.get(0).get("decision").stringValue());
        assertEquals("2026-09-30", verdicts.get(0).get("value").stringValue());
        assertEquals("period", verdicts.get(1).get("field").stringValue());
        assertEquals("HOLD", verdicts.get(1).get("decision").stringValue());
        assertEquals("ambiguous", verdicts.get(1).get("reasonCode").stringValue());
        // No review prose and no verdict reached the public snapshot.
        String snapshotText = Files.readString(snapshotFile(versionId));
        for (String leaked : List.of("fieldVerdicts", "contradicted", "ambiguous", "operator-field-verdict", "reviewer-a", "2026Q3")) {
            assertFalse(snapshotText.contains(leaked), leaked);
        }
    }

    @Test
    void aLiveProviderHandoffWithAnOperatorFinalApprovalAndADeclaredOriginIsStagedAsExactlyThatAndStaysStable() throws Exception {
        Built live = HandoffFixtures.build(Spec.standard().withLive().withManualApproval().withOrigin());
        handoff.envelope = live.envelopeBytes();

        GraphHandoffResult result = importer.run(live.request());

        assertTrue(result.succeeded(), () -> String.valueOf(result.failure() == null ? null : result.failure().failure()));
        JsonNode written = HandoffFixtures.parse(GraphHandoffResultWriter.toBytes(result));
        JsonNode provenance = written.get("provenance");
        assertEquals("synthetic", provenance.get("sourceKind").stringValue(), "the source kind is independent of the mode");
        assertEquals("live", provenance.get("executionMode").stringValue());
        assertEquals("provider", provenance.get("recordingKind").stringValue());
        // The edges rest on one operator's final approval, never on a verifier verdict; the structural relation is still the
        // manual operator assertion it always was (a different literal from the approval).
        assertEquals(1, provenance.get("approvalBases").size());
        assertEquals(1, provenance.get("approvalBases").get("operator-final-approval").intValue());
        assertEquals(1, provenance.get("relationOrigins").get("manual-operator-review").intValue());
        assertEquals("manual-operator-review", provenance.get("structuralRelationOrigin").stringValue());

        String versionId = live.versionId();
        JsonNode receipt = HandoffFixtures.parse(Files.readAllBytes(receiptFile(versionId)));
        assertEquals(live.bundle(), receipt.get("bundle"), "the retained receipt holds the complete bundle");
        JsonNode used = receipt.get("bundle").get("sources").get(0).get("reviewUsed").get(0);
        assertEquals("operator-final-approval", used.get("approvalBasis").get("kind").stringValue());
        assertEquals("reviewer-final", used.get("approvalBasis").get("reviewer").stringValue());
        assertEquals(1, used.get("revision").intValue());
        JsonNode involves = receipt.get("bundle").get("relations").get(0);
        assertEquals("INVOLVES", involves.get("type").stringValue());
        assertEquals("manual-operator-final-approval", involves.get("provenance").get("s3SemanticValidation").stringValue());
        assertEquals("audit-metadata-not-a-verifier-verdict",
                receipt.get("appVerification").get("approvalBasis").stringValue());
        JsonNode article = receipt.get("bundle").get("articles").get(0);
        assertEquals(Canonical.sha256(TEXT), article.get("textSha256").stringValue());
        assertEquals("origin-wire-1", article.get("origin").get("originId").stringValue());
        JsonNode support = receipt.get("bundle").get("issues").get(0).get("sourceSupport");
        assertEquals(1, support.get("articleCount").intValue());
        assertEquals(1, support.get("knownLineageCount").intValue(), "lineage groups, not articles");
        assertEquals(1, support.get("independentSourceCount").intValue());

        // The public snapshot stays format 3 and carries neither the approval, the origin nor the support.
        String snapshotText = Files.readString(snapshotFile(versionId));
        assertEquals(3, GraphSnapshotCodec.read(Files.readAllBytes(snapshotFile(versionId)), versionId).snapshotFormat());
        for (String internal : List.of("operator-final-approval", "reviewer-final", "origin-wire-1", "operator-declared-origin",
                "sourceSupport", "knownLineageCount", "textSha256", "approvalBasis")) {
            assertFalse(snapshotText.contains(internal), internal);
        }

        // The same pins again: a no-op, with the same truthful statement.
        GraphHandoffResult again = importer.run(live.request());
        assertEquals(Outcome.UNCHANGED, again.staged().outcome());
        assertEquals(1, again.staged().approvalBases().get("operator-final-approval"));
        assertEquals("live", again.staged().executionMode());
    }

    @Test
    void aSelfConsistentBundleWithForgedBasisCountsGroupsOrTextDigestIsRefusedBeforeAnythingIsWritten() throws Exception {
        InMemoryGraphHandoffRepository.State graphBefore = graph.state();
        InMemoryDocumentRegistry.State registryBefore = registry.state();
        long filesBefore = fileCount();
        Built manual = HandoffFixtures.build(Spec.standard().withManualApproval());
        record Forgery(String rule, Built forged, GraphHandoffFailure expected) {
        }
        List<Forgery> forgeries = List.of(
                new Forgery("a text digest that is not the stored text",
                        HandoffFixtures.repinned(built, b -> ((ObjectNode) b.get("articles").get(0)).put("textSha256", "0".repeat(64))),
                        GraphHandoffFailure.TEXT_MISMATCH),
                new Forgery("a lineage count nobody declared",
                        HandoffFixtures.repinned(built, b -> ((ObjectNode) b.get("issues").get(0).get("sourceSupport"))
                                .put("knownLineageCount", 1)), GraphHandoffFailure.BUNDLE_INVALID),
                new Forgery("independence claimed over an unknown origin",
                        HandoffFixtures.repinned(built, b -> ((ObjectNode) b.get("issues").get(0).get("sourceSupport"))
                                .put("independentSourceCount", 1)), GraphHandoffFailure.BUNDLE_INVALID),
                new Forgery("an invented duplicate group",
                        HandoffFixtures.repinned(built, b -> ((ArrayNode) b.get("issues").get(0).get("sourceSupport")
                                .get("duplicateGroups")).addArray().add(ARTICLE_ID).add(ARTICLE_ID)), GraphHandoffFailure.BUNDLE_INVALID),
                new Forgery("an operator approval relabelled as the verifier's verdict",
                        HandoffFixtures.repinned(manual, b -> ((ObjectNode) b.get("relations").get(0).get("provenance"))
                                .put("s3SemanticValidation", "independent-verifier-supported-all-claims")),
                        GraphHandoffFailure.BUNDLE_INVALID),
                new Forgery("an approval basis at another review revision",
                        HandoffFixtures.repinned(manual, b -> ((ObjectNode) b.get("sources").get(0).get("reviewUsed").get(0)
                                .get("approvalBasis")).put("revision", 7)), GraphHandoffFailure.BUNDLE_INVALID));
        for (Forgery forgery : forgeries) {
            handoff.envelope = forgery.forged().envelopeBytes();

            GraphHandoffException failure = failure(importer.run(forgery.forged().request()));

            assertEquals(forgery.expected(), failure.failure(), forgery.rule());
            assertEquals(0, graph.writes(), forgery.rule());
            assertNothingWritten(graphBefore, registryBefore, filesBefore);
        }
    }

    @Test
    void anExportOfAnEarlierBundleSchemaIsAnInvalidBundleAndNothingIsWritten() throws Exception {
        for (String schema : List.of("zoop-graph-handoff-bundle-1", "zoop-graph-handoff-bundle-2", "zoop-graph-handoff-bundle-3",
                "zoop-graph-handoff-bundle-5", "zoop-graph-handoff-bundle-6")) {
            InMemoryGraphHandoffRepository.State graphBefore = graph.state();
            InMemoryDocumentRegistry.State registryBefore = registry.state();
            long filesBefore = fileCount();
            ObjectNode envelope = built.envelope().deepCopy();
            ObjectNode bundle = (ObjectNode) envelope.get("bundle");
            bundle.put("schemaVersion", schema);
            ObjectNode issue = (ObjectNode) bundle.get("issues").get(0);
            // What each earlier build wrote: -3 has provenance without `withheld` and no verdicts, -2 no provenance, -1 no mentions;
            // -5 has today's issues, so only its schema string marks it as earlier; -6 lacks the issue summary and its policy key.
            if (schema.endsWith("-6")) {
                issue.remove("summary");
                ((ObjectNode) bundle.get("policy")).remove("issueSummary");
            } else if (!schema.endsWith("-5")) {
                issue.remove("fieldVerdicts");
                if (schema.endsWith("-3")) {
                    ((ObjectNode) issue.get("fieldProvenance")).remove("withheld");
                } else {
                    issue.remove("fieldProvenance");
                }
                if (schema.endsWith("-1")) {
                    issue.remove("mentions");
                }
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
        GraphHandoffImporter legacy = new GraphHandoffImporter((HandoffExporter) handoffId -> {
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
        assertEquals("existing", again.staged().bundleSnapshot().file());
        assertEquals(List.of(HANDOFF_ID), again.staged().sources());
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
        graph.seedCompany(COMPANY_A, "다른 이름", "합성기업");
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
        assertEquals("existing", next.staged().bundleSnapshot().file());
        assertEquals(1, graph.state().versions().size());
    }

    @Test
    void aVersionStagedBeforeTheCompositionTableAnswersUnchangedWithoutABundleProjection() throws Exception {
        // Staged under a rule, so the projection is its own artifact; then the migration's backfill shape: one source row per
        // imported version with no rule-free projection (none was kept then).
        graph.publication = new PublicationState(3, 0, List.of(INVOLVES_SINGLE));
        importer.run(built.request());
        graph.backfillWithoutBundleSnapshot(built.versionId());
        registry.removeArtifact("artifact-bundle-" + built.versionId());
        Files.delete(bundleFile(built.versionId()));
        InMemoryGraphHandoffRepository.State graphBefore = graph.state();
        InMemoryDocumentRegistry.State registryBefore = registry.state();
        long filesBefore = fileCount();

        GraphHandoffResult again = importer.run(built.request());

        assertTrue(again.succeeded(), () -> String.valueOf(again.failure() == null ? null : again.failure().failure()));
        assertEquals(Outcome.UNCHANGED, again.staged().outcome());
        assertNull(again.staged().bundleSnapshot());
        assertEquals(List.of(HANDOFF_ID), again.staged().sources());
        JsonNode written = HandoffFixtures.parse(GraphHandoffResultWriter.toBytes(again));
        assertTrue(written.get("bundleSnapshot").isNull());
        assertTrue(written.get("composition").get("newSource").isNull(), "a re-import composed nothing new");
        assertEquals("[\"" + HANDOFF_ID + "\"]", written.get("composition").get("sources").toString());
        assertEquals(graphBefore, graph.state());
        assertEquals(registryBefore, registry.state());
        assertEquals(filesBefore, fileCount(), "an unchanged import never writes the projection it did not keep");
        assertFalse(Files.exists(bundleFile(built.versionId())));
    }

    @Test
    void aVersionWhoseCompositionIsNotThisOneBundleIsAConflict() throws Exception {
        importer.run(built.request());
        String versionId = built.versionId();
        graph.insertSource(new GraphHandoffRepository.NewSource(versionId, 1, "handoff-unit-other",
                "artifact-receipt-" + versionId, null));
        InMemoryGraphHandoffRepository.State graphBefore = graph.state();

        GraphHandoffResult result = importer.run(built.request());

        assertEquals(GraphHandoffFailure.VERSION_CONFLICT, failure(result).failure());
        assertEquals(graphBefore, graph.state());
    }

    @Test
    void aTamperedBundleProjectionIsRefusedByTheRegistryReadOnTheNextImport() throws Exception {
        graph.publication = new PublicationState(3, 0, List.of(INVOLVES_SINGLE));
        importer.run(built.request());
        String versionId = built.versionId();
        // Same length, other bytes: the registered hash no longer matches, which the verified read reports as a changed file.
        Path file = bundleFile(versionId);
        byte[] bytes = Files.readAllBytes(file);
        bytes[bytes.length - 2] = (byte) (bytes[bytes.length - 2] == ']' ? '}' : ']');
        Files.write(file, bytes);

        GraphHandoffResult result = importer.run(built.request());

        assertEquals(GraphHandoffFailure.TEXT_MISMATCH, failure(result).failure());
    }

    @Test
    void aRetryAfterAnUnknownCommitAndARuleSwitchStagesUnderTheNewRulesWithoutAFileConflict() throws Exception {
        // PR #326 review: the lost attempt left the file of its rules; the switch changes the bytes the retry writes.
        graph.publication = new PublicationState(3, 0, List.of(INVOLVES_SINGLE));
        transaction.failCommitOnce = true;
        assertEquals(GraphHandoffFailure.DATABASE_UNAVAILABLE, failure(importer.run(built.request())).failure());
        Path lostFile = root.resolve("graph_snapshot")
                .resolve(GraphHandoffImporter.snapshotFileName(built.versionId(), List.of("involves-single@1")));
        assertTrue(Files.exists(lostFile), "the unknown outcome keeps the file");

        graph.publication = new PublicationState(4, 0, List.of());
        GraphHandoffResult retry = importer.run(built.request());

        assertTrue(retry.succeeded(), () -> String.valueOf(retry.failure() == null ? null : retry.failure().failure()));
        assertEquals(Outcome.STAGED, retry.staged().outcome());
        assertEquals("created", retry.staged().snapshot().file(), "its own file, not the orphan of the other rule set");
        assertEquals(List.of(), graph.inserted().get(0).ruleIds());
        assertEquals(4, graph.inserted().get(0).ruleRevision());
        assertEquals(2, GraphSnapshotCodec.read(Files.readAllBytes(snapshotFile(built.versionId())), built.versionId())
                .relations().size(), "the snapshot of the rules read by the retry");
        assertTrue(Files.exists(lostFile), "the orphan is left alone, never registered");

        // Under the same rules a lost attempt's file is adopted, as without rules.
        freshSetUp();
        graph.publication = new PublicationState(3, 0, List.of(INVOLVES_SINGLE));
        transaction.failCommitOnce = true;
        importer.run(built.request());
        GraphHandoffResult same = importer.run(built.request());
        assertTrue(same.succeeded());
        assertEquals("existing", same.staged().snapshot().file());
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

    // ------------------------------------------------------------------------------------------------ structural paths ----

    private Built builtWith(Shape shape) {
        Built twoHop = HandoffFixtures.build(Spec.standard().withShape(shape));
        handoff.envelope = twoHop.envelopeBytes();
        return twoHop;
    }

    private static List<String> strings(JsonNode array) {
        List<String> values = new java.util.ArrayList<>();
        for (JsonNode item : array.values()) {
            values.add(item.stringValue());
        }
        return values;
    }

    private JsonNode structuralOf(JsonNode bundle) {
        for (JsonNode relation : bundle.get("relations").values()) {
            if (relation.get("type").stringValue().equals("STRUCTURALLY_RELATED_TO")) {
                return relation;
            }
        }
        throw new AssertionError("no structural relation");
    }

    // ------------------------------------------------------------------------------------------------ impacts --------------

    @Test
    void aVerifiedImpactIsRetainedRawInTheReceiptWhileTheSnapshotCarriesOnlyItsQuoteSpan() throws Exception {
        Built impact = HandoffFixtures.build(Spec.standard().withImpact());
        handoff.envelope = impact.envelopeBytes();

        GraphHandoffResult result = importer.run(impact.request());

        assertTrue(result.succeeded(), () -> String.valueOf(result.failure() == null ? null : result.failure().failure()));
        String versionId = impact.versionId();
        JsonNode receipt = HandoffFixtures.parse(Files.readAllBytes(receiptFile(versionId)));
        assertEquals(impact.bundle().get("impacts"), receipt.get("bundle").get("impacts"), "the receipt retains every row raw");
        assertEquals(impact.bundle(), receipt.get("bundle"));
        assertEquals(1, receipt.get("bundle").get("counts").get("impacts").intValue());
        assertTrue(strings(receipt.get("appVerification").get("checks"))
                .contains("impact_rows_closed_over_involves_sources_approvals_and_labels"));
        assertEquals("audit-metadata-not-a-verifier-verdict", receipt.get("appVerification").get("approvalBasis").stringValue());

        String quote = impact.bundle().get("impacts").get(0).get("effects").get("positive").get(0).stringValue();
        String snapshotText = Files.readString(snapshotFile(versionId));
        PublicGraphSnapshot snapshot = GraphSnapshotCodec.read(Files.readAllBytes(snapshotFile(versionId)), versionId);
        assertEquals(3, snapshot.snapshotFormat());
        assertEquals(4, snapshot.evidence().size());
        assertTrue(snapshot.evidence().stream().anyMatch(e -> e.evidenceId().equals(quote)),
                "the quote's span is a public span, nothing more");
        // No impact content of any kind reaches the public snapshot: no reserved field name at any depth, no reserved literal value and none of
        // the exact proposal/candidate strings. (The raw text is NOT searched for words: an id may legitimately contain one.)
        String candidateId = impact.bundle().get("impacts").get(0).get("impactCandidateId").stringValue();
        assertEquals(List.of(), HandoffFixtures.impactLeaks(snapshotText, candidateId, "합성 영향"));
        assertEquals(4, HandoffFixtures.parse(GraphHandoffResultWriter.toBytes(result)).get("evidenceRows").get("registered").intValue());
    }

    @Test
    void aDefaultAndAnOperatorApprovedHandoffRetainTheirNotProposedAndNotApplicableRowsOnlyInTheReceipt() throws Exception {
        // The handoff id is the snapshot's sourceBundleId and may legitimately contain a reserved word ("impacts"): only object keys and
        // exact protected values are leaks, never an identifier's substring.
        for (Spec spec : List.of(Spec.standard().withHandoffId("handoff-default-impacts"),
                Spec.standard().withHandoffId("handoff-manual-impacts").withManualApproval())) {
            Built world = HandoffFixtures.build(spec);
            handoff.envelope = world.envelopeBytes();

            assertTrue(importer.run(world.request()).succeeded(), spec.handoffId());

            JsonNode receipt = HandoffFixtures.parse(Files.readAllBytes(receiptFile(world.versionId())));
            JsonNode rows = receipt.get("bundle").get("impacts");
            assertEquals(1, rows.size(), spec.handoffId());
            assertEquals(spec.manualApproval() ? "not-applicable" : "not-proposed", rows.get(0).get("status").stringValue());
            String snapshotText = Files.readString(snapshotFile(world.versionId()));
            assertTrue(snapshotText.contains("\"sourceBundleId\":\"" + spec.handoffId() + "\""), spec.handoffId());
            assertEquals(List.of(), HandoffFixtures.impactLeaks(snapshotText), spec.handoffId());
        }
    }

    @Test
    void anImpactRowThatContradictsItsEdgeOrApprovalIsRefusedBeforeAnythingIsWritten() throws Exception {
        InMemoryGraphHandoffRepository.State graphBefore = graph.state();
        InMemoryDocumentRegistry.State registryBefore = registry.state();
        long filesBefore = fileCount();
        Built manual = HandoffFixtures.build(Spec.standard().withHandoffId("handoff-manual-forged").withManualApproval());
        List<Built> forged = List.of(
                HandoffFixtures.repinned(built, b -> ((ObjectNode) b.get("impacts").get(0)).put("status", "not-applicable")),
                HandoffFixtures.repinned(manual, b -> ((ObjectNode) b.get("impacts").get(0)).put("status", "not-proposed")),
                HandoffFixtures.repinned(built, b -> ((ObjectNode) b.get("impacts").get(0)).put("companyId", COMPANY_B)));
        for (Built world : forged) {
            handoff.envelope = world.envelopeBytes();

            GraphHandoffException failure = failure(importer.run(world.request()));

            assertEquals(GraphHandoffFailure.BUNDLE_INVALID, failure.failure());
            assertEquals(0, graph.writes());
            assertEquals(graphBefore, graph.state());
            assertEquals(registryBefore, registry.state());
            assertEquals(filesBefore, fileCount());
        }
    }

    @Test
    void aOneHopEdgeKeepsItsCompletePathAndBasisScopesOnlyInTheReceipt() throws Exception {
        assertTrue(importer.run(built.request()).succeeded());
        String versionId = built.versionId();

        JsonNode receipt = HandoffFixtures.parse(Files.readAllBytes(receiptFile(versionId)));
        JsonNode structural = structuralOf(receipt.get("bundle"));
        assertEquals(List.of(COMPANY_A, COMPANY_B), strings(structural.get("structuralPath").get("companyIds")));
        assertEquals("complete", structural.get("structuralPath").get("status").stringValue());
        JsonNode link = structural.get("structuralPath").get("links").get(0);
        assertEquals(COMPANY_B, link.get("supplierCompanyId").stringValue(), "the supplier direction is the S3 fact, not the chain order");
        assertEquals(COMPANY_A, link.get("customerCompanyId").stringValue());
        assertEquals("부품 공급 계약", structural.get("basis").get(0).get("businessScope").stringValue());
        assertEquals("배터리", structural.get("basis").get(0).get("productScope").stringValue());
        assertEquals(0, receipt.get("bundle").get("pathCompanies").size());
        assertEquals(0, receipt.get("bundle").get("counts").get("pathCompanies").intValue());

        JsonNode app = receipt.get("appVerification");
        assertTrue(strings(app.get("checks")).contains("structural_path_closed_over_involves_basis_and_catalog"));
        assertEquals("operator-mapped-basis-chain-not-causality-or-price-direction", app.get("structuralPath").stringValue());

        // None of the private path data is in the public snapshot, in any wording.
        String snapshot = new String(Files.readAllBytes(snapshotFile(versionId)), StandardCharsets.UTF_8);
        for (String privateText : List.of("structuralPath", "pathCompanies", "businessScope", "productScope", "부품 공급 계약",
                "supplierCompanyId", "customerCompanyId", "companyIds")) {
            assertFalse(snapshot.contains(privateText), privateText);
        }
    }

    @Test
    void aTwoHopChainThroughAMappedMiddleCompanyStagesThePrivateCompanyOnlyInTheReceipt() throws Exception {
        graph.seedCompany(COMPANY_M, "합성중간");
        Built twoHop = builtWith(Shape.TWO_HOP_PRIVATE);

        GraphHandoffResult result = importer.run(twoHop.request());

        assertTrue(result.succeeded(), () -> String.valueOf(result.failure() == null ? null : result.failure().failure()));
        assertEquals(2, result.staged().companies(), "a private path company is not a public company");
        byte[] snapshotBytes = Files.readAllBytes(snapshotFile(twoHop.versionId()));
        PublicGraphSnapshot snapshot = GraphSnapshotCodec.read(snapshotBytes, twoHop.versionId());
        assertEquals(java.util.Set.of(COMPANY_A, COMPANY_B),
                snapshot.companies().stream().map(c -> c.companyId()).collect(java.util.stream.Collectors.toSet()));
        assertEquals(2, snapshot.relations().size(), "one INVOLVES and the one structural edge: no node or edge for the middle");
        assertEquals(2, snapshot.relations().stream().filter(r -> r.relationType().equals("STRUCTURALLY_RELATED_TO"))
                .findFirst().orElseThrow().basis().size());
        String text = new String(snapshotBytes, StandardCharsets.UTF_8);
        for (String privateText : List.of(COMPANY_M, "합성중간", "structuralPath", "pathCompanies", "businessScope", "소재 공급 계약")) {
            assertFalse(text.contains(privateText), privateText);
        }

        JsonNode receipt = HandoffFixtures.parse(Files.readAllBytes(receiptFile(twoHop.versionId())));
        assertEquals(twoHop.bundle(), receipt.get("bundle"), "the receipt retains the complete bundle");
        JsonNode pathCompanies = receipt.get("bundle").get("pathCompanies");
        assertEquals(1, pathCompanies.size());
        assertEquals(COMPANY_M, pathCompanies.get(0).get("id").stringValue());
        assertEquals(1, receipt.get("bundle").get("counts").get("pathCompanies").intValue());
        JsonNode path = structuralOf(receipt.get("bundle")).get("structuralPath");
        assertEquals(List.of(COMPANY_A, COMPANY_M, COMPANY_B), strings(path.get("companyIds")));
        assertEquals(COMPANY_M, path.get("links").get(0).get("supplierCompanyId").stringValue());
        assertEquals(COMPANY_A, path.get("links").get(0).get("customerCompanyId").stringValue());
        assertEquals(COMPANY_B, path.get("links").get(1).get("supplierCompanyId").stringValue());
        assertEquals(COMPANY_M, path.get("links").get(1).get("customerCompanyId").stringValue());
        // No private counter reaches the public import result contract.
        JsonNode written = HandoffFixtures.parse(GraphHandoffResultWriter.toBytes(result));
        assertFalse(written.toString().contains("pathCompanies"));
        assertEquals(2, written.get("counts").get("companies").intValue());
    }

    @Test
    void aTwoHopChainThroughAPublicMiddleCompanyNeedsNoPathCompany() throws Exception {
        graph.seedCompany(COMPANY_M, "합성중간");
        Built twoHop = builtWith(Shape.TWO_HOP_PUBLIC);

        GraphHandoffResult result = importer.run(twoHop.request());

        assertTrue(result.succeeded(), () -> String.valueOf(result.failure() == null ? null : result.failure().failure()));
        assertEquals(3, result.staged().companies());
        PublicGraphSnapshot snapshot = GraphSnapshotCodec.read(Files.readAllBytes(snapshotFile(twoHop.versionId())),
                twoHop.versionId());
        assertTrue(snapshot.companies().stream().anyMatch(c -> c.companyId().equals(COMPANY_M)));
        JsonNode receipt = HandoffFixtures.parse(Files.readAllBytes(receiptFile(twoHop.versionId())));
        assertEquals(0, receipt.get("bundle").get("pathCompanies").size());
        assertEquals(List.of(COMPANY_A, COMPANY_M, COMPANY_B),
                strings(structuralOf(receipt.get("bundle")).get("structuralPath").get("companyIds")));
    }

    @Test
    void aTwoHopChainWithAnUnmappedMiddleStagesAnUnavailablePathWithoutInventingACompany() throws Exception {
        Built twoHop = builtWith(Shape.TWO_HOP_UNMAPPED);

        GraphHandoffResult result = importer.run(twoHop.request());

        assertTrue(result.succeeded(), () -> String.valueOf(result.failure() == null ? null : result.failure().failure()));
        assertEquals(2, result.staged().companies());
        JsonNode receipt = HandoffFixtures.parse(Files.readAllBytes(receiptFile(twoHop.versionId())));
        JsonNode path = structuralOf(receipt.get("bundle")).get("structuralPath");
        assertEquals("unavailable", path.get("status").stringValue());
        assertEquals("intermediate_company_unmapped", path.get("reason").stringValue());
        assertFalse(path.has("companyIds"), "nothing is truncated or fabricated");
        assertEquals(0, receipt.get("bundle").get("pathCompanies").size());
        assertEquals(2, structuralOf(receipt.get("bundle")).get("basis").size());
    }

    @Test
    void aPathCompanyThatIsMissingOrNamedDifferentlyInTheCatalogueRollsEverythingBack() throws Exception {
        Built twoHop = builtWith(Shape.TWO_HOP_PRIVATE);
        for (String catalogued : new String[] {null, "다른 중간"}) {
            graph = new InMemoryGraphHandoffRepository("fixture-active", 2);
            graph.seedCompany(COMPANY_A, "합성기업");
            graph.seedCompany(COMPANY_B, "합성부품");
            if (catalogued != null) {
                graph.seedCompany(COMPANY_M, catalogued, "합성중간");
            }
            importer = newImporter();
            InMemoryGraphHandoffRepository.State graphBefore = graph.state();
            InMemoryDocumentRegistry.State registryBefore = registry.state();
            long filesBefore = fileCount();

            assertEquals(GraphHandoffFailure.COMPANY_MISMATCH, failure(importer.run(twoHop.request())).failure(),
                    String.valueOf(catalogued));

            assertEquals(graphBefore, graph.state());
            assertEquals(registryBefore, registry.state());
            assertEquals(filesBefore, fileCount());
            assertEquals(0, graph.writes());
            assertFalse(Files.exists(snapshotFile(twoHop.versionId())));
            assertFalse(Files.exists(receiptFile(twoHop.versionId())));
        }
        graph = new InMemoryGraphHandoffRepository("fixture-active", 2);
        graph.seedCompany(COMPANY_A, "합성기업");
        graph.seedCompany(COMPANY_B, "합성부품");
        graph.seedCompany(COMPANY_M, "합성중간");
        importer = newImporter();
        assertTrue(importer.run(twoHop.request()).succeeded(), "the same pins stage once the catalogue is right");
    }

    @Test
    void repeatingATwoHopImportIsUnchangedAndKeepsTheSameBytes() throws Exception {
        graph.seedCompany(COMPANY_M, "합성중간");
        Built twoHop = builtWith(Shape.TWO_HOP_PRIVATE);
        assertTrue(importer.run(twoHop.request()).succeeded());
        byte[] snapshotBytes = Files.readAllBytes(snapshotFile(twoHop.versionId()));
        byte[] receiptBytes = Files.readAllBytes(receiptFile(twoHop.versionId()));

        GraphHandoffResult again = importer.run(twoHop.request());

        assertTrue(again.succeeded());
        assertEquals(Outcome.UNCHANGED, again.staged().outcome());
        assertTrue(java.util.Arrays.equals(snapshotBytes, Files.readAllBytes(snapshotFile(twoHop.versionId()))));
        assertTrue(java.util.Arrays.equals(receiptBytes, Files.readAllBytes(receiptFile(twoHop.versionId()))));
    }

    // ------------------------------------------------------------------------------------------ the HTTP handoff source -----

    private GraphHandoffImporter httpImporter(HandoffFixtures.FakeHandoffRead reads) {
        return new GraphHandoffImporter(new HttpHandoffSource(reads), ingestion, new IngestionExportParser(), store, registry, graph,
                transaction, Clock.fixed(NOW, ZoneOffset.UTC));
    }

    @Test
    void theHttpHandoffSourceStagesTheSameVersionAsTheCliAndTheReceiptSaysWhereTheBundleCameFrom() throws Exception {
        HandoffFixtures.FakeHandoffRead reads = new HandoffFixtures.FakeHandoffRead(HandoffFixtures.read(built));
        GraphHandoffImporter http = httpImporter(reads);

        GraphHandoffResult result = http.run(built.request());

        assertTrue(result.succeeded(), () -> String.valueOf(result.failure() == null ? null : result.failure().failure()));
        assertEquals(Outcome.STAGED, result.staged().outcome());
        String versionId = built.versionId();
        assertEquals(1, reads.bundleCalls.get(), "one bundle read to check");
        assertEquals(1, reads.statusCalls.get(), "one content-free status read right before the commit");
        // The snapshot is a function of the verified bundle alone, so it is byte-identical to the CLI path's.
        freshSetUp();
        importer.run(built.request());
        byte[] cliSnapshot = Files.readAllBytes(snapshotFile(versionId));
        freshSetUp();
        reads = new HandoffFixtures.FakeHandoffRead(HandoffFixtures.read(built));
        http = httpImporter(reads);
        assertEquals(Outcome.STAGED, http.run(built.request()).staged().outcome());
        assertTrue(java.util.Arrays.equals(cliSnapshot, Files.readAllBytes(snapshotFile(versionId))));
        // The receipt keeps the same manifest, bundle and digests, and under `producer` the service's answer instead of a CLI receipt.
        JsonNode receipt = HandoffFixtures.parse(Files.readAllBytes(receiptFile(versionId)));
        assertEquals(built.manifestDigest(), receipt.get("manifestDigest").stringValue());
        assertEquals(built.bundleDigest(), receipt.get("bundleDigest").stringValue());
        assertEquals(built.bundle(), receipt.get("bundle"));
        JsonNode producer = receipt.get("producer");
        assertFalse(producer.has("receipt"));
        assertFalse(producer.has("attempts"));
        assertEquals(HandoffReadParser.TRANSPORT, producer.get("read").get("transport").stringValue());
        assertEquals(built.bundleDigest(), producer.get("read").get("verification").get("bundleDigest").stringValue());
        // The same pins again: unchanged, through the same route.
        assertEquals(Outcome.UNCHANGED, http.run(built.request()).staged().outcome());
    }

    @Test
    void aHandoffWithheldByTheServiceBetweenTheCheckAndTheCommitRollsTheHttpImportBack() throws Exception {
        InMemoryGraphHandoffRepository.State graphBefore = graph.state();
        InMemoryDocumentRegistry.State registryBefore = registry.state();
        long filesBefore = fileCount();
        GraphHandoffImporter http = httpImporter(new HandoffFixtures.FakeHandoffRead(HandoffFixtures.read(built)).withholdFrom(2));

        GraphHandoffException failure = failure(http.run(built.request()));

        assertEquals(GraphHandoffFailure.HANDOFF_WITHHELD, failure.failure());
        assertEquals("source_unauthorized", failure.cliCode());
        assertNothingWritten(graphBefore, registryBefore, filesBefore);
    }

    @Test
    void theSamePinsReadAgainLaterAreUnchangedAlthoughTheServiceStampsEveryAnswerAnew() throws Exception {
        HandoffFixtures.FakeHandoffRead reads = new HandoffFixtures.FakeHandoffRead(HandoffFixtures.read(built));
        GraphHandoffImporter http = httpImporter(reads);
        assertEquals(Outcome.STAGED, http.run(built.request()).staged().outcome());
        byte[] receipt = Files.readAllBytes(receiptFile(built.versionId()));

        // ai/service stamps observedAt and delivery.checkedAt per request: a later read of the same pins differs only there.
        HandoffRead first = reads.answer;
        reads.answer = new HandoffRead(first.handoffId(), first.state(),
                new HandoffReadClient.Delivery("current", Optional.empty(), Optional.of("2026-10-17T01:00:00+00:00")),
                first.verification(), first.manifest(), first.bundle(), "2026-10-17T01:00:01Z");

        GraphHandoffResult again = http.run(built.request());

        assertTrue(again.succeeded(), () -> String.valueOf(again.failure() == null ? null : again.failure().failure()));
        assertEquals(Outcome.UNCHANGED, again.staged().outcome());
        assertTrue(java.util.Arrays.equals(receipt, Files.readAllBytes(receiptFile(built.versionId()))), "the first receipt is kept");
    }
}
