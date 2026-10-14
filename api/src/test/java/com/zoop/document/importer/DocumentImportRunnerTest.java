package com.zoop.document.importer;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.PosixFilePermission;
import java.util.Set;

import com.zoop.artifact.storage.ArtifactFileStore;
import com.zoop.document.DocumentImportFailure;
import com.zoop.document.service.InMemoryDocumentRegistry;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.node.ArrayNode;
import tools.jackson.databind.node.ObjectNode;

import static com.zoop.document.importer.ExportFixtures.PLAIN_HASH;
import static com.zoop.document.importer.ExportFixtures.PLAIN_TEXT;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/** The operator entry point: exclusive result file, redacted output, non-zero exit (an exception) on any failure. */
class DocumentImportRunnerTest {
    private static final Observation OBSERVATION = new Observation("r1", "synthetic-source", 0, 0,
            "doc-" + "a".repeat(64), "b".repeat(64), "c".repeat(64));

    @TempDir
    Path temp;
    private Path base;
    private Path artifacts;
    private DocumentImportSettings settings;
    private DocumentImporterTest.FakeExporter exporter;
    private InMemoryDocumentRegistry registry;
    private DocumentImportRunner runner;

    @BeforeEach
    void setUp() throws IOException {
        base = temp.toRealPath();
        artifacts = Files.createDirectory(base.resolve("artifacts"));
        settings = new DocumentImportSettings(base.resolve("request.json"), base.resolve("result.json"),
                base.resolve("cli"), base.resolve("state"), base.resolve("sources.json"), artifacts);
        exporter = new DocumentImporterTest.FakeExporter();
        exporter.serve(OBSERVATION, PLAIN_TEXT, PLAIN_HASH, ExportFixtures.OBSERVED_AT);
        registry = new InMemoryDocumentRegistry();
        runner = new DocumentImportRunner(settings, new ImportRequestParser(), new DocumentImporter(exporter,
                new IngestionExportParser(), ArtifactFileStore.at(artifacts),
                new DocumentImporterTest.TransactionalService(registry)));
    }

    private static ObjectNode item(String kind) {
        ObjectNode item = ExportFixtures.JSON.createObjectNode();
        item.put("kind", kind);
        ObjectNode observation = item.putObject("observation");
        observation.put("roundId", OBSERVATION.roundId());
        observation.put("sourceId", OBSERVATION.sourceId());
        observation.put("page", OBSERVATION.page());
        observation.put("ordinal", OBSERVATION.ordinal());
        observation.put("documentId", OBSERVATION.documentId());
        observation.put("rawVersion", OBSERVATION.rawVersion());
        observation.put("documentVersion", OBSERVATION.documentVersion());
        item.putObject("currentVersion").putNull("expected");
        return item;
    }

    private void writeRequest(ObjectNode... items) throws IOException {
        ObjectNode root = ExportFixtures.JSON.createObjectNode();
        root.put("schemaVersion", "zoop-document-import-1");
        ArrayNode array = root.putArray("items");
        for (ObjectNode item : items) {
            array.add(item);
        }
        Files.write(settings.request(), ExportFixtures.bytes(root));
    }

    private JsonNode result() throws IOException {
        return ExportFixtures.JSON.readTree(Files.readAllBytes(settings.result()));
    }

    @Test
    void aSuccessfulRunWritesTheResultExclusivelyAndReturns() throws Exception {
        writeRequest(item("news"));

        runner.run(null);

        JsonNode written = result();
        assertEquals("succeeded", written.get("status").stringValue());
        assertEquals("imported", written.get("items").get(0).get("status").stringValue());
        assertEquals(OBSERVATION.documentId(), written.get("items").get(0).get("documentId").stringValue());
        Set<PosixFilePermission> permissions = Files.getPosixFilePermissions(settings.result());
        assertFalse(permissions.stream().anyMatch(p -> p.name().startsWith("GROUP") || p.name().startsWith("OTHERS")));
        assertEquals(1, registry.state().articles().size());
        assertEquals(PLAIN_TEXT, Files.readString(artifacts.resolve("extracted_text")
                .resolve("text-" + OBSERVATION.documentVersion() + ".txt"), StandardCharsets.UTF_8));
    }

    @Test
    void aFailedItemWritesTheResultThenEndsTheRunWithACodeOnlyException() throws Exception {
        exporter.refuse(OBSERVATION, "source_unauthorized");
        writeRequest(item("news"));

        DocumentImportAbortedException aborted = assertThrows(DocumentImportAbortedException.class, () -> runner.run(null));

        assertEquals(DocumentImportFailure.INGESTION_EXPORT_FAILED, aborted.failure());
        assertEquals("document import failed: ingestion_export_failed", aborted.getMessage());
        assertFalse(aborted.getMessage().contains(base.toString()));
        JsonNode written = result();
        assertEquals("failed", written.get("status").stringValue());
        assertEquals("source_unauthorized", written.get("items").get(0).get("failure").get("ingestionCode").stringValue());
        assertTrue(registry.state().articles().isEmpty());
    }

    @Test
    void anExistingResultFileIsNeverOverwrittenAndNoWorkIsDone() throws Exception {
        writeRequest(item("news"));
        Files.writeString(settings.result(), "earlier outcome");

        DocumentImportAbortedException aborted = assertThrows(DocumentImportAbortedException.class, () -> runner.run(null));

        assertEquals(DocumentImportFailure.RESULT_UNAVAILABLE, aborted.failure());
        assertEquals("earlier outcome", Files.readString(settings.result()));
        assertTrue(exporter.calls.isEmpty());
        assertTrue(registry.state().articles().isEmpty());
    }

    @Test
    void aSecondRunWithTheSameResultPathIsRefusedAndTheFirstResultSurvives() throws Exception {
        writeRequest(item("news"));
        runner.run(null);
        byte[] first = Files.readAllBytes(settings.result());

        DocumentImportAbortedException aborted = assertThrows(DocumentImportAbortedException.class, () -> runner.run(null));

        assertEquals(DocumentImportFailure.RESULT_UNAVAILABLE, aborted.failure());
        assertEquals(new String(first, StandardCharsets.UTF_8),
                new String(Files.readAllBytes(settings.result()), StandardCharsets.UTF_8));
    }

    @Test
    void anInvalidRequestIsReportedInTheResultWithoutRunningAnything() throws Exception {
        Files.writeString(settings.request(), "{\"schemaVersion\":\"zoop-document-import-1\",\"items\":[],\"items\":[]}");

        DocumentImportAbortedException aborted = assertThrows(DocumentImportAbortedException.class, () -> runner.run(null));

        assertEquals(DocumentImportFailure.REQUEST_INVALID, aborted.failure());
        JsonNode written = result();
        assertEquals("failed", written.get("status").stringValue());
        assertEquals("request_invalid", written.get("failure").get("code").stringValue());
        assertEquals(0, written.get("items").size());
        assertTrue(exporter.calls.isEmpty());
    }

    @Test
    void aRequestCannotCarryAPreExportedDocumentOrAGrant() throws Exception {
        for (String key : new String[] {"export", "document", "grant", "text"}) {
            ObjectNode item = item("news");
            item.putObject(key).put("text", PLAIN_TEXT);
            writeRequest(item);
            Files.deleteIfExists(settings.result());

            DocumentImportAbortedException aborted = assertThrows(DocumentImportAbortedException.class,
                    () -> runner.run(null), key);

            assertEquals(DocumentImportFailure.REQUEST_INVALID, aborted.failure(), key);
            Files.delete(settings.result());
        }
        assertTrue(exporter.calls.isEmpty());
        assertTrue(registry.state().articles().isEmpty());
    }

    @Test
    void aMissingOrOversizedRequestFileIsInvalid() throws Exception {
        DocumentImportAbortedException missing = assertThrows(DocumentImportAbortedException.class, () -> runner.run(null));
        assertEquals(DocumentImportFailure.REQUEST_INVALID, missing.failure());
        assertEquals("request_invalid", result().get("failure").get("code").stringValue());
        Files.delete(settings.result());

        Files.write(settings.request(), new byte[ImportRequestParser.MAX_BYTES + 1]);
        DocumentImportAbortedException oversized = assertThrows(DocumentImportAbortedException.class,
                () -> runner.run(null));
        assertEquals(DocumentImportFailure.REQUEST_INVALID, oversized.failure());
        assertTrue(exporter.calls.isEmpty());
    }
}
