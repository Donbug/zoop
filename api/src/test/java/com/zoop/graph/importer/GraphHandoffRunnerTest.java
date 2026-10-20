package com.zoop.graph.importer;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.PosixFilePermission;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.Set;

import com.zoop.artifact.storage.ArtifactFileStore;
import com.zoop.document.importer.IngestionExportParser;
import com.zoop.document.service.InMemoryDocumentRegistry;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.transaction.support.TransactionOperations;
import tools.jackson.databind.JsonNode;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/** The operator entry point: exclusive result file, redacted output, non-zero exit (an exception) on any failure. */
class GraphHandoffRunnerTest {
    @TempDir
    Path temp;
    private Path base;
    private Path artifacts;
    private GraphHandoffImportSettings settings;
    private HandoffFixtures.Built built;
    private HandoffFixtures.FakeHandoff handoff;
    private HandoffFixtures.FakeIngestion ingestion;
    private InMemoryGraphHandoffRepository graph;
    private GraphHandoffRunner runner;

    @BeforeEach
    void setUp() throws IOException {
        base = temp.toRealPath();
        artifacts = Files.createDirectory(base.resolve("artifacts"));
        settings = new GraphHandoffImportSettings(base.resolve("request.json"), base.resolve("result.json"),
                base.resolve("zoop-ai-handoff"), base.resolve("handoff"), base.resolve("relation"), base.resolve("extraction"),
                base.resolve("zoop-ai-ingest"), base.resolve("ingestion"), base.resolve("sources.json"),
                base.resolve("canonical.json"), base.resolve("decisions.json"), base.resolve("bindings.json"), artifacts);
        ArtifactFileStore store = ArtifactFileStore.at(artifacts);
        InMemoryDocumentRegistry registry = new InMemoryDocumentRegistry();
        graph = new InMemoryGraphHandoffRepository("fixture-active", 2);
        graph.seedCompany(HandoffFixtures.COMPANY_A, "합성기업");
        graph.seedCompany(HandoffFixtures.COMPANY_B, "합성부품");
        HandoffFixtures.seedApp(store, registry, HandoffFixtures.TEXT);
        built = HandoffFixtures.build();
        handoff = new HandoffFixtures.FakeHandoff(built.envelopeBytes());
        ingestion = new HandoffFixtures.FakeIngestion();
        runner = new GraphHandoffRunner(settings, new GraphHandoffRequestParser(), new GraphHandoffImporter(handoff, ingestion,
                new IngestionExportParser(), store, registry, graph, TransactionOperations.withoutTransaction(),
                Clock.fixed(Instant.parse("2026-10-17T00:00:00Z"), ZoneOffset.UTC)));
    }

    private void writeRequest(GraphHandoffRequest request) throws IOException {
        String json = "{\"schemaVersion\":\"zoop-graph-handoff-import-1\",\"handoffId\":\"" + request.handoffId()
                + "\",\"expectedManifestDigest\":\"" + request.expectedManifestDigest() + "\",\"expectedBundleDigest\":\""
                + request.expectedBundleDigest() + "\",\"operator\":\"" + request.operator() + "\"}";
        Files.writeString(settings.request(), json);
    }

    private JsonNode result() throws IOException {
        return HandoffFixtures.parse(Files.readAllBytes(settings.result()));
    }

    @Test
    void aSuccessfulRunWritesTheRedactedResultExclusivelyAndReturns() throws Exception {
        writeRequest(built.request());

        runner.run(null);

        JsonNode written = result();
        assertEquals("succeeded", written.get("status").stringValue());
        assertEquals("staged", written.get("outcome").stringValue());
        assertEquals(built.versionId(), written.get("graphVersionId").stringValue());
        assertEquals("not-published", written.get("publication").stringValue());
        assertEquals("not-activated", written.get("activation").stringValue());
        assertEquals("unsupported", written.get("nextActivation").stringValue());
        assertEquals(built.bundleDigest(), written.get("digests").get("bundle").stringValue());
        Set<PosixFilePermission> permissions = Files.getPosixFilePermissions(settings.result());
        assertFalse(permissions.stream().anyMatch(p -> p.name().startsWith("GROUP") || p.name().startsWith("OTHERS")));
        String text = Files.readString(settings.result(), StandardCharsets.UTF_8);
        assertFalse(text.contains(base.toString()), "the result must hold no path");
        assertFalse(text.contains(HandoffFixtures.EVENT), "the result must hold no source text");
        assertEquals(1, graph.state().versions().size());
        assertEquals("fixture-active", graph.activeVersionId);
    }

    @Test
    void aFailedImportWritesTheResultThenEndsTheRunWithACodeOnlyException() throws Exception {
        ingestion.refuseAlways("source_unauthorized");
        writeRequest(built.request());

        GraphHandoffAbortedException aborted = assertThrows(GraphHandoffAbortedException.class, () -> runner.run(null));

        assertEquals(GraphHandoffFailure.INGESTION_EXPORT_FAILED, aborted.failure());
        assertEquals("graph handoff import failed: ingestion_export_failed", aborted.getMessage());
        assertFalse(aborted.getMessage().contains(base.toString()));
        JsonNode written = result();
        assertEquals("failed", written.get("status").stringValue());
        assertEquals("ingestion_export_failed", written.get("failure").get("code").stringValue());
        assertEquals("source_unauthorized", written.get("failure").get("ingestionCode").stringValue());
        assertEquals(0, written.get("failure").get("observation").intValue());
        assertTrue(graph.state().versions().isEmpty());
    }

    @Test
    void aWithheldHandoffCarriesItsCodeAsHandoffCode() throws Exception {
        handoff.withholdFrom(1);
        writeRequest(built.request());

        assertThrows(GraphHandoffAbortedException.class, () -> runner.run(null));

        JsonNode failure = result().get("failure");
        assertEquals("handoff_withheld", failure.get("code").stringValue());
        assertEquals("source_unauthorized", failure.get("handoffCode").stringValue());
    }

    @Test
    void anInvalidRequestIsReportedWithoutAnyWork() throws Exception {
        Files.writeString(settings.request(), "{\"schemaVersion\":\"zoop-graph-handoff-import-1\"}");

        GraphHandoffAbortedException aborted = assertThrows(GraphHandoffAbortedException.class, () -> runner.run(null));

        assertEquals(GraphHandoffFailure.REQUEST_INVALID, aborted.failure());
        assertEquals("request_invalid", result().get("failure").get("code").stringValue());
        assertEquals(0, handoff.calls.get());
    }

    @Test
    void anExistingResultFileIsNeverOverwrittenAndNoWorkIsDone() throws Exception {
        writeRequest(built.request());
        Files.writeString(settings.result(), "earlier outcome");

        GraphHandoffAbortedException aborted = assertThrows(GraphHandoffAbortedException.class, () -> runner.run(null));

        assertEquals(GraphHandoffFailure.RESULT_UNAVAILABLE, aborted.failure());
        assertEquals("earlier outcome", Files.readString(settings.result()));
        assertEquals(0, handoff.calls.get());
        assertTrue(graph.state().versions().isEmpty());
    }

    @Test
    void aMissingRequestFileIsARequestFailure() {
        GraphHandoffAbortedException aborted = assertThrows(GraphHandoffAbortedException.class, () -> runner.run(null));

        assertEquals(GraphHandoffFailure.REQUEST_INVALID, aborted.failure());
        assertTrue(Files.exists(settings.result()));
    }
}
