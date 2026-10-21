package com.zoop.document.evidence.service;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.PosixFilePermissions;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
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

    private void setUp() throws IOException {
        world = new EvidenceWorld(temp);
        sources = world.directory.resolve("sources.json");
        found = new GraphEvidence(GRAPH_VERSION, SELECTED_AS_OF,
                new GraphEvidence.Span(ARTICLE, VERSION, (int) EvidenceWorld.START, (int) EvidenceWorld.END), List.of("iss-1", "iss-2"));
        world.registry.insertArtifactIfAbsent(new ArtifactRow(EARLIER_RECEIPT, "verification_receipt",
                "artifact-root:verification_receipt/gone.json", "d".repeat(64), 10, "application/json", NOW));
        world.read.evidence.put(EVIDENCE_ID, new EvidenceView(EVIDENCE_ID, ARTICLE, VERSION, TEXT, QUOTE, EvidenceWorld.START,
                EvidenceWorld.END, "body", Boolean.TRUE, EARLIER_RECEIPT));
        writeReceipt(receipt(pins(PROVIDER, SOURCE_GRANT, SOURCE_REVISION)));
        writeSources(source(PROVIDER, SOURCE_GRANT, SOURCE_REVISION, true, "known", List.of("read", "store", "quote-display"),
                "operator-owned authored synthetic fixtures", null));
    }

    private GraphEvidenceReader port() {
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
        root.put("manifestDigest", "m".repeat(64));
        ObjectNode bundle = root.putObject("bundle");
        ArrayNode articles = bundle.putArray("articles");
        ObjectNode other = articles.addObject();
        other.put("articleId", "art-other");
        other.put("articleVersion", VERSION);
        other.putArray("observations").add(pins("someone-else", "other-grant", "other-rev"));
        ObjectNode article = articles.addObject();
        article.put("articleId", ARTICLE);
        article.put("articleVersion", VERSION);
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
        found = new GraphEvidence(GRAPH_VERSION, SELECTED_AS_OF, null, List.of());
        assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, refused());
    }

    @Test
    void theSnapshotSpanMustEqualTheRowExactly() throws Exception {
        setUp();
        for (GraphEvidence.Span span : List.of(new GraphEvidence.Span("art-x", VERSION, 5, 9),
                new GraphEvidence.Span(ARTICLE, "v9", 5, 9), new GraphEvidence.Span(ARTICLE, VERSION, 4, 9),
                new GraphEvidence.Span(ARTICLE, VERSION, 5, 10))) {
            found = new GraphEvidence(GRAPH_VERSION, SELECTED_AS_OF, span, List.of("iss-1"));
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
    void aReceiptThatCannotBeVerifiedOrDoesNotDescribeThisVersionExactlyWithholdsTheEvidence() throws Exception {
        setUp();
        byte[] original = Files.readAllBytes(receiptFile());

        Files.write(receiptFile(), EvidenceWorld.bytes("{}"));
        assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, refused(), "bytes differ from the registered hash");
        Files.write(receiptFile(), original);
        assertNotNull(get());

        List<Consumer<ObjectNode>> edits = new ArrayList<>();
        edits.add(n -> n.put("schemaVersion", "zoop-graph-handoff-import-receipt-2"));
        edits.add(n -> n.put("handoffId", "handoff-other"));
        edits.add(n -> n.remove("bundle"));
        edits.add(n -> n.putObject("bundle").putArray("articles"));
        edits.add(n -> ((ArrayNode) n.get("bundle").get("articles")).add(
                ((ArrayNode) n.get("bundle").get("articles")).get(1).deepCopy()));
        edits.add(n -> ((ObjectNode) n.get("bundle").get("articles").get(1)).putArray("observations"));
        edits.add(n -> ((ObjectNode) n.get("bundle").get("articles").get(1).get("observations").get(0).get("grant"))
                .put("revision", ""));
        edits.add(n -> ((ObjectNode) n.get("bundle").get("articles").get(1).get("observations").get(0).get("grant"))
                .put("revision", 7));
        edits.add(n -> ((ObjectNode) n.get("bundle").get("articles").get(1).get("observations").get(0)).remove("grant"));
        int index = 0;
        for (Consumer<ObjectNode> edit : edits) {
            ObjectNode edited = receipt(pins(PROVIDER, SOURCE_GRANT, SOURCE_REVISION));
            edit.accept(edited);
            rewriteRegisteredReceipt(edited);
            assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, refused(), "receipt variant " + index++);
        }
    }

    @Test
    void theReceiptOfAnEarlierOrTheCurrentBundleSchemaServesTheSameEvidenceBecauseOnlyItsArticlesAreRead() throws Exception {
        setUp();
        // A version imported under bundle -1 (issues without mentions), -2 (mentions, no field provenance) or -3 (field provenance,
        // no operator field verdicts) stays readable: nothing re-verifies the retained bundle, and -4 adds the issue's field verdicts
        // (and the withheld list of its provenance) beside the same articles.
        for (String schema : List.of("zoop-graph-handoff-bundle-1", "zoop-graph-handoff-bundle-2", "zoop-graph-handoff-bundle-3",
                "zoop-graph-handoff-bundle-4")) {
            ObjectNode edited = receipt(pins(PROVIDER, SOURCE_GRANT, SOURCE_REVISION));
            ObjectNode bundle = (ObjectNode) edited.get("bundle");
            bundle.put("schemaVersion", schema);
            ObjectNode issue = bundle.putArray("issues").addObject();
            issue.put("id", "iss-1");
            if (!schema.endsWith("-1")) {
                issue.putArray("mentions").addObject().put("verification", "none");
            }
            if (schema.endsWith("-3") || schema.endsWith("-4")) {
                ObjectNode provenance = issue.putObject("fieldProvenance").put("selection", "unanimous").put("verification", "none");
                if (schema.endsWith("-4")) {
                    provenance.putArray("withheld").add("eventTime");
                    ObjectNode verdict = issue.putArray("fieldVerdicts").addObject();
                    verdict.put("field", "eventTime").put("decision", "REJECT").put("verification", "operator-field-verdict");
                    verdict.putArray("evidenceIds");
                }
            }
            rewriteRegisteredReceipt(edited);
            assertNotNull(get(), schema);
        }
    }

    @Test
    void aReceiptOfTheFullBundle4WithApprovalBasesLiveProvenanceAndSourceSupportServesTheSameEvidence() throws Exception {
        setUp();
        // The importer's receipt holds the whole bundle: per-source provenance and review approvals (an operator's final approval
        // beside an automatic verdict), the origin and text digest of every article and the issue's sourceSupport. The evidence
        // read takes only the article's observation pins from it and must neither need nor trip over any of it.
        ObjectNode edited = receipt(pins(PROVIDER, SOURCE_GRANT, SOURCE_REVISION));
        ObjectNode bundle = (ObjectNode) edited.get("bundle");
        bundle.put("schemaVersion", "zoop-graph-handoff-bundle-4");
        bundle.putObject("provenance").put("declaredSourceKind", "synthetic").put("observedSourceKind", "synthetic")
                .put("executionMode", "live").put("recordingKind", "provider");
        ObjectNode source = bundle.putArray("sources").addObject();
        source.putObject("provenance").put("sourceKind", "synthetic").put("executionMode", "live").put("recordingKind", "provider");
        ArrayNode used = source.putArray("reviewUsed");
        used.addObject().put("relationCandidateId", "rc-" + "1".repeat(64)).put("revision", 2).putObject("approvalBasis")
                .put("kind", "automatic-verifier").put("revision", 2).putNull("reviewer").put("decidedAt", "2026-10-21T00:00:00Z");
        used.addObject().put("relationCandidateId", "rc-" + "2".repeat(64)).put("revision", 3).putObject("approvalBasis")
                .put("kind", "operator-final-approval").put("revision", 3).put("reviewer", "reviewer-1")
                .put("decidedAt", "2026-10-21T01:00:00Z");
        ArrayNode articles = (ArrayNode) bundle.get("articles");
        ObjectNode article = (ObjectNode) articles.get(1);
        article.put("textSha256", "a".repeat(64));
        article.putObject("origin").put("originId", "origin-1").put("reviewer", "reviewer-1").put("decisionRef", "d:1")
                .put("decisionVersion", "v1").put("verification", "operator-declared-origin");
        ObjectNode issue = bundle.putArray("issues").addObject();
        issue.put("id", "iss-1");
        issue.putObject("sourceSupport").put("articleCount", 1).put("knownLineageCount", 1).put("independentSourceCount", 1)
                .putArray("unknownLineageArticles");
        rewriteRegisteredReceipt(edited);
        assertNotNull(get());
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
    void aMissingOrWrongKindOfReceiptAndAMissingStoreAreHandledAsDenialOrUnavailable() throws Exception {
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
        assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, refused(), "wrong kind");
        world.registry.replaceArtifact(new ArtifactRow(row.id(), row.kind(), row.storageUri(), row.sha256(), row.bytes(),
                "text/plain", row.createdAt()));
        assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, refused(), "wrong media type");
        world.registry.removeArtifact(row.id());
        assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, refused(), "no receipt registered for the selected version");
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
        found = new GraphEvidence(GRAPH_VERSION, Instant.parse("2026-01-01T00:00:00Z"), found.span(), found.eventIds());
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
}
