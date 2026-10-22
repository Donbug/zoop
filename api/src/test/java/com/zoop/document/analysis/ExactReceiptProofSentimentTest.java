package com.zoop.document.analysis;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;

import com.zoop.document.analysis.ExactReceiptProof.SentimentSubject;
import java.nio.charset.StandardCharsets;
import org.junit.jupiter.api.Test;

class ExactReceiptProofSentimentTest {
    private static final String DIGEST = "a".repeat(64);

    private static SentimentSubject subject() {
        return new SentimentSubject("analysis-2", "job-2", "art-1", "v1", "text-1", DIGEST,
                "result-2", ResultAssessor.artifactId("job-1", "document-sentiment", DIGEST),
                ResultAssessor.artifactId("job-1", "semantic-verification", DIGEST));
    }

    private static byte[] receipt(String kind, String policy) {
        return ("""
                {"schemaVersion":"zoop-exact-receipt-1","analysisId":"analysis-2","aiJobId":"job-2",
                 "creatorJobId":"job-1","kind":"%s","documentId":"art-1","documentVersion":"v1",
                 "textArtifactId":"text-1","textSha256":"%s","inputDigest":"%s",
                 "resultVersion":"result-2","policyVersion":"%s",
                 "citations":[{"evidenceId":null,"modelEvidenceId":"model-ev-1","start":0,"end":3,
                               "rawLocatorIds":["raw-1"]}]}
                """.formatted(kind, DIGEST, DIGEST, policy)).getBytes(StandardCharsets.UTF_8);
    }

    @Test
    void provesTheCreatorOnlyForTheExactSentimentReceipt() {
        assertEquals("job-1", ExactReceiptProof.sentimentCreatorJobId(
                receipt("document-sentiment", "zoop-document-gate-2"), subject()));
        assertNull(ExactReceiptProof.sentimentCreatorJobId(
                receipt("document-summary", "zoop-document-gate-2"), subject()));
        assertNull(ExactReceiptProof.sentimentCreatorJobId(
                receipt("document-sentiment", "old-policy"), subject()));
    }
}
