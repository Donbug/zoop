package com.zoop.document.analysis;

import java.nio.charset.StandardCharsets;

import com.zoop.ai.AnalysisKind;
import com.zoop.ai.ExecutionMode;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/** The operator request is closed: it can name documents and analyses, never supply text, rights, paths or results. */
class AnalysisRequestParserTest {
    private static final String DOC = "doc-" + "a".repeat(64);
    private static final String ANALYSIS = "da-" + "b".repeat(32);
    private final AnalysisRequestParser parser = new AnalysisRequestParser();

    private static String prepareItem() {
        return "{\"observation\":{\"roundId\":\"r1\",\"sourceId\":\"src\",\"page\":0,\"ordinal\":1,\"documentId\":\"" + DOC
                + "\",\"rawVersion\":\"" + "c".repeat(64) + "\",\"documentVersion\":\"" + "d".repeat(64) + "\"},"
                + "\"kind\":\"document-summary\",\"companyId\":\"SYNTH-A\",\"grant\":{\"grantId\":\"g\",\"revision\":\"r1\"},"
                + "\"mode\":\"replay\",\"sourceKind\":\"synthetic\",\"latest\":{\"expected\":null}}";
    }

    private static byte[] request(String command, String items) {
        return ("{\"schemaVersion\":\"zoop-document-analysis-1\",\"command\":\"" + command + "\",\"items\":[" + items + "]}")
                .getBytes(StandardCharsets.UTF_8);
    }

    private void assertInvalid(byte[] bytes) {
        AnalysisException error = assertThrows(AnalysisException.class, () -> parser.parse(bytes));
        assertEquals(AnalysisFailure.REQUEST_INVALID, error.failure());
        assertTrue(error.details().isEmpty(), "the code is all that is reported");
    }

    @Test
    void parsesAPrepareBatch() {
        AnalysisRequest.Prepare request = (AnalysisRequest.Prepare) parser.parse(request("prepare", prepareItem()));

        assertEquals("prepare", request.command());
        assertEquals(1, request.size());
        AnalysisRequest.PrepareItem item = request.items().get(0);
        assertEquals(DOC, item.observation().documentId());
        assertEquals(1, item.observation().ordinal());
        assertEquals(AnalysisKind.DOCUMENT_SUMMARY, item.kind());
        assertEquals("SYNTH-A", item.companyId());
        assertEquals(new AnalysisRequest.GrantRef("g", "r1"), item.grant());
        assertEquals(ExecutionMode.REPLAY, item.mode());
        assertEquals("synthetic", item.sourceKind());
        assertNull(item.expectedLatest());
    }

    @Test
    void theLatestExpectationIsRequiredAndTypedAndALiveRunMayBeActual() {
        AnalysisRequest.Prepare again = (AnalysisRequest.Prepare) parser.parse(request("prepare",
                prepareItem().replace("\"expected\":null", "\"expected\":\"" + ANALYSIS + "\"")));
        assertEquals(ANALYSIS, again.items().get(0).expectedLatest());

        AnalysisRequest.Prepare live = (AnalysisRequest.Prepare) parser.parse(request("prepare",
                prepareItem().replace("\"mode\":\"replay\"", "\"mode\":\"live\"").replace("synthetic", "actual")));
        assertEquals(ExecutionMode.LIVE, live.items().get(0).mode());
        assertEquals("actual", live.items().get(0).sourceKind());

        assertInvalid(request("prepare", prepareItem().replace(",\"latest\":{\"expected\":null}", "")));
        assertInvalid(request("prepare", prepareItem().replace("{\"expected\":null}", "null")));
        assertInvalid(request("prepare", prepareItem().replace("{\"expected\":null}", "{}")));
        assertInvalid(request("prepare", prepareItem().replace("null}}", "\"" + "b".repeat(32) + "\"}}")));
        assertInvalid(request("prepare", prepareItem().replace("\"expected\":null", "\"expected\":\"da-short\"")));
    }

    @Test
    void parsesAnAdvanceBatchWithTheRecoveryOptIn() {
        AnalysisRequest.Advance request = (AnalysisRequest.Advance) parser.parse(request("advance",
                "{\"analysisId\":\"" + ANALYSIS + "\"},{\"analysisId\":\"" + ANALYSIS + "\",\"recover\":true}"));

        assertEquals("advance", request.command());
        assertEquals(2, request.size());
        assertFalse(request.items().get(0).recover(), "recovery is never implied");
        assertTrue(request.items().get(1).recover());
        assertInvalid(request("advance", "{\"analysisId\":\"" + ANALYSIS + "\",\"recover\":\"true\"}"));
        assertInvalid(request("advance", "{\"analysisId\":\"" + ANALYSIS + "\",\"recover\":1}"));
        assertInvalid(request("advance", "{\"analysisId\":\"da-" + "B".repeat(32) + "\"}"));
        assertInvalid(request("advance", "{\"analysisId\":\"" + ANALYSIS + "\",\"aiJobId\":\"s1-x\"}"));
        assertInvalid(request("advance", "{}"));
    }

    @Test
    void refusesEveryWayToSupplyWhatTheAppMustDeriveItself() {
        for (String key : new String[] {"export", "document", "text", "grants", "result", "company", "path", "aiJobId"}) {
            assertInvalid(request("prepare", prepareItem().replace("\"kind\":", "\"" + key + "\":{\"x\":1},\"kind\":")));
        }
        assertInvalid(request("prepare", prepareItem().replace("\"grantId\":\"g\"", "\"grantId\":\"g\",\"expiresAt\":null")));
        assertInvalid(request("prepare", prepareItem().replace("\"page\":0", "\"page\":0,\"url\":\"x\"")));
    }

    @Test
    void refusesWhatTheWorkerWouldRefuseOrWhatIsOutOfRange() {
        assertInvalid(request("prepare", prepareItem().replace("synthetic", "actual")));
        assertInvalid(request("prepare", prepareItem().replace("\"synthetic\"", "\"real\"")));
        assertInvalid(request("prepare", prepareItem().replace("document-summary", "semantic-verification")));
        assertInvalid(request("prepare", prepareItem().replace("document-summary", "briefing-outlook")));
        assertInvalid(request("prepare", prepareItem().replace("\"replay\"", "\"batch\"")));
        assertInvalid(request("prepare", prepareItem().replace(DOC, "doc-ABC")));
        assertInvalid(request("prepare", prepareItem().replace("c".repeat(64), "c".repeat(63))));
        assertInvalid(request("prepare", prepareItem().replace("\"page\":0", "\"page\":-1")));
        assertInvalid(request("prepare", prepareItem().replace("\"page\":0", "\"page\":1.5")));
        assertInvalid(request("prepare", prepareItem().replace("\"companyId\":\"SYNTH-A\"", "\"companyId\":\"\"")));
        assertInvalid(request("prepare", prepareItem().replace("\"grantId\":\"g\"", "\"grantId\":\"\"")));
        assertInvalid(request("prepare", prepareItem().replace("\"companyId\":\"SYNTH-A\"", "\"companyId\":\"a\\u0000b\"")));
        assertInvalid(request("prepare", prepareItem().replace("\"companyId\":\"SYNTH-A\"", "\"companyId\":\"" + "x".repeat(201) + "\"")));
    }

    @Test
    void theRequestEnvelopeIsClosedAndBounded() {
        assertInvalid(new byte[0]);
        assertInvalid("{}".getBytes(StandardCharsets.UTF_8));
        assertInvalid("[]".getBytes(StandardCharsets.UTF_8));
        assertInvalid("not json".getBytes(StandardCharsets.UTF_8));
        assertInvalid(new byte[] {(byte) 0xff});
        assertInvalid(request("prepare", ""));
        assertInvalid(request("cancel", prepareItem()));
        assertInvalid(request("prepare", "{\"analysisId\":\"" + ANALYSIS + "\"}"));
        assertInvalid(request("advance", prepareItem()));
        assertInvalid(("{\"schemaVersion\":\"zoop-document-analysis-2\",\"command\":\"prepare\",\"items\":[" + prepareItem() + "]}")
                .getBytes(StandardCharsets.UTF_8));
        assertInvalid(("{\"schemaVersion\":\"zoop-document-analysis-1\",\"command\":\"prepare\",\"command\":\"advance\",\"items\":["
                + prepareItem() + "]}").getBytes(StandardCharsets.UTF_8));
        assertInvalid(("{\"schemaVersion\":\"zoop-document-analysis-1\",\"command\":\"prepare\",\"items\":[" + prepareItem()
                + "],\"extra\":1}").getBytes(StandardCharsets.UTF_8));

        String hundred = String.join(",", java.util.Collections.nCopies(AnalysisRequest.MAX_ITEMS, prepareItem()));
        assertEquals(AnalysisRequest.MAX_ITEMS, parser.parse(request("prepare", hundred)).size());
        assertInvalid(request("prepare", hundred + "," + prepareItem()));
        byte[] huge = new byte[AnalysisRequestParser.MAX_BYTES + 1];
        java.util.Arrays.fill(huge, (byte) ' ');
        assertInvalid(huge);
    }
}
