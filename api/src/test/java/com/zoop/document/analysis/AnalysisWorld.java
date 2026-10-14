package com.zoop.document.analysis;

import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneId;
import java.time.ZoneOffset;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import java.util.function.Supplier;

import com.zoop.ai.AnalysisKind;
import com.zoop.ai.http.HttpAiAnalysisClient;
import com.zoop.ai.ExecutionMode;
import com.zoop.artifact.storage.ArtifactFileStore;
import com.zoop.common.json.Canonical;
import com.zoop.document.DocumentImportException;
import com.zoop.document.analysis.repository.AnalysisRow;
import com.zoop.document.analysis.service.DocumentAnalysisService;
import com.zoop.document.analysis.service.ReserveCommand;
import com.zoop.document.analysis.service.Reservation;
import com.zoop.document.analysis.service.SettleCommand;
import com.zoop.document.analysis.service.Settlement;
import com.zoop.document.importer.IngestionExportParser;
import com.zoop.document.importer.IngestionExporter;
import com.zoop.document.importer.Observation;
import com.zoop.document.repository.ArtifactRow;
import com.zoop.document.repository.VersionRow;
import com.zoop.document.service.InMemoryDocumentRegistry;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;
import tools.jackson.databind.node.ArrayNode;
import tools.jackson.databind.node.ObjectNode;

/**
 * One complete operator world for the analysis tests, built from the fixtures the real worker and the real service wire models
 * produced ({@code api/scripts/export_document_analysis_fixtures.py}): a registered synthetic document (Korean text with an
 * emoji, so UTF-16 and code point offsets differ), its stored text file, a company, the operator's flat grant registry, the real
 * artifact file store in a temporary directory, the real {@link DocumentAnalyzer} and the real HTTP client talking to a scripted
 * loopback AI service. Only the database (a double with relational semantics) and the S2-1 export (a stand-in for the CLI,
 * which the operator smoke runs for real) are replaced.
 */
final class AnalysisWorld implements AutoCloseable {
    static final JsonMapper JSON = JsonMapper.builder().build();
    static final ObjectNode RESULTS = load();
    static final ObjectNode DOCUMENT = (ObjectNode) RESULTS.get("document");
    static final String SOURCE = RESULTS.get("sourceId").stringValue();
    static final String DOCUMENT_ID = DOCUMENT.get("documentId").stringValue();
    static final String VERSION = DOCUMENT.get("documentVersion").stringValue();
    static final String TEXT = DOCUMENT.get("text").stringValue();
    static final String COMPANY_ID = RESULTS.get("company").get("companyId").stringValue();
    static final String COMPANY_NAME = RESULTS.get("company").get("name").stringValue();
    static final String GRANT_ID = RESULTS.get("grant").get("grantId").stringValue();
    static final String GRANT_REVISION = RESULTS.get("grant").get("revision").stringValue();
    static final Instant NOW = Instant.parse("2026-10-14T05:00:00Z");
    static final String SUMMARY = "document-summary";
    static final String SENTIMENT = "document-sentiment";

    /** What the scripted AI service answers; the tests change it between runs. */
    static final class Script {
        volatile boolean known;
        volatile boolean dropSubmitReply;
        volatile ObjectNode status;
        volatile ObjectNode envelope;
    }

    static final class MutableClock extends Clock {
        private volatile Instant now;

        MutableClock(Instant now) {
            this.now = now;
        }

        void set(Instant value) {
            this.now = value;
        }

        @Override
        public ZoneId getZone() {
            return ZoneOffset.UTC;
        }

        @Override
        public Clock withZone(ZoneId zone) {
            return this;
        }

        @Override
        public Instant instant() {
            return now;
        }
    }

    /** The reserve and settle transactions of the real service over doubles that can roll back. */
    static final class TransactionalService extends DocumentAnalysisService {
        private final InMemoryDocumentRegistry registry;
        private final InMemoryAnalysisWorld analyses;

        TransactionalService(InMemoryDocumentRegistry registry, InMemoryAnalysisWorld analyses, Clock clock) {
            super(registry, analyses, clock);
            this.registry = registry;
            this.analyses = analyses;
        }

        @Override
        public Reservation reserve(ReserveCommand command) {
            return registry.transactionally(() -> analyses.transactionally(() -> super.reserve(command)));
        }

        @Override
        public Settlement settle(SettleCommand command) {
            return registry.transactionally(() -> analyses.transactionally(() -> super.settle(command)));
        }
    }

    /** The S2-1 export of the fixture document, or a refusal. */
    static final class FakeExporter implements IngestionExporter {
        volatile DocumentImportException refusal;
        volatile ObjectNode document = DOCUMENT.deepCopy();
        int exports;

        @Override
        public byte[] export(Observation observation) {
            exports++;
            if (refusal != null) {
                throw refusal;
            }
            ObjectNode root = JSON.createObjectNode();
            root.put("schemaVersion", IngestionExportParser.SCHEMA_VERSION);
            ObjectNode node = root.putObject("observation");
            node.put("roundId", observation.roundId());
            node.put("sourceId", observation.sourceId());
            node.put("page", observation.page());
            node.put("ordinal", observation.ordinal());
            node.put("pageId", "page-0");
            node.put("observedAt", "2026-10-14T01:02:03.456789+00:00");
            node.put("documentId", observation.documentId());
            node.put("rawVersion", observation.rawVersion());
            node.put("documentVersion", observation.documentVersion());
            node.put("url", "https://example.invalid/a");
            node.put("title", "authored");
            node.put("publishedAt", "2026-10-08T09:00:00+09:00");
            node.putNull("modifiedAt");
            node.putNull("sourceRevision");
            node.put("mediaType", "text/html");
            ObjectNode grant = root.putObject("grant");
            grant.put("grantId", "s2-grant");
            grant.put("revision", "s2-1");
            root.set("document", document.deepCopy());
            root.putObject("locatorMetadata").put("rawHash", "9".repeat(64));
            return JSON.writeValueAsBytes(root);
        }
    }

    final Path root;
    final Path grantsFile;
    final ArtifactFileStore store;
    final InMemoryDocumentRegistry registry = new InMemoryDocumentRegistry();
    final InMemoryAnalysisWorld analyses = new InMemoryAnalysisWorld();
    final FakeAiService ai;
    private final HttpAiAnalysisClient client;
    final Script script = new Script();
    final MutableClock clock = new MutableClock(NOW);
    final FakeExporter exporter = new FakeExporter();
    final TransactionalService service = new TransactionalService(registry, analyses, clock);
    final DocumentAnalyzer analyzer;
    final ArrayDeque<String> hex = new ArrayDeque<>();
    ObjectNode grantsDocument;

    AnalysisWorld(Path directory) throws IOException {
        this.root = Files.createDirectory(directory.toRealPath().resolve("artifacts"));
        this.grantsFile = directory.toRealPath().resolve("grants.json");
        this.store = ArtifactFileStore.at(root);
        this.ai = new FakeAiService();
        ai.respond(this::answer);
        this.client = ai.client();
        this.analyzer = new DocumentAnalyzer(grantsFile, exporter, new IngestionExportParser(), store, registry, analyses,
                service, client, clock, (Supplier<String>) hex::removeFirst);
        seedDocument();
        analyses.seedCompany(COMPANY_ID, COMPANY_NAME);
        grantsDocument = defaultGrants();
        saveGrants();
    }

    private static ObjectNode load() {
        try (InputStream in = AnalysisWorld.class.getResourceAsStream("/document-analysis/worker-results.json")) {
            return (ObjectNode) JSON.readTree(in);
        } catch (IOException error) {
            throw new IllegalStateException("fixture is missing: run api/scripts/export_document_analysis_fixtures.py", error);
        }
    }

    /** A copy of one worker scenario: its {@code submit}, {@code status} and {@code envelope} (and {@code cache}). */
    static ObjectNode scenario(String name) {
        return (ObjectNode) RESULTS.get("scenarios").get(name).deepCopy();
    }

    static ObjectNode defaultGrants() {
        ObjectNode registry = JSON.createObjectNode();
        registry.put("schemaVersion", GrantRegistry.SCHEMA);
        ObjectNode grant = registry.putArray("grants").addObject();
        grant.put("grantId", GRANT_ID);
        grant.put("revision", GRANT_REVISION);
        grant.put("sourceId", SOURCE);
        grant.put("enabled", true);
        grant.put("rights", "known");
        ArrayNode operations = grant.putArray("allowedOperations");
        List.of("read", "store", "model-send", "quote-display").forEach(operations::add);
        grant.putArray("recipients").add(GrantRegistry.REPLAY_RECIPIENT);
        ArrayNode purposes = grant.putArray("purposes");
        List.of("document-summary", "document-sentiment", "semantic-verification").forEach(purposes::add);
        grant.putArray("evidence").add("authored synthetic fixture");
        grant.putNull("expiresAt");
        return registry;
    }

    ObjectNode grant() {
        return (ObjectNode) grantsDocument.get("grants").get(0);
    }

    void saveGrants() throws IOException {
        Files.write(grantsFile, JSON.writeValueAsBytes(grantsDocument));
    }

    /** The registered article, its immutable version and the stored text file, as the document import would leave them. */
    private void seedDocument() throws IOException {
        byte[] text = TEXT.getBytes(StandardCharsets.UTF_8);
        ArtifactFileStore.StoredFile file;
        try (ArtifactFileStore.Session session = store.open()) {
            file = session.put("extracted_text", "text-" + VERSION + ".txt", text);
        }
        registry.seedArticle(DOCUMENT_ID, "news", SOURCE, null, "available");
        registry.insertArtifactIfAbsent(new ArtifactRow("text-" + VERSION, "extracted_text", file.uri(), file.sha256(),
                file.bytes(), "text/plain; charset=utf-8", NOW));
        registry.insertVersionIfAbsent(new VersionRow(DOCUMENT_ID, VERSION, "authored", null, "https://example.invalid/a", NOW,
                null, "datetime", null, "text-" + VERSION, NOW));
    }

    // ---- requests ---------------------------------------------------------------------------------------------------

    static Observation observation() {
        return new Observation("round-1", SOURCE, 0, 0, DOCUMENT_ID, "5".repeat(64), VERSION);
    }

    static AnalysisRequest.PrepareItem item(String kind, String expectedLatest) {
        return new AnalysisRequest.PrepareItem(observation(), AnalysisKind.fromWire(kind).orElseThrow(), COMPANY_ID,
                new AnalysisRequest.GrantRef(GRANT_ID, GRANT_REVISION), ExecutionMode.REPLAY, "synthetic", expectedLatest);
    }

    /** The next prepare issues this AI job id and analysis id (32 hex characters each). */
    void issue(String jobHex, String analysisHex) {
        hex.addLast(jobHex);
        hex.addLast(analysisHex);
    }

    AnalysisRunResult prepare(String kind, String expectedLatest) {
        return analyzer.run(new AnalysisRequest.Prepare(List.of(item(kind, expectedLatest))));
    }

    AnalysisRunResult advance(String analysisId, boolean recover) {
        return analyzer.run(new AnalysisRequest.Advance(List.of(new AnalysisRequest.AdvanceItem(analysisId, recover))));
    }

    /** The single item of a one-item run. */
    static AnalysisItemResult only(AnalysisRunResult result) {
        return result.items().get(0);
    }

    static AnalysisItemResult.Prepared prepared(AnalysisRunResult result) {
        return (AnalysisItemResult.Prepared) only(result);
    }

    static AnalysisItemResult.Failed failed(AnalysisRunResult result) {
        return (AnalysisItemResult.Failed) only(result);
    }

    static AnalysisItemResult.Settled settled(AnalysisRunResult result) {
        return (AnalysisItemResult.Settled) only(result);
    }

    // ---- the scripted AI service ----------------------------------------------------------------------------------------

    private FakeAiService.Reply answer(FakeAiService.Request request) {
        String path = request.path();
        if (request.is("POST", "/analysis-jobs")) {
            script.known = true;
            if (script.dropSubmitReply) {
                return FakeAiService.Reply.json(503, FakeAiService.error("runtime_unavailable", true, request));
            }
            return FakeAiService.Reply.json(202, text(queued(script.status)));
        }
        if (request.is("POST", "/recover")) {
            return FakeAiService.Reply.json(202, text(script.status));
        }
        if (request.is("GET", "/result")) {
            return FakeAiService.Reply.json(200, text(script.envelope));
        }
        if (request.method().equals("GET") && path.contains("/analysis-jobs/")) {
            return script.known ? FakeAiService.Reply.json(200, text(script.status))
                    : FakeAiService.Reply.json(404, FakeAiService.error("job_not_found", false, request));
        }
        return FakeAiService.Reply.json(500, "{}");
    }

    /** A status as the service acknowledges a new submit: the job is queued and the caller should wait. */
    static ObjectNode queued(ObjectNode status) {
        ObjectNode copy = status.deepCopy();
        copy.put("state", "queued");
        copy.put("phase", "input.persisted");
        copy.put("resumeMode", "unsent_only");
        copy.putArray("artifactIds");
        copy.put("next", "wait");
        ((ObjectNode) copy.get("dispatch")).put("state", "pending");
        return copy;
    }

    static String text(JsonNode node) {
        return JSON.writeValueAsString(node);
    }

    /** From now on the service knows the job and answers with this scenario's status and result. */
    void serve(ObjectNode scenarioStatus, ObjectNode scenarioEnvelope) {
        script.known = true;
        script.status = scenarioStatus;
        script.envelope = scenarioEnvelope;
    }

    /** The service does not know the job yet; a submit makes it known and answers {@code queued}. */
    void serveUnknown(ObjectNode scenarioStatus, ObjectNode scenarioEnvelope) {
        serve(scenarioStatus, scenarioEnvelope);
        script.known = false;
    }

    // ---- inspection --------------------------------------------------------------------------------------------------

    Path file(String directory, String name) {
        return root.resolve(directory).resolve(name);
    }

    List<String> files(String directory) throws IOException {
        Path folder = root.resolve(directory);
        if (!Files.isDirectory(folder)) {
            return List.of();
        }
        try (var stream = Files.list(folder)) {
            return stream.map(path -> path.getFileName().toString()).sorted().toList();
        }
    }

    Optional<ArtifactRow> artifact(String id) {
        return registry.findArtifact(id);
    }

    List<String> artifactKinds() {
        List<String> kinds = new ArrayList<>();
        registry.state().artifacts().values().forEach(row -> kinds.add(row.kind()));
        return kinds.stream().sorted().toList();
    }

    AnalysisRow row(String id) {
        return analyses.row(id);
    }

    /** SHA-256 of the canonical JSON form (what the worker's {@code digest} computes). */
    static String digest(JsonNode node) {
        return Canonical.digest(node);
    }

    @Override
    public void close() {
        client.close();
        ai.close();
    }
}
