package com.zoop.document.analysis;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.attribute.PosixFilePermissions;
import java.util.List;
import java.util.function.Consumer;

import com.zoop.common.json.Canonical;
import com.zoop.common.json.Text;
import com.zoop.document.DocumentImportException;
import com.zoop.document.analysis.repository.AnalysisRow;
import com.zoop.document.repository.ArtifactRow;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.node.ObjectNode;

import static com.zoop.document.analysis.AnalysisWorld.COMPANY_ID;
import static com.zoop.document.analysis.AnalysisWorld.COMPANY_NAME;
import static com.zoop.document.analysis.AnalysisWorld.DOCUMENT_ID;
import static com.zoop.document.analysis.AnalysisWorld.GRANT_ID;
import static com.zoop.document.analysis.AnalysisWorld.GRANT_REVISION;
import static com.zoop.document.analysis.AnalysisWorld.JSON;
import static com.zoop.document.analysis.AnalysisWorld.NOW;
import static com.zoop.document.analysis.AnalysisWorld.SENTIMENT;
import static com.zoop.document.analysis.AnalysisWorld.SUMMARY;
import static com.zoop.document.analysis.AnalysisWorld.TEXT;
import static com.zoop.document.analysis.AnalysisWorld.failed;
import static com.zoop.document.analysis.AnalysisWorld.prepared;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * {@code prepare} reserves an analysis: a fresh export, the registered document, the company and the operator's current grant
 * are checked, the immutable {@code ai_submit} file and one pending row with its newly issued AI job id are committed, and the
 * AI service is never called. Every refusal leaves no row, no artifact and no file behind.
 */
class DocumentAnalyzerPrepareTest extends AnalysisTestSupport {

    private void assertNothingWritten() throws IOException {
        assertTrue(world.analyses.rows().isEmpty(), "a refused prepare left a row");
        assertEquals(List.of("extracted_text"), world.artifactKinds().stream().distinct().toList(), "an artifact row was left");
        assertEquals(List.of(), world.files("ai_submit"), "a submit file was left");
        assertTrue(world.ai.requests.isEmpty(), "prepare must never call the AI service");
    }

    @Test
    void reservesAPendingSummaryWithoutCallingTheAiService() throws IOException {
        world.issue(JOB_HEX, ANALYSIS_HEX);

        AnalysisRunResult run = world.prepare(SUMMARY, null);

        assertTrue(run.succeeded());
        AnalysisItemResult.Prepared prepared = prepared(run);
        assertEquals("da-" + ANALYSIS_HEX, prepared.analysisId());
        assertEquals("s1-" + JOB_HEX, prepared.aiJobId());
        assertEquals(1, prepared.requestNo());
        assertEquals("summary", prepared.stage());
        assertTrue(world.ai.requests.isEmpty(), "prepare must never call the AI service");

        AnalysisRow row = world.row(prepared.analysisId());
        assertEquals("pending", row.status());
        assertNull(row.companyId(), "a summary has no company of its own");
        assertEquals(DOCUMENT_ID, row.articleId());
        assertEquals(GRANT_ID, row.grantReference());
        assertEquals(GRANT_REVISION, row.grantRevision());
        assertEquals(NOW, row.grantCheckedAt(), "the grant snapshot is the check that was just made");
        assertNull(row.resultVersion());
        assertNull(row.reason());

        // The immutable request: exactly the submit the real worker accepted for this document, company and grant.
        String name = "submit-" + prepared.aiJobId() + ".json";
        byte[] stored = read("ai_submit", name);
        assertEquals(Canonical.write(AnalysisWorld.scenario("summary").get("submit")), new String(stored, StandardCharsets.UTF_8));
        ArtifactRow artifact = world.artifact("submit-" + prepared.aiJobId()).orElseThrow();
        assertEquals("ai_submit", artifact.kind());
        assertEquals("application/json", artifact.mediaType());
        assertEquals("artifact-root:ai_submit/" + name, artifact.storageUri());
        assertEquals(sha256(stored), artifact.sha256());
        assertEquals(stored.length, artifact.bytes());
        assertEquals(PosixFilePermissions.fromString("rw-------"), Files.getPosixFilePermissions(world.file("ai_submit", name)));
        JsonNode company = JSON.readTree(stored).get("input").get("company");
        assertEquals(COMPANY_NAME, company.get("name").stringValue(), "the company name is frozen from the catalog");
    }

    @Test
    void aSentimentIsScopedToItsCompanyAndASummaryIsNot() {
        world.issue(JOB_HEX, ANALYSIS_HEX);
        AnalysisItemResult.Prepared summary = prepared(world.prepare(SUMMARY, null));
        world.issue("02".repeat(16), "a2".repeat(16));
        AnalysisItemResult.Prepared sentiment = prepared(world.prepare(SENTIMENT, null));

        assertNull(world.row(summary.analysisId()).companyId());
        assertEquals(COMPANY_ID, world.row(sentiment.analysisId()).companyId());
        assertEquals("sentiment", sentiment.stage());
        assertEquals(1, sentiment.requestNo(), "each stage counts its own requests");
    }

    @Test
    void aPendingScopeIsNotReservedAgainAndTheLossIsReported() throws IOException {
        world.issue(JOB_HEX, ANALYSIS_HEX);
        String first = prepared(world.prepare(SUMMARY, null)).analysisId();
        List<String> before = world.files("ai_submit");

        world.issue("02".repeat(16), "a2".repeat(16));
        AnalysisItemResult.Failed stale = failed(world.prepare(SUMMARY, null));
        assertEquals(AnalysisFailure.LATEST_CONFLICT, stale.failure());
        assertEquals(first, stale.details().get("latestAnalysisId"));
        assertEquals("pending", stale.details().get("latestStatus"));

        world.issue("03".repeat(16), "a3".repeat(16));
        AnalysisItemResult.Failed pending = failed(world.prepare(SUMMARY, first));
        assertEquals(AnalysisFailure.ANALYSIS_PENDING, pending.failure());
        assertEquals(first, pending.details().get("latestAnalysisId"));

        assertEquals(1, world.analyses.rows().size());
        assertEquals(before, world.files("ai_submit"), "a refused reservation must remove the submit file it created");
        assertTrue(world.ai.requests.isEmpty());
    }

    @Test
    void anUnknownCompanyIsRefusedBeforeAnythingIsWritten() throws IOException {
        world.issue(JOB_HEX, ANALYSIS_HEX);
        AnalysisRequest.PrepareItem item = new AnalysisRequest.PrepareItem(AnalysisWorld.observation(),
                com.zoop.ai.AnalysisKind.DOCUMENT_SUMMARY, "NO-SUCH-COMPANY", new AnalysisRequest.GrantRef(GRANT_ID, GRANT_REVISION),
                com.zoop.ai.ExecutionMode.REPLAY, "synthetic", null);

        AnalysisRunResult run = world.analyzer.run(new AnalysisRequest.Prepare(List.of(item)));

        assertEquals(AnalysisFailure.COMPANY_UNKNOWN, failed(run).failure());
        assertNothingWritten();
    }

    @Test
    void theOperatorGrantMustCoverTheUseRightNow() throws IOException {
        List<Object[]> cases = List.of(
                new Object[] {"disabled", "source_rights_unknown_or_denied", (Consumer<ObjectNode>) g -> g.put("enabled", false)},
                new Object[] {"rights", "source_rights_unknown_or_denied", (Consumer<ObjectNode>) g -> g.put("rights", "unknown")},
                new Object[] {"evidence", "source_rights_unknown_or_denied",
                        (Consumer<ObjectNode>) g -> g.putArray("evidence")},
                new Object[] {"revision", "grant_revision_or_source_changed", (Consumer<ObjectNode>) g -> g.put("revision", "rev-2")},
                new Object[] {"source", "grant_revision_or_source_changed", (Consumer<ObjectNode>) g -> g.put("sourceId", "other")},
                new Object[] {"expired", "source_grant_expired",
                        (Consumer<ObjectNode>) g -> g.put("expiresAt", "2026-10-14T04:59:59Z")},
                new Object[] {"expiryUnreadable", "source_grant_expiry_invalid",
                        (Consumer<ObjectNode>) g -> g.put("expiresAt", "tomorrow")},
                new Object[] {"quoteDisplay", "source_operation_denied", (Consumer<ObjectNode>) g -> {
                    g.putArray("allowedOperations").add("read").add("store").add("model-send");
                }},
                new Object[] {"modelSend", "source_operation_denied", (Consumer<ObjectNode>) g -> {
                    g.putArray("allowedOperations").add("read").add("store").add("quote-display");
                }},
                new Object[] {"purpose", "source_purpose_or_recipient_denied", (Consumer<ObjectNode>) g -> {
                    g.putArray("purposes").add("document-summary");
                }},
                new Object[] {"recipient", "source_purpose_or_recipient_denied", (Consumer<ObjectNode>) g -> g.putArray("recipients")});
        for (Object[] testCase : cases) {
            @SuppressWarnings("unchecked")
            Consumer<ObjectNode> change = (Consumer<ObjectNode>) testCase[2];
            world.grantsDocument = AnalysisWorld.defaultGrants();
            change.accept(world.grant());
            world.saveGrants();
            world.issue(JOB_HEX, ANALYSIS_HEX);

            AnalysisItemResult.Failed denied = failed(world.prepare(SUMMARY, null));

            assertEquals(AnalysisFailure.GRANT_DENIED, denied.failure(), "case " + testCase[0]);
            assertEquals(testCase[1], denied.details().get("grantCode"), "case " + testCase[0]);
            assertNothingWritten();
            world.hex.clear();
        }
    }

    @Test
    void aMissingGrantIsDeniedAndAnUnreadableRegistryIsReportedWithoutItsContent() throws IOException {
        world.grant().put("grantId", "another-grant");
        world.saveGrants();
        world.issue(JOB_HEX, ANALYSIS_HEX);
        AnalysisItemResult.Failed missing = failed(world.prepare(SUMMARY, null));
        assertEquals(AnalysisFailure.GRANT_DENIED, missing.failure());
        assertEquals("source_rights_unknown_or_denied", missing.details().get("grantCode"));

        Files.writeString(world.grantsFile, "{not json");
        world.issue(JOB_HEX, ANALYSIS_HEX);
        AnalysisItemResult.Failed unreadable = failed(world.prepare(SUMMARY, null));
        assertEquals(AnalysisFailure.GRANT_REGISTRY_UNAVAILABLE, unreadable.failure());
        assertEquals("grant_registry_unreadable", unreadable.details().get("registry"));
        assertNothingWritten();
    }

    @Test
    void aLiveJobDoesNotNeedItsRecipientBeforeAnyCallExists() throws IOException {
        world.grant().putArray("recipients");
        world.saveGrants();
        world.issue(JOB_HEX, ANALYSIS_HEX);
        AnalysisRequest.PrepareItem live = new AnalysisRequest.PrepareItem(AnalysisWorld.observation(),
                com.zoop.ai.AnalysisKind.DOCUMENT_SUMMARY, COMPANY_ID, new AnalysisRequest.GrantRef(GRANT_ID, GRANT_REVISION),
                com.zoop.ai.ExecutionMode.LIVE, "actual", null);

        AnalysisRunResult run = world.analyzer.run(new AnalysisRequest.Prepare(List.of(live)));

        // A live recipient (provider and endpoint revision) cannot be known before a call exists: the worker, the service and
        // the settlement check it later, so prepare reserves while a replay of the same grant would be denied.
        assertTrue(run.succeeded(), run.toString());
        String stored = new String(read("ai_submit", "submit-s1-" + JOB_HEX + ".json"), StandardCharsets.UTF_8);
        JsonNode provenance = JSON.readTree(stored).get("provenance");
        assertEquals("live", provenance.get("executionMode").stringValue());
        assertEquals("provider", provenance.get("recordingKind").stringValue());
        assertEquals("actual", provenance.get("sourceKind").stringValue());
    }

    @Test
    void aPrivateArticleIsNotAnalysed() throws IOException {
        world.registry.setAccessStatus(DOCUMENT_ID, "private");
        world.issue(JOB_HEX, ANALYSIS_HEX);

        assertEquals(AnalysisFailure.ARTICLE_ACCESS_UNAVAILABLE, failed(world.prepare(SUMMARY, null)).failure());
        assertNothingWritten();
    }

    @Test
    void aDocumentThatWasNeverImportedIsNotAnalysed() throws IOException {
        AnalysisRequest.PrepareItem item = new AnalysisRequest.PrepareItem(
                new com.zoop.document.importer.Observation("round-1", AnalysisWorld.SOURCE, 0, 0, "doc-" + "c".repeat(64),
                        "5".repeat(64), "d".repeat(64)),
                com.zoop.ai.AnalysisKind.DOCUMENT_SUMMARY, COMPANY_ID, new AnalysisRequest.GrantRef(GRANT_ID, GRANT_REVISION),
                com.zoop.ai.ExecutionMode.REPLAY, "synthetic", null);
        // the stand-in exporter serves the fixture document for any observation; only the registered rows decide
        world.exporter.document.put("documentId", "doc-" + "c".repeat(64));
        world.exporter.document.put("documentVersion", "d".repeat(64));
        world.exporter.document.put("textArtifactId", "text-" + "d".repeat(64));

        AnalysisRunResult run = world.analyzer.run(new AnalysisRequest.Prepare(List.of(item)));

        assertEquals(AnalysisFailure.DOCUMENT_NOT_REGISTERED, failed(run).failure());
        assertNothingWritten();
    }

    @Test
    void theExportersRefusalIsReportedWithItsCodeOnly() throws IOException {
        world.exporter.refusal = DocumentImportException.ingestionRefused("source_unauthorized");
        world.issue(JOB_HEX, ANALYSIS_HEX);

        AnalysisItemResult.Failed refused = failed(world.prepare(SUMMARY, null));

        assertEquals(AnalysisFailure.INGESTION_EXPORT_FAILED, refused.failure());
        assertEquals("source_unauthorized", refused.details().get("ingestionCode"));
        assertNothingWritten();
    }

    @Test
    void textThatIsNotTheRegisteredVersionIsNotSubmitted() throws IOException {
        // A valid export (hash and offsets are right) whose text is not the text registered for this version.
        String other = TEXT + "!";
        world.exporter.document.put("text", other);
        world.exporter.document.put("sourceHash", Canonical.sha256(Text.pythonJsonString(other)));
        world.issue(JOB_HEX, ANALYSIS_HEX);

        AnalysisItemResult.Failed changed = failed(world.prepare(SUMMARY, null));

        assertEquals(AnalysisFailure.DOCUMENT_VERSION_MISMATCH, changed.failure());
        assertNothingWritten();
    }

    @Test
    void rawLocatorsAreCodePointSpansThatMustFitTheText() throws IOException {
        // UTF-16 length is longer than the code point count (the text has an emoji): a locator that ends there is not a span.
        int utf16 = TEXT.length();
        int codePoints = TEXT.codePointCount(0, TEXT.length());
        assertTrue(utf16 > codePoints);
        for (int end : new int[] {utf16, 0}) {
            ObjectNode locator = (ObjectNode) world.exporter.document.get("rawLocators").get(0);
            locator.put("end", end);
            world.issue(JOB_HEX, ANALYSIS_HEX);

            assertEquals(AnalysisFailure.EXPORT_INVALID, failed(world.prepare(SUMMARY, null)).failure(), "end " + end);
            assertNothingWritten();
            world.hex.clear();
        }
        world.exporter.document.putArray("rawLocators");
        world.issue(JOB_HEX, ANALYSIS_HEX);
        assertEquals(AnalysisFailure.EXPORT_INVALID, failed(world.prepare(SUMMARY, null)).failure(), "no locator at all");
        assertNothingWritten();
    }

    @Test
    void aSubmitBeyondTheServiceRequestLimitIsNeverReserved() throws IOException {
        // The importer's own bound is 500,000 code points; as 4-byte characters that is 2,000,000 bytes of text alone, which
        // with the rest of the request exceeds the 2,000,000 bytes the AI service accepts.
        String huge = "\uD83D\uDE00".repeat(500_000);
        ObjectNode document = world.exporter.document;
        document.put("text", huge);
        document.put("sourceHash", Canonical.sha256(Text.pythonJsonString(huge)));
        ((ObjectNode) document.get("rawLocators").get(0)).put("end", 500_000);
        world.issue(JOB_HEX, ANALYSIS_HEX);

        AnalysisRunResult run = world.prepare(SUMMARY, null);

        assertEquals(AnalysisFailure.REQUEST_TOO_LARGE, failed(run).failure());
        assertNothingWritten();
    }

    @Test
    void anUnchangedRequestAfterAnAvailableResultIsRefused() throws IOException {
        String first = prepareAnalysis(SUMMARY);
        ObjectNode scenario = AnalysisWorld.scenario("summary");
        serve(scenario);
        assertEquals("available", AnalysisWorld.settled(world.advance(first, false)).outcome());

        world.issue("02".repeat(16), "a2".repeat(16));
        AnalysisItemResult.Failed unchanged = failed(world.prepare(SUMMARY, first));

        assertEquals(AnalysisFailure.ANALYSIS_UNCHANGED, unchanged.failure());
        assertEquals(first, unchanged.details().get("analysisId"));
        assertEquals(1, world.analyses.rows().size());
        assertEquals(List.of("submit-s1-" + JOB_HEX + ".json"), world.files("ai_submit"));
    }
}
