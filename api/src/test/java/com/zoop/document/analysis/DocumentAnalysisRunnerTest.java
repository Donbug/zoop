package com.zoop.document.analysis;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.PosixFilePermissions;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.node.ObjectNode;

import static com.zoop.document.analysis.AnalysisWorld.JSON;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * The operator entry point end to end except the database and the S2-1 CLI: the result file is reserved exclusively before any
 * work, holds only identifiers and states, and a failed run ends with an exception so the process exits non-zero.
 */
class DocumentAnalysisRunnerTest extends AnalysisTestSupport {
    private Path request;
    private Path result;
    private DocumentAnalysisRunner runner;

    @BeforeEach
    void settings() throws IOException {
        Path real = temp.toRealPath();
        request = real.resolve("request.json");
        result = real.resolve("result.json");
        Path cli = Files.writeString(real.resolve("zoop-ai-ingest"), "#!/bin/sh\n");
        Files.setPosixFilePermissions(cli, PosixFilePermissions.fromString("rwx------"));
        Files.writeString(request, "{}");
        DocumentAnalysisSettings settings = DocumentAnalysisSettings.of(request.toString(), result.toString(),
                world.grantsFile.toString(), cli.toString(), Files.createDirectory(real.resolve("state")).toString(),
                Files.writeString(real.resolve("sources.json"), "{}").toString(), world.root.toString());
        runner = new DocumentAnalysisRunner(settings, new AnalysisRequestParser(), world.analyzer);
    }

    private void writeRequest(String command, String items) throws IOException {
        Files.writeString(request, "{\"schemaVersion\":\"zoop-document-analysis-1\",\"command\":\"" + command + "\",\"items\":["
                + items + "]}");
    }

    private static String prepareItem() {
        return "{\"observation\":{\"roundId\":\"round-1\",\"sourceId\":\"" + AnalysisWorld.SOURCE + "\",\"page\":0,\"ordinal\":0,"
                + "\"documentId\":\"" + AnalysisWorld.DOCUMENT_ID + "\",\"rawVersion\":\"" + "5".repeat(64)
                + "\",\"documentVersion\":\"" + AnalysisWorld.VERSION + "\"},\"kind\":\"document-summary\",\"companyId\":\""
                + AnalysisWorld.COMPANY_ID + "\",\"grant\":{\"grantId\":\"" + AnalysisWorld.GRANT_ID + "\",\"revision\":\""
                + AnalysisWorld.GRANT_REVISION + "\"},\"mode\":\"replay\",\"sourceKind\":\"synthetic\","
                + "\"latest\":{\"expected\":null}}";
    }

    @Test
    void aSuccessfulRunWritesAnOwnerOnlyResultWithIdentifiersAndStatesOnly() throws IOException {
        world.issue(JOB_HEX, ANALYSIS_HEX);
        writeRequest("prepare", prepareItem());

        runner.run(null);

        assertEquals(PosixFilePermissions.fromString("rw-------"), Files.getPosixFilePermissions(result));
        String text = Files.readString(result, StandardCharsets.UTF_8);
        JsonNode parsed = JSON.readTree(text);
        assertEquals("zoop-document-analysis-1", parsed.get("schemaVersion").stringValue());
        assertEquals("prepare", parsed.get("command").stringValue());
        assertEquals("succeeded", parsed.get("status").stringValue());
        JsonNode item = parsed.get("items").get(0);
        assertEquals("prepared", item.get("status").stringValue());
        assertEquals("da-" + ANALYSIS_HEX, item.get("analysisId").stringValue());
        assertEquals("s1-" + JOB_HEX, item.get("aiJobId").stringValue());
        assertEquals(1, item.get("requestNo").intValue());
        assertEquals("summary", item.get("stage").stringValue());
        assertFalse(text.contains(AnalysisWorld.TEXT), "the result never carries document text");
        assertFalse(text.contains(world.root.toString()), "the result never carries a path");
        assertFalse(text.contains(AnalysisWorld.COMPANY_NAME));
    }

    @Test
    void aFailedItemEndsTheRunWithAnExceptionAfterTheResultIsWritten() throws IOException {
        writeRequest("advance", "{\"analysisId\":\"da-" + "f".repeat(32) + "\"}");

        DocumentAnalysisAbortedException aborted = assertThrows(DocumentAnalysisAbortedException.class, () -> runner.run(null));

        assertEquals(AnalysisFailure.ANALYSIS_UNKNOWN, aborted.failure());
        assertEquals("document analysis failed: analysis_unknown", aborted.getMessage());
        JsonNode parsed = JSON.readTree(Files.readString(result));
        assertEquals("failed", parsed.get("status").stringValue());
        assertEquals("failed", parsed.get("items").get(0).get("status").stringValue());
        assertEquals("analysis_unknown", parsed.get("items").get(0).get("failure").get("code").stringValue());
    }

    @Test
    void anInvalidRequestIsReportedAsTheWholeRequestFailing() throws IOException {
        Files.writeString(request, "{\"schemaVersion\":\"zoop-document-analysis-1\",\"command\":\"prepare\",\"items\":[],\"x\":1}");

        DocumentAnalysisAbortedException aborted = assertThrows(DocumentAnalysisAbortedException.class, () -> runner.run(null));

        assertEquals(AnalysisFailure.REQUEST_INVALID, aborted.failure());
        JsonNode parsed = JSON.readTree(Files.readString(result));
        assertEquals("failed", parsed.get("status").stringValue());
        assertEquals("request_invalid", parsed.get("failure").get("code").stringValue());
        assertEquals(0, parsed.get("items").size());
        assertTrue(parsed.get("command").isNull(), "an unreadable request has no command");
    }

    @Test
    void anExistingResultFileIsNeverOverwrittenAndNothingRuns() throws IOException {
        Files.writeString(result, "earlier");
        writeRequest("prepare", prepareItem());
        world.issue(JOB_HEX, ANALYSIS_HEX);

        DocumentAnalysisAbortedException aborted = assertThrows(DocumentAnalysisAbortedException.class, () -> runner.run(null));

        assertEquals(AnalysisFailure.RESULT_UNAVAILABLE, aborted.failure());
        assertEquals("earlier", Files.readString(result));
        assertTrue(world.analyses.rows().isEmpty(), "no work may start before the result file is reserved");
        assertNotNull(world.hex.peekFirst(), "the ids were never drawn");
    }

    @Test
    void pendingOutcomesAreSuccessesAndFailedItemsStopTheBatch() throws IOException {
        String id = prepareAnalysis(AnalysisWorld.SUMMARY);
        ObjectNode scenario = AnalysisWorld.scenario("summary");
        world.serve(AnalysisWorld.queued(statusOf(scenario)), envelopeOf(scenario));
        writeRequest("advance", "{\"analysisId\":\"" + id + "\"},{\"analysisId\":\"da-" + "f".repeat(32) + "\"},{\"analysisId\":\""
                + id + "\"}");

        assertThrows(DocumentAnalysisAbortedException.class, () -> runner.run(null));

        JsonNode items = JSON.readTree(Files.readString(result)).get("items");
        assertEquals("pending", items.get(0).get("status").stringValue());
        assertEquals("wait", items.get(0).get("waiting").stringValue());
        assertEquals("failed", items.get(1).get("status").stringValue());
        assertEquals("not_attempted", items.get(2).get("status").stringValue());
    }
}
