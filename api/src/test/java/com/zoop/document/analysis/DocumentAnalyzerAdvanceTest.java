package com.zoop.document.analysis;

import java.io.IOException;
import java.io.UncheckedIOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.Set;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.function.Consumer;

import com.zoop.artifact.storage.ArtifactFileStore;
import com.zoop.common.json.Canonical;
import com.zoop.document.analysis.repository.AnalysisRow;
import com.zoop.document.analysis.repository.EvidenceRow;
import com.zoop.document.analysis.repository.ExecutionRow;
import org.junit.jupiter.api.Test;
import org.springframework.dao.DataAccessResourceFailureException;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.node.ArrayNode;
import tools.jackson.databind.node.ObjectNode;

import static com.zoop.document.analysis.AnalysisWorld.DOCUMENT_ID;
import static com.zoop.document.analysis.AnalysisWorld.GRANT_ID;
import static com.zoop.document.analysis.AnalysisWorld.GRANT_REVISION;
import static com.zoop.document.analysis.AnalysisWorld.JSON;
import static com.zoop.document.analysis.AnalysisWorld.SENTIMENT;
import static com.zoop.document.analysis.AnalysisWorld.SOURCE;
import static com.zoop.document.analysis.AnalysisWorld.SUMMARY;
import static com.zoop.document.analysis.AnalysisWorld.TEXT;
import static com.zoop.document.analysis.AnalysisWorld.VERSION;
import static com.zoop.document.analysis.AnalysisWorld.failed;
import static com.zoop.document.analysis.AnalysisWorld.only;
import static com.zoop.document.analysis.AnalysisWorld.scenario;
import static com.zoop.document.analysis.AnalysisWorld.settled;
import static org.junit.jupiter.api.Assertions.assertArrayEquals;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertInstanceOf;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * {@code advance} moves a reserved analysis forward against a loopback AI service answered with what the real worker and the
 * real service wire models produced. Every assertion is about what the operator (and the database) can observe: the requests
 * the service saw, the stored rows, artifacts, files and counted executions.
 */
class DocumentAnalyzerAdvanceTest extends AnalysisTestSupport {
    private static final String JOB = jobOf("01");
    private static final List<String> RECEIPT_ONLY = List.of("ai_call_receipt", "ai_call_receipt", "ai_submit", "extracted_text");

    private static ObjectNode result(ObjectNode artifact) {
        return (ObjectNode) artifact.get("result");
    }

    private static ObjectNode citation(ObjectNode artifact, int index) {
        return (ObjectNode) artifact.get("result").get("citations").get(index);
    }

    private static String evidenceId(String analysisId, String modelId) {
        return "ev-" + sha256("{\"analysisId\":\"" + analysisId + "\",\"evidenceId\":\"" + modelId + "\"}");
    }

    private AnalysisItemResult.Settled settleSummary(String id) {
        serve(scenario("summary"));
        return settled(world.advance(id, false));
    }

    // ---- reaching the service -------------------------------------------------------------------------------------------

    @Test
    void aJobTheServiceDoesNotKnowIsSubmittedOnceFromTheStoredBytes() throws IOException {
        String id = prepareAnalysis(SUMMARY);
        ObjectNode scenario = scenario("summary");
        world.serveUnknown(statusOf(scenario), envelopeOf(scenario));

        AnalysisItemResult first = only(world.advance(id, false));

        assertEquals("wait", assertInstanceOf(AnalysisItemResult.Pending.class, first).waiting());
        assertEquals(1, world.ai.calls("GET", "/" + JOB).size(), "status is always read first");
        List<FakeAiService.Request> posts = world.ai.calls("POST", "/analysis-jobs");
        assertEquals(1, posts.size());
        JsonNode sent = JSON.readTree(posts.get(0).body());
        JsonNode stored = JSON.readTree(read("ai_submit", "submit-" + JOB + ".json"));
        assertEquals(JOB, sent.get("jobId").stringValue(), "never a new job id");
        assertEquals(Canonical.write(stored.get("input")), Canonical.write(sent.get("input")));
        assertEquals(Canonical.write(stored.get("provenance")), Canonical.write(sent.get("provenance")));
        assertEquals("pending", world.row(id).status());

        // The service now knows the job: the next advance reads its status and never submits again.
        world.script.status = AnalysisWorld.queued(statusOf(scenario));
        AnalysisItemResult second = only(world.advance(id, false));

        assertEquals("wait", assertInstanceOf(AnalysisItemResult.Pending.class, second).waiting());
        assertEquals(1, world.ai.calls("POST", "/analysis-jobs").size(), "a known job is never submitted again");
        assertEquals(2, world.ai.calls("GET", "/" + JOB).size());
    }

    @Test
    void aLostSubmitReplyIsAnUnknownOutcomeThatNeverBecomesASecondSubmit() {
        String id = prepareAnalysis(SUMMARY);
        ObjectNode scenario = scenario("summary");
        world.serveUnknown(statusOf(scenario), envelopeOf(scenario));
        world.script.dropSubmitReply = true;

        AnalysisItemResult.Failed unknown = failed(world.advance(id, false));

        assertEquals(AnalysisFailure.SUBMIT_OUTCOME_UNKNOWN, unknown.failure());
        assertEquals("pending", world.row(id).status());
        assertEquals(1, world.ai.calls("POST", "/analysis-jobs").size());

        world.script.dropSubmitReply = false;
        world.script.status = AnalysisWorld.queued(statusOf(scenario));
        AnalysisItemResult again = only(world.advance(id, false));

        assertEquals("wait", assertInstanceOf(AnalysisItemResult.Pending.class, again).waiting());
        assertEquals(1, world.ai.calls("POST", "/analysis-jobs").size(), "the service registered the job: status answers now");
    }

    @Test
    void aSubmitTheServiceRejectsAsInvalidIsAFailedAnalysisWithItsCode() {
        String id = prepareAnalysis(SUMMARY);
        world.ai.respond(request -> request.is("POST", "/analysis-jobs")
                ? FakeAiService.Reply.json(422, FakeAiService.error("invalid_request", false, request))
                : FakeAiService.Reply.json(404, FakeAiService.error("job_not_found", false, request)));

        AnalysisItemResult.Settled failed = settled(world.advance(id, false));

        assertEquals("failed", failed.outcome());
        assertEquals("invalid_request", failed.reason());
        assertEquals("failed", world.row(id).status());
        assertEquals(0, failed.executionsRecorded());
        assertTrue(world.analyses.executions().isEmpty());
    }

    @Test
    void otherRefusalsOfASubmitWriteNothing() {
        String id = prepareAnalysis(SUMMARY);
        world.ai.respond(request -> request.is("POST", "/analysis-jobs")
                ? FakeAiService.Reply.json(409, FakeAiService.error("idempotency_conflict", false, request))
                : FakeAiService.Reply.json(404, FakeAiService.error("job_not_found", false, request)));
        assertEquals(AnalysisFailure.SUBMIT_CONFLICT, failed(world.advance(id, false)).failure());

        world.ai.respond(request -> request.is("POST", "/analysis-jobs")
                ? FakeAiService.Reply.json(403, FakeAiService.error("scope_denied", false, request))
                : FakeAiService.Reply.json(404, FakeAiService.error("job_not_found", false, request)));
        AnalysisItemResult.Failed refused = failed(world.advance(id, false));
        assertEquals(AnalysisFailure.SUBMIT_REFUSED, refused.failure());
        assertEquals("scope_denied", refused.details().get("aiCode"));
        assertEquals("pending", world.row(id).status());
    }

    @Test
    void aServiceThatCannotAnswerStatusIsNotASubmitReason() {
        String id = prepareAnalysis(SUMMARY);
        world.ai.respond(request -> FakeAiService.Reply.json(503, FakeAiService.error("runtime_unavailable", true, request)));

        AnalysisItemResult.Failed unavailable = failed(world.advance(id, false));

        assertEquals(AnalysisFailure.STATUS_UNAVAILABLE, unavailable.failure());
        assertEquals("runtime_unavailable", unavailable.details().get("aiCode"));
        assertTrue(world.ai.calls("POST", "/analysis-jobs").isEmpty(), "only a 404 job_not_found allows a submit");
    }

    @Test
    void theServicesNextActionDecidesAndRecoverNeedsTheOperatorsOptIn() {
        String id = prepareAnalysis(SUMMARY);
        ObjectNode scenario = scenario("summary");
        statusOf(scenario).put("state", "queued").put("phase", "input.persisted").put("next", "recover");
        serve(scenario);

        assertEquals(AnalysisFailure.RECOVER_REQUIRED, failed(world.advance(id, false)).failure());
        assertTrue(world.ai.calls("POST", "/recover").isEmpty());

        AnalysisItemResult recovering = only(world.advance(id, true));
        assertEquals("recovering", assertInstanceOf(AnalysisItemResult.Pending.class, recovering).waiting());
        assertEquals(1, world.ai.calls("POST", "/recover").size());
        assertEquals("pending", world.row(id).status());

        statusOf(scenario).put("state", "reconciling").put("next", "operator_reconcile");
        world.script.status = statusOf(scenario);
        assertEquals(AnalysisFailure.OPERATOR_RECONCILE_REQUIRED, failed(world.advance(id, true)).failure());
    }

    @Test
    void aStatusThatIsAboutAnotherKindOfJobIsRefused() {
        String id = prepareAnalysis(SUMMARY);
        ObjectNode scenario = scenario("summary");
        statusOf(scenario).put("kind", "document-sentiment");
        serve(scenario);

        assertEquals(AnalysisFailure.STATUS_BINDING_INVALID, failed(world.advance(id, false)).failure());
        assertEquals("pending", world.row(id).status());
    }

    @Test
    void receiptsThatAreNotCompleteYetKeepTheAnalysisPendingWithoutReadingTheResult() {
        String id = prepareAnalysis(SUMMARY);
        ObjectNode scenario = scenario("summary");
        statusOf(scenario).put("unreceiptedAttempts", 1);
        serve(scenario);

        AnalysisItemResult pending = only(world.advance(id, false));

        assertEquals("receipts_incomplete", assertInstanceOf(AnalysisItemResult.Pending.class, pending).waiting());
        assertTrue(world.ai.calls("GET", "/result").isEmpty());
        assertEquals("pending", world.row(id).status());
    }

    @Test
    void anUnknownAnalysisAndAHeldStoreAreReportedAndStopTheRun() {
        assertEquals(AnalysisFailure.ANALYSIS_UNKNOWN, failed(world.advance("da-" + "f".repeat(32), false)).failure());

        AnalysisRunResult twice = world.analyzer.run(new AnalysisRequest.Advance(List.of(
                new AnalysisRequest.AdvanceItem("da-" + "f".repeat(32), false),
                new AnalysisRequest.AdvanceItem("da-" + "e".repeat(32), false))));
        assertFalse(twice.succeeded());
        assertInstanceOf(AnalysisItemResult.NotAttempted.class, twice.items().get(1), "a run stops at the first failure");

        try (ArtifactFileStore.Session held = world.store.open()) {
            assertTrue(held != null);
            AnalysisRunResult busy = world.advance("da-" + "f".repeat(32), false);
            assertEquals(AnalysisFailure.ANALYSIS_BUSY, busy.requestFailure());
            assertInstanceOf(AnalysisItemResult.NotAttempted.class, only(busy));
        }
    }

    @Test
    void aSubmitFileThatChangedOnDiskIsNeverSent() throws IOException {
        String id = prepareAnalysis(SUMMARY);
        Files.write(world.file("ai_submit", "submit-" + JOB + ".json"), "{\"tampered\":true}".getBytes(StandardCharsets.UTF_8));
        ObjectNode scenario = scenario("summary");
        world.serveUnknown(statusOf(scenario), envelopeOf(scenario));

        assertEquals(AnalysisFailure.ARTIFACT_FILE_CONFLICT, failed(world.advance(id, false)).failure());
        assertTrue(world.ai.requests.isEmpty(), "bytes that are not the committed artifact are never sent");
    }

    // ---- authority is read again before the app asks the service to do any work ----------------------------------------------
    // A job the service does not know is submitted from the stored bytes, a stuck one is recovered: both make the service (and
    // its worker) spend a model call, so the operator's CURRENT grant copy and the CURRENT article must allow it first. Reading
    // a status is not such a request and is not asserted here.

    private void assertNotSubmitted(Consumer<ObjectNode> revoke, String grantCode) throws IOException {
        String id = prepareAnalysis(SUMMARY);
        ObjectNode scenario = scenario("summary");
        world.serveUnknown(statusOf(scenario), envelopeOf(scenario));
        revoke.accept(world.grant());
        world.saveGrants();

        AnalysisItemResult item = only(world.advance(id, false));

        AnalysisItemResult.Failed refused = assertInstanceOf(AnalysisItemResult.Failed.class, item,
                "a revoked grant must refuse the advance before a job is submitted");
        assertEquals(AnalysisFailure.GRANT_DENIED, refused.failure());
        assertEquals(grantCode, refused.details().get("grantCode"));
        assertTrue(world.ai.calls("POST", "/analysis-jobs").isEmpty(), "no submit without current authority");
        assertEquals("pending", world.row(id).status());
        assertEquals(List.of("ai_submit", "extracted_text"), world.artifactKinds());
        assertTrue(world.analyses.executions().isEmpty());
    }

    private void assertNotRecovered(Consumer<ObjectNode> revoke, String grantCode) throws IOException {
        String id = prepareAnalysis(SUMMARY);
        ObjectNode scenario = scenario("summary");
        statusOf(scenario).put("state", "queued").put("phase", "input.persisted").put("next", "recover");
        serve(scenario);
        revoke.accept(world.grant());
        world.saveGrants();

        AnalysisItemResult item = only(world.advance(id, true));

        AnalysisItemResult.Failed refused = assertInstanceOf(AnalysisItemResult.Failed.class, item,
                "a revoked grant must refuse the advance before a job is recovered");
        assertEquals(AnalysisFailure.GRANT_DENIED, refused.failure());
        assertEquals(grantCode, refused.details().get("grantCode"));
        assertTrue(world.ai.calls("POST", "/recover").isEmpty(), "no recover without current authority");
        assertEquals("pending", world.row(id).status());
        assertEquals(List.of("ai_submit", "extracted_text"), world.artifactKinds());
    }

    @Test
    void aGrantThatNoLongerAllowsModelSendIsNeverSubmitted() throws IOException {
        assertNotSubmitted(grant -> grant.putArray("allowedOperations").add("read").add("store").add("quote-display"),
                "source_operation_denied");
    }

    @Test
    void aDisabledGrantIsNeverSubmitted() throws IOException {
        assertNotSubmitted(grant -> grant.put("enabled", false), "source_rights_unknown_or_denied");
    }

    @Test
    void aGrantThatExpiredSincePrepareIsNeverSubmitted() throws IOException {
        assertNotSubmitted(grant -> {
            grant.put("expiresAt", "2026-10-14T05:30:00Z");
            world.clock.set(Instant.parse("2026-10-14T06:00:00Z"));
        }, "source_grant_expired");
    }

    @Test
    void anArticleThatBecamePrivateIsNeverSubmitted() {
        String id = prepareAnalysis(SUMMARY);
        ObjectNode scenario = scenario("summary");
        world.serveUnknown(statusOf(scenario), envelopeOf(scenario));
        world.registry.setAccessStatus(DOCUMENT_ID, "private");

        AnalysisItemResult item = only(world.advance(id, false));

        AnalysisItemResult.Failed refused = assertInstanceOf(AnalysisItemResult.Failed.class, item,
                "a private article must refuse the advance before a job is submitted");
        assertEquals(AnalysisFailure.ARTICLE_ACCESS_UNAVAILABLE, refused.failure());
        assertTrue(world.ai.calls("POST", "/analysis-jobs").isEmpty(), "no submit for an article that is no longer available");
        assertEquals("pending", world.row(id).status());
    }

    @Test
    void aGrantThatNoLongerAllowsModelSendIsNeverRecovered() throws IOException {
        assertNotRecovered(grant -> grant.putArray("allowedOperations").add("read").add("store").add("quote-display"),
                "source_operation_denied");
    }

    @Test
    void aGrantThatExpiredSincePrepareIsNeverRecovered() throws IOException {
        assertNotRecovered(grant -> {
            grant.put("expiresAt", "2026-10-14T05:30:00Z");
            world.clock.set(Instant.parse("2026-10-14T06:00:00Z"));
        }, "source_grant_expired");
    }

    @Test
    void anArticleThatBecamePrivateIsNeverRecovered() {
        String id = prepareAnalysis(SUMMARY);
        ObjectNode scenario = scenario("summary");
        statusOf(scenario).put("state", "queued").put("phase", "input.persisted").put("next", "recover");
        serve(scenario);
        world.registry.setAccessStatus(DOCUMENT_ID, "private");

        AnalysisItemResult item = only(world.advance(id, true));

        AnalysisItemResult.Failed refused = assertInstanceOf(AnalysisItemResult.Failed.class, item,
                "a private article must refuse the advance before a job is recovered");
        assertEquals(AnalysisFailure.ARTICLE_ACCESS_UNAVAILABLE, refused.failure());
        assertTrue(world.ai.calls("POST", "/recover").isEmpty(), "no recover for an article that is no longer available");
        assertEquals("pending", world.row(id).status());
    }

    // ---- settling a result ----------------------------------------------------------------------------------------------

    @Test
    void anAvailableSummaryIsStoredWithItsEvidenceReceiptsAndExecutions() throws IOException {
        String id = prepareAnalysis(SUMMARY);
        ObjectNode fixture = scenario("summary");

        AnalysisItemResult.Settled done = settleSummary(id);

        assertEquals("available", done.outcome());
        assertNull(done.reason());
        assertEquals(2, done.executionsRecorded());
        assertEquals(0, done.executionsExisting());
        assertEquals(2, done.evidence());
        assertTrue(world.ai.calls("POST", "/analysis-jobs").isEmpty(), "the service already knew the job");
        assertEquals(1, world.ai.calls("GET", "/result").size());

        ObjectNode main = artifact(fixture, "document-summary");
        ObjectNode verifier = artifact(fixture, "semantic-verification");
        AnalysisRow row = world.row(id);
        assertEquals("available", row.status());
        assertNull(row.reason());
        assertEquals(main.get("resultVersion").stringValue(), row.resultVersion());
        assertEquals(main.get("artifactId").stringValue(), row.resultArtifactId());
        assertEquals(verifier.get("artifactId").stringValue(), row.semanticReceiptId());
        assertEquals("exact-" + id, row.exactReceiptId());
        assertEquals(OffsetDateTime.parse(main.get("producedAt").stringValue()).toInstant(), row.producedAt());
        assertEquals("authored-synthetic-document-summary", row.model());
        assertEquals(main.get("promptVersion").stringValue(), row.promptVersion());
        assertNull(row.reasoningEffort());

        // The public result: model evidence ids are rewritten to the app's own, nothing else of the answer is changed.
        JsonNode dto = JSON.readTree(world.analyses.resultJson(id));
        assertEquals("zoop-ai-s1-1", dto.get("schemaVersion").stringValue());
        assertEquals(main.get("artifactId").stringValue(), dto.get("artifactId").stringValue());
        assertEquals(DOCUMENT_ID, dto.get("documentId").stringValue());
        assertEquals(VERSION, dto.get("documentVersion").stringValue());
        assertEquals(row.resultVersion(), dto.get("resultVersion").stringValue());
        assertEquals(result(main).get("text").stringValue(), dto.get("text").stringValue());
        assertEquals(result(main).get("limitations"), dto.get("limitations"));
        assertEquals(main.get("provenance"), dto.get("provenance"));
        assertEquals(evidenceId(id, "e1"), dto.get("claims").get(0).get("evidenceIds").get(0).stringValue());
        assertEquals(evidenceId(id, "e2"), dto.get("citations").get(1).get("evidenceId").stringValue());
        assertEquals(0, dto.get("claims").get(2).get("evidenceIds").size(), "a limitation has no citation");

        // Evidence quotes are code point slices of the stored text (the text starts with an emoji, so UTF-16 would differ).
        List<EvidenceRow> evidence = world.analyses.evidenceRows();
        assertEquals(2, evidence.size());
        for (EvidenceRow quote : evidence) {
            assertEquals(slice(TEXT, (int) quote.startOffset(), (int) quote.endOffset()), quote.quote());
            assertEquals("exact-" + id, quote.verificationArtifactId());
            assertEquals("text-" + VERSION, quote.textArtifactId());
            assertEquals(DOCUMENT_ID, quote.articleId());
            assertEquals(List.of("raw-1"), quote.rawLocatorIds());
        }
        assertEquals(Set.of(evidenceId(id, "e1"), evidenceId(id, "e2")),
                Set.of(evidence.get(0).id(), evidence.get(1).id()));

        assertEquals(List.of("ai_call_receipt", "ai_call_receipt", "ai_submit", "analysis_result", "exact_receipt",
                "extracted_text", "semantic_receipt"), world.artifactKinds());
        assertEquals(Canonical.write(main), new String(read("analysis_result", main.get("artifactId").stringValue() + ".json"),
                StandardCharsets.UTF_8));
        assertEquals(Canonical.write(verifier), new String(read("semantic_receipt",
                verifier.get("artifactId").stringValue() + ".json"), StandardCharsets.UTF_8));
        JsonNode exact = JSON.readTree(read("exact_receipt", "exact-" + id + ".json"));
        assertEquals("zoop-exact-receipt-1", exact.get("schemaVersion").stringValue());
        assertEquals(sha256(TEXT), exact.get("textSha256").stringValue());
        assertEquals(row.resultVersion(), exact.get("resultVersion").stringValue());

        List<ExecutionRow> executions = world.analyses.executions();
        assertEquals(2, executions.size());
        assertEquals(Set.of("document-summary", "semantic-verification"),
                Set.of(executions.get(0).stage(), executions.get(1).stage()));
        for (ExecutionRow execution : executions) {
            assertEquals(JOB, execution.aiJobId());
            assertEquals(id, execution.documentAnalysisId());
            assertEquals("news-analysis", execution.feature());
            assertEquals("replay", execution.executionMode());
            assertEquals("succeeded", execution.status());
            assertEquals(GRANT_ID, execution.grantId());
            assertEquals(GRANT_REVISION, execution.grantRevision());
            assertTrue(execution.receiptArtifactId().startsWith("rcpt-"));
            JsonNode scope = JSON.readTree(execution.grantScope());
            assertEquals(SOURCE, scope.get("sourceId").stringValue());
            assertEquals(JSON.readTree("[\"read\",\"store\",\"model-send\",\"quote-display\"]"), scope.get("requiredOperations"));
            assertEquals(JSON.readTree("[\"document-summary\",\"semantic-verification\"]"), scope.get("requiredPurposes"));
            assertEquals(JSON.readTree("[\"authored-replay\"]"), scope.get("requiredRecipients"));
            assertNull(execution.inputTokens(), "tokens the provider did not report stay NULL");
        }
    }

    @Test
    void advancingASettledAnalysisCallsAndChangesNothing() {
        String id = prepareAnalysis(SUMMARY);
        settleSummary(id);
        AnalysisRow before = world.row(id);
        int requests = world.ai.requests.size();
        int executions = world.analyses.executions().size();

        AnalysisItemResult again = only(world.advance(id, false));

        AnalysisItemResult.AlreadySettled settled = assertInstanceOf(AnalysisItemResult.AlreadySettled.class, again);
        assertEquals("available", settled.outcome());
        assertEquals(requests, world.ai.requests.size());
        assertEquals(executions, world.analyses.executions().size());
        assertEquals(before, world.row(id), "a terminal row is immutable");
    }

    @Test
    void aSentimentKeepsItsCompanyAndStoresNoEvidence() throws IOException {
        String id = prepareAnalysis(SENTIMENT, "03", null);
        ObjectNode fixture = scenario("sentiment");
        serve(fixture);

        AnalysisItemResult.Settled done = settled(world.advance(id, false));

        assertEquals("available", done.outcome());
        assertEquals(0, done.evidence());
        assertTrue(world.analyses.evidenceRows().isEmpty());
        ObjectNode main = artifact(fixture, "document-sentiment");
        AnalysisRow row = world.row(id);
        assertEquals(AnalysisWorld.COMPANY_ID, row.companyId());
        assertEquals(main.get("resultVersion").stringValue(), row.resultVersion());
        JsonNode dto = JSON.readTree(world.analyses.resultJson(id));
        assertEquals("mixed", dto.get("label").stringValue());
        assertEquals(AnalysisWorld.COMPANY_ID, dto.get("companyId").stringValue());
        assertEquals(result(main).get("rationale").stringValue(), dto.get("rationale").stringValue());
        assertEquals(2, dto.get("quotes").size());
        assertEquals(citation(main, 0).get("quote").stringValue(), dto.get("quotes").get(0).stringValue());
        assertEquals("authored-synthetic-document-sentiment", dto.get("model").stringValue());
        assertEquals(main.get("promptVersion").stringValue(), dto.get("promptVersion").stringValue());
        // The literal ERD attribution: the sentiment stage is document-sentiment, its independent verification news-analysis.
        Set<String> features = Set.of(world.analyses.executions().get(0).feature(), world.analyses.executions().get(1).feature());
        assertEquals(Set.of("document-sentiment", "news-analysis"), features);
    }

    @Test
    void aSummaryTheVerifierHoldsOrRejectsIsWithheldWithoutAnyContent() throws IOException {
        String previous = null;
        for (String[] variant : new String[][] {{"summaryHold", "04", "semantic_hold"}, {"summaryReject", "05", "semantic_reject"}}) {
            String id = prepareAnalysis(SUMMARY, variant[1], previous);
            previous = id;
            serve(scenario(variant[0]));

            AnalysisItemResult.Settled done = settled(world.advance(id, false));

            assertEquals("withheld", done.outcome(), variant[0]);
            assertEquals(variant[2], done.reason(), variant[0]);
            assertEquals(2, done.executionsRecorded(), "receipts are usage history even when the content is withheld");
            AnalysisRow row = world.row(id);
            assertEquals("withheld", row.status());
            assertNull(row.resultVersion());
            assertNull(world.analyses.resultJson(id));
            assertEquals("authored-synthetic-document-summary", row.model(), "the generation receipt's model is still known");
        }
        assertEquals(List.of(), world.files("analysis_result"));
        assertEquals(List.of(), world.files("semantic_receipt"));
        assertEquals(List.of(), world.files("exact_receipt"));
        assertTrue(world.analyses.evidenceRows().isEmpty());
    }

    @Test
    void aResultTheServiceWithheldIsWithheldWithTheServicesCodeAndItsReceiptsAreKept() throws IOException {
        String id = prepareAnalysis(SUMMARY);
        ObjectNode fixture = scenario("summary");
        ObjectNode delivery = (ObjectNode) envelopeOf(fixture).get("delivery");
        delivery.put("state", "withheld").put("reason", "source_operation_denied");
        envelopeOf(fixture).putNull("job");
        serve(fixture);

        AnalysisItemResult.Settled done = settled(world.advance(id, false));

        assertEquals("withheld", done.outcome());
        assertEquals("source_operation_denied", done.reason());
        assertEquals(2, done.executionsRecorded());
        assertEquals(RECEIPT_ONLY, world.artifactKinds());
        assertEquals(List.of(), world.files("analysis_result"));
    }

    private void assertWithheldByRegistry(Consumer<ObjectNode> revoke, String reason) throws IOException {
        String id = prepareAnalysis(SUMMARY);
        serve(scenario("summary"));
        revoke.accept(world.grant());
        world.saveGrants();

        AnalysisItemResult.Settled done = settled(world.advance(id, false));

        assertEquals("withheld", done.outcome());
        assertEquals(reason, done.reason());
        assertEquals(reason, world.row(id).reason());
        assertNull(world.row(id).resultVersion());
        assertNull(world.analyses.resultJson(id));
        assertEquals(RECEIPT_ONLY, world.artifactKinds());
        assertEquals(2, world.analyses.executions().size());
        assertEquals(List.of(), world.files("analysis_result"));
        assertTrue(world.analyses.evidenceRows().isEmpty());
    }

    @Test
    void aGrantRevokedAfterTheAiJobFinishedWithholdsItsResult() throws IOException {
        assertWithheldByRegistry(grant -> grant.putArray("allowedOperations").add("read").add("store").add("model-send"),
                "source_operation_denied");
    }

    @Test
    void aDisabledGrantWithholdsItsResult() throws IOException {
        assertWithheldByRegistry(grant -> grant.put("enabled", false), "source_rights_unknown_or_denied");
    }

    @Test
    void aChangedGrantRevisionWithholdsItsResult() throws IOException {
        assertWithheldByRegistry(grant -> grant.put("revision", "rev-2"), "grant_revision_or_source_changed");
    }

    @Test
    void aRecipientThatIsNoLongerGrantedWithholdsItsResult() throws IOException {
        assertWithheldByRegistry(grant -> grant.putArray("recipients"), "source_purpose_or_recipient_denied");
    }

    @Test
    void aGrantThatExpiredWhileTheJobRanWithholdsItsResult() throws IOException {
        assertWithheldByRegistry(grant -> {
            grant.put("expiresAt", "2026-10-14T05:30:00Z");
            world.clock.set(Instant.parse("2026-10-14T06:00:00Z"));
        }, "source_grant_expired");
    }

    @Test
    void anArticleThatBecamePrivateWithholdsItsResult() throws IOException {
        String id = prepareAnalysis(SUMMARY);
        serve(scenario("summary"));
        world.registry.setAccessStatus(DOCUMENT_ID, "private");

        AnalysisItemResult.Settled done = settled(world.advance(id, false));

        assertEquals("withheld", done.outcome());
        assertEquals("article_access_unavailable", done.reason());
        assertEquals(RECEIPT_ONLY, world.artifactKinds());
    }

    @Test
    void aFailedJobIsAFailedAnalysisWithTheServicesCodeAndItsCountedAttempt() {
        String id = prepareAnalysis(SUMMARY, "06", null);
        serve(scenario("summaryFailed"));

        AnalysisItemResult.Settled done = settled(world.advance(id, false));

        assertEquals("failed", done.outcome());
        assertEquals("provider_http_500", done.reason());
        AnalysisRow row = world.row(id);
        assertEquals("failed", row.status());
        assertEquals("provider_http_500", row.reason());
        assertEquals("authored-synthetic-document-summary", row.model());
        assertEquals(1, world.analyses.executions().size());
        ExecutionRow attempt = world.analyses.executions().get(0);
        assertEquals("failed", attempt.status());
        assertEquals("provider_http_500", attempt.errorCode());
        assertEquals("document-summary", attempt.stage());
        assertEquals(List.of("ai_call_receipt", "ai_submit", "extracted_text"), world.artifactKinds());
    }

    // ---- results that cannot be attributed (nothing is written, the analysis stays pending) -----------------------------

    private AnalysisItemResult.Failed assertRefused(Consumer<ObjectNode> tamper, AnalysisFailure failure, String detail)
            throws IOException {
        String id = prepareAnalysis(SUMMARY);
        ObjectNode fixture = scenario("summary");
        tamper.accept(fixture);
        serve(fixture);

        AnalysisItemResult.Failed refused = failed(world.advance(id, false));

        assertEquals(failure, refused.failure());
        if (detail != null) {
            assertEquals(detail, refused.details().get("detail"));
        }
        assertEquals("pending", world.row(id).status(), "an unattributable result must leave the analysis pending");
        assertEquals(List.of("ai_submit", "extracted_text"), world.artifactKinds());
        assertTrue(world.analyses.executions().isEmpty());
        assertTrue(world.analyses.evidenceRows().isEmpty());
        assertEquals(List.of(), world.files("ai_call_receipt"));
        assertEquals(List.of(), world.files("analysis_result"));
        return refused;
    }

    @Test
    void aResultComputedFromAnotherInputIsRefused() throws IOException {
        assertRefused(fixture -> ((ObjectNode) job(fixture).get("input").get("input").get("company")).put("name", "다른 회사"),
                AnalysisFailure.RESULT_BINDING_INVALID, "input_changed");
    }

    @Test
    void receiptsThatDisagreeWithThePayloadAreRefused() throws IOException {
        assertRefused(fixture -> ((ObjectNode) envelopeOf(fixture).get("receipts").get(0).get("config")).put("model", "other"),
                AnalysisFailure.RECEIPTS_INVALID, "calls");
    }

    @Test
    void artifactsOfAnotherJobThatIsNotACacheHitAreRefused() throws IOException {
        assertRefused(fixture -> job(fixture).get("artifacts").values()
                .forEach(artifact -> ((ObjectNode) artifact).put("jobId", jobOf("0f"))),
                AnalysisFailure.RESULT_BINDING_INVALID, "artifact_job");
    }

    @Test
    void aPayloadOutsideTheContractIsRefused() throws IOException {
        assertRefused(fixture -> artifact(fixture, "document-summary").put("unexpected", true),
                AnalysisFailure.RESULT_PAYLOAD_INVALID, "shape");
    }

    @Test
    void aStoredTextFileThatChangedIsNeverTrusted() throws IOException {
        String id = prepareAnalysis(SUMMARY);
        serve(scenario("summary"));
        Files.write(world.file("extracted_text", "text-" + VERSION + ".txt"), "changed".getBytes(StandardCharsets.UTF_8));

        assertEquals(AnalysisFailure.ARTIFACT_FILE_CONFLICT, failed(world.advance(id, false)).failure());
        assertEquals("pending", world.row(id).status());
    }

    // ---- content gates: attributable but not usable (withheld with the gate's own code) ---------------------------------

    private void assertContentWithheld(Consumer<ObjectNode> tamper, String reason) throws IOException {
        String id = prepareAnalysis(SUMMARY);
        ObjectNode fixture = scenario("summary");
        tamper.accept(fixture);
        serve(fixture);

        AnalysisItemResult.Settled done = settled(world.advance(id, false));

        assertEquals("withheld", done.outcome());
        assertEquals(reason, done.reason());
        assertNull(world.row(id).resultVersion());
        assertNull(world.analyses.resultJson(id));
        assertEquals(RECEIPT_ONLY, world.artifactKinds(), "no content artifact is stored for a withheld result");
        assertTrue(world.analyses.evidenceRows().isEmpty());
        assertEquals(2, world.analyses.executions().size());
    }

    @Test
    void anOutdatedPolicyIsWithheld() throws IOException {
        assertContentWithheld(fixture -> {
            artifact(fixture, "document-summary").put("policyVersion", "zoop-document-gate-1");
            artifact(fixture, "semantic-verification").put("policyVersion", "zoop-document-gate-1");
        }, "document_policy_outdated");
    }

    @Test
    void aForgedResultVersionIsWithheld() throws IOException {
        assertContentWithheld(fixture -> artifact(fixture, "document-summary").put("resultVersion", "result-" + "0".repeat(64)),
                "artifact_digest_mismatch");
    }

    @Test
    void aForgedModelConfigurationRevisionIsWithheld() throws IOException {
        assertContentWithheld(fixture -> artifact(fixture, "document-summary").put("modelConfigRevision", "0".repeat(64)),
                "artifact_digest_mismatch");
    }

    @Test
    void aVerifierThatIsMissingWithholdsTheResult() throws IOException {
        assertContentWithheld(fixture -> {
            String verifierId = artifact(fixture, "semantic-verification").get("artifactId").stringValue();
            ArrayNode artifacts = (ArrayNode) job(fixture).get("artifacts");
            for (int index = artifacts.size() - 1; index >= 0; index--) {
                if (verifierId.equals(artifacts.get(index).get("artifactId").stringValue())) {
                    artifacts.remove(index);
                }
            }
            for (ObjectNode holder : List.of(job(fixture), statusOf(fixture), (ObjectNode) envelopeOf(fixture).get("status"))) {
                ArrayNode ids = (ArrayNode) holder.get("artifactIds");
                for (int index = ids.size() - 1; index >= 0; index--) {
                    if (verifierId.equals(ids.get(index).stringValue())) {
                        ids.remove(index);
                    }
                }
            }
        }, "artifact_set_invalid");
    }

    @Test
    void citationOffsetsAreCodePointsNotUtf16Units() throws IOException {
        // The text starts with an emoji (two UTF-16 units, one code point). A model that counted UTF-16 units points one
        // position too far for everything after it, which the code point check must not accept.
        assertContentWithheld(fixture -> {
            ObjectNode main = artifact(fixture, "document-summary");
            ObjectNode second = citation(main, 1);
            second.put("start", second.get("start").intValue() + 1);
            second.put("end", second.get("end").intValue() + 1);
            retag(main);
        }, "quote_mismatch");
    }

    @Test
    void aQuoteThatIsNotTheCitedTextIsWithheld() throws IOException {
        assertContentWithheld(fixture -> {
            ObjectNode main = artifact(fixture, "document-summary");
            citation(main, 0).put("quote", "다른 인용");
            retag(main);
        }, "quote_mismatch");
    }

    @Test
    void aCitedLocatorThatDoesNotExistIsWithheld() throws IOException {
        assertContentWithheld(fixture -> {
            ObjectNode main = artifact(fixture, "document-summary");
            citation(main, 0).putArray("rawLocatorIds").add("raw-unknown");
            retag(main);
        }, "raw_locator_mismatch");
    }

    @Test
    void aClaimWithoutACitationIsWithheld() throws IOException {
        assertContentWithheld(fixture -> {
            ObjectNode main = artifact(fixture, "document-summary");
            ((ObjectNode) main.get("claims").get(0)).putArray("evidenceIds");
            ((ObjectNode) result(main).get("claims").get(0)).putArray("evidenceIds");
            retag(main);
            // The verifier is shown the same citation-less claim (its claims are not part of any digest), so the claims still
            // agree and the gate that must refuse this answer is the missing citation, not the claim comparison.
            ((ObjectNode) artifact(fixture, "semantic-verification").get("claims").get(0)).putArray("evidenceIds");
        }, "claim_citation_missing");
    }

    @Test
    void limitationsThatAreNotTheLimitationClaimsAreWithheld() throws IOException {
        assertContentWithheld(fixture -> {
            ObjectNode main = artifact(fixture, "document-summary");
            result(main).putArray("limitations");
            retag(main);
        }, "limitation_claim_coverage_invalid");
    }

    @Test
    void textThatIsNotMadeOfTheClaimsIsWithheld() throws IOException {
        assertContentWithheld(fixture -> {
            ObjectNode main = artifact(fixture, "document-summary");
            result(main).put("text", "다른 요약");
            retag(main);
        }, "unattributed_text");
    }

    // ---- the verifier must have verified exactly the claims the answer makes ---------------------------------------------------
    // An answer whose claims were edited and re-hashed (claims, text and result version all consistent) still carries the
    // verifier's verdict about the OLD claims. Every claim of the verifier artifact must equal the answer's claim: same id,
    // text, assertion kind and evidence ids.

    @Test
    void aClaimTextTheVerifierNeverSawIsWithheldEvenWhenTheAnswerIsRehashed() throws IOException {
        assertContentWithheld(fixture -> {
            ObjectNode main = artifact(fixture, "document-summary");
            String changed = "합성 알파의 이익이 급증했다.";
            String first = result(main).get("claims").get(0).get("text").stringValue();
            ((ObjectNode) main.get("claims").get(1)).put("text", changed);
            ((ObjectNode) result(main).get("claims").get(1)).put("text", changed);
            result(main).put("text", first + "\n" + changed);
            retag(main);
        }, "semantic_claim_coverage_invalid");
    }

    @Test
    void aClaimWhoseEvidenceTheVerifierNeverSawIsWithheld() throws IOException {
        assertContentWithheld(fixture -> {
            ObjectNode main = artifact(fixture, "document-summary");
            ((ObjectNode) main.get("claims").get(0)).putArray("evidenceIds").add("e2");
            ((ObjectNode) result(main).get("claims").get(0)).putArray("evidenceIds").add("e2");
            retag(main);
        }, "semantic_claim_coverage_invalid");
    }

    @Test
    void aClaimWhoseAssertionKindTheVerifierNeverSawIsWithheld() throws IOException {
        assertContentWithheld(fixture -> {
            ObjectNode main = artifact(fixture, "document-summary");
            ((ObjectNode) main.get("claims").get(1)).put("assertionKind", "interpretation");
            ((ObjectNode) result(main).get("claims").get(1)).put("assertionKind", "interpretation");
            retag(main);
        }, "semantic_claim_coverage_invalid");
    }

    @Test
    void aSentimentWhoseClaimTheVerifierNeverSawIsWithheldToo() throws IOException {
        String id = prepareAnalysis(SENTIMENT, "03", null);
        ObjectNode fixture = scenario("sentiment");
        ObjectNode main = artifact(fixture, "document-sentiment");
        String changed = "합성 알파의 이익이 급증했다.";
        String first = result(main).get("claims").get(0).get("text").stringValue();
        ((ObjectNode) main.get("claims").get(1)).put("text", changed);
        ((ObjectNode) result(main).get("claims").get(1)).put("text", changed);
        result(main).put("rationale", first + "\n" + changed);
        retag(main);
        serve(fixture);

        AnalysisItemResult item = only(world.advance(id, false));

        AnalysisItemResult.Settled done = assertInstanceOf(AnalysisItemResult.Settled.class, item);
        assertEquals("withheld", done.outcome());
        assertEquals("semantic_claim_coverage_invalid", done.reason());
        assertNull(world.row(id).resultVersion());
        assertNull(world.analyses.resultJson(id));
        assertTrue(world.analyses.evidenceRows().isEmpty());
    }

    // ---- cache reuse, usage counted once, and rollbacks ---------------------------------------------------------------

    @Test
    void aCacheServedResultIsAttributedToTheJobThatCreatedItAndItsAttemptsAreNotCountedTwice() throws IOException {
        String first = prepareAnalysis(SUMMARY);
        serve(scenario("summary"));
        // The first request is withheld by the app's own current-grant check: terminal, with its two attempts counted.
        world.grant().putArray("allowedOperations").add("read").add("store").add("model-send");
        world.saveGrants();
        assertEquals("source_operation_denied", settled(world.advance(first, false)).reason());
        assertEquals(2, world.analyses.executions().size());

        // Rights restored at the same revision: an explicit re-request is the same question, so the worker serves it from cache.
        world.grantsDocument = AnalysisWorld.defaultGrants();
        world.saveGrants();
        String second = prepareAnalysis(SUMMARY, "02", first);
        ObjectNode cache = (ObjectNode) scenario("summary").get("cache");
        world.serve(statusOf(cache), envelopeOf(cache));

        AnalysisItemResult.Settled done = settled(world.advance(second, false));

        assertEquals("available", done.outcome());
        assertEquals(0, done.executionsRecorded(), "the attempts belong to the job that made them");
        assertEquals(2, done.executionsExisting());
        assertEquals(2, world.analyses.executions().size());
        for (ExecutionRow execution : world.analyses.executions()) {
            assertEquals(jobOf("01"), execution.aiJobId());
            assertEquals(first, execution.documentAnalysisId());
        }
        AnalysisRow row = world.row(second);
        assertEquals("available", row.status());
        assertEquals(artifact(scenario("summary"), "document-summary").get("resultVersion").stringValue(), row.resultVersion());
        assertEquals(artifact(scenario("summary"), "document-summary").get("artifactId").stringValue(), row.resultArtifactId());
        assertEquals("withheld", world.row(first).status(), "a terminal row is never rewritten");
        assertEquals(List.of("ai_call_receipt", "ai_call_receipt", "ai_submit", "ai_submit", "analysis_result", "exact_receipt",
                "extracted_text", "semantic_receipt"), world.artifactKinds());
        assertEquals(2, world.analyses.evidenceRows().size());
    }

    @Test
    void aCacheServedResultOfAnUnknownCreatorIsRefused() throws IOException {
        String id = prepareAnalysis(SUMMARY, "02", null);
        ObjectNode cache = (ObjectNode) scenario("summary").get("cache");
        world.serve(statusOf(cache), envelopeOf(cache));

        AnalysisItemResult.Failed refused = failed(world.advance(id, false));

        assertEquals(AnalysisFailure.ARTIFACT_CREATOR_UNKNOWN, refused.failure());
        assertEquals("pending", world.row(id).status());
        assertTrue(world.analyses.executions().isEmpty());
    }

    @Test
    void aLostConnectionWhileSettlingKeepsTheFilesAndTheRerunCountsEverythingOnce() throws IOException {
        String id = prepareAnalysis(SUMMARY);
        serve(scenario("summary"));
        world.analyses.failNextEvidenceInsert(new DataAccessResourceFailureException("connection lost"));

        AnalysisItemResult.Failed lost = failed(world.advance(id, false));

        assertEquals(AnalysisFailure.DATABASE_UNAVAILABLE, lost.failure());
        assertEquals("pending", world.row(id).status(), "the transaction rolled back as a whole");
        assertTrue(world.analyses.executions().isEmpty());
        assertEquals(1, world.files("analysis_result").size(), "the outcome of a commit is unknown: the file is kept");
        assertEquals(2, world.files("ai_call_receipt").size());

        AnalysisItemResult.Settled done = settled(world.advance(id, false));

        assertEquals("available", done.outcome());
        assertEquals(2, done.executionsRecorded());
        assertEquals(2, world.analyses.executions().size());
        assertEquals(2, world.analyses.evidenceRows().size());
        assertEquals(1, world.files("analysis_result").size(), "the same file was adopted, not duplicated");
        assertEquals(2, world.files("ai_call_receipt").size());
    }

    @Test
    void aSettlementThatIsRefusedRemovesTheFilesItCreated() throws IOException {
        String id = prepareAnalysis(SUMMARY);
        ObjectNode fixture = scenario("summary");
        serve(fixture);
        // An attempt of this job is already counted differently: the settlement must refuse instead of counting it again.
        JsonNode attempt = envelopeOf(fixture).get("receipts").get(0);
        world.analyses.insertExecution(new ExecutionRow("aix-other", "news-analysis", "replay", "succeeded", id, JOB,
                attempt.get("attemptId").stringValue(), attempt.get("stage").stringValue(), "rcpt-other", GRANT_ID,
                GRANT_REVISION, "{\"sourceId\":\"" + SOURCE + "\",\"requiredOperations\":[],\"requiredPurposes\":[],"
                        + "\"requiredRecipients\":[]}", "authored-replay", "another-model", "p", null, null, null, null,
                Instant.parse("2026-10-14T00:00:00Z"), null));

        AnalysisItemResult.Failed refused = failed(world.advance(id, false));

        assertEquals(AnalysisFailure.EXECUTION_CONFLICT, refused.failure());
        assertEquals("pending", world.row(id).status());
        for (String directory : List.of("analysis_result", "semantic_receipt", "exact_receipt", "ai_call_receipt")) {
            assertEquals(List.of(), world.files(directory), directory + " files of a refused settlement must be removed");
        }
        assertEquals(List.of("ai_submit", "extracted_text"), world.artifactKinds());
        assertEquals(1, world.analyses.executions().size());
    }

    // ---- a grant that changes while the settlement waits for the row lock ------------------------------------------------------
    // The grant was checked before the files were written and the row lock was requested; the commit must not rely on that
    // earlier read. The registry file and the database cannot change atomically together, so a revocation in the last instant
    // between the re-check and the commit stays a documented window; a revocation DURING the wait must not be committed.

    private void assertWithheldWhenTheGrantChangesWhileWaitingForTheRowLock(Consumer<ObjectNode> change, String reason)
            throws IOException {
        String id = prepareAnalysis(SUMMARY);
        serve(scenario("summary"));
        AtomicInteger requestsAtTheLock = new AtomicInteger(-1);
        world.analyses.afterNextRowLock(() -> {
            requestsAtTheLock.set(world.ai.requests.size());
            change.accept(world.grant());
            try {
                world.saveGrants();
            } catch (IOException failure) {
                throw new UncheckedIOException(failure);
            }
        });

        AnalysisItemResult item = only(world.advance(id, false));

        assertTrue(requestsAtTheLock.get() >= 0, "the settlement locked the analysis row");
        AnalysisItemResult.Settled done = assertInstanceOf(AnalysisItemResult.Settled.class, item,
                "a grant changed while waiting for the row lock must not be settled as available");
        assertEquals("withheld", done.outcome());
        assertEquals(reason, done.reason());
        assertEquals(reason, world.row(id).reason());
        assertNull(world.row(id).resultVersion());
        assertNull(world.analyses.resultJson(id));
        assertEquals(RECEIPT_ONLY, world.artifactKinds(), "no content artifact is registered");
        for (String directory : List.of("analysis_result", "semantic_receipt", "exact_receipt")) {
            assertEquals(List.of(), world.files(directory), directory + " files this attempt wrote for the refused content must go");
        }
        assertEquals(2, world.analyses.executions().size(), "the attempts still count");
        assertTrue(world.analyses.evidenceRows().isEmpty());
        assertEquals(requestsAtTheLock.get(), world.ai.requests.size(), "no AI request between the row lock and the commit");
    }

    @Test
    void aGrantRevokedWhileWaitingForTheRowLockIsNotCommittedAsAvailable() throws IOException {
        assertWithheldWhenTheGrantChangesWhileWaitingForTheRowLock(
                grant -> grant.putArray("allowedOperations").add("read").add("store").add("model-send"),
                "source_operation_denied");
    }

    @Test
    void aGrantDisabledWhileWaitingForTheRowLockIsNotCommittedAsAvailable() throws IOException {
        assertWithheldWhenTheGrantChangesWhileWaitingForTheRowLock(grant -> grant.put("enabled", false),
                "source_rights_unknown_or_denied");
    }

    @Test
    void aGrantThatExpiresWhileWaitingForTheRowLockIsNotCommittedAsAvailable() throws IOException {
        assertWithheldWhenTheGrantChangesWhileWaitingForTheRowLock(grant -> {
            grant.put("expiresAt", "2026-10-14T05:30:00Z");
            world.clock.set(Instant.parse("2026-10-14T06:00:00Z"));
        }, "source_grant_expired");
    }

    // ---- a file conflict after some files were already stored --------------------------------------------------------------------
    // The files are stored one by one before the database transaction exists. A conflict on a later one must remove every file
    // THIS attempt created (nothing refers to them), but never a file that was already there: adopted files belong to an earlier
    // attempt whose commit outcome may be unknown, and the conflicting file is somebody else's.

    private static final byte[] PLANTED = "{\"planted\":true}".getBytes(StandardCharsets.UTF_8);

    private void plant(String directory, String name) {
        try (ArtifactFileStore.Session session = world.store.open()) {
            session.put(directory, name, PLANTED);
        }
    }

    @Test
    void aLateFileConflictRemovesEveryFileThisAttemptCreatedAndLeavesThePlantedOne() throws IOException {
        String id = prepareAnalysis(SUMMARY);
        ObjectNode fixture = scenario("summary");
        serve(fixture);
        String verifier = artifact(fixture, "semantic-verification").get("artifactId").stringValue();
        plant("semantic_receipt", verifier + ".json");

        AnalysisItemResult item = only(world.advance(id, false));

        AnalysisItemResult.Failed refused = assertInstanceOf(AnalysisItemResult.Failed.class, item);
        assertEquals(AnalysisFailure.ARTIFACT_FILE_CONFLICT, refused.failure());
        assertEquals("pending", world.row(id).status());
        assertArrayEquals(PLANTED, Files.readAllBytes(world.file("semantic_receipt", verifier + ".json")));
        for (String directory : List.of("ai_call_receipt", "analysis_result", "exact_receipt")) {
            assertEquals(List.of(), world.files(directory), directory + " files this attempt created must not leak");
        }
        assertEquals(List.of("ai_submit", "extracted_text"), world.artifactKinds());
        assertTrue(world.analyses.executions().isEmpty());
    }

    @Test
    void aLateFileConflictKeepsAdoptedFilesAndRemovesOnlyTheOnesItCreated() throws IOException {
        String id = prepareAnalysis(SUMMARY);
        ObjectNode fixture = scenario("summary");
        serve(fixture);
        String main = artifact(fixture, "document-summary").get("artifactId").stringValue();
        String verifier = artifact(fixture, "semantic-verification").get("artifactId").stringValue();
        // First attempt: every file is stored, then the commit outcome is unknown, so all of them stay.
        world.analyses.failNextEvidenceInsert(new DataAccessResourceFailureException("connection lost"));
        assertEquals(AnalysisFailure.DATABASE_UNAVAILABLE, failed(world.advance(id, false)).failure());
        // Afterwards the answer's file is gone and the verifier's file was replaced by a different object.
        Files.delete(world.file("analysis_result", main + ".json"));
        Files.delete(world.file("semantic_receipt", verifier + ".json"));
        plant("semantic_receipt", verifier + ".json");

        AnalysisItemResult item = only(world.advance(id, false));

        AnalysisItemResult.Failed refused = assertInstanceOf(AnalysisItemResult.Failed.class, item);
        assertEquals(AnalysisFailure.ARTIFACT_FILE_CONFLICT, refused.failure());
        assertEquals("pending", world.row(id).status());
        assertEquals(2, world.files("ai_call_receipt").size(), "the receipt files were adopted, not created by this attempt");
        assertEquals(1, world.files("exact_receipt").size(), "never reached; still the first attempt's file");
        assertArrayEquals(PLANTED, Files.readAllBytes(world.file("semantic_receipt", verifier + ".json")));
        assertFalse(Files.exists(world.file("analysis_result", main + ".json")),
                "the answer file this attempt created must be removed when a later file conflicts");
        assertEquals(List.of("ai_submit", "extracted_text"), world.artifactKinds());
        assertTrue(world.analyses.executions().isEmpty());
    }
}
