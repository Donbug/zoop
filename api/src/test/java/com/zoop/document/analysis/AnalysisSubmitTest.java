package com.zoop.document.analysis;

import java.nio.charset.StandardCharsets;
import java.util.function.Consumer;

import com.zoop.ai.AnalysisKind;
import com.zoop.ai.ExecutionMode;
import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.node.ArrayNode;
import tools.jackson.databind.node.ObjectNode;

import static org.junit.jupiter.api.Assertions.assertArrayEquals;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * The stored {@code ai_submit} is the only source of what the app asks the AI service and of what it later accepts as an
 * answer: it must be exactly a valid, canonical S1 submit, never a lookalike.
 */
class AnalysisSubmitTest {

    private static ObjectNode submitNode() {
        return (ObjectNode) AnalysisWorld.scenario("summary").get("submit");
    }

    private static void assertMalformed(Consumer<ObjectNode> tamper) {
        ObjectNode node = submitNode();
        tamper.accept(node);
        assertThrows(StrictJson.Malformed.class, () -> AnalysisSubmit.parse(Canonical.bytes(node)));
    }

    @Test
    void aWorkerSubmitIsParsedAndHasItsCanonicalBytesBack() {
        ObjectNode node = submitNode();
        byte[] bytes = Canonical.bytes(node);

        AnalysisSubmit submit = AnalysisSubmit.parse(bytes);

        assertArrayEquals(bytes, submit.bytes());
        assertEquals("s1-" + "01".repeat(16), submit.jobId());
        assertEquals(AnalysisKind.DOCUMENT_SUMMARY, submit.kind());
        assertEquals(ExecutionMode.REPLAY, submit.mode());
        assertEquals(AnalysisWorld.DOCUMENT_ID, submit.documentId());
        assertEquals(AnalysisWorld.VERSION, submit.documentVersion());
        assertEquals("text-" + AnalysisWorld.VERSION, submit.textArtifactId());
        assertEquals(AnalysisWorld.TEXT, submit.text());
        assertEquals(AnalysisWorld.COMPANY_ID, submit.companyId());
        assertEquals(AnalysisWorld.COMPANY_NAME, submit.companyName());
        assertEquals(AnalysisWorld.GRANT_ID, submit.grantId());
        assertEquals(1, submit.locators().size());
        assertEquals(AnalysisWorld.TEXT.codePointCount(0, AnalysisWorld.TEXT.length()), submit.locators().get(0).end());
        assertTrue(submit.withinRequestLimit());
        assertEquals(Canonical.write(node), submit.canonicalText());
        assertEquals("s1-" + "01".repeat(16), submit.toSubmission().jobId());
        assertEquals(Canonical.write(node.get("input")), submit.toSubmission().inputJson());
        assertEquals(Canonical.write(node.get("provenance")), submit.toSubmission().provenanceJson());
        assertEquals("AnalysisSubmit[jobId=s1-" + "01".repeat(16) + ", kind=document-summary, mode=replay]", submit.toString());
    }

    @Test
    void theIdentityIgnoresOnlyTheJobId() {
        ObjectNode other = submitNode();
        other.put("jobId", "s1-" + "02".repeat(16));
        ObjectNode otherCompany = submitNode();
        ((ObjectNode) otherCompany.get("input").get("company")).put("name", "다른 회사");

        AnalysisSubmit first = AnalysisSubmit.parse(Canonical.bytes(submitNode()));

        assertEquals(first.identity(), AnalysisSubmit.parse(Canonical.bytes(other)).identity());
        assertNotEquals(first.identity(), AnalysisSubmit.parse(Canonical.bytes(otherCompany)).identity());
    }

    @Test
    void bytesThatAreNotCanonicalAreRefused() {
        String canonical = Canonical.write(submitNode());

        assertThrows(StrictJson.Malformed.class, () -> AnalysisSubmit.parse((" " + canonical).getBytes(StandardCharsets.UTF_8)));
        assertThrows(StrictJson.Malformed.class, () -> AnalysisSubmit.parse(canonical.replace("\"kind\"", "\"kind\" ").getBytes(StandardCharsets.UTF_8)));
        assertThrows(StrictJson.Malformed.class, () -> AnalysisSubmit.parse(new byte[] {(byte) 0xff}));
    }

    @Test
    void anythingOutsideTheSubmitContractIsRefused() {
        assertMalformed(node -> node.put("unexpected", 1));
        assertMalformed(node -> node.remove("provenance"));
        assertMalformed(node -> node.put("schemaVersion", "zoop-ai-s1-2"));
        assertMalformed(node -> node.put("jobId", "not a job id"));
        assertMalformed(node -> node.put("kind", "semantic-verification"));
        assertMalformed(node -> node.put("kind", "briefing-outlook"));
        assertMalformed(node -> node.put("mode", "batch"));
        assertMalformed(node -> ((ObjectNode) node.get("input")).put("candidate", "text"));
        assertMalformed(node -> ((ObjectNode) node.get("input")).remove("company"));
        assertMalformed(node -> ((ObjectNode) node.get("input").get("company")).put("name", ""));
        assertMalformed(node -> ((ObjectNode) node.get("input")).put("grantRevision", ""));
        assertMalformed(node -> ((ObjectNode) node.get("input").get("document")).put("inputKind", "summary"));
        assertMalformed(node -> ((ObjectNode) node.get("input").get("document")).put("extra", true));
    }

    @Test
    void theProvenanceMustFollowTheModeAndAReplayIsAlwaysSynthetic() {
        assertMalformed(node -> ((ObjectNode) node.get("provenance")).put("sourceKind", "actual"));
        assertMalformed(node -> ((ObjectNode) node.get("provenance")).put("executionMode", "live"));
        assertMalformed(node -> ((ObjectNode) node.get("provenance")).put("recordingKind", "provider"));
        assertMalformed(node -> ((ObjectNode) node.get("provenance")).put("sourceKind", "synthetic ").put("extra", 1));
        assertMalformed(node -> {
            node.put("mode", "live");
            ((ObjectNode) node.get("provenance")).put("executionMode", "live");
        });
        AnalysisSubmit live = AnalysisSubmit.parse(Canonical.bytes(liveNode()));
        assertEquals(ExecutionMode.LIVE, live.mode());
        assertEquals("actual", live.sourceKind());
    }

    private static ObjectNode liveNode() {
        ObjectNode node = submitNode();
        node.put("mode", "live");
        ObjectNode provenance = (ObjectNode) node.get("provenance");
        provenance.put("sourceKind", "actual");
        provenance.put("executionMode", "live");
        provenance.put("recordingKind", "provider");
        return node;
    }

    @Test
    void theDocumentMustHashToItsSourceHashAndItsLocatorsMustBeCodePointSpans() {
        int codePoints = AnalysisWorld.TEXT.codePointCount(0, AnalysisWorld.TEXT.length());
        assertTrue(AnalysisWorld.TEXT.length() > codePoints, "the fixture text has an emoji, so UTF-16 length differs");

        assertMalformed(node -> ((ObjectNode) node.get("input").get("document")).put("sourceHash", "0".repeat(64)));
        assertMalformed(node -> ((ObjectNode) node.get("input").get("document")).put("text", AnalysisWorld.TEXT + "!"));
        assertMalformed(node -> ((ObjectNode) node.get("input").get("document").get("rawLocators").get(0))
                .put("end", AnalysisWorld.TEXT.length()));
        assertMalformed(node -> ((ObjectNode) node.get("input").get("document").get("rawLocators").get(0)).put("end", 0));
        assertMalformed(node -> ((ObjectNode) node.get("input").get("document").get("rawLocators").get(0)).put("start", codePoints));
        assertMalformed(node -> ((ObjectNode) node.get("input").get("document")).putArray("rawLocators"));
        assertMalformed(node -> {
            ObjectNode document = (ObjectNode) node.get("input").get("document");
            ObjectNode twin = ((ArrayNode) document.get("rawLocators")).addObject();
            twin.put("locatorId", "raw-1");
            twin.put("start", 0);
            twin.put("end", 1);
        });
    }
}
