package com.zoop.document.importer;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.PosixFilePermissions;
import java.security.MessageDigest;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.LocalDate;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HexFormat;
import java.util.List;
import java.util.Map;
import java.util.Set;

import com.zoop.artifact.storage.ArtifactFileStore;
import com.zoop.document.DocumentImportException;
import com.zoop.document.DocumentImportFailure;
import com.zoop.document.repository.ArtifactRow;
import com.zoop.document.service.ArticleKind;
import com.zoop.document.service.DocumentRegistrationService;
import com.zoop.document.service.InMemoryDocumentRegistry;
import com.zoop.document.service.PointerPolicy;
import com.zoop.document.service.RegistrationCommand;
import com.zoop.document.service.RegistrationOutcome;
import com.zoop.document.service.RegistrationOutcome.PointerResult;
import com.zoop.document.service.RegistrationOutcome.Presence;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.dao.DataAccessResourceFailureException;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.node.ObjectNode;

import static com.zoop.document.importer.ExportFixtures.EMOJI_HASH;
import static com.zoop.document.importer.ExportFixtures.EMOJI_TEXT;
import static com.zoop.document.importer.ExportFixtures.MIXED_HASH;
import static com.zoop.document.importer.ExportFixtures.MIXED_TEXT;
import static com.zoop.document.importer.ExportFixtures.PLAIN_HASH;
import static com.zoop.document.importer.ExportFixtures.PLAIN_TEXT;
import static com.zoop.document.importer.ExportFixtures.hex64;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertArrayEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertInstanceOf;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * The whole item pipeline with the real parser, file store, importer and registration service; only the S2-1 export
 * (a stand-in for the CLI, which the operator smoke runs for real) and the database (a double with relational semantics and
 * a reproduced transaction boundary) are replaced.
 */
class DocumentImporterTest {
    private static final String SOURCE = "synthetic-source";
    private static final String FIRST_OBSERVED = "2026-10-14T01:02:03.456789+00:00";
    private static final String LATER_OBSERVED = "2026-10-14T03:00:00+00:00";

    private static final Observation A1 = obs("r1", SOURCE, 0, 0, 'a', '1');
    private static final Observation B1 = obs("r1", SOURCE, 0, 1, 'b', '9');
    private static final Observation A2 = obs("r2", SOURCE, 0, 0, 'a', '2');
    /** The replay of A1 in a later round: same document, same version, new observation time. */
    private static final Observation A1_REPLAY = obs("r3", SOURCE, 0, 0, 'a', '1');
    private static final Observation A3 = obs("r4", SOURCE, 0, 0, 'a', '3');

    @TempDir
    Path temp;
    private Path root;
    private ArtifactFileStore store;
    private InMemoryDocumentRegistry registry;
    private FakeExporter exporter;
    private TransactionalService service;
    private DocumentImporter importer;

    @BeforeEach
    void setUp() throws IOException {
        root = Files.createDirectory(temp.toRealPath().resolve("artifacts"));
        store = ArtifactFileStore.at(root);
        registry = new InMemoryDocumentRegistry();
        exporter = new FakeExporter();
        service = new TransactionalService(registry);
        importer = new DocumentImporter(exporter, new IngestionExportParser(), store, service);
        exporter.serve(A1, PLAIN_TEXT, PLAIN_HASH, FIRST_OBSERVED);
        exporter.serve(B1, PLAIN_TEXT, PLAIN_HASH, FIRST_OBSERVED);
        exporter.serve(A2, MIXED_TEXT, MIXED_HASH, FIRST_OBSERVED);
        exporter.serve(A1_REPLAY, PLAIN_TEXT, PLAIN_HASH, LATER_OBSERVED);
        exporter.serve(A3, EMOJI_TEXT, EMOJI_HASH, FIRST_OBSERVED);
    }

    private static Observation obs(String round, String source, int page, int ordinal, char document, char version) {
        return new Observation(round, source, page, ordinal, "doc-" + hex64(document), hex64('r'), hex64(version));
    }

    private static ImportItem item(Observation observation, PointerPolicy pointer) {
        return new ImportItem(ArticleKind.NEWS, observation, pointer);
    }

    private DocumentImportResult run(ImportItem... items) {
        return importer.run(new ImportRequest(List.of(items)));
    }

    private Path textFile(Observation observation) {
        return root.resolve("extracted_text").resolve("text-" + observation.documentVersion() + ".txt");
    }

    private static ItemResult.Imported imported(DocumentImportResult result, int index) {
        return assertInstanceOf(ItemResult.Imported.class, result.items().get(index));
    }

    private static ItemResult.Failed failed(DocumentImportResult result, int index) {
        return assertInstanceOf(ItemResult.Failed.class, result.items().get(index));
    }

    private static String sha256(byte[] bytes) throws Exception {
        return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes));
    }

    private static JsonNode json(DocumentImportResult result) {
        return ExportFixtures.JSON.readTree(DocumentImportResultWriter.toBytes(result));
    }

    @Test
    void registersEveryIdentityVerbatimAndStoresTheExactUtf8Bytes() throws Exception {
        DocumentImportResult result = run(item(A1, PointerPolicy.moveFrom(null)));

        assertTrue(result.succeeded());
        ItemResult.Imported item = imported(result, 0);
        assertEquals(A1.documentId(), item.documentId());
        assertEquals(A1.documentVersion(), item.documentVersion());
        assertEquals("text-" + A1.documentVersion(), item.textArtifactId());
        assertEquals(Presence.CREATED, item.article());
        assertEquals(Presence.CREATED, item.artifact());
        assertEquals(Presence.CREATED, item.artifactFile());
        assertEquals(Presence.CREATED, item.version());
        assertEquals(PointerResult.MOVED, item.pointer());
        assertEquals(A1.documentVersion(), item.currentVersion());
        assertEquals(Instant.parse("2026-10-14T01:02:03.456789Z"), item.collectedAt());
        assertEquals("operator-grant", item.grantId());
        assertEquals("rights-1", item.grantRevision());

        byte[] expectedBytes = PLAIN_TEXT.getBytes(StandardCharsets.UTF_8);
        assertEquals(PLAIN_TEXT, Files.readString(textFile(A1), StandardCharsets.UTF_8));
        InMemoryDocumentRegistry.State state = registry.state();
        assertEquals(1, state.articles().size());
        assertEquals(A1.documentId(), state.articles().get(A1.documentId()).id());
        assertEquals(SOURCE, state.articles().get(A1.documentId()).provider());
        assertEquals("news", state.articles().get(A1.documentId()).kind());
        assertEquals(A1.documentVersion(), state.articles().get(A1.documentId()).currentVersion());
        ArtifactRow artifact = state.artifacts().get("text-" + A1.documentVersion());
        assertEquals("extracted_text", artifact.kind());
        assertEquals("artifact-root:extracted_text/text-" + A1.documentVersion() + ".txt", artifact.storageUri());
        assertEquals(sha256(expectedBytes), artifact.sha256());
        assertEquals(expectedBytes.length, artifact.bytes());
        assertEquals("text/plain; charset=utf-8", artifact.mediaType());
        var version = state.versions().values().iterator().next();
        assertEquals("authored", version.title());
        assertEquals("https://example.invalid/a", version.url());
        assertEquals(Instant.parse("2026-10-08T00:00:00Z"), version.publishedAt());
        assertEquals("datetime", version.publicationPrecision());
        assertNull(version.rawArtifactId());
        assertEquals("text-" + A1.documentVersion(), version.textArtifactId());
    }

    @Test
    void everyTextShapeIsStoredByteForByte() throws Exception {
        run(item(A2, PointerPolicy.keep()), item(A3, PointerPolicy.keep()));

        assertArrayEquals(MIXED_TEXT.getBytes(StandardCharsets.UTF_8), Files.readAllBytes(textFile(A2)));
        assertArrayEquals(EMOJI_TEXT.getBytes(StandardCharsets.UTF_8), Files.readAllBytes(textFile(A3)));
    }

    @Test
    void twoSourcesWithTheSameBytesStayTwoDocumentsWithTwoArtifacts() throws Exception {
        Observation other = obs("r1", "other-source", 0, 2, 'c', '8');
        exporter.serve(other, PLAIN_TEXT, PLAIN_HASH, FIRST_OBSERVED);

        DocumentImportResult result = run(item(A1, PointerPolicy.moveFrom(null)), item(other, PointerPolicy.keep()));

        assertTrue(result.succeeded());
        InMemoryDocumentRegistry.State state = registry.state();
        assertEquals(2, state.articles().size());
        assertEquals(2, state.artifacts().size());
        ArtifactRow first = state.artifacts().get("text-" + A1.documentVersion());
        ArtifactRow second = state.artifacts().get("text-" + other.documentVersion());
        assertEquals(first.sha256(), second.sha256());
        assertEquals(first.bytes(), second.bytes());
        assertFalse(first.storageUri().equals(second.storageUri()));
        assertEquals("other-source", state.articles().get(other.documentId()).provider());
        assertEquals(Files.readString(textFile(A1)), Files.readString(textFile(other)));
        assertFalse(Files.isSameFile(textFile(A1), textFile(other)));
    }

    @Test
    void replayNewVersionAndPointerSequenceKeepsEveryRuleAcrossRuns() throws Exception {
        // Run 1: first registration of two documents with the same bytes, explicit pointer from "none".
        DocumentImportResult first = run(item(A1, PointerPolicy.moveFrom(null)), item(B1, PointerPolicy.moveFrom(null)));
        assertTrue(first.succeeded());
        assertEquals(PointerResult.MOVED, imported(first, 0).pointer());
        assertEquals(PointerResult.MOVED, imported(first, 1).pointer());
        assertEquals(2, exporter.calls.size());

        // Run 2: identical request is a no-op, but it still takes a fresh export per item.
        InMemoryDocumentRegistry.State beforeRerun = registry.state();
        Object inode = Files.readAttributes(textFile(A1), "unix:ino").get("ino");
        long modified = Files.getLastModifiedTime(textFile(A1)).toMillis();
        DocumentImportResult rerun = run(item(A1, PointerPolicy.moveFrom(null)), item(B1, PointerPolicy.moveFrom(null)));
        assertTrue(rerun.succeeded());
        for (int index = 0; index < 2; index++) {
            ItemResult.Imported item = imported(rerun, index);
            assertEquals(Presence.EXISTING, item.article());
            assertEquals(Presence.EXISTING, item.artifact());
            assertEquals(Presence.EXISTING, item.artifactFile());
            assertEquals(Presence.EXISTING, item.version());
            assertEquals(PointerResult.ALREADY_CURRENT, item.pointer());
        }
        assertEquals(beforeRerun, registry.state());
        assertEquals(inode, Files.readAttributes(textFile(A1), "unix:ino").get("ino"));
        assertEquals(modified, Files.getLastModifiedTime(textFile(A1)).toMillis());
        assertEquals(4, exporter.calls.size());

        // Run 3: a new version of the same document is inserted; the pointer stays on the first version.
        DocumentImportResult newVersion = run(item(A2, PointerPolicy.keep()));
        assertEquals(Presence.CREATED, imported(newVersion, 0).version());
        assertEquals(Presence.EXISTING, imported(newVersion, 0).article());
        assertEquals(PointerResult.UNCHANGED, imported(newVersion, 0).pointer());
        assertEquals(A1.documentVersion(), imported(newVersion, 0).currentVersion());

        // Run 4: a replay of the first version, observed later, adds nothing and keeps the first observation.
        InMemoryDocumentRegistry.State beforeReplay = registry.state();
        DocumentImportResult replay = run(item(A1_REPLAY, PointerPolicy.keep()));
        assertEquals(Presence.EXISTING, imported(replay, 0).version());
        assertEquals(Instant.parse("2026-10-14T01:02:03.456789Z"), imported(replay, 0).collectedAt());
        assertEquals(PointerResult.UNCHANGED, imported(replay, 0).pointer());
        assertEquals(A1.documentVersion(), imported(replay, 0).currentVersion());
        assertEquals(beforeReplay, registry.state());

        // Run 5: an explicit compare-and-set to the newer version.
        DocumentImportResult moved = run(item(A2, PointerPolicy.moveFrom(A1.documentVersion())));
        assertEquals(PointerResult.MOVED, imported(moved, 0).pointer());
        assertEquals(A2.documentVersion(), imported(moved, 0).currentVersion());

        // Run 6: the out-of-order replay may not pull the pointer back; the batch stops there and rolls the item back.
        InMemoryDocumentRegistry.State beforeConflict = registry.state();
        int callsBefore = exporter.calls.size();
        DocumentImportResult conflict = run(item(A1_REPLAY, PointerPolicy.moveFrom(A1.documentVersion())),
                item(A3, PointerPolicy.keep()));
        assertFalse(conflict.succeeded());
        ItemResult.Failed failure = failed(conflict, 0);
        assertEquals(DocumentImportFailure.CURRENT_VERSION_CONFLICT, failure.failure());
        assertTrue(failure.hasCurrentVersion());
        assertEquals(A2.documentVersion(), failure.currentVersion());
        assertEquals(new ItemResult.NotAttempted(1), conflict.items().get(1));
        assertEquals(beforeConflict, registry.state());
        assertFalse(Files.exists(textFile(A3)));
        assertEquals(callsBefore + 1, exporter.calls.size());

        // Run 7: a new version with a stale expectation: its freshly created file and rows are removed again.
        DocumentImportResult stale = run(item(A3, PointerPolicy.moveFrom(A1.documentVersion())));
        assertEquals(DocumentImportFailure.CURRENT_VERSION_CONFLICT, failed(stale, 0).failure());
        assertEquals(A2.documentVersion(), failed(stale, 0).currentVersion());
        assertEquals(beforeConflict, registry.state());
        assertFalse(Files.exists(textFile(A3)));
        assertTrue(registry.state().versions().keySet().stream().noneMatch(key -> key.endsWith(A3.documentVersion())));

        // The state is intact and the same item still imports correctly afterwards.
        DocumentImportResult recovered = run(item(A3, PointerPolicy.keep()));
        assertEquals(Presence.CREATED, imported(recovered, 0).artifactFile());
        assertEquals(A2.documentVersion(), imported(recovered, 0).currentVersion());
    }

    @Test
    void aFileThatExistedBeforeTheItemIsNeverRemovedWhenTheItemRollsBack() throws Exception {
        run(item(A1, PointerPolicy.moveFrom(null)));
        // A crash orphan: the exact bytes of A3 are on disk, but A3 was never registered.
        ownerOnlyFile(textFile(A3), EMOJI_TEXT);

        DocumentImportResult conflict = run(item(A3, PointerPolicy.moveFrom(hex64('z'))));
        assertEquals(DocumentImportFailure.CURRENT_VERSION_CONFLICT, failed(conflict, 0).failure());
        assertEquals(EMOJI_TEXT, Files.readString(textFile(A3), StandardCharsets.UTF_8));
        assertTrue(registry.state().versions().keySet().stream().noneMatch(key -> key.endsWith(A3.documentVersion())));

        // The next import of the same item adopts the orphan after comparing its bytes.
        DocumentImportResult adopted = run(item(A3, PointerPolicy.keep()));
        assertEquals(Presence.EXISTING, imported(adopted, 0).artifactFile());
        assertEquals(Presence.CREATED, imported(adopted, 0).version());
        assertEquals(EMOJI_TEXT, Files.readString(textFile(A3), StandardCharsets.UTF_8));
    }

    @Test
    void aDifferentFileAtTheArtifactNameIsAConflictAndStaysUntouched() throws Exception {
        Files.createDirectory(root.resolve("extracted_text"), PosixFilePermissions.asFileAttribute(
                PosixFilePermissions.fromString("rwx------")));
        ownerOnlyFile(textFile(A1), "tampered");

        DocumentImportResult result = run(item(A1, PointerPolicy.moveFrom(null)));

        assertEquals(DocumentImportFailure.ARTIFACT_FILE_CONFLICT, failed(result, 0).failure());
        assertEquals("tampered", Files.readString(textFile(A1), StandardCharsets.UTF_8));
        assertEquals(0, registry.writeAttempts());
        assertTrue(registry.state().articles().isEmpty());
    }

    @Test
    void privateAndDeletedArticlesAreDeniedAndTheFileTheItemCreatedIsRemoved() throws Exception {
        for (String access : List.of("private", "deleted")) {
            registry = new InMemoryDocumentRegistry();
            service = new TransactionalService(registry);
            importer = new DocumentImporter(exporter, new IngestionExportParser(), store, service);
            registry.seedArticle(A1.documentId(), "news", SOURCE, null, access);
            InMemoryDocumentRegistry.State before = registry.state();

            DocumentImportResult result = run(item(A1, PointerPolicy.moveFrom(null)));

            assertEquals(DocumentImportFailure.ARTICLE_ACCESS_UNAVAILABLE, failed(result, 0).failure(), access);
            assertEquals(before, registry.state());
            assertEquals(access, registry.state().articles().get(A1.documentId()).accessStatus());
            assertFalse(Files.exists(textFile(A1)), access);
        }
    }

    @Test
    void aFilesystemFailureNeverTouchesTheDatabase() throws Exception {
        Files.writeString(root.resolve("extracted_text"), "not a directory");

        DocumentImportResult result = run(item(A1, PointerPolicy.moveFrom(null)));

        assertEquals(DocumentImportFailure.ARTIFACT_STORE_UNAVAILABLE, failed(result, 0).failure());
        assertEquals(0, service.registerCalls);
        assertEquals(0, registry.writeAttempts());
        assertTrue(registry.state().articles().isEmpty());
    }

    /** A fixture the store may adopt or compare: owner-only like everything the store itself creates. */
    private static Path ownerOnlyFile(Path file, String content) throws IOException {
        Files.writeString(file, content, StandardCharsets.UTF_8);
        Files.setPosixFilePermissions(file, PosixFilePermissions.fromString("rw-------"));
        return file;
    }

    @Test
    void anUnknownDatabaseOutcomeKeepsTheFileSoTheNextRunCanAdoptIt() throws Exception {
        service.failWith(new DataAccessResourceFailureException("jdbc:postgresql://127.0.0.1/db password=secret-password"));

        DocumentImportResult result = run(item(A1, PointerPolicy.moveFrom(null)));

        assertEquals(DocumentImportFailure.DATABASE_UNAVAILABLE, failed(result, 0).failure());
        assertTrue(Files.exists(textFile(A1)));
        assertFalse(new String(DocumentImportResultWriter.toBytes(result), StandardCharsets.UTF_8).contains("secret"));

        service.failWith(null);
        DocumentImportResult retry = run(item(A1, PointerPolicy.moveFrom(null)));
        assertTrue(retry.succeeded());
        assertEquals(Presence.EXISTING, imported(retry, 0).artifactFile());
        assertEquals(Presence.CREATED, imported(retry, 0).article());
    }

    @Test
    void anUnexpectedFailureIsReportedWithoutItsMessage() throws Exception {
        service.failWith(new IllegalStateException("bug carrying secret text " + PLAIN_TEXT));

        DocumentImportResult result = run(item(A1, PointerPolicy.moveFrom(null)));

        assertEquals(DocumentImportFailure.INTERNAL_ERROR, failed(result, 0).failure());
        String written = new String(DocumentImportResultWriter.toBytes(result), StandardCharsets.UTF_8);
        assertFalse(written.contains("secret"));
        assertFalse(written.contains(PLAIN_TEXT));
    }

    @Test
    void theRunStopsAtTheFirstFailureAndReportsWhatIsAlreadyCommitted() throws Exception {
        exporter.refuse(B1, "source_unauthorized");

        DocumentImportResult result = run(item(A1, PointerPolicy.moveFrom(null)), item(B1, PointerPolicy.keep()),
                item(A2, PointerPolicy.keep()));

        assertFalse(result.succeeded());
        assertEquals(DocumentImportFailure.INGESTION_EXPORT_FAILED, result.firstFailure());
        assertInstanceOf(ItemResult.Imported.class, result.items().get(0));
        assertEquals("source_unauthorized", failed(result, 1).ingestionCode());
        assertEquals(new ItemResult.NotAttempted(2), result.items().get(2));
        assertEquals(List.of(A1, B1), exporter.calls);
        assertEquals(1, registry.state().articles().size());
        assertTrue(Files.exists(textFile(A1)));
        assertFalse(Files.exists(textFile(A2)));

        JsonNode written = json(result);
        assertEquals("failed", written.get("status").stringValue());
        assertEquals("imported", written.get("items").get(0).get("status").stringValue());
        assertEquals("failed", written.get("items").get(1).get("status").stringValue());
        assertEquals("ingestion_export_failed", written.get("items").get(1).get("failure").get("code").stringValue());
        assertEquals("source_unauthorized", written.get("items").get(1).get("failure").get("ingestionCode").stringValue());
        assertEquals("not_attempted", written.get("items").get(2).get("status").stringValue());
    }

    @Test
    void aRevokedGrantBlocksEveryWriteEvenForAnAlreadyRegisteredVersion() throws Exception {
        run(item(A1, PointerPolicy.moveFrom(null)), item(A2, PointerPolicy.keep()));
        InMemoryDocumentRegistry.State before = registry.state();
        Path a3 = textFile(A3);
        exporter.refuse(A1, "source_unauthorized");
        exporter.refuse(A2, "source_unauthorized");
        exporter.refuse(A3, "source_unauthorized");

        for (ImportItem item : List.of(item(A1, PointerPolicy.keep()), item(A1, PointerPolicy.moveFrom(null)),
                item(A2, PointerPolicy.moveFrom(A1.documentVersion())), item(A3, PointerPolicy.keep()))) {
            DocumentImportResult result = run(item);
            assertEquals(DocumentImportFailure.INGESTION_EXPORT_FAILED, failed(result, 0).failure());
            assertEquals("source_unauthorized", failed(result, 0).ingestionCode());
        }

        assertEquals(before, registry.state());
        assertFalse(Files.exists(a3));
        assertEquals(A1.documentVersion(), registry.state().articles().get(A1.documentId()).currentVersion());
    }

    @Test
    void aGrantWithReadAndQuoteDisplayButWithoutStoreImportsNothingBecauseTheExportAlwaysRequiresStore() throws Exception {
        Path exportFile = Files.write(temp.toRealPath().resolve("export-a1.json"),
                ExportFixtures.bytes(ExportFixtures.export(A1, PLAIN_TEXT, PLAIN_HASH)));
        // Stand-in for the pipeline when the current grant allows read and quote-display only: an export that requires
        // `store` is refused, one that does not is served. The importer must therefore always pass --require-store.
        String withoutStore = """
                #!/bin/sh
                cat > /dev/null
                case " $* " in
                  *" --require-store "*)
                    printf '%s' '{"schemaVersion":"zoop-ingestion-s2-1","error":{"code":"source_unauthorized"}}'
                    exit 2;;
                esac
                cat 'EXPORT_FILE'
                """.replace("EXPORT_FILE", exportFile.toString());
        DocumentImporter real = realImporter(withoutStore, "without-store");

        DocumentImportResult result = real.run(new ImportRequest(List.of(item(A1, PointerPolicy.moveFrom(null)))));

        assertEquals(DocumentImportFailure.INGESTION_EXPORT_FAILED, failed(result, 0).failure());
        assertEquals("source_unauthorized", failed(result, 0).ingestionCode());
        assertFalse(Files.exists(root.resolve("extracted_text")));
        assertEquals(0, service.registerCalls);
        assertEquals(0, registry.writeAttempts());
        assertTrue(registry.state().articles().isEmpty());

        // Control: the same stand-in for a grant that does allow store serves the export, so the refusal above is the
        // flag's doing and not an artefact of the stand-in.
        String withStore = "#!/bin/sh\ncat > /dev/null\ncat '" + exportFile + "'\n";
        DocumentImportResult allowed = realImporter(withStore, "with-store")
                .run(new ImportRequest(List.of(item(A1, PointerPolicy.moveFrom(null)))));
        assertTrue(allowed.succeeded());
        assertTrue(Files.exists(textFile(A1)));
    }

    private DocumentImporter realImporter(String script, String name) throws IOException {
        Path cli = Files.writeString(temp.toRealPath().resolve("fake-ingest-" + name), script);
        Files.setPosixFilePermissions(cli, PosixFilePermissions.fromString("rwx------"));
        ProcessIngestionExporter process = new ProcessIngestionExporter(cli, temp.toRealPath().resolve("state"),
                temp.toRealPath().resolve("sources.json"), Duration.ofSeconds(30), ProcessIngestionExporter.MAX_STDOUT_BYTES,
                Map.of(), temp.toRealPath().toString());
        return new DocumentImporter(process, new IngestionExportParser(), store, service);
    }

    @Test
    void anExportThatIsNotTheRequestedObservationWritesNothing() throws Exception {
        // The CLI answers for version 2 when version 1 was asked for.
        exporter.responses.put(A1, ExportFixtures.bytes(ExportFixtures.export(A2, MIXED_TEXT, MIXED_HASH)));

        DocumentImportResult result = run(item(A1, PointerPolicy.moveFrom(null)));

        assertEquals(DocumentImportFailure.EXPORT_INVALID, failed(result, 0).failure());
        assertEquals(0, registry.writeAttempts());
        assertFalse(Files.exists(root.resolve("extracted_text")));
    }

    @Test
    void aTamperedExportIsRefusedBeforeAnyFileOrRow() throws Exception {
        ObjectNode tampered = ExportFixtures.export(A1, PLAIN_TEXT, PLAIN_HASH);
        ExportFixtures.documentOf(tampered).put("text", PLAIN_TEXT + " tampered");
        exporter.responses.put(A1, ExportFixtures.bytes(tampered));

        DocumentImportResult result = run(item(A1, PointerPolicy.moveFrom(null)));

        assertEquals(DocumentImportFailure.TEXT_HASH_MISMATCH, failed(result, 0).failure());
        assertEquals(0, registry.writeAttempts());
        assertFalse(Files.exists(root.resolve("extracted_text")));
    }

    @Test
    void aBusyStoreFailsTheWholeRequestBeforeAnyExport() throws Exception {
        try (ArtifactFileStore.Session other = store.open()) {
            DocumentImportResult result = run(item(A1, PointerPolicy.moveFrom(null)), item(A2, PointerPolicy.keep()));

            assertFalse(result.succeeded());
            assertEquals(DocumentImportFailure.IMPORT_BUSY, result.requestFailure());
            assertEquals(List.of(new ItemResult.NotAttempted(0), new ItemResult.NotAttempted(1)), result.items());
            assertTrue(exporter.calls.isEmpty());
            assertEquals(0, registry.writeAttempts());
            assertEquals("import_busy", json(result).get("failure").get("code").stringValue());
        }
    }

    @Test
    void theResultDocumentHasTheDocumentedShapeAndNeitherTextNorPaths() throws Exception {
        DocumentImportResult result = run(item(A1, PointerPolicy.moveFrom(null)), item(A2, PointerPolicy.keep()));

        JsonNode written = json(result);
        assertEquals(Set.of("schemaVersion", "status", "items"), Set.copyOf(written.propertyNames()));
        assertEquals("zoop-document-import-1", written.get("schemaVersion").stringValue());
        assertEquals("succeeded", written.get("status").stringValue());
        JsonNode first = written.get("items").get(0);
        assertEquals(Set.of("index", "status", "documentId", "documentVersion", "textArtifactId", "article", "artifact",
                "artifactFile", "version", "currentVersion", "collectedAt", "grant"), Set.copyOf(first.propertyNames()));
        assertEquals(0, first.get("index").intValue());
        assertEquals("imported", first.get("status").stringValue());
        assertEquals("created", first.get("article").stringValue());
        assertEquals("created", first.get("artifactFile").stringValue());
        assertEquals("moved", first.get("currentVersion").get("result").stringValue());
        assertEquals(A1.documentVersion(), first.get("currentVersion").get("value").stringValue());
        assertEquals("2026-10-14T01:02:03.456789Z", first.get("collectedAt").stringValue());
        assertEquals("operator-grant", first.get("grant").get("grantId").stringValue());
        assertEquals("unchanged", written.get("items").get(1).get("currentVersion").get("result").stringValue());

        String raw = new String(DocumentImportResultWriter.toBytes(result), StandardCharsets.UTF_8);
        assertFalse(raw.contains(PLAIN_TEXT));
        assertFalse(raw.contains(root.toString()));
        assertFalse(raw.contains(temp.toString()));
        assertFalse(raw.contains("artifact-root"));
    }

    @Test
    void anUnsetPointerIsAJsonNullNotAnAbsentValue() throws Exception {
        DocumentImportResult result = run(item(A1, PointerPolicy.keep()));

        JsonNode pointer = json(result).get("items").get(0).get("currentVersion");
        assertEquals("unchanged", pointer.get("result").stringValue());
        assertTrue(pointer.has("value"));
        assertTrue(pointer.get("value").isNull());

        DocumentImportResult conflict = run(item(A2, PointerPolicy.moveFrom(hex64('q'))));
        JsonNode failure = json(conflict).get("items").get(0).get("failure");
        assertEquals("current_version_conflict", failure.get("code").stringValue());
        assertTrue(failure.has("currentVersion"));
        assertTrue(failure.get("currentVersion").isNull());
    }

    private void serveCollected(Observation observation, String precision, String raw, String kind) {
        ObjectNode export = ExportFixtures.collected(ExportFixtures.export(observation, PLAIN_TEXT, PLAIN_HASH), kind, precision, raw);
        ExportFixtures.observationOf(export).put("observedAt", LATER_OBSERVED);
        exporter.responses.put(observation, ExportFixtures.bytes(export));
    }

    @Test
    void aCollectedDayIsRegisteredAsADayAndTheFetchTimeIsTheCollectionTime() {
        Observation collected = obs("r5", SOURCE, 0, 0, 'c', '5');
        serveCollected(collected, "day", "2026-10-14", "news");

        DocumentImportResult result = run(item(collected, PointerPolicy.keep()));

        assertTrue(result.succeeded());
        ItemResult.Imported item = imported(result, 0);
        Instant fetched = Instant.parse("2026-10-13T23:59:58.123456Z");
        assertEquals(fetched, item.collectedAt());
        assertEquals("day", item.publicationPrecision());
        var version = registry.state().versions().values().iterator().next();
        assertNull(version.publishedAt());
        assertEquals(LocalDate.of(2026, 10, 14), version.publishedDate());
        assertEquals("day", version.publicationPrecision());
        assertEquals(fetched, version.collectedAt());

        JsonNode written = json(result).get("items").get(0);
        assertEquals(Set.of("index", "status", "documentId", "documentVersion", "textArtifactId", "article", "artifact",
                "artifactFile", "version", "currentVersion", "collectedAt", "grant", "publicationPrecision", "collection"),
                Set.copyOf(written.propertyNames()));
        assertEquals("day", written.get("publicationPrecision").stringValue());
        JsonNode collection = written.get("collection");
        assertEquals("collected_http", collection.get("provenance").stringValue());
        assertEquals("synthetic_loopback", collection.get("network").stringValue());
        assertEquals("news", collection.get("documentKind").stringValue());
        assertEquals("2026-10-13T23:59:58.123456Z", collection.get("fetchedAt").stringValue());
        assertEquals(200, collection.get("httpStatus").intValue());
        assertEquals("day", collection.get("declaredPublication").get("precision").stringValue());
        assertEquals("2026-10-14", collection.get("declaredPublication").get("raw").stringValue());
        assertEquals(hex64('9'), collection.get("bodySha256").stringValue());
    }

    @Test
    void anOffsetLessDeclaredTimeIsStoredAsUnknownButItsDeclaredFormIsReported() {
        Observation collected = obs("r5", SOURCE, 0, 0, 'c', '5');
        serveCollected(collected, "unresolved", "2026-10-14T09:30:00", "news");

        DocumentImportResult result = run(item(collected, PointerPolicy.keep()));

        var version = registry.state().versions().values().iterator().next();
        assertNull(version.publishedAt());
        assertNull(version.publishedDate());
        assertEquals("unknown", version.publicationPrecision());
        JsonNode declared = json(result).get("items").get(0).get("collection").get("declaredPublication");
        assertEquals("unresolved", declared.get("precision").stringValue());
        assertEquals("2026-10-14T09:30:00", declared.get("raw").stringValue());
    }

    @Test
    void aKindThatDiffersFromTheOneDeclaredWhenCollectingIsRefusedAndRegistersNothing() {
        Observation collected = obs("r5", SOURCE, 0, 0, 'c', '5');
        serveCollected(collected, "day", "2026-10-14", "disclosure");

        DocumentImportResult result = run(item(collected, PointerPolicy.keep()));

        assertEquals(DocumentImportFailure.ARTICLE_KIND_CONFLICT, failed(result, 0).failure());
        assertTrue(registry.state().versions().isEmpty());
        assertFalse(Files.exists(textFile(collected)));
    }

    @Test
    void anAuthoredImportKeepsItsResultKeysAndItsReceiptTime() {
        DocumentImportResult result = run(item(A1, PointerPolicy.keep()));

        assertNull(imported(result, 0).collected());
        assertFalse(json(result).get("items").get(0).has("collection"));
        assertFalse(json(result).get("items").get(0).has("publicationPrecision"));
        assertEquals(Instant.parse("2026-10-14T01:02:03.456789Z"), imported(result, 0).collectedAt());
    }

    /** Stand-in for {@code zoop-ai-ingest export}: serves a prepared document, refuses, or fails. */
    static final class FakeExporter implements IngestionExporter {
        final Map<Observation, Object> responses = new HashMap<>();
        final List<Observation> calls = new ArrayList<>();

        void serve(Observation observation, String text, String hash, String observedAt) {
            ObjectNode export = ExportFixtures.export(observation, text, hash);
            ExportFixtures.observationOf(export).put("observedAt", observedAt);
            responses.put(observation, ExportFixtures.bytes(export));
        }

        void refuse(Observation observation, String code) {
            responses.put(observation, code);
        }

        @Override
        public byte[] export(Observation observation) {
            calls.add(observation);
            Object response = responses.get(observation);
            if (response instanceof byte[] bytes) {
                return bytes;
            }
            if (response instanceof String code) {
                throw DocumentImportException.ingestionRefused(code);
            }
            throw new DocumentImportException(DocumentImportFailure.INGESTION_EXPORT_UNAVAILABLE);
        }
    }

    /** The real service with the transaction boundary reproduced and an optional injected failure. */
    static final class TransactionalService extends DocumentRegistrationService {
        private final InMemoryDocumentRegistry registry;
        private RuntimeException failure;
        int registerCalls;

        TransactionalService(InMemoryDocumentRegistry registry) {
            super(registry, Clock.fixed(Instant.parse("2026-10-14T05:00:00Z"), ZoneOffset.UTC));
            this.registry = registry;
        }

        void failWith(RuntimeException failure) {
            this.failure = failure;
        }

        @Override
        public RegistrationOutcome register(RegistrationCommand command) {
            registerCalls++;
            if (failure != null) {
                throw failure;
            }
            return registry.transactionally(() -> super.register(command));
        }
    }
}
