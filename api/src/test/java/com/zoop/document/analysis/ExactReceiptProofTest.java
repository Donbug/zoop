package com.zoop.document.analysis;

import java.nio.charset.StandardCharsets;

import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.node.ObjectNode;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;

class ExactReceiptProofTest {
    private static final String DIGEST = "b".repeat(64);
    private static final String TEXT_SHA = "a".repeat(64);

    private static String independentArtifactId(String job, String kind) {
        ObjectNode node = StrictJson.newObject();
        node.put("jobId", job);
        node.put("kind", kind);
        node.put("inputDigest", DIGEST);
        return "artifact-" + Canonical.digest(node);
    }

    private static String evidenceId(String analysis, String model) {
        ObjectNode node = StrictJson.newObject();
        node.put("analysisId", analysis);
        node.put("evidenceId", model);
        return "ev-" + Canonical.digest(node);
    }

    private static byte[] receipt(String creator) {
        ObjectNode node = StrictJson.newObject();
        node.put("schemaVersion", "zoop-exact-receipt-1");
        node.put("analysisId", "an-2");
        node.put("aiJobId", "job-2");
        node.put("creatorJobId", creator);
        node.put("kind", "document-summary");
        node.put("documentId", "art-1");
        node.put("documentVersion", "v1");
        node.put("textArtifactId", "text-1");
        node.put("textSha256", TEXT_SHA);
        node.put("inputDigest", DIGEST);
        node.put("resultVersion", "result-2");
        node.put("policyVersion", "zoop-document-gate-2");
        ObjectNode citation = node.putArray("citations").addObject();
        citation.put("evidenceId", evidenceId("an-2", "e1"));
        citation.put("modelEvidenceId", "e1");
        citation.put("start", 5);
        citation.put("end", 9);
        citation.putArray("rawLocatorIds").add("loc-1");
        return Canonical.bytes(node);
    }

    private static ExactReceiptProof.Subject subject() {
        return new ExactReceiptProof.Subject("an-2", "job-2", "art-1", "v1", "text-1", TEXT_SHA, "result-2",
                independentArtifactId("job-0", "document-summary"), independentArtifactId("job-0", "semantic-verification"),
                evidenceId("an-2", "e1"), 5, 9);
    }

    @Test
    void theSharedArtifactIdRuleReproducesTheIndependentComputation() {
        assertEquals(independentArtifactId("job-0", "document-summary"),
                ResultAssessor.artifactId("job-0", "document-summary", DIGEST));
        assertEquals(independentArtifactId("job-0", "semantic-verification"),
                ResultAssessor.artifactId("job-0", "semantic-verification", DIGEST));
    }

    @Test
    void aReceiptThatMatchesEverythingNamesItsCreator() {
        assertEquals("job-0", ExactReceiptProof.creatorJobId(receipt("job-0"), subject()));
    }

    @Test
    void anyDoubtIsNullAndNeverAnException() {
        assertNull(ExactReceiptProof.creatorJobId(receipt("job-1"), subject()), "another creator reproduces other artifact ids");
        assertNull(ExactReceiptProof.creatorJobId(receipt("job-2"), subject()), "the creator is never the analysis itself");
        assertNull(ExactReceiptProof.creatorJobId("{".getBytes(StandardCharsets.UTF_8), subject()));
        assertNull(ExactReceiptProof.creatorJobId(new byte[] {(byte) 0xff}, subject()));
        assertNull(ExactReceiptProof.creatorJobId("[]".getBytes(StandardCharsets.UTF_8), subject()));
        assertNull(ExactReceiptProof.creatorJobId(receipt("job-0"), new ExactReceiptProof.Subject("an-2", "job-2", "art-1", "v1",
                "text-1", TEXT_SHA, "result-2", independentArtifactId("job-0", "document-summary"),
                independentArtifactId("job-0", "semantic-verification"), evidenceId("an-2", "e1"), 5, 10)));
    }
}
