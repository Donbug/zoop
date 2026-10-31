package com.zoop.document.evidence.service;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.PosixFilePermissions;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.function.Consumer;
import java.util.stream.Stream;

import com.zoop.artifact.storage.ArtifactFileStore;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import com.zoop.document.evidence.dto.EvidenceResponse;
import com.zoop.document.evidence.graph.GraphEvidence;
import com.zoop.document.evidence.graph.GraphEvidenceReader;
import com.zoop.document.evidence.repository.EvidenceView;
import com.zoop.document.repository.ArtifactRow;
import com.zoop.document.repository.VersionRow;
import com.zoop.graph.importer.LegacyRealPackage;
import com.zoop.graph.publication.GraphPublicationAuthority;
import com.zoop.graph.snapshot.ArtifactGraphSnapshotStore;
import com.zoop.graph.read.DisclosureExclusions;
import com.zoop.graph.read.GraphEvidenceSnapshotReader;
import com.zoop.graph.read.PublicGraphReader;
import com.zoop.graph.rules.PublicationRuleEvaluator;
import com.zoop.graph.rules.RuleDefinition;
import com.zoop.graph.snapshot.PublicGraphSnapshot;
import com.zoop.graph.version.GraphVersionRecord;
import com.zoop.graph.version.GraphVersionRepository;
import com.zoop.graph.version.GraphVersionSelector;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import tools.jackson.databind.node.ArrayNode;
import tools.jackson.databind.node.ObjectNode;

import static com.zoop.document.evidence.service.EvidenceWorld.ARTICLE;
import static com.zoop.document.evidence.service.EvidenceWorld.NOW;
import static com.zoop.document.evidence.service.EvidenceWorld.PROVIDER;
import static com.zoop.document.evidence.service.EvidenceWorld.QUOTE;
import static com.zoop.document.evidence.service.EvidenceWorld.TEXT;
import static com.zoop.document.evidence.service.EvidenceWorld.VERSION;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * The graph body evidence path of {@code getEvidence} against in-memory statements, a real S2-1 source registry file, a real
 * artifact store holding the import receipt, and a stubbed pinned-graph port. The pinned snapshot itself is proven by
 * {@code GraphEvidenceSnapshotReaderTest}; the SQL, the HTTP shape and the real activation are proven by the Java/PostgreSQL smoke.
 */
class GraphEvidenceServiceTest {
    private static final String HANDOFF = "handoff-1";
    private static final String GRAPH_VERSION = "gv-" + Canonical.sha256(HANDOFF);
    private static final String EARLIER_RECEIPT = "artifact-receipt-gv-earlier-import";
    private static final String SOURCE_GRANT = "grant-1";
    private static final String SOURCE_REVISION = "rev-1";
    private static final Instant SELECTED_AS_OF = Instant.parse("2026-10-10T00:00:00Z");
    private static final String EVIDENCE_ID = "ev-" + "c".repeat(64);
    private static final List<String> ALL = List.of("read", "store", "model-send", "quote-display");

    @TempDir
    Path temp;

    private EvidenceWorld world;
    private Path sources;
    private GraphEvidence found;
    private final AtomicInteger graphReads = new AtomicInteger();
    private RuntimeException graphFailure;
    /** When set, the REAL pinned reader answers instead of the stub {@link #found}. */
    private GraphEvidenceReader realPort;

    @Test
    void legacyReceiptRequiresPinnedV2ManifestAndBundle() {
        ObjectNode receipt = StrictJson.newObject();
        receipt.put("schemaVersion", LegacyRealPackage.RECEIPT_SCHEMA);
        ObjectNode manifest = receipt.putObject("manifest");
        manifest.put("schemaVersion", LegacyRealPackage.MANIFEST_SCHEMA); manifest.put("bundleDigest", "a".repeat(64));
        ObjectNode bundle = receipt.putObject("bundle");
        bundle.put("schemaVersion", LegacyRealPackage.BUNDLE_SCHEMA);
        bundle.put("provenanceKind", "legacy-real"); bundle.put("sourceSystem", "investmate-poc-bff");
        for (String field : List.of("issues", "relations", "companies", "articles", "evidence")) bundle.putArray(field);
        bundle.putObject("evidenceIdMap");
        receipt.putObject("legacyProvenance"); receipt.putObject("appVerification");
        receipt.put("bundleDigest", "a".repeat(64)); receipt.put("contentDigest", Canonical.digest(bundle));
        String digest = Canonical.digest(manifest), migration = "legacy-real:" + digest;
        receipt.put("manifestDigest", digest); receipt.put("migrationId", migration);
        assertEquals(bundle, GraphReceiptGrants.bundle(Canonical.bytes(receipt), "gv-" + Canonical.sha256(migration)).node());
        manifest.put("schemaVersion", "zoop-legacy-real-manifest-1");
        digest = Canonical.digest(manifest); migration = "legacy-real:" + digest;
        receipt.put("manifestDigest", digest); receipt.put("migrationId", migration);
        String graphVersion = "gv-" + Canonical.sha256(migration);
        assertThrows(GraphReceiptGrants.Malformed.class, () -> GraphReceiptGrants.bundle(Canonical.bytes(receipt), graphVersion));
    }

    private void setUp() throws IOException {
        world = new EvidenceWorld(temp, Instant.parse("2026-10-01T00:00:00Z"));
        sources = world.directory.resolve("sources.json");
        found = new GraphEvidence(GRAPH_VERSION, SELECTED_AS_OF,
                new GraphEvidence.Span(ARTICLE, VERSION, (int) EvidenceWorld.START, (int) EvidenceWorld.END), List.of("iss-1", "iss-2"),
                List.of(), List.of());
        world.registry.insertArtifactIfAbsent(new ArtifactRow(EARLIER_RECEIPT, "verification_receipt",
                "artifact-root:verification_receipt/gone.json", "d".repeat(64), 10, "application/json", NOW));
        world.read.evidence.put(EVIDENCE_ID, new EvidenceView(EVIDENCE_ID, ARTICLE, VERSION, TEXT, QUOTE, EvidenceWorld.START,
                EvidenceWorld.END, "body", Boolean.TRUE, EARLIER_RECEIPT));
        writeReceipt(receipt(pins(PROVIDER, SOURCE_GRANT, SOURCE_REVISION)));
        world.registerGraph(stackSnapshot(), stackSnapshot());
        writeSources(source(PROVIDER, SOURCE_GRANT, SOURCE_REVISION, true, "known", List.of("read", "store", "quote-display"),
                "operator-owned authored synthetic fixtures", null));
    }

    private GraphEvidenceReader port() {
        if (realPort != null) {
            return realPort;
        }
        return (version, asOf, id) -> {
            graphReads.incrementAndGet();
            if (graphFailure != null) {
                throw graphFailure;
            }
            return found;
        };
    }

    private EvidenceService service() {
        return world.service(null, sources, world.store, port());
    }

    private EvidenceResponse get() {
        return service().read(EVIDENCE_ID, null, null, null, null, "req-g");
    }

    private ErrorCode refused() {
        return assertThrows(CustomException.class, this::get).getErrorCode();
    }

    // ---- fixtures --------------------------------------------------------------------------------------------------------

    private static ObjectNode pins(String sourceId, String grantId, String revision) {
        ObjectNode observation = StrictJson.newObject();
        observation.put("roundId", "round-1");
        observation.put("sourceId", sourceId);
        observation.put("page", 0);
        observation.put("ordinal", 0);
        observation.put("observedAt", "2026-10-14T00:00:00Z");
        observation.putObject("grant").put("grantId", grantId).put("revision", revision);
        return observation;
    }

    private static ObjectNode receipt(ObjectNode... observations) {
        ObjectNode root = StrictJson.newObject();
        root.put("schemaVersion", GraphReceiptGrants.SCHEMA);
        root.put("handoffId", HANDOFF);
        ObjectNode bundle = root.putObject("bundle");
        ArrayNode articles = bundle.putArray("articles");
        ObjectNode article = articles.addObject();
        article.put("articleId", ARTICLE);
        article.put("articleVersion", VERSION);
        article.put("textSha256", EvidenceWorld.TEXT_SHA);
        ArrayNode list = article.putArray("observations");
        for (ObjectNode observation : observations) {
            list.add(observation);
        }
        return root;
    }

    private void writeReceipt(ObjectNode receipt) throws IOException {
        byte[] bytes = Canonical.bytes(receipt);
        try (ArtifactFileStore.Session session = world.store.open()) {
            ArtifactFileStore.StoredFile file = session.put("verification_receipt", GRAPH_VERSION + ".json", bytes);
            world.registry.insertArtifactIfAbsent(new ArtifactRow("artifact-receipt-" + GRAPH_VERSION, "verification_receipt",
                    file.uri(), file.sha256(), file.bytes(), "application/json", NOW));
        }
    }

    private Path receiptFile() {
        return world.root.resolve("verification_receipt").resolve(GRAPH_VERSION + ".json");
    }

    private static String source(String sourceId, String grantId, String revision, boolean enabled, String rights,
            List<String> operations, String evidence, String expiresAt) {
        ObjectNode source = StrictJson.newObject();
        source.put("sourceId", sourceId);
        source.put("adapter", "authored-files");
        source.put("inputRoot", "/srv/zoop/inputs");
        source.putArray("allowedHosts").add("example.invalid");
        ObjectNode scope = source.putArray("scopes").addObject();
        scope.put("scopeId", "body");
        scope.put("selection", "authored source slice");
        scope.putNull("initialCursor");
        scope.putNull("articleXPath");
        scope.putArray("timestampLimitations").add("authored fixtures");
        ObjectNode grant = source.putObject("grant");
        grant.put("grantId", grantId);
        grant.put("revision", revision);
        grant.put("sourceId", sourceId);
        grant.put("enabled", enabled);
        grant.put("rights", rights);
        ArrayNode ops = grant.putArray("allowedOperations");
        operations.forEach(ops::add);
        grant.putArray("recipients");
        grant.putArray("purposes");
        grant.putArray("evidence").add(evidence);
        if (expiresAt == null) {
            grant.putNull("expiresAt");
        } else {
            grant.put("expiresAt", expiresAt);
        }
        return source.toString();
    }

    private void writeSources(String... entries) throws IOException {
        Files.writeString(sources, "{\"schemaVersion\":\"zoop-ingestion-s2-1\",\"revision\":\"registry-1\",\"sources\":["
                + String.join(",", entries) + "]}");
    }

    private static List<String> snapshot(Path root) throws IOException {
        try (Stream<Path> paths = Files.walk(root)) {
            List<String> entries = new ArrayList<>();
            for (Path path : paths.sorted().toList()) {
                entries.add(path + "|" + (Files.isDirectory(path) ? "dir" : Files.size(path)) + "|"
                        + PosixFilePermissions.toString(Files.getPosixFilePermissions(path)) + "|"
                        + Files.getLastModifiedTime(path).toMillis());
            }
            return entries;
        }
    }

    // ---- the served answer -----------------------------------------------------------------------------------------------

    @Test
    void impactProjectionUsesTheSameQuoteAndReturnsDenialsInsideItsTransactionCallback() throws Exception {
        setUp();
        assertEquals(QUOTE, service().readImpactCitation(EVIDENCE_ID, null, GRAPH_VERSION, SELECTED_AS_OF, "impact-read").quote());
        writeSources(source(PROVIDER, SOURCE_GRANT, SOURCE_REVISION, false, "known", List.of("read", "store", "quote-display"), "authored", null));
        assertNull(service().readImpactCitation(EVIDENCE_ID, null, GRAPH_VERSION, SELECTED_AS_OF, "impact-denied"));
        assertNull(service().readImpactCitation("ev-" + "0".repeat(64), null, GRAPH_VERSION, SELECTED_AS_OF, "impact-missing"));
    }

    @Test
    void impactProjectionNeverTurnsAnOutageIntoAnAbsentAssessment() throws Exception {
        setUp(); graphFailure = new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
        assertEquals(ErrorCode.SOURCE_UNAVAILABLE, assertThrows(CustomException.class,
                () -> service().readImpactCitation(EVIDENCE_ID, null, GRAPH_VERSION, SELECTED_AS_OF, "impact-outage")).getErrorCode());
    }

    @Test
    void servesTheGraphBodyEvidenceFromTheSelectedVersionWithoutTheS1Registry() throws Exception {
        setUp();
        List<String> files = snapshot(world.root);
        int writes = world.registry.writeAttempts();

        EvidenceResponse response = get();

        assertEquals(EVIDENCE_ID, response.id());
        assertEquals(QUOTE, response.quote());
        assertEquals(EvidenceWorld.START, response.start());
        assertEquals(EvidenceWorld.END, response.end());
        assertEquals(ARTICLE, response.articleId());
        assertEquals(VERSION, response.articleVersion());
        assertEquals(VERSION, response.documentVersion());
        assertEquals(Boolean.TRUE, response.quoteVerified());
        assertEquals(List.of("iss-1", "iss-2"), response.eventIds(), "the visible issues that cite it");
        assertEquals("public_graph_snapshot", response.metadata().source());
        assertEquals(GRAPH_VERSION, response.metadata().graphVersion(), "the selected version, not a guess");
        assertEquals(SELECTED_AS_OF, response.metadata().asOf(), "the selection's reference time, not the clock");
        assertEquals(false, response.metadata().partial());
        assertEquals(List.of(), response.metadata().failures());
        assertNull(response.sentiment());
        assertNull(response.documentSummary(), "serving an S1 summary would need S1 authority");
        assertNull(response.analysisStatus());
        assertNull(response.analysisProvenance());
        assertNull(response.resultVersion());
        assertEquals("제목", response.article().title());
        assertEquals(files, snapshot(world.root), "no file is created, locked or changed by the read");
        assertEquals(writes, world.registry.writeAttempts());
    }

    @Test
    void theGraphPathNeverReadsTheS1Registry() throws Exception {
        setUp();
        // grants unset on purpose: the S1 registry would answer 503
        assertNotNull(get());
        assertEquals(1, graphReads.get());
    }

    @Test
    void aKnownCompanyMakesItPartialWithoutASentimentAndAnUnknownOneIsNotFoundAfterTheEvidenceDecision() throws Exception {
        setUp();
        world.read.companies.add("SYNTH-A");

        EvidenceResponse response = service().read(EVIDENCE_ID, null, null, null, "SYNTH-A", "req-c");

        assertEquals(true, response.metadata().partial());
        assertNull(response.sentiment());
        assertEquals(List.of("sentiment"), response.metadata().failures().stream().map(f -> f.section()).toList());
        assertEquals("SOURCE_UNAVAILABLE", response.metadata().failures().get(0).code());
        assertEquals(List.of("iss-1", "iss-2"), response.eventIds(), "the event link itself is not a failed section");
        assertEquals(ErrorCode.RESOURCE_NOT_FOUND,
                assertThrows(CustomException.class, () -> service().read(EVIDENCE_ID, null, null, null, "NOPE", "r")).getErrorCode());

        world.registry.setAccessStatus(ARTICLE, "private");
        assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE,
                assertThrows(CustomException.class, () -> service().read(EVIDENCE_ID, null, null, null, "NOPE", "r")).getErrorCode(),
                "an unknown company does not make withheld evidence look like a missing company");
    }

    @Test
    void anS1RowStaysOnTheS1PathAndAPinOnItIsRefusedBeforeAnyRegistryOrGraphRead() throws Exception {
        setUp();
        world.normal();
        EvidenceService service = service();

        for (Consumer<EvidenceService> pinned : List.<Consumer<EvidenceService>>of(
                s -> s.read(world.evidenceId, null, GRAPH_VERSION, null, null, "r"),
                s -> s.read(world.evidenceId, null, null, "2026-10-15T00:00:00Z", null, "r"))) {
            assertEquals(ErrorCode.VERSION_UNAVAILABLE, assertThrows(CustomException.class, () -> pinned.accept(service)).getErrorCode());
        }
        // The S1 registry is unset in this service: an unpinned S1 read says 503, which proves the S1 path (not the graph path) ran.
        assertEquals(ErrorCode.SOURCE_UNAVAILABLE,
                assertThrows(CustomException.class, () -> service.read(world.evidenceId, null, null, null, null, "r")).getErrorCode());
        assertEquals(0, graphReads.get(), "an S1 citation never touches the graph port");
    }

    @Test
    void aRoundIsRefusedBeforeAnyLookupAndAnUnknownIdIsNotFound() throws Exception {
        setUp();
        EvidenceService service = service();

        assertEquals(ErrorCode.VERSION_UNAVAILABLE,
                assertThrows(CustomException.class, () -> service.read(EVIDENCE_ID, "brf-1", null, null, null, "r")).getErrorCode());
        assertEquals(0, world.read.calls);
        assertEquals(ErrorCode.RESOURCE_NOT_FOUND,
                assertThrows(CustomException.class, () -> service.read("ev-" + "0".repeat(64), null, GRAPH_VERSION, null, null, "r"))
                        .getErrorCode(), "an unknown id is absent whatever is pinned");
        assertEquals(0, graphReads.get());
    }

    @Test
    void theSelectorsOutcomePassesThroughUnchanged() throws Exception {
        setUp();
        for (ErrorCode code : List.of(ErrorCode.VERSION_UNAVAILABLE, ErrorCode.INVALID_REQUEST, ErrorCode.SOURCE_UNAVAILABLE)) {
            graphFailure = new CustomException(code);
            assertEquals(code, refused());
        }
        graphFailure = null;
        assertNotNull(get());
    }

    // ---- visibility and span -----------------------------------------------------------------------------------------------

    @Test
    void anEvidenceThatIsNotVisibleInThePinnedFilteredVersionIsWithheld() throws Exception {
        setUp();
        found = new GraphEvidence(GRAPH_VERSION, SELECTED_AS_OF, null, List.of(), List.of(), List.of());
        assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, refused());
    }

    @Test
    void theSnapshotSpanMustEqualTheRowExactly() throws Exception {
        setUp();
        for (GraphEvidence.Span span : List.of(new GraphEvidence.Span("art-x", VERSION, 5, 9),
                new GraphEvidence.Span(ARTICLE, "v9", 5, 9), new GraphEvidence.Span(ARTICLE, VERSION, 4, 9),
                new GraphEvidence.Span(ARTICLE, VERSION, 5, 10))) {
            found = new GraphEvidence(GRAPH_VERSION, SELECTED_AS_OF, span, List.of("iss-1"), List.of(), List.of());
            assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, refused(), span.toString());
        }
    }

    @Test
    void onlyAVerifiedBodyRowWithConsistentOffsetsAndTheVersionsTextIsServed() throws Exception {
        setUp();
        EvidenceView row = world.read.evidence.get(EVIDENCE_ID);
        for (EvidenceView broken : List.of(
                new EvidenceView(row.id(), row.articleId(), row.articleVersion(), row.textArtifactId(), row.quote(), row.startOffset(),
                        row.endOffset(), "title", Boolean.TRUE, row.verificationArtifactId()),
                new EvidenceView(row.id(), row.articleId(), row.articleVersion(), row.textArtifactId(), row.quote(), row.startOffset(),
                        row.endOffset(), "body", Boolean.FALSE, row.verificationArtifactId()),
                new EvidenceView(row.id(), row.articleId(), row.articleVersion(), "text-other", row.quote(), row.startOffset(),
                        row.endOffset(), "body", Boolean.TRUE, row.verificationArtifactId()),
                new EvidenceView(row.id(), row.articleId(), row.articleVersion(), row.textArtifactId(), "짧", row.startOffset(),
                        row.endOffset(), "body", Boolean.TRUE, row.verificationArtifactId()))) {
            world.read.evidence.put(EVIDENCE_ID, broken);
            assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, refused(), broken.inputKind() + broken.quoteVerified() + broken.textArtifactId());
        }
        world.read.evidence.put(EVIDENCE_ID, row);
        assertNotNull(get());
    }

    @Test
    void theCurrentArticleAccessGatesItButANewerVersionDoesNot() throws Exception {
        setUp();
        for (String status : List.of("private", "deleted")) {
            world.registry.setAccessStatus(ARTICLE, status);
            assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, refused(), status);
        }
        world.registry.setAccessStatus(ARTICLE, "available");
        assertNotNull(get());

        world.registry.insertVersionIfAbsent(new VersionRow(ARTICLE, "v2", null, null, null, null, null, "unknown", null, TEXT, NOW));
        world.registry.movePointer(ARTICLE, VERSION, "v2");
        assertNotNull(get(), "the snapshot pins the version, so a newer current version does not withdraw it");
    }

    // ---- the receipt of the selected version -----------------------------------------------------------------------------

    @Test
    void theRowsOwnEarlierReceiptIsNeverReadWhenSeveralImportsShareTheRow() throws Exception {
        setUp();
        // The row points at EARLIER_RECEIPT, which is registered but has no file: only the selected version's receipt counts.
        assertNotNull(get());
        // A later import under another revision must be judged by ITS pins, not by the earlier import's.
        writeSources(source(PROVIDER, SOURCE_GRANT, "rev-2", true, "known", List.of("read", "store", "quote-display"),
                "operator-owned", null));
        assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, refused(), "the selected receipt pins rev-1, the registry now has rev-2");
    }

    @Test
    void anUnverifiableReceiptMakesThePublicationUnavailableWhileInvalidGrantPinsWithholdEvidence() throws Exception {
        setUp();
        byte[] original = Files.readAllBytes(receiptFile());

        Files.write(receiptFile(), EvidenceWorld.bytes("{}"));
        assertEquals(ErrorCode.SOURCE_UNAVAILABLE, refused(), "bytes differ from the registered hash");
        Files.write(receiptFile(), original);
        assertNotNull(get());

        for (Consumer<ObjectNode> edit : List.<Consumer<ObjectNode>>of(
                n -> n.put("schemaVersion", "zoop-graph-handoff-import-receipt-2"),
                n -> n.put("handoffId", "handoff-other"), n -> n.remove("bundle"))) {
            ObjectNode edited = receipt(pins(PROVIDER, SOURCE_GRANT, SOURCE_REVISION));
            edit.accept(edited);
            rewriteRegisteredReceipt(edited);
            assertEquals(ErrorCode.SOURCE_UNAVAILABLE, refused());
        }
        List<Consumer<ObjectNode>> edits = new ArrayList<>();
        edits.add(n -> n.putObject("bundle").putArray("articles"));
        edits.add(n -> ((ArrayNode) n.get("bundle").get("articles")).add(
                ((ArrayNode) n.get("bundle").get("articles")).get(0).deepCopy()));
        edits.add(n -> ((ObjectNode) n.get("bundle").get("articles").get(0)).putArray("observations"));
        edits.add(n -> ((ObjectNode) n.get("bundle").get("articles").get(0).get("observations").get(0).get("grant"))
                .put("revision", ""));
        edits.add(n -> ((ObjectNode) n.get("bundle").get("articles").get(0).get("observations").get(0).get("grant"))
                .put("revision", 7));
        edits.add(n -> ((ObjectNode) n.get("bundle").get("articles").get(0).get("observations").get(0)).remove("grant"));
        int index = 0;
        for (Consumer<ObjectNode> edit : edits) {
            ObjectNode edited = receipt(pins(PROVIDER, SOURCE_GRANT, SOURCE_REVISION));
            edit.accept(edited);
            rewriteRegisteredReceipt(edited);
            assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, refused(), "receipt variant " + index++);
        }
    }


    /** A new receipt file under the same artifact id: registered hash and size follow, so only the content is at fault. */
    private void rewriteRegisteredReceipt(ObjectNode receipt) throws IOException {
        byte[] bytes = Canonical.bytes(receipt);
        Files.write(receiptFile(), bytes);
        ArtifactRow row = world.registry.findArtifact("artifact-receipt-" + GRAPH_VERSION).orElseThrow();
        world.registry.replaceArtifact(new ArtifactRow(row.id(), row.kind(), row.storageUri(), ArtifactFileStore.sha256(bytes),
                bytes.length, row.mediaType(), row.createdAt()));
    }

    @Test
    void aMissingOrWrongKindOfReceiptAndAMissingStoreMakeThePublicationUnavailable() throws Exception {
        setUp();
        assertEquals(ErrorCode.SOURCE_UNAVAILABLE,
                assertThrows(CustomException.class, () -> world.service(null, sources, null, port())
                        .read(EVIDENCE_ID, null, null, null, null, "r")).getErrorCode(),
                "without an artifact root the receipt cannot be read: unavailable, never absence");
        Files.setPosixFilePermissions(receiptFile(), PosixFilePermissions.fromString("rw-r--r--"));
        assertEquals(ErrorCode.SOURCE_UNAVAILABLE, refused(), "an insecure file is a storage problem");
        Files.setPosixFilePermissions(receiptFile(), PosixFilePermissions.fromString("rw-------"));
        assertNotNull(get());

        ArtifactRow row = world.registry.findArtifact("artifact-receipt-" + GRAPH_VERSION).orElseThrow();
        world.registry.replaceArtifact(new ArtifactRow(row.id(), "exact_receipt", row.storageUri(), row.sha256(), row.bytes(),
                row.mediaType(), row.createdAt()));
        assertEquals(ErrorCode.SOURCE_UNAVAILABLE, refused(), "wrong kind");
        world.registry.replaceArtifact(new ArtifactRow(row.id(), row.kind(), row.storageUri(), row.sha256(), row.bytes(),
                "text/plain", row.createdAt()));
        assertEquals(ErrorCode.SOURCE_UNAVAILABLE, refused(), "wrong media type");
        world.registry.removeArtifact(row.id());
        assertEquals(ErrorCode.SOURCE_UNAVAILABLE, refused(), "no receipt registered for the selected version");
    }

    @Test
    void everyPinMustBelongToTheArticlesProviderAndEveryDistinctPinMustBeAllowed() throws Exception {
        setUp();
        writeReceipt2(pins(PROVIDER, SOURCE_GRANT, SOURCE_REVISION), pins(PROVIDER, SOURCE_GRANT, SOURCE_REVISION));
        assertNotNull(get(), "equal pins are one pin");

        writeReceipt2(pins("other-source", "g-2", "r-2"));
        writeSources(source("other-source", "g-2", "r-2", true, "known", List.of("read", "store", "quote-display"), "e", null));
        assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, refused(), "the receipt names a source that is not the article's provider");

        writeReceipt2(pins(PROVIDER, SOURCE_GRANT, SOURCE_REVISION), pins(PROVIDER, "grant-b", "rev-b"));
        writeSources(source(PROVIDER, SOURCE_GRANT, SOURCE_REVISION, true, "known", List.of("read", "store", "quote-display"), "e", null));
        assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, refused(), "one pin of two no longer matches: all of them are checked");
    }

    private void writeReceipt2(ObjectNode... observations) throws IOException {
        rewriteRegisteredReceipt(receipt(observations));
    }

    // ---- current authority -------------------------------------------------------------------------------------------------

    @Test
    void everyChangeOfTheCurrentSourceGrantWithholdsTheEvidenceAndRestoringItServesAgain() throws Exception {
        setUp();
        List<String> needed = List.of("read", "store", "quote-display");
        String valid = source(PROVIDER, SOURCE_GRANT, SOURCE_REVISION, true, "known", needed, "e", null);
        List<String> denied = List.of(
                source(PROVIDER, SOURCE_GRANT, "rev-2", true, "known", needed, "e", null),
                source(PROVIDER, "grant-2", SOURCE_REVISION, true, "known", needed, "e", null),
                source(PROVIDER, SOURCE_GRANT, SOURCE_REVISION, false, "known", needed, "e", null),
                source(PROVIDER, SOURCE_GRANT, SOURCE_REVISION, true, "unknown", needed, "e", null),
                source(PROVIDER, SOURCE_GRANT, SOURCE_REVISION, true, "denied", needed, "e", null),
                source(PROVIDER, SOURCE_GRANT, SOURCE_REVISION, true, "known", needed, "  ", null),
                source(PROVIDER, SOURCE_GRANT, SOURCE_REVISION, true, "known", needed, "e", "2026-10-15T00:59:59Z"),
                source(PROVIDER, SOURCE_GRANT, SOURCE_REVISION, true, "known", needed, "e", "2026-10-15T01:00:00Z"),
                source(PROVIDER, SOURCE_GRANT, SOURCE_REVISION, true, "known", List.of("store", "quote-display"), "e", null),
                source(PROVIDER, SOURCE_GRANT, SOURCE_REVISION, true, "known", List.of("read", "quote-display"), "e", null),
                source(PROVIDER, SOURCE_GRANT, SOURCE_REVISION, true, "known", List.of("read", "store", "model-send"), "e", null),
                source(PROVIDER, SOURCE_GRANT, SOURCE_REVISION, true, "known", List.of(), "e", null),
                source("another-source", SOURCE_GRANT, SOURCE_REVISION, true, "known", needed, "e", null));
        int index = 0;
        for (String change : denied) {
            writeSources(change);
            assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, refused(), "change " + index++);
            writeSources(valid);
            assertNotNull(get(), "the registry is read fresh on every request");
        }
        writeSources(source(PROVIDER, SOURCE_GRANT, SOURCE_REVISION, true, "known", needed, "e", "2026-10-15T01:00:01Z"));
        assertNotNull(get(), "an unexpired grant still covers it");
        writeSources(source(PROVIDER, SOURCE_GRANT, SOURCE_REVISION, true, "known", ALL, "e", null));
        assertNotNull(get());
        writeSources(source(PROVIDER, SOURCE_GRANT, SOURCE_REVISION, true, "known", needed, "e", null));
        assertNotNull(get(), "omitting model-send is allowed: a displayed quote is sent to no model");
    }

    @Test
    void theAuthorityClockIsNowEvenWhenAnHistoricalAsOfWasSelected() throws Exception {
        setUp();
        found = new GraphEvidence(GRAPH_VERSION, Instant.parse("2026-01-01T00:00:00Z"), found.span(), found.eventIds(),
                found.basisRefs(), found.impactRefs());
        writeSources(source(PROVIDER, SOURCE_GRANT, SOURCE_REVISION, true, "known", List.of("read", "store", "quote-display"), "e",
                "2026-06-01T00:00:00Z"));

        assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, refused(), "the grant expired before now, whatever the historical asOf says");
        writeSources(source(PROVIDER, SOURCE_GRANT, SOURCE_REVISION, true, "known", List.of("read", "store", "quote-display"), "e",
                "2027-01-01T00:00:00Z"));
        assertEquals(Instant.parse("2026-01-01T00:00:00Z"), get().metadata().asOf());
    }

    @Test
    void anUnsetMissingOrInvalidSourceRegistryIsUnavailableNeverOpenAndNeverEmpty() throws Exception {
        setUp();
        EvidenceService unset = world.service(null, null, world.store, port());
        assertEquals(ErrorCode.SOURCE_UNAVAILABLE,
                assertThrows(CustomException.class, () -> unset.read(EVIDENCE_ID, null, null, null, null, "r")).getErrorCode());

        String valid = Files.readString(sources);
        for (String broken : List.of("{", "{\"schemaVersion\":\"other\",\"revision\":\"r\",\"sources\":[]}",
                valid.replace("\"revision\":\"registry-1\"", "\"revision\":\"x\",\"revision\":\"y\""),
                valid.replace("\"enabled\":true", "\"enabled\":true,\"extra\":1"),
                valid.replace("\"expiresAt\":null", "\"expiresAt\":\"yesterday\""))) {
            Files.writeString(sources, broken);
            assertEquals(ErrorCode.SOURCE_UNAVAILABLE, refused(), broken);
        }
        Files.delete(sources);
        assertEquals(ErrorCode.SOURCE_UNAVAILABLE, refused());
        Files.write(sources, new byte[2_000_001]);
        assertEquals(ErrorCode.SOURCE_UNAVAILABLE, refused());
        Files.writeString(sources, valid);
        assertNotNull(get());
        assertTrue(Files.isRegularFile(sources));
    }

    @Test
    void aDatabaseFailureOnTheGraphPathIsUnavailableNeverABlankSuccess() throws Exception {
        setUp();
        world.read.failure = new org.springframework.dao.QueryTimeoutException("canceling statement due to statement timeout");
        assertEquals(ErrorCode.SOURCE_UNAVAILABLE, refused());
    }

    // ---- basis-only evidence ---------------------------------------------------------------------------------------------

    private static final String RELATION = "edge-structural-1";
    private static final String BASIS_KEY = "7".repeat(64);
    private static final String BASIS_TYPE = "STRUCTURALLY_RELATED_TO";

    private static GraphEvidence.BasisRef basisRef() {
        return new GraphEvidence.BasisRef(RELATION, BASIS_TYPE, "iss-1", "KRX:B", BASIS_KEY);
    }

    private static ObjectNode basisNode(String key, String... evidenceIds) {
        ObjectNode basis = StrictJson.newObject();
        basis.put("relationKey", key);
        basis.put("relationType", "SUPPLIES");
        ArrayNode ids = basis.putArray("evidenceIds");
        for (String id : evidenceIds) {
            ids.add(id);
        }
        return basis;
    }

    private static ObjectNode relationNode(String id, String type, String source, String target, ObjectNode... bases) {
        ObjectNode relation = StrictJson.newObject();
        relation.put("id", id);
        relation.put("type", type);
        relation.put("source", source);
        relation.put("target", target);
        relation.putArray("evidenceIds");
        ArrayNode list = relation.putArray("basis");
        for (ObjectNode basis : bases) {
            list.add(basis);
        }
        return relation;
    }

    private static ObjectNode withRelations(ObjectNode receipt, ObjectNode... relations) {
        ArrayNode list = ((ObjectNode) receipt.get("bundle")).putArray("relations");
        for (ObjectNode relation : relations) {
            list.add(relation);
        }
        return receipt;
    }

    private static ObjectNode relationOf(ObjectNode receipt, int index) {
        return (ObjectNode) receipt.get("bundle").get("relations").get(index);
    }

    private static ObjectNode basisOf(ObjectNode receipt) {
        return (ObjectNode) relationOf(receipt, 0).get("basis").get(0);
    }

    /** The evidence is cited by no visible issue or relation, only by the one visible structural basis the receipt records. */
    private void basisOnly() throws IOException {
        setUp();
        found = new GraphEvidence(GRAPH_VERSION, SELECTED_AS_OF, found.span(), List.of(), List.of(basisRef()), List.of());
        rewriteRegisteredReceipt(basisReceipt());
    }

    private static ObjectNode basisReceipt() {
        return withRelations(receipt(pins(PROVIDER, SOURCE_GRANT, SOURCE_REVISION)),
                relationNode(RELATION, BASIS_TYPE, "iss-1", "KRX:B", basisNode(BASIS_KEY, EVIDENCE_ID)));
    }

    @Test
    void aBasisOnlySpanIsServedWithoutEventsWhenTheReceiptProvesExactlyThatBasisCitesIt() throws Exception {
        basisOnly();

        EvidenceResponse response = get();

        assertEquals(EVIDENCE_ID, response.id());
        assertEquals(QUOTE, response.quote());
        assertEquals(List.of(), response.eventIds(), "a basis is not an event");
        assertEquals(GRAPH_VERSION, response.metadata().graphVersion());
        assertEquals(Boolean.TRUE, response.quoteVerified());
        assertEquals(1, graphReads.get());
    }

    @Test
    void aReceiptThatDoesNotProveTheBasisMembershipExactlyWithholdsTheBasisOnlySpan() throws Exception {
        basisOnly();
        List<Consumer<ObjectNode>> edits = new ArrayList<>();
        edits.add(n -> ((ObjectNode) n.get("bundle")).remove("relations"));
        edits.add(n -> ((ObjectNode) n.get("bundle")).putArray("relations"));
        edits.add(n -> ((ObjectNode) n.get("bundle")).put("relations", "x"));
        edits.add(n -> ((ArrayNode) n.get("bundle").get("relations")).add(relationOf(n, 0).deepCopy()));
        edits.add(n -> relationOf(n, 0).put("id", "edge-other"));
        edits.add(n -> relationOf(n, 0).put("type", "INVOLVES"));
        edits.add(n -> relationOf(n, 0).put("source", "iss-2"));
        edits.add(n -> relationOf(n, 0).put("target", "KRX:Z"));
        edits.add(n -> relationOf(n, 0).remove("basis"));
        edits.add(n -> relationOf(n, 0).putArray("basis"));
        edits.add(n -> basisOf(n).put("relationKey", "8".repeat(64)));
        edits.add(n -> basisOf(n).remove("relationKey"));
        edits.add(n -> ((ArrayNode) relationOf(n, 0).get("basis")).add(basisOf(n).deepCopy()));
        edits.add(n -> basisOf(n).putArray("evidenceIds").add("ev-" + "d".repeat(64)));
        edits.add(n -> basisOf(n).putArray("evidenceIds"));
        edits.add(n -> basisOf(n).remove("evidenceIds"));
        edits.add(n -> basisOf(n).put("evidenceIds", EVIDENCE_ID));
        int index = 0;
        for (Consumer<ObjectNode> edit : edits) {
            ObjectNode edited = basisReceipt();
            edit.accept(edited);
            rewriteRegisteredReceipt(edited);
            assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, refused(), "receipt variant " + index++);
        }
        rewriteRegisteredReceipt(basisReceipt());
        assertNotNull(get(), "the exact receipt serves it again");
    }

    @Test
    void readableIsTheSameJudgementAsTheReadForAPinnedBasisOnlySpan() throws Exception {
        basisOnly();
        // What chat jobs use to accept a selected evidence id and to re-check a stored citation.
        assertTrue(service().readable(EVIDENCE_ID, GRAPH_VERSION, null, "req-r"));

        ObjectNode notProven = basisReceipt();
        basisOf(notProven).putArray("evidenceIds").add("ev-" + "d".repeat(64));
        rewriteRegisteredReceipt(notProven);
        assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, refused());
        assertFalse(service().readable(EVIDENCE_ID, GRAPH_VERSION, null, "req-r"));

        rewriteRegisteredReceipt(basisReceipt());
        graphFailure = new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
        assertFalse(service().readable(EVIDENCE_ID, GRAPH_VERSION, null, "req-r"), "unverifiable is not readable");
        assertFalse(service().readable("ev-" + "0".repeat(64), GRAPH_VERSION, null, "req-r"));
        assertFalse(service().readable("not-an-evidence-id", GRAPH_VERSION, null, "req-r"));
    }

    @Test
    void readabilityKeepsAnOutageApartFromADenial() throws Exception {
        basisOnly();
        // A chat tool reports what it found: an outage must not read as "this evidence does not exist".
        assertEquals(EvidenceService.Readability.READABLE, service().readability(EVIDENCE_ID, GRAPH_VERSION, null, "req-r"));

        ObjectNode notProven = basisReceipt();
        basisOf(notProven).putArray("evidenceIds").add("ev-" + "d".repeat(64));
        rewriteRegisteredReceipt(notProven);
        assertEquals(EvidenceService.Readability.DENIED, service().readability(EVIDENCE_ID, GRAPH_VERSION, null, "req-r"));
        assertEquals(EvidenceService.Readability.DENIED,
                service().readability("ev-" + "0".repeat(64), GRAPH_VERSION, null, "req-r"));
        assertEquals(EvidenceService.Readability.DENIED,
                service().readability("not-an-evidence-id", GRAPH_VERSION, null, "req-r"));

        rewriteRegisteredReceipt(basisReceipt());
        graphFailure = new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
        assertEquals(EvidenceService.Readability.UNAVAILABLE,
                service().readability(EVIDENCE_ID, GRAPH_VERSION, null, "req-r"));
    }

    @Test
    void shownNowHidesADenialButReportsAnUnverifiableStateAsUnavailable() throws Exception {
        basisOnly();
        // getEvent: the same judgement as the read, with "cannot verify now" kept apart from "withheld".
        assertTrue(service().shownNow(EVIDENCE_ID, GRAPH_VERSION, null, "req-s"));

        ObjectNode notProven = basisReceipt();
        basisOf(notProven).putArray("evidenceIds").add("ev-" + "d".repeat(64));
        rewriteRegisteredReceipt(notProven);
        assertFalse(service().shownNow(EVIDENCE_ID, GRAPH_VERSION, null, "req-s"), "a withheld citation is hidden");
        assertFalse(service().shownNow("ev-" + "0".repeat(64), GRAPH_VERSION, null, "req-s"), "an unknown id is hidden");
        assertFalse(service().shownNow("not-an-evidence-id", GRAPH_VERSION, null, "req-s"));

        rewriteRegisteredReceipt(basisReceipt());
        graphFailure = new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
        assertEquals(ErrorCode.SOURCE_UNAVAILABLE, assertThrows(CustomException.class,
                () -> service().shownNow(EVIDENCE_ID, GRAPH_VERSION, null, "req-s")).getErrorCode(),
                "an unreadable store is a 503, never a hidden citation");
        assertFalse(service().readable(EVIDENCE_ID, GRAPH_VERSION, null, "req-s"), "readable keeps its chat meaning");
        graphFailure = new org.springframework.dao.DataAccessResourceFailureException("database down");
        assertEquals(ErrorCode.SOURCE_UNAVAILABLE, assertThrows(CustomException.class,
                () -> service().shownNow(EVIDENCE_ID, GRAPH_VERSION, null, "req-s")).getErrorCode());
    }

    @Test
    void theRelationsOwnCitationInTheReceiptNeverStandsInForTheBasisCitation() throws Exception {
        basisOnly();
        ObjectNode edited = basisReceipt();
        // The relation lists the evidence as its own, but the basis the snapshot referenced does not: no union of the two.
        relationOf(edited, 0).putArray("evidenceIds").add(EVIDENCE_ID);
        basisOf(edited).putArray("evidenceIds").add("ev-" + "d".repeat(64));
        rewriteRegisteredReceipt(edited);

        assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, refused());
    }

    @Test
    void anotherBasisOfTheSameRelationThatDoesNotCiteTheSpanIsNotAFailureButEveryCandidateMustResolveExactly() throws Exception {
        basisOnly();
        GraphEvidence.BasisRef second = new GraphEvidence.BasisRef(RELATION, BASIS_TYPE, "iss-1", "KRX:B", "8".repeat(64));
        found = new GraphEvidence(GRAPH_VERSION, SELECTED_AS_OF, found.span(), List.of(), List.of(basisRef(), second), List.of());

        ObjectNode both = withRelations(receipt(pins(PROVIDER, SOURCE_GRANT, SOURCE_REVISION)),
                relationNode(RELATION, BASIS_TYPE, "iss-1", "KRX:B", basisNode(BASIS_KEY, EVIDENCE_ID),
                        basisNode("8".repeat(64), "ev-" + "e".repeat(64))));
        rewriteRegisteredReceipt(both);
        assertNotNull(get(), "one candidate cites it, the other basis rests on other evidence");

        ObjectNode missing = withRelations(receipt(pins(PROVIDER, SOURCE_GRANT, SOURCE_REVISION)),
                relationNode(RELATION, BASIS_TYPE, "iss-1", "KRX:B", basisNode(BASIS_KEY, EVIDENCE_ID)));
        rewriteRegisteredReceipt(missing);
        assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, refused(), "a candidate the receipt does not hold fails the whole read");
    }

    @Test
    void aReceiptOfAnEarlierSchemaWithoutBasesCannotServeABasisOnlySpanButStillServesDirectlyCitedOnes() throws Exception {
        basisOnly();
        rewriteRegisteredReceipt(receipt(pins(PROVIDER, SOURCE_GRANT, SOURCE_REVISION)));
        assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, refused(), "no relations in the receipt: fail closed");

        found = new GraphEvidence(GRAPH_VERSION, SELECTED_AS_OF, found.span(), List.of("iss-1"), List.of(), List.of());
        assertEquals(List.of("iss-1"), get().eventIds(), "a directly cited span needs no basis proof");
    }

    @Test
    void everyCurrentRightsAndRowGateStillAppliesToABasisOnlySpan() throws Exception {
        basisOnly();
        List<String> needed = List.of("read", "store", "quote-display");
        String valid = source(PROVIDER, SOURCE_GRANT, SOURCE_REVISION, true, "known", needed, "e", null);
        for (String revoked : List.of(
                source(PROVIDER, SOURCE_GRANT, "rev-2", true, "known", needed, "e", null),
                source(PROVIDER, SOURCE_GRANT, SOURCE_REVISION, false, "known", needed, "e", null),
                source(PROVIDER, SOURCE_GRANT, SOURCE_REVISION, true, "known", List.of("read", "store"), "e", null),
                source(PROVIDER, SOURCE_GRANT, SOURCE_REVISION, true, "known", needed, "e", "2026-10-15T01:00:00Z"))) {
            writeSources(revoked);
            assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, refused(), revoked);
            writeSources(valid);
            assertNotNull(get(), "restored");
        }
        for (String status : List.of("private", "deleted")) {
            world.registry.setAccessStatus(ARTICLE, status);
            assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, refused(), status);
        }
        world.registry.setAccessStatus(ARTICLE, "available");
        assertNotNull(get());

        EvidenceView row = world.read.evidence.get(EVIDENCE_ID);
        world.read.evidence.put(EVIDENCE_ID, new EvidenceView(row.id(), row.articleId(), row.articleVersion(), row.textArtifactId(),
                row.quote(), row.startOffset(), row.endOffset(), "body", Boolean.FALSE, row.verificationArtifactId()));
        assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, refused(), "an unverified row is never served as basis evidence");
        world.read.evidence.put(EVIDENCE_ID, row);
        assertNotNull(get());
    }

    @Test
    void aTamperedOrUnreadableReceiptMakesABasisOnlyPublicationUnavailable() throws Exception {
        basisOnly();
        byte[] original = Files.readAllBytes(receiptFile());

        Files.write(receiptFile(), EvidenceWorld.bytes("{}"));
        assertEquals(ErrorCode.SOURCE_UNAVAILABLE, refused(), "bytes differ from the registered hash and size");
        Files.write(receiptFile(), original);
        assertNotNull(get());

        Files.setPosixFilePermissions(receiptFile(), PosixFilePermissions.fromString("rw-r--r--"));
        assertEquals(ErrorCode.SOURCE_UNAVAILABLE, refused(), "an insecure receipt file is a storage problem, not absence");
        Files.setPosixFilePermissions(receiptFile(), PosixFilePermissions.fromString("rw-------"));

        Files.delete(sources);
        assertEquals(ErrorCode.SOURCE_UNAVAILABLE, refused(), "the current registry is unavailable: never a silent success");
    }

    @Test
    void theReceiptOfAnotherGraphVersionNeverProvesABasisForThisOne() throws Exception {
        basisOnly();
        ObjectNode other = basisReceipt();
        other.put("handoffId", "handoff-other");
        rewriteRegisteredReceipt(other);

        assertEquals(ErrorCode.SOURCE_UNAVAILABLE, refused());
    }

    @Test
    void theBasisOnlyReadWritesNothingAndCreatesNoFile() throws Exception {
        basisOnly();
        List<String> files = snapshot(world.root);
        int writes = world.registry.writeAttempts();

        assertNotNull(get());

        assertEquals(files, snapshot(world.root), "no file is created, locked or changed by the read");
        assertEquals(writes, world.registry.writeAttempts());
    }

    // ---- the HTTP shape --------------------------------------------------------------------------------------------------

    @Test
    void theHttpShapeKeepsEveryContractKeyAndMapsTheStatuses() throws Exception {
        setUp();
        org.springframework.test.web.servlet.MockMvc mvc = org.springframework.test.web.servlet.setup.MockMvcBuilders
                .standaloneSetup(new com.zoop.document.evidence.controller.EvidenceController(service()))
                .setControllerAdvice(new com.zoop.common.exception.GlobalExceptionHandler())
                .addFilters(new com.zoop.common.request.RequestIdFilter()).build();
        String path = "/api/v1/evidence/" + EVIDENCE_ID;

        String json = mvc.perform(org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get(path)
                        .param("graphVersion", GRAPH_VERSION))
                .andExpect(org.springframework.test.web.servlet.result.MockMvcResultMatchers.status().isOk())
                .andExpect(org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath("$.metadata.graphVersion")
                        .value(GRAPH_VERSION))
                .andExpect(org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath("$.metadata.asOf")
                        .value("2026-10-10T00:00:00Z"))
                .andExpect(org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath("$.eventIds[0]").value("iss-1"))
                .andReturn().getResponse().getContentAsString(java.nio.charset.StandardCharsets.UTF_8);
        assertEquals(java.util.Set.of("id", "quote", "start", "end", "articleId", "articleVersion", "article", "quoteVerified",
                "eventIds", "metadata", "sentiment", "documentVersion", "documentSummary", "analysisStatus", "analysisProvenance",
                "resultVersion"), java.util.Set.copyOf(StrictJson.parseObject(json).node().propertyNames()));

        mvc.perform(org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get(path).param("round", "brf-1"))
                .andExpect(org.springframework.test.web.servlet.result.MockMvcResultMatchers.status().isConflict());
        mvc.perform(org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get(path).param("asOf", "yesterday"))
                .andExpect(org.springframework.test.web.servlet.result.MockMvcResultMatchers.status().isUnprocessableEntity());
        Files.delete(sources);
        mvc.perform(org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get(path))
                .andExpect(org.springframework.test.web.servlet.result.MockMvcResultMatchers.status().isServiceUnavailable());
        writeSources(source(PROVIDER, SOURCE_GRANT, "rev-2", true, "known", List.of("read", "store", "quote-display"), "e", null));
        mvc.perform(org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get(path))
                .andExpect(org.springframework.test.web.servlet.result.MockMvcResultMatchers.status().isNotFound())
                .andExpect(org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath("$.error.code")
                        .value("EVIDENCE_UNAVAILABLE"));
    }

    // ---- the real pinned reader under the real service ---------------------------------------------------------------------

    private static final String DIRECT_ID = "ev-" + "a".repeat(64);
    private static final Instant ACTIVATED = Instant.parse("2026-10-10T00:00:00Z");
    private static final String BEFORE_VERIFICATION = "2026-10-11T00:00:00Z";
    private static final String AFTER_VERIFICATION = "2026-10-13T00:00:00Z";

    /** The version is the one active pointer from {@link #ACTIVATED} on, and the only one ever activated. */
    private final class OneVersion implements GraphVersionRepository {
        private final ArtifactRow artifact = world.registry.findArtifact("artifact-" + GRAPH_VERSION).orElseThrow();
        private final GraphVersionRecord record = new GraphVersionRecord(GRAPH_VERSION, 1, "snapshot", artifact.id(),
                artifact.storageUri(), artifact.sha256(), true);

        @Override
        public Optional<GraphVersionRecord> find(String versionId) {
            return GRAPH_VERSION.equals(versionId) ? Optional.of(record) : Optional.empty();
        }

        @Override
        public Optional<GraphVersionRecord> active() {
            return Optional.of(record);
        }

        @Override
        public Optional<String> activeVersionIdAt(Instant asOf) {
            return asOf.isBefore(ACTIVATED) ? Optional.empty() : Optional.of(GRAPH_VERSION);
        }

        @Override
        public boolean everActivated(String versionId) {
            return GRAPH_VERSION.equals(versionId);
        }

        @Override
        public Optional<Instant> firstActivatedAt(String versionId) {
            return GRAPH_VERSION.equals(versionId) ? Optional.of(ACTIVATED) : Optional.empty();
        }
    }

    /**
     * One issue citing {@link #DIRECT_ID}; its structural edge cites it too and carries ONE basis (verified 2026-10-12) on the
     * same article, so {@link #EVIDENCE_ID} (the same span text, cited by nobody) is a basis-only span.
     */
    private static PublicGraphSnapshot stackSnapshot() {
        return new PublicGraphSnapshot(PublicGraphSnapshot.FORMAT, GRAPH_VERSION, HANDOFF,
                List.of(new PublicGraphSnapshot.Company("KRX:A", "A", null, null), new PublicGraphSnapshot.Company("KRX:B", "B", null, null)),
                List.of(new PublicGraphSnapshot.Issue("iss-1", "이슈", "2026-10-01", "day", null, null, null, null, "domestic", "geo-1",
                        List.of(DIRECT_ID), List.of(ARTICLE), List.of(DIRECT_ID), List.of(), null, "2026-10-01T00:00:00Z")),
                List.of(new PublicGraphSnapshot.Relation("edge-involves", "INVOLVES", "iss-1", "KRX:A", null, null, List.of(DIRECT_ID), List.of()),
                        new PublicGraphSnapshot.Relation(RELATION, BASIS_TYPE, "iss-1", "KRX:B", null, null, List.of(DIRECT_ID),
                                List.of(new PublicGraphSnapshot.Basis(BASIS_KEY, "SUPPLIES", "2026-10-12T00:00:00Z", null, null, List.of("KR"),
                                        List.of(new PublicGraphSnapshot.ArticleRef(ARTICLE, VERSION)))))),
                List.of(new PublicGraphSnapshot.Article(ARTICLE, VERSION, "제목", "https://example.invalid/a", "2026-10-01T00:00:00Z")),
                List.of(new PublicGraphSnapshot.Evidence(DIRECT_ID, ARTICLE, VERSION, (int) EvidenceWorld.START, (int) EvidenceWorld.END),
                        new PublicGraphSnapshot.Evidence(EVIDENCE_ID, ARTICLE, VERSION, (int) EvidenceWorld.START, (int) EvidenceWorld.END)));
    }

    private void realReader(java.util.function.Supplier<DisclosureExclusions> exclusions) throws IOException {
        realReader(exclusions, stackSnapshot());
    }

    private void realReader(java.util.function.Supplier<DisclosureExclusions> exclusions, PublicGraphSnapshot snapshot) throws IOException {
        realReader(exclusions, snapshot, snapshot, List.of());
    }

    private void realReader(java.util.function.Supplier<DisclosureExclusions> exclusions, PublicGraphSnapshot snapshot,
            PublicGraphSnapshot projection, List<com.zoop.graph.importer.GraphHandoffRepository.RuleRow> rules) throws IOException {
        basisOnly();
        world.registerGraph(snapshot, projection, rules);
        realPort = new GraphEvidenceSnapshotReader(publicReader(
                new GraphVersionSelector(new OneVersion(), java.time.Clock.fixed(NOW, java.time.ZoneOffset.UTC)), exclusions));
        world.read.evidence.put(DIRECT_ID, new EvidenceView(DIRECT_ID, ARTICLE, VERSION, TEXT, QUOTE, EvidenceWorld.START,
                EvidenceWorld.END, "body", Boolean.TRUE, EARLIER_RECEIPT));
    }

    private PublicGraphReader publicReader(GraphVersionSelector selector,
            java.util.function.Supplier<DisclosureExclusions> exclusions) {
        return new PublicGraphReader(selector, new ArtifactGraphSnapshotStore(world.store, world.registry, null),
                pinned -> exclusions.get(), world.publications(world.store),
                new GraphPublicationAuthority(world.registry, new DocumentReadSources(sources), pinned -> exclusions.get(),
                        java.time.Clock.fixed(NOW, java.time.ZoneOffset.UTC)));
    }

    private ErrorCode outcome(String evidenceId, String graphVersion, String asOf) {
        try {
            service().read(evidenceId, null, graphVersion, asOf, null, "req-s");
            return null;
        } catch (CustomException refused) {
            return refused.getErrorCode();
        }
    }

    @Test
    void theBasisOnlySpanIsServedUnderTheRealReaderWithoutEventsAndTheDirectOneKeepsItsEvent() throws Exception {
        realReader(() -> DisclosureExclusions.NONE);

        EvidenceResponse basis = service().read(EVIDENCE_ID, null, null, null, null, "r1");
        assertEquals(List.of(), basis.eventIds());
        assertEquals(GRAPH_VERSION, basis.metadata().graphVersion());
        EvidenceResponse direct = service().read(DIRECT_ID, null, null, null, null, "r2");
        assertEquals(List.of("iss-1"), direct.eventIds(), "directly cited evidence is unchanged by the basis seam");
        // The version alone is read as of its first publication (#88, ACTIVATED 10-10), before this basis was verified
        // (10-12): only the directly cited span is shown then, as with that asOf.
        assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, outcome(EVIDENCE_ID, GRAPH_VERSION, null),
                "the selected version pinned explicitly, at its first publication");
        assertNull(outcome(DIRECT_ID, GRAPH_VERSION, null));
        assertEquals(ErrorCode.VERSION_UNAVAILABLE, outcome(EVIDENCE_ID, "gv-" + "0".repeat(64), null), "a version that was never active");
    }

    @Test
    void anAsOfBeforeTheBasisWasVerifiedOrBeforeTheVersionExistedWithholdsOnlyTheBasisOnlySpan() throws Exception {
        realReader(() -> DisclosureExclusions.NONE);

        assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, outcome(EVIDENCE_ID, null, BEFORE_VERIFICATION),
                "the basis was verified 2026-10-12: a later basis never leaks into an earlier asOf");
        assertNull(outcome(DIRECT_ID, null, BEFORE_VERIFICATION), "the directly cited evidence is visible at that asOf");
        assertNull(outcome(EVIDENCE_ID, null, AFTER_VERIFICATION));
        assertNull(outcome(DIRECT_ID, null, AFTER_VERIFICATION));
        assertEquals(ErrorCode.VERSION_UNAVAILABLE, outcome(EVIDENCE_ID, null, "2026-10-09T00:00:00Z"));
        assertEquals(ErrorCode.VERSION_UNAVAILABLE, outcome(DIRECT_ID, null, "2026-10-09T00:00:00Z"));
    }

    @Test
    void anExcludedRelationIssueOrEvidenceWithdrawsTheBasisOnlySpanAndRestoringItServesAgain() throws Exception {
        DisclosureExclusions[] current = {DisclosureExclusions.NONE};
        realReader(() -> current[0]);
        assertNull(outcome(EVIDENCE_ID, null, null));

        current[0] = new DisclosureExclusions(1, java.util.Set.of(), java.util.Set.of(RELATION), java.util.Set.of());
        assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, outcome(EVIDENCE_ID, null, null), "the structural relation is excluded");
        assertNull(outcome(DIRECT_ID, null, null), "the issue's own evidence is untouched by a relation exclusion");
        current[0] = DisclosureExclusions.NONE;
        assertNull(outcome(EVIDENCE_ID, null, null), "restored");

        current[0] = new DisclosureExclusions(2, java.util.Set.of("iss-1"), java.util.Set.of(), java.util.Set.of());
        assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, outcome(EVIDENCE_ID, null, null), "the issue is excluded and takes its relations with it");
        assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, outcome(DIRECT_ID, null, null));
        current[0] = DisclosureExclusions.NONE;
        assertNull(outcome(EVIDENCE_ID, null, null), "restored");
        assertNull(outcome(DIRECT_ID, null, null));

        current[0] = new DisclosureExclusions(3, java.util.Set.of(), java.util.Set.of(), java.util.Set.of(EVIDENCE_ID));
        assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, outcome(EVIDENCE_ID, null, null), "the evidence itself is excluded");
        assertNull(outcome(DIRECT_ID, null, null));
        current[0] = DisclosureExclusions.NONE;
        assertNull(outcome(EVIDENCE_ID, null, null), "restored");
    }

    @Test
    void currentRightsReceiptAndArticleGatesStillDecideUnderTheRealReader() throws Exception {
        realReader(() -> DisclosureExclusions.NONE);
        List<String> needed = List.of("read", "store", "quote-display");

        writeSources(source(PROVIDER, SOURCE_GRANT, SOURCE_REVISION, true, "known", List.of("read", "store"), "e", null));
        assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, outcome(EVIDENCE_ID, null, null), "a revoked operation");
        assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, outcome(DIRECT_ID, null, null));
        writeSources(source(PROVIDER, SOURCE_GRANT, SOURCE_REVISION, true, "known", needed, "e", null));
        assertNull(outcome(EVIDENCE_ID, null, null), "restored");

        world.registry.setAccessStatus(ARTICLE, "private");
        assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, outcome(EVIDENCE_ID, null, null), "a private article");
        world.registry.setAccessStatus(ARTICLE, "available");
        assertNull(outcome(EVIDENCE_ID, null, null), "restored");

        byte[] original = Files.readAllBytes(receiptFile());
        Files.write(receiptFile(), EvidenceWorld.bytes("{}"));
        assertEquals(ErrorCode.SOURCE_UNAVAILABLE, outcome(EVIDENCE_ID, null, null), "a tampered receipt");
        assertEquals(ErrorCode.SOURCE_UNAVAILABLE, outcome(DIRECT_ID, null, null));
        Files.write(receiptFile(), original);
        assertNull(outcome(EVIDENCE_ID, null, null), "restored");
    }

    private static final String SECOND_ID = "ev-" + "e".repeat(64);
    private static final String SECOND_KEY = "8".repeat(64);

    /** The stack snapshot with a SECOND basis (verified 2026-10-14) on the same article, whose own evidence is {@link #SECOND_ID}. */
    private static PublicGraphSnapshot twoBasisSnapshot() {
        PublicGraphSnapshot one = stackSnapshot();
        PublicGraphSnapshot.Relation structural = one.relations().get(1);
        PublicGraphSnapshot.Basis first = structural.basis().get(0);
        PublicGraphSnapshot.Basis second = new PublicGraphSnapshot.Basis(SECOND_KEY, "SUPPLIES", "2026-10-14T00:00:00Z", null, null,
                List.of("KR"), List.of(new PublicGraphSnapshot.ArticleRef(ARTICLE, VERSION)));
        List<PublicGraphSnapshot.Evidence> evidence = new ArrayList<>(one.evidence());
        evidence.add(new PublicGraphSnapshot.Evidence(SECOND_ID, ARTICLE, VERSION, (int) EvidenceWorld.START, (int) EvidenceWorld.END));
        return new PublicGraphSnapshot(one.snapshotFormat(), one.versionId(), one.sourceBundleId(), one.companies(), one.issues(),
                List.of(one.relations().get(0), new PublicGraphSnapshot.Relation(structural.relationId(), structural.relationType(),
                        structural.source(), structural.target(), structural.role(), structural.assertionStatus(), structural.evidenceIds(),
                        List.of(first, second))), one.articles(), evidence);
    }

    @Test
    void aBasisVerifiedAfterAsOfNeverLeaksItsEvidenceThroughAnEarlierBasisOfTheSameArticle() throws Exception {
        realReader(() -> DisclosureExclusions.NONE, twoBasisSnapshot());
        world.read.evidence.put(SECOND_ID, new EvidenceView(SECOND_ID, ARTICLE, VERSION, TEXT, QUOTE, EvidenceWorld.START,
                EvidenceWorld.END, "body", Boolean.TRUE, EARLIER_RECEIPT));
        rewriteRegisteredReceipt(withRelations(receipt(pins(PROVIDER, SOURCE_GRANT, SOURCE_REVISION)),
                relationNode(RELATION, BASIS_TYPE, "iss-1", "KRX:B", basisNode(BASIS_KEY, EVIDENCE_ID), basisNode(SECOND_KEY, SECOND_ID))));
        String between = "2026-10-13T00:00:00Z";   // after the first basis (10-12), before the second (10-14)
        String after = "2026-10-15T00:00:00Z";

        assertNull(outcome(EVIDENCE_ID, null, between), "the first basis is verified and cites it");
        assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, outcome(SECOND_ID, null, between),
                "the second basis is not verified yet: the visible first basis (same article) must not carry its evidence");
        assertNull(outcome(EVIDENCE_ID, null, after));
        assertNull(outcome(SECOND_ID, null, after), "once the second basis is verified its own evidence is served");
        assertNull(outcome(SECOND_ID, null, null));
    }

    @Test
    void aReceiptOfTheEarlierBundle4ShapeWithBasesServesABasisOnlySpanUnderTheCurrentGates() throws Exception {
        basisOnly();
        ObjectNode edited = basisReceipt();
        // A -4 bundle has no structuralPath, pathCompanies or basis scopes, but the relation and basis keys the seam reads are the same.
        ((ObjectNode) edited.get("bundle")).put("schemaVersion", "zoop-graph-handoff-bundle-4");
        rewriteRegisteredReceipt(edited);

        assertEquals(List.of(), get().eventIds(), "an already imported receipt with the needed shape serves a basis-only span");
        writeSources(source(PROVIDER, SOURCE_GRANT, "rev-2", true, "known", List.of("read", "store", "quote-display"), "e", null));
        assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, refused(), "the current rights gate still decides");
    }

    // ---- impact-only evidence --------------------------------------------------------------------------------------------

    private static final String INVOLVES_EDGE = "edge-involves";
    private static final String JOB = "rel-1";
    private static final String RC = "rc-" + "2".repeat(64);
    private static final String OTHER_RC = "rc-" + "9".repeat(64);
    private static final String OTHER_ID = "ev-" + "d".repeat(64);

    private static GraphEvidence.ImpactRef impactRef() {
        return new GraphEvidence.ImpactRef(INVOLVES_EDGE, "INVOLVES", "iss-1", "KRX:A");
    }

    private static ObjectNode involvesNode(String id, String company, String... candidates) {
        ObjectNode relation = relationNode(id, "INVOLVES", "iss-1", company);
        ArrayNode refs = relation.putArray("sourceRefs");
        for (String candidate : candidates) {
            refs.addObject().put("kind", "s3-relation").put("jobId", JOB).put("id", candidate);
        }
        return relation;
    }

    /** One impact row in the closed 13-key shape; a verified row lists {@code positive} (the verifier-mapped quotes). */
    private static ObjectNode impactRow(String edge, String company, String candidate, String status, String... positive) {
        ObjectNode row = StrictJson.newObject();
        row.put("edgeId", edge);
        row.put("issueId", "iss-1");
        row.put("companyId", company);
        row.putObject("sourceRelation").put("jobId", JOB).put("relationCandidateId", candidate);
        row.put("status", status);
        row.putNull("code");
        if (status.equals("verified")) {
            row.put("impactCandidateId", "ic-" + "a".repeat(64));
            row.put("label", "positive");
            row.put("targetVerdict", "supported");
            ObjectNode effects = row.putObject("effects");
            ArrayNode ids = effects.putArray("positive");
            for (String id : positive) {
                ids.add(id);
            }
            effects.putArray("negative");
            effects.putArray("neutral");
            effects.putArray("uncertain");
            row.put("verifier", "called");
            row.put("verifierRequestDigest", "b".repeat(64));
            ObjectNode proposal = row.putObject("proposal");
            proposal.put("direction", "positive");
            proposal.put("reason", "합성 사유");
            proposal.putNull("limitations");
            proposal.put("verification", "none");
        } else {
            row.putNull("impactCandidateId");
            row.putNull("label");
            row.putNull("targetVerdict");
            row.putNull("effects");
            row.put("verifier", "not-called");
            row.putNull("verifierRequestDigest");
            row.putNull("proposal");
        }
        return row;
    }

    /**
     * A receipt with the INVOLVES relation of KRX:A (one S3 source relation) and the structural relation whose only basis rests on
     * OTHER evidence, so the span is cited by no basis; {@code rows} are the receipt's impact rows.
     */
    private static ObjectNode impactReceipt(ObjectNode... rows) {
        ObjectNode receipt = withRelations(receipt(pins(PROVIDER, SOURCE_GRANT, SOURCE_REVISION)),
                involvesNode(INVOLVES_EDGE, "KRX:A", RC),
                relationNode(RELATION, BASIS_TYPE, "iss-1", "KRX:B", basisNode(BASIS_KEY, OTHER_ID)));
        ArrayNode impacts = ((ObjectNode) receipt.get("bundle")).putArray("impacts");
        for (ObjectNode row : rows) {
            impacts.add(row);
        }
        return receipt;
    }

    private static ObjectNode verifiedReceipt() {
        return impactReceipt(impactRow(INVOLVES_EDGE, "KRX:A", RC, "verified", EVIDENCE_ID));
    }

    private static ObjectNode rowOf(ObjectNode receipt) {
        return (ObjectNode) receipt.get("bundle").get("impacts").get(0);
    }

    /** The evidence is cited by no visible issue or relation and by no basis: only the one visible INVOLVES relation can serve it. */
    private void impactOnly() throws IOException {
        setUp();
        found = new GraphEvidence(GRAPH_VERSION, SELECTED_AS_OF, found.span(), List.of(), List.of(), List.of(impactRef()));
        rewriteRegisteredReceipt(verifiedReceipt());
    }

    @Test
    void anImpactOnlySpanIsServedWithoutEventsWhenAVerifiedRowOfTheReferencedRelationListsIt() throws Exception {
        impactOnly();

        EvidenceResponse response = get();

        assertEquals(EVIDENCE_ID, response.id());
        assertEquals(QUOTE, response.quote());
        assertEquals(List.of(), response.eventIds(), "an impact quote is not an event citation");
        assertEquals(GRAPH_VERSION, response.metadata().graphVersion());
        assertEquals(Boolean.TRUE, response.quoteVerified());
        assertEquals(1, graphReads.get());
    }

    @Test
    void everyEffectSideOfAVerifiedRowServesItAndEveryOtherStatusOrIdDoesNot() throws Exception {
        impactOnly();
        for (String side : List.of("positive", "negative", "neutral", "uncertain")) {
            ObjectNode edited = verifiedReceipt();
            ((ObjectNode) rowOf(edited).get("effects")).putArray("positive");
            ((ObjectNode) rowOf(edited).get("effects")).putArray(side).add(EVIDENCE_ID);
            rewriteRegisteredReceipt(edited);
            assertNotNull(get(), "a quote the verifier mapped as " + side);
        }
        for (String status : List.of("not-applicable", "not-proposed", "no-evidence", "technical-reject", "verifier-reject", "withheld")) {
            rewriteRegisteredReceipt(impactReceipt(impactRow(INVOLVES_EDGE, "KRX:A", RC, status)));
            assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, refused(), status + " proves nothing");
        }
        rewriteRegisteredReceipt(impactReceipt(impactRow(INVOLVES_EDGE, "KRX:A", RC, "verified", OTHER_ID)));
        assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, refused(), "a verified row that lists other evidence");
        rewriteRegisteredReceipt(impactReceipt());
        assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, refused(), "no row for the relation: impact absence is unavailable, never a pass");
        rewriteRegisteredReceipt(verifiedReceipt());
        assertNotNull(get(), "restored");
    }

    @Test
    void aVerifiedRowOfAnotherRelationNeverServesThisOne() throws Exception {
        impactOnly();
        ObjectNode elsewhere = withRelations(receipt(pins(PROVIDER, SOURCE_GRANT, SOURCE_REVISION)),
                involvesNode(INVOLVES_EDGE, "KRX:A", RC), involvesNode("edge-other", "KRX:C", RC));
        ((ObjectNode) elsewhere.get("bundle")).putArray("impacts").add(impactRow("edge-other", "KRX:C", RC, "verified", EVIDENCE_ID))
                .add(impactRow(INVOLVES_EDGE, "KRX:A", RC, "not-proposed"));
        rewriteRegisteredReceipt(elsewhere);

        assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, refused(), "the referenced edge's own row decides, not another edge's");
    }

    @Test
    void aReceiptThatDoesNotBindTheImpactRowsToTheRelationExactlyWithholdsTheImpactOnlySpan() throws Exception {
        impactOnly();
        List<Consumer<ObjectNode>> edits = new ArrayList<>();
        edits.add(n -> ((ObjectNode) n.get("bundle")).put("impacts", "x"));
        edits.add(n -> ((ObjectNode) n.get("bundle")).putObject("impacts"));
        edits.add(n -> rowOf(n).remove("proposal"));
        edits.add(n -> rowOf(n).put("aggregate", "positive"));
        edits.add(n -> ((ArrayNode) n.get("bundle").get("impacts")).add(rowOf(n).deepCopy()));
        edits.add(n -> rowOf(n).put("issueId", "iss-2"));
        edits.add(n -> rowOf(n).put("companyId", "KRX:Z"));
        edits.add(n -> ((ObjectNode) rowOf(n).get("sourceRelation")).put("relationCandidateId", OTHER_RC));
        edits.add(n -> ((ObjectNode) rowOf(n).get("sourceRelation")).put("extra", "x"));
        edits.add(n -> rowOf(n).remove("sourceRelation"));
        edits.add(n -> rowOf(n).put("edgeId", 7));
        edits.add(n -> rowOf(n).remove("edgeId"));
        edits.add(n -> rowOf(n).put("status", 7));
        edits.add(n -> ((ObjectNode) rowOf(n).get("effects")).remove("uncertain"));
        edits.add(n -> ((ObjectNode) rowOf(n).get("effects")).put("positive", EVIDENCE_ID));
        edits.add(n -> ((ObjectNode) rowOf(n).get("effects")).put("supporting", "x"));
        edits.add(n -> rowOf(n).putNull("effects"));
        edits.add(n -> ((ArrayNode) n.get("bundle").get("relations")).remove(0));
        edits.add(n -> ((ArrayNode) n.get("bundle").get("relations")).add(n.get("bundle").get("relations").get(0).deepCopy()));
        edits.add(n -> relationOf(n, 0).put("type", "FOLLOWS"));
        edits.add(n -> relationOf(n, 0).put("source", "iss-2"));
        edits.add(n -> relationOf(n, 0).put("target", "KRX:Z"));
        edits.add(n -> relationOf(n, 0).remove("sourceRefs"));
        edits.add(n -> relationOf(n, 0).putArray("sourceRefs"));
        edits.add(n -> relationOf(n, 0).put("id", "edge-renamed"));
        int index = 0;
        for (Consumer<ObjectNode> edit : edits) {
            ObjectNode edited = verifiedReceipt();
            edit.accept(edited);
            rewriteRegisteredReceipt(edited);
            assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, refused(), "receipt variant " + index++);
        }
        rewriteRegisteredReceipt(verifiedReceipt());
        assertNotNull(get(), "the exact receipt serves it again");
    }

    @Test
    void aReceiptWithoutImpactsOfTheEarlierSchemasNeverServesAnImpactOnlySpanAndIsNotReadAsNotProposed() throws Exception {
        impactOnly();
        for (String schema : List.of("zoop-graph-handoff-bundle-4", "zoop-graph-handoff-bundle-5")) {
            ObjectNode earlier = withRelations(receipt(pins(PROVIDER, SOURCE_GRANT, SOURCE_REVISION)),
                    involvesNode(INVOLVES_EDGE, "KRX:A", RC));
            ((ObjectNode) earlier.get("bundle")).put("schemaVersion", schema);
            rewriteRegisteredReceipt(earlier);
            assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, refused(), schema);
        }
        found = new GraphEvidence(GRAPH_VERSION, SELECTED_AS_OF, found.span(), List.of("iss-1"), List.of(), List.of());
        assertEquals(List.of("iss-1"), get().eventIds(), "a directly cited span needs neither seam");
    }

    // ---- the two seams together: valid non-membership of one, structural malformation of either ----------------------------

    /** A candidate basis AND a candidate INVOLVES relation: the basis does not cite the span, the verified impact row does. */
    private void bothSeams() throws IOException {
        setUp();
        found = new GraphEvidence(GRAPH_VERSION, SELECTED_AS_OF, found.span(), List.of(), List.of(basisRef()), List.of(impactRef()));
        rewriteRegisteredReceipt(verifiedReceipt());
    }

    @Test
    void aBasisThatDoesNotCiteTheSpanIsValidNonMembershipAndTheVerifiedImpactRowStillServesIt() throws Exception {
        bothSeams();

        EvidenceResponse response = get();

        assertEquals(List.of(), response.eventIds());
        assertEquals(EVIDENCE_ID, response.id());
        // The same receipt with the span listed by the basis serves it through the basis, with no impact row needed at all.
        ObjectNode basisProves = withRelations(receipt(pins(PROVIDER, SOURCE_GRANT, SOURCE_REVISION)),
                involvesNode(INVOLVES_EDGE, "KRX:A", RC), relationNode(RELATION, BASIS_TYPE, "iss-1", "KRX:B", basisNode(BASIS_KEY, EVIDENCE_ID)));
        ((ObjectNode) basisProves.get("bundle")).putArray("impacts").add(impactRow(INVOLVES_EDGE, "KRX:A", RC, "not-proposed"));
        rewriteRegisteredReceipt(basisProves);
        assertNotNull(get(), "membership is basis-proven OR impact-proven");
    }

    @Test
    void neitherSeamProvingTheSpanWithholdsItEvenWhenBothReceiptsAreValid() throws Exception {
        bothSeams();
        rewriteRegisteredReceipt(impactReceipt(impactRow(INVOLVES_EDGE, "KRX:A", RC, "no-evidence")));

        assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, refused());
    }

    @Test
    void aMalformedBasisIsNeverBypassedByAnImpactRowThatWouldProveTheSpan() throws Exception {
        bothSeams();
        List<Consumer<ObjectNode>> edits = new ArrayList<>();
        edits.add(n -> ((ArrayNode) n.get("bundle").get("relations")).remove(1));
        edits.add(n -> ((ArrayNode) n.get("bundle").get("relations")).add(relationOf(n, 1).deepCopy()));
        edits.add(n -> relationOf(n, 1).put("target", "KRX:Z"));
        edits.add(n -> relationOf(n, 1).put("id", "edge-renamed"));
        edits.add(n -> relationOf(n, 1).remove("basis"));
        edits.add(n -> relationOf(n, 1).putArray("basis"));
        edits.add(n -> ((ObjectNode) relationOf(n, 1).get("basis").get(0)).remove("relationKey"));
        edits.add(n -> ((ObjectNode) relationOf(n, 1).get("basis").get(0)).put("relationKey", "8".repeat(64)));
        edits.add(n -> ((ArrayNode) relationOf(n, 1).get("basis")).add(relationOf(n, 1).get("basis").get(0).deepCopy()));
        edits.add(n -> ((ObjectNode) relationOf(n, 1).get("basis").get(0)).remove("evidenceIds"));
        int index = 0;
        for (Consumer<ObjectNode> edit : edits) {
            ObjectNode edited = verifiedReceipt();
            edit.accept(edited);
            rewriteRegisteredReceipt(edited);
            assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, refused(), "malformed basis variant " + index++);
        }
        rewriteRegisteredReceipt(verifiedReceipt());
        assertNotNull(get(), "the exact receipt serves it again");
    }

    @Test
    void aMalformedImpactIsNeverBypassedByABasisThatProvesTheSpan() throws Exception {
        bothSeams();
        List<Consumer<ObjectNode>> edits = new ArrayList<>();
        edits.add(n -> ((ArrayNode) n.get("bundle").get("impacts")).add(rowOf(n).deepCopy()));
        edits.add(n -> rowOf(n).remove("proposal"));
        edits.add(n -> rowOf(n).put("companyId", "KRX:Z"));
        edits.add(n -> ((ObjectNode) rowOf(n).get("sourceRelation")).put("relationCandidateId", OTHER_RC));
        edits.add(n -> ((ArrayNode) n.get("bundle").get("relations")).add(relationOf(n, 0).deepCopy()));
        edits.add(n -> relationOf(n, 0).put("type", "FOLLOWS"));
        edits.add(n -> ((ObjectNode) n.get("bundle")).put("impacts", "x"));
        int index = 0;
        for (Consumer<ObjectNode> edit : edits) {
            // The basis cites the span exactly, so it alone would serve it.
            ObjectNode edited = withRelations(receipt(pins(PROVIDER, SOURCE_GRANT, SOURCE_REVISION)),
                    involvesNode(INVOLVES_EDGE, "KRX:A", RC),
                    relationNode(RELATION, BASIS_TYPE, "iss-1", "KRX:B", basisNode(BASIS_KEY, EVIDENCE_ID)));
            ((ObjectNode) edited.get("bundle")).putArray("impacts").add(impactRow(INVOLVES_EDGE, "KRX:A", RC, "not-proposed"));
            edit.accept(edited);
            rewriteRegisteredReceipt(edited);
            assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, refused(), "malformed impact variant " + index++);
        }
    }

    @Test
    void aReceiptWithoutImpactsStillServesABasisOnlySpanThatAlsoHasAnImpactCandidate() throws Exception {
        setUp();
        found = new GraphEvidence(GRAPH_VERSION, SELECTED_AS_OF, found.span(), List.of(), List.of(basisRef()), List.of(impactRef()));
        // A -5 receipt: a structural basis that cites the span, a relation list, no impacts key at all.
        rewriteRegisteredReceipt(withRelations(receipt(pins(PROVIDER, SOURCE_GRANT, SOURCE_REVISION)),
                involvesNode(INVOLVES_EDGE, "KRX:A", RC), relationNode(RELATION, BASIS_TYPE, "iss-1", "KRX:B", basisNode(BASIS_KEY, EVIDENCE_ID))));

        assertEquals(List.of(), get().eventIds(), "the impact seam is inert without impacts");
    }

    @Test
    void everyCurrentRightsRowAndReceiptGateStillAppliesToAnImpactOnlySpan() throws Exception {
        impactOnly();
        List<String> needed = List.of("read", "store", "quote-display");
        String valid = source(PROVIDER, SOURCE_GRANT, SOURCE_REVISION, true, "known", needed, "e", null);
        for (String revoked : List.of(
                source(PROVIDER, SOURCE_GRANT, "rev-2", true, "known", needed, "e", null),
                source(PROVIDER, SOURCE_GRANT, SOURCE_REVISION, false, "known", needed, "e", null),
                source(PROVIDER, SOURCE_GRANT, SOURCE_REVISION, true, "known", List.of("read", "store"), "e", null),
                source(PROVIDER, SOURCE_GRANT, SOURCE_REVISION, true, "known", needed, "e", "2026-10-15T01:00:00Z"))) {
            writeSources(revoked);
            assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, refused(), revoked);
            writeSources(valid);
            assertNotNull(get(), "restored");
        }
        for (String status : List.of("private", "deleted")) {
            world.registry.setAccessStatus(ARTICLE, status);
            assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, refused(), status);
        }
        world.registry.setAccessStatus(ARTICLE, "available");
        assertNotNull(get());

        EvidenceView row = world.read.evidence.get(EVIDENCE_ID);
        world.read.evidence.put(EVIDENCE_ID, new EvidenceView(row.id(), row.articleId(), row.articleVersion(), row.textArtifactId(),
                row.quote(), row.startOffset(), row.endOffset(), "body", Boolean.FALSE, row.verificationArtifactId()));
        assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, refused(), "an unverified row is never served as an impact quote");
        world.read.evidence.put(EVIDENCE_ID, row);
        assertNotNull(get());

        byte[] original = Files.readAllBytes(receiptFile());
        Files.write(receiptFile(), EvidenceWorld.bytes("{}"));
        assertEquals(ErrorCode.SOURCE_UNAVAILABLE, refused(), "tampered receipt bytes");
        Files.write(receiptFile(), original);
        assertNotNull(get(), "restored");
        Files.setPosixFilePermissions(receiptFile(), PosixFilePermissions.fromString("rw-r--r--"));
        assertEquals(ErrorCode.SOURCE_UNAVAILABLE, refused(), "an insecure receipt file is a storage problem, not absence");
        Files.setPosixFilePermissions(receiptFile(), PosixFilePermissions.fromString("rw-------"));

        ObjectNode other = verifiedReceipt();
        other.put("handoffId", "handoff-other");
        rewriteRegisteredReceipt(other);
        assertEquals(ErrorCode.SOURCE_UNAVAILABLE, refused(), "the receipt of another graph version never proves an impact quote");
    }

    // ---- the real pinned reader: impact-only quote end to end through the service ------------------------------------------------

    /** The stack snapshot, a receipt whose basis cites OTHER evidence and whose verified INVOLVES row lists {@link #EVIDENCE_ID}. */
    private void realImpactReader(java.util.function.Supplier<DisclosureExclusions> exclusions) throws IOException {
        realReader(exclusions);
        rewriteRegisteredReceipt(verifiedReceipt());
    }

    @Test
    void anImpactOnlyQuoteIsServedUnderTheRealReaderWithEmptyEventIdsAndTheDirectOneKeepsItsEvent() throws Exception {
        realImpactReader(() -> DisclosureExclusions.NONE);

        EvidenceResponse impact = service().read(EVIDENCE_ID, null, null, null, null, "r1");
        assertEquals(List.of(), impact.eventIds());
        assertEquals(GRAPH_VERSION, impact.metadata().graphVersion());
        assertEquals(List.of("iss-1"), service().read(DIRECT_ID, null, null, null, null, "r2").eventIds());
        assertNull(outcome(EVIDENCE_ID, GRAPH_VERSION, null), "the selected version pinned explicitly");
        assertNull(outcome(EVIDENCE_ID, null, AFTER_VERIFICATION));
        assertNull(outcome(EVIDENCE_ID, null, BEFORE_VERIFICATION),
                "the INVOLVES relation does not depend on the time of a structural basis");
        assertEquals(ErrorCode.VERSION_UNAVAILABLE, outcome(EVIDENCE_ID, null, "2026-10-09T00:00:00Z"),
                "before the version was ever active: the asOf semantics are unchanged");
        assertEquals(ErrorCode.VERSION_UNAVAILABLE, outcome(EVIDENCE_ID, "gv-" + "0".repeat(64), null));
    }

    @Test
    void anExcludedInvolvesEdgeIssueOrQuoteWithdrawsTheImpactOnlyQuoteAndRestoringItServesAgain() throws Exception {
        DisclosureExclusions[] current = {DisclosureExclusions.NONE};
        realImpactReader(() -> current[0]);
        assertNull(outcome(EVIDENCE_ID, null, null));

        current[0] = new DisclosureExclusions(1, java.util.Set.of(), java.util.Set.of(INVOLVES_EDGE), java.util.Set.of());
        assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, outcome(EVIDENCE_ID, null, null), "the INVOLVES edge is excluded");
        assertNull(outcome(DIRECT_ID, null, null), "the issue's own evidence is untouched by a relation exclusion");
        current[0] = DisclosureExclusions.NONE;
        assertNull(outcome(EVIDENCE_ID, null, null), "restored");

        current[0] = new DisclosureExclusions(2, java.util.Set.of("iss-1"), java.util.Set.of(), java.util.Set.of());
        assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, outcome(EVIDENCE_ID, null, null), "the issue is excluded with its relations");
        current[0] = DisclosureExclusions.NONE;
        assertNull(outcome(EVIDENCE_ID, null, null), "restored");

        current[0] = new DisclosureExclusions(3, java.util.Set.of(), java.util.Set.of(), java.util.Set.of(EVIDENCE_ID));
        assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, outcome(EVIDENCE_ID, null, null), "the quote itself is excluded");
        current[0] = DisclosureExclusions.NONE;
        assertNull(outcome(EVIDENCE_ID, null, null), "restored");

        // The INVOLVES relation's own evidence being excluded removes the relation (the relation is dropped once any evidence is).
        current[0] = new DisclosureExclusions(4, java.util.Set.of(), java.util.Set.of(), java.util.Set.of(DIRECT_ID));
        assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, outcome(EVIDENCE_ID, null, null));
        current[0] = DisclosureExclusions.NONE;
        assertNull(outcome(EVIDENCE_ID, null, null), "restored");
    }

    @Test
    void currentRightsPrivateArticleAndTamperedReceiptStillDecideAnImpactOnlyQuoteUnderTheRealReader() throws Exception {
        realImpactReader(() -> DisclosureExclusions.NONE);
        List<String> needed = List.of("read", "store", "quote-display");

        writeSources(source(PROVIDER, SOURCE_GRANT, "rev-2", true, "known", needed, "e", null));
        assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, outcome(EVIDENCE_ID, null, null), "the grant revision was revoked");
        writeSources(source(PROVIDER, SOURCE_GRANT, SOURCE_REVISION, true, "known", needed, "e", null));
        assertNull(outcome(EVIDENCE_ID, null, null), "restored");

        world.registry.setAccessStatus(ARTICLE, "private");
        assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, outcome(EVIDENCE_ID, null, null), "a private article");
        world.registry.setAccessStatus(ARTICLE, "available");
        assertNull(outcome(EVIDENCE_ID, null, null), "restored");

        byte[] original = Files.readAllBytes(receiptFile());
        Files.write(receiptFile(), EvidenceWorld.bytes("{}"));
        assertEquals(ErrorCode.SOURCE_UNAVAILABLE, outcome(EVIDENCE_ID, null, null), "tampered receipt bytes");
        Files.write(receiptFile(), original);
        assertNull(outcome(EVIDENCE_ID, null, null), "restored");
    }

    @Test
    void aMalformedBasisUnderTheRealReaderIsNeverBypassedByTheImpactRowAndRestoringItServesAgain() throws Exception {
        realImpactReader(() -> DisclosureExclusions.NONE);
        assertNull(outcome(EVIDENCE_ID, null, null));

        // The snapshot references the structural basis (the same article); the receipt's basis list lost its relationKey.
        ObjectNode broken = verifiedReceipt();
        ((ObjectNode) relationOf(broken, 1).get("basis").get(0)).remove("relationKey");
        rewriteRegisteredReceipt(broken);
        assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, outcome(EVIDENCE_ID, null, null), "the malformed basis is not hidden by the verified row");
        assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, outcome(EVIDENCE_ID, null, AFTER_VERIFICATION));
        // Before the basis was verified the snapshot references no basis at all: the same receipt serves through the impact row only.
        assertNull(outcome(EVIDENCE_ID, null, BEFORE_VERIFICATION), "no basis candidate, so no basis malformation is read");
        rewriteRegisteredReceipt(verifiedReceipt());
        assertNull(outcome(EVIDENCE_ID, null, null), "restored");
    }

    private void roundImpactReader(Instant cutoff, java.util.function.Supplier<DisclosureExclusions> exclusions) throws IOException {
        realImpactReader(exclusions);
        var basis = new com.zoop.graph.version.BriefingGraphLookup.Basis("brf-1", GRAPH_VERSION, cutoff,
                Map.of("iss-1", List.of("KRX:A")));
        realPort = new GraphEvidenceSnapshotReader(publicReader(
                new GraphVersionSelector(new OneVersion(), java.time.Clock.fixed(NOW, java.time.ZoneOffset.UTC),
                        (round, request) -> basis), exclusions));
    }

    private EvidenceResponse getRound() {
        return service().read(EVIDENCE_ID, "brf-1", null, null, null, "req-round");
    }

    @Test
    void anOriginalRoundKeepsImpactOnlyQuotesBeforeAnyStructuralBasisOrActivationWithoutLeakingTheirLabels() throws Exception {
        Instant cutoff = Instant.parse("2026-10-09T00:00:00Z");
        DisclosureExclusions[] exclusions = {DisclosureExclusions.NONE};
        roundImpactReader(cutoff, () -> exclusions[0]);
        assertEquals(ErrorCode.VERSION_UNAVAILABLE, outcome(EVIDENCE_ID, null, cutoff.toString()),
                "the ordinary historical selector has no activation at this cutoff");

        EvidenceResponse response = service().read(EVIDENCE_ID, "brf-1", GRAPH_VERSION, cutoff.toString(), null, "req-round");
        assertEquals(QUOTE, response.quote());
        assertEquals(List.of(), response.eventIds());
        assertEquals(GRAPH_VERSION, response.metadata().graphVersion());
        assertEquals(cutoff, response.metadata().asOf());
        assertNull(response.documentSummary());
        assertNull(response.sentiment());
        assertNull(response.analysisStatus());
        assertNull(response.analysisProvenance());
        assertNull(response.resultVersion());
        var located = realPort.readRound("brf-1", null, null, EVIDENCE_ID, null, "req-round").graph();
        assertTrue(located.basisRefs().isEmpty(), "the structural basis was not yet verified");
        assertEquals(List.of(impactRef()), located.impactRefs());

        rewriteRegisteredReceipt(impactReceipt(impactRow(INVOLVES_EDGE, "KRX:A", RC, "no-evidence")));
        assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, assertThrows(CustomException.class, this::getRound).getErrorCode(),
                "keeping a candidate article is not permission to serve its quotes");
        rewriteRegisteredReceipt(verifiedReceipt());
        assertNotNull(getRound());
        exclusions[0] = new DisclosureExclusions(1, java.util.Set.of(), java.util.Set.of(), java.util.Set.of(EVIDENCE_ID));
        assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, assertThrows(CustomException.class, this::getRound).getErrorCode());
    }

    @Test
    void anOriginalRoundUsesBothMembershipProofsAndCurrentRightsOfItsSelectedReceipt() throws Exception {
        roundImpactReader(Instant.parse(AFTER_VERIFICATION), () -> DisclosureExclusions.NONE);
        assertNotNull(getRound(), "the row points at an earlier receipt; only the round's selected receipt is usable");
        ObjectNode brokenBasis = verifiedReceipt();
        ((ObjectNode) relationOf(brokenBasis, 1).get("basis").get(0)).remove("relationKey");
        rewriteRegisteredReceipt(brokenBasis);
        assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, assertThrows(CustomException.class, this::getRound).getErrorCode());

        ObjectNode brokenImpact = verifiedReceipt();
        ((ObjectNode) relationOf(brokenImpact, 1).get("basis").get(0)).putArray("evidenceIds").add(EVIDENCE_ID);
        rowOf(brokenImpact).remove("proposal");
        rewriteRegisteredReceipt(brokenImpact);
        assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, assertThrows(CustomException.class, this::getRound).getErrorCode());
        rewriteRegisteredReceipt(verifiedReceipt());
        writeSources(source(PROVIDER, SOURCE_GRANT, SOURCE_REVISION, true, "known", List.of("read", "store", "quote-display"),
                "e", "2026-10-14T00:00:00Z"));
        assertEquals(ErrorCode.VERSION_UNAVAILABLE, assertThrows(CustomException.class, this::getRound).getErrorCode(),
                "current rights removed the round's required headline source");
        writeSources(source(PROVIDER, SOURCE_GRANT, SOURCE_REVISION, true, "known", List.of("read", "store", "quote-display"),
                "e", null));
        assertNotNull(getRound());
        assertEquals(ErrorCode.INVALID_REQUEST, assertThrows(CustomException.class,
                () -> service().read(EVIDENCE_ID, "brf-1", GRAPH_VERSION, BEFORE_VERIFICATION, null, "req-round")).getErrorCode());
        assertEquals(ErrorCode.INVALID_REQUEST, assertThrows(CustomException.class,
                () -> service().read(EVIDENCE_ID, "brf-1", "gv-other", null, null, "req-round")).getErrorCode());
    }

    @Test
    void theImpactOnlyReadWritesNothingAndCreatesNoFile() throws Exception {
        impactOnly();
        List<String> files = snapshot(world.root);
        int writes = world.registry.writeAttempts();

        assertNotNull(get());

        assertEquals(files, snapshot(world.root), "no file is created, locked or changed by the read");
        assertEquals(writes, world.registry.writeAttempts());
    }

    // ---- activation precheck (FS059, PR #275 review 1) -------------------------------------------------------------------

    /** Both steps, the last one at the clock's now (the activation time when nothing else is going on). */
    private void precheck() {
        service().prepareGraphActivation(GRAPH_VERSION, Map.of(EVIDENCE_ID, found), "req-a").accept(NOW);
    }

    @Test
    void aGrantValidWhenTheChecksStartButExpiredAtActivationIsRefused() throws Exception {
        setUp();
        // Valid at NOW, ends one second later (an expiry equal to the judged time already denies).
        writeSources(source(PROVIDER, SOURCE_GRANT, SOURCE_REVISION, true, "known", List.of("read", "store", "quote-display"),
                "e", "2026-10-15T01:00:01Z"));
        var atActivation = service().prepareGraphActivation(GRAPH_VERSION, Map.of(EVIDENCE_ID, found), "req-a");

        atActivation.accept(NOW);
        assertEquals(ErrorCode.REVISION_CONFLICT, assertThrows(CustomException.class,
                () -> atActivation.accept(NOW.plusSeconds(2))).getErrorCode(),
                "the slow step judged nothing by time; the activation time decides");
    }

    @Test
    void theSlowStepNeverReadsTheRegistry() throws Exception {
        setUp();
        Files.delete(sources);

        var atActivation = service().prepareGraphActivation(GRAPH_VERSION, Map.of(EVIDENCE_ID, found), "req-a");

        assertEquals(ErrorCode.SOURCE_UNAVAILABLE, assertThrows(CustomException.class,
                () -> atActivation.accept(NOW)).getErrorCode(), "the registry is read once, at the activation time");
    }

    private ErrorCode precheckRefused() {
        return assertThrows(CustomException.class, this::precheck).getErrorCode();
    }

    @Test
    void theActivationPrecheckPassesWhatGetEvidenceServesWithoutAPinnedGraphRead() throws Exception {
        setUp();
        assertNotNull(get());
        graphReads.set(0);

        precheck();

        assertEquals(0, graphReads.get(), "the version is not active yet, so the selector must not be asked");
    }

    @Test
    void theActivationPrecheckRefusesWhateverGetEvidenceWouldWithholdAsAConflict() throws Exception {
        setUp();
        List<String> needed = List.of("read", "store", "quote-display");
        world.registry.setAccessStatus(ARTICLE, "private");
        assertEquals(ErrorCode.REVISION_CONFLICT, precheckRefused(), "article made private after the import");
        world.registry.setAccessStatus(ARTICLE, "available");

        writeSources(source(PROVIDER, SOURCE_GRANT, "rev-2", true, "known", needed, "e", null));
        assertEquals(ErrorCode.REVISION_CONFLICT, precheckRefused(), "grant revision changed after the import");
        writeSources(source(PROVIDER, SOURCE_GRANT, SOURCE_REVISION, false, "known", needed, "e", null));
        assertEquals(ErrorCode.REVISION_CONFLICT, precheckRefused(), "source disabled after the import");
        writeSources(source(PROVIDER, SOURCE_GRANT, SOURCE_REVISION, true, "known", needed, "e", null));
        precheck();

        world.read.evidence.remove(EVIDENCE_ID);
        assertEquals(ErrorCode.REVISION_CONFLICT, precheckRefused(), "the staged citation row is gone");
    }

    @Test
    void anUnreadableRegistryMakesTheActivationPrecheckUnavailableNotAConflict() throws Exception {
        setUp();
        Files.delete(sources);

        assertEquals(ErrorCode.SOURCE_UNAVAILABLE, precheckRefused());
    }

    @Test
    void activationAcceptsBasisAndImpactMembershipButRefusesAnUnprovenImpactCandidate() throws Exception {
        bothSeams();
        precheck();

        found = new GraphEvidence(GRAPH_VERSION, SELECTED_AS_OF, found.span(), List.of(), List.of(basisRef()), List.of());
        rewriteRegisteredReceipt(basisReceipt());
        precheck();

        found = new GraphEvidence(GRAPH_VERSION, SELECTED_AS_OF, found.span(), List.of(), List.of(), List.of(impactRef()));
        rewriteRegisteredReceipt(verifiedReceipt());
        precheck();
        rewriteRegisteredReceipt(impactReceipt(impactRow(INVOLVES_EDGE, "KRX:A", RC, "no-evidence")));
        assertEquals(ErrorCode.REVISION_CONFLICT, precheckRefused(), "impact-only candidates need receipt proof too");

        found = new GraphEvidence(GRAPH_VERSION, SELECTED_AS_OF, found.span(), List.of(), List.of(basisRef()), List.of(impactRef()));
        assertEquals(ErrorCode.REVISION_CONFLICT, precheckRefused(), "neither candidate proves membership");
        assertEquals(0, graphReads.get(), "activation uses the supplied snapshot, never the active-version selector");
    }

    @Test
    void activationNeverBypassesMalformedBasisOrImpactMembershipWithTheOtherSeam() throws Exception {
        bothSeams();
        ObjectNode brokenBasis = verifiedReceipt();
        ((ObjectNode) relationOf(brokenBasis, 1).get("basis").get(0)).remove("relationKey");
        rewriteRegisteredReceipt(brokenBasis);
        assertEquals(ErrorCode.REVISION_CONFLICT, precheckRefused(), "a verified impact cannot bypass a malformed basis");

        ObjectNode brokenImpact = verifiedReceipt();
        ((ObjectNode) relationOf(brokenImpact, 1).get("basis").get(0)).putArray("evidenceIds").add(EVIDENCE_ID);
        rowOf(brokenImpact).remove("proposal");
        rewriteRegisteredReceipt(brokenImpact);
        assertEquals(ErrorCode.REVISION_CONFLICT, precheckRefused(), "a citing basis cannot bypass a malformed impact");

        rewriteRegisteredReceipt(verifiedReceipt());
        precheck();
    }

    @Test
    void impactActivationRechecksCurrentRightsAtActivationAfterReceiptMembershipWasProven() throws Exception {
        impactOnly();
        var atActivation = service().prepareGraphActivation(GRAPH_VERSION, Map.of(EVIDENCE_ID, found), "req-a");
        atActivation.accept(NOW);

        writeSources(source(PROVIDER, SOURCE_GRANT, "rev-2", true, "known", List.of("read", "store", "quote-display"), "e", null));
        assertEquals(ErrorCode.REVISION_CONFLICT, assertThrows(CustomException.class,
                () -> atActivation.accept(NOW)).getErrorCode(), "rights revoked after membership proof still refuse activation");

        writeSources(source(PROVIDER, SOURCE_GRANT, SOURCE_REVISION, true, "known", List.of("read", "store", "quote-display"),
                "e", "2026-10-15T01:00:01Z"));
        atActivation.accept(NOW);
        assertEquals(ErrorCode.REVISION_CONFLICT, assertThrows(CustomException.class,
                () -> atActivation.accept(NOW.plusSeconds(2))).getErrorCode(), "impact grants are judged at activation time");
    }

    // ---- a publication rule's output under the real reader (#146) ----------------------------------------------------------------

    private static final String HIDDEN_EDGE = "edge-hidden";

    /**
     * The stack snapshot plus a forecast issue whose own INVOLVES edge is the only citation of {@link #EVIDENCE_ID} (same article
     * version as the stack). {@code structural}/{@code involves} keep the stack's structural edge (a basis candidate on that
     * article) and its INVOLVES edge (an impact candidate on it).
     */
    private static PublicGraphSnapshot withForecastIssue(boolean structural, boolean involves) {
        PublicGraphSnapshot stack = stackSnapshot();
        List<PublicGraphSnapshot.Issue> issues = new ArrayList<>(stack.issues());
        issues.add(new PublicGraphSnapshot.Issue("iss-2", "전망 이슈", "2026-10-01", "day", null, "forecast", null, null, "domestic",
                "geo-1", List.of(EVIDENCE_ID), List.of(ARTICLE), List.of(EVIDENCE_ID), List.of(), null, "2026-10-01T00:00:00Z"));
        List<PublicGraphSnapshot.Relation> relations = new ArrayList<>();
        for (PublicGraphSnapshot.Relation relation : stack.relations()) {
            boolean keep = "INVOLVES".equals(relation.relationType()) ? involves : structural;
            if (keep) relations.add(relation);
        }
        relations.add(new PublicGraphSnapshot.Relation(HIDDEN_EDGE, "INVOLVES", "iss-2", "KRX:A", null, null, List.of(EVIDENCE_ID),
                List.of()));
        return new PublicGraphSnapshot(stack.snapshotFormat(), stack.versionId(), stack.sourceBundleId(), stack.companies(), issues,
                relations, stack.articles(), stack.evidence());
    }

    private static final com.zoop.graph.importer.GraphHandoffRepository.RuleRow FORECAST_RULE =
            new com.zoop.graph.importer.GraphHandoffRepository.RuleRow("speculative-issue@1",
                    "{\"kind\":\"assertion_status\",\"hide\":[\"forecast\"]}");

    /** What the importer stores for that snapshot with {@code speculative-issue@1} enabled. */
    private static PublicGraphSnapshot ruleApplied(boolean structural, boolean involves) {
        PublicationRuleEvaluator.Outcome outcome = PublicationRuleEvaluator.apply(withForecastIssue(structural, involves),
                List.of(new PublicationRuleEvaluator.EnabledRule("speculative-issue@1",
                        new RuleDefinition.AssertionStatus(java.util.Set.of("forecast")))));
        assertEquals(java.util.Set.of("iss-2"), outcome.hiddenIssueIds());
        assertEquals(java.util.Set.of(HIDDEN_EDGE), outcome.hiddenRelationIds());
        assertTrue(outcome.snapshot().evidence().stream().anyMatch(e -> e.evidenceId().equals(EVIDENCE_ID)),
                "the span stays in the snapshot as an indirect candidate: its article version is still cited");
        return outcome.snapshot();
    }

    /** A receipt whose basis cites OTHER evidence and whose verified INVOLVES row lists OTHER evidence: it proves no span. */
    private static ObjectNode receiptProvingNothing() {
        return impactReceipt(impactRow(INVOLVES_EDGE, "KRX:A", RC, "verified", OTHER_ID));
    }

    @Test
    void aSpanOnlyItsHiddenRelationCitedIsServedBeforeTheRuleAndWithheldAfterItUnlessTheReceiptProvesIt() throws Exception {
        realReader(() -> DisclosureExclusions.NONE, withForecastIssue(true, true));
        rewriteRegisteredReceipt(receiptProvingNothing());
        assertNull(outcome(EVIDENCE_ID, null, null), "before the rule the hidden edge cites it directly");

        PublicGraphSnapshot filtered = ruleApplied(true, true);
        GraphEvidence located = GraphEvidenceSnapshotReader.locate(filtered, GRAPH_VERSION, NOW, EVIDENCE_ID);
        assertEquals(List.of(), located.eventIds());
        assertFalse(located.basisRefs().isEmpty(), "a basis candidate on the same article version");
        assertFalse(located.impactRefs().isEmpty(), "an impact candidate on the same article version");

        // The same world and receipt, now pinned to what the importer stores with the rule on.
        world.registerGraph(filtered, withForecastIssue(true, true), List.of(FORECAST_RULE));
        realPort = new GraphEvidenceSnapshotReader(publicReader(
                new GraphVersionSelector(new OneVersion(), java.time.Clock.fixed(NOW, java.time.ZoneOffset.UTC)),
                () -> DisclosureExclusions.NONE));
        assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, outcome(EVIDENCE_ID, null, null),
                "a candidate the receipt does not prove is never served once its own relation is hidden");
        assertNull(outcome(DIRECT_ID, null, null), "the visible issue's own evidence is untouched by the rule");

        rewriteRegisteredReceipt(basisReceipt());
        assertNull(outcome(EVIDENCE_ID, null, null), "a visible basis the receipt proves still serves it");
        rewriteRegisteredReceipt(verifiedReceipt());
        assertNull(outcome(EVIDENCE_ID, null, null), "a visible INVOLVES row the receipt proves still serves it");
    }

    @Test
    void aStructuralBasisOnlyCandidateLeftByTheRuleNeedsTheReceiptsBasisAndNeverAnImpactRow() throws Exception {
        PublicGraphSnapshot filtered = ruleApplied(true, false);
        GraphEvidence located = GraphEvidenceSnapshotReader.locate(filtered, GRAPH_VERSION, NOW, EVIDENCE_ID);
        assertFalse(located.basisRefs().isEmpty());
        assertEquals(List.of(), located.impactRefs(), "no visible INVOLVES edge cites the article version");

        realReader(() -> DisclosureExclusions.NONE, filtered, withForecastIssue(true, false), List.of(FORECAST_RULE));
        rewriteRegisteredReceipt(receiptProvingNothing());
        assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, outcome(EVIDENCE_ID, null, null));
        rewriteRegisteredReceipt(verifiedReceipt());
        assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, outcome(EVIDENCE_ID, null, null),
                "an impact row of an edge that is not visible proves nothing");
        rewriteRegisteredReceipt(basisReceipt());
        assertNull(outcome(EVIDENCE_ID, null, null));
    }

    @Test
    void anImpactOnlyCandidateLeftByTheRuleNeedsAVerifiedRowAndNeverABasis() throws Exception {
        PublicGraphSnapshot filtered = ruleApplied(false, true);
        GraphEvidence located = GraphEvidenceSnapshotReader.locate(filtered, GRAPH_VERSION, NOW, EVIDENCE_ID);
        assertEquals(List.of(), located.basisRefs(), "no visible structural edge has a basis on the article version");
        assertFalse(located.impactRefs().isEmpty());

        realReader(() -> DisclosureExclusions.NONE, filtered, withForecastIssue(false, true), List.of(FORECAST_RULE));
        rewriteRegisteredReceipt(receiptProvingNothing());
        assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, outcome(EVIDENCE_ID, null, null));
        rewriteRegisteredReceipt(basisReceipt());
        assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, outcome(EVIDENCE_ID, null, null),
                "a basis of an edge that is not visible proves nothing");
        rewriteRegisteredReceipt(verifiedReceipt());
        assertNull(outcome(EVIDENCE_ID, null, null));
    }
}
