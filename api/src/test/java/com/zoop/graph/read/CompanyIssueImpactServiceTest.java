package com.zoop.graph.read;

import static com.zoop.graph.read.GraphReadFixtures.HBM_SUPPLY;
import static com.zoop.graph.read.GraphReadFixtures.HYNIX;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import com.zoop.common.json.StrictJson;
import com.zoop.document.evidence.service.EvidenceService;
import java.time.Instant;
import org.junit.jupiter.api.Test;

class CompanyIssueImpactServiceTest {
    private static final Instant NOW = Instant.parse("2026-10-16T12:00:00Z");
    private static final String EVIDENCE_ID = "ev-bb3008cb36e9b51c0d2fd77af059259332b1887cc04862e185a496c3dcc9e421";

    @Test
    void readsVerifiedImpactFromAValidInvolvesReceiptWithSourceRefKind() {
        EvidenceService evidence = mock(EvidenceService.class);
        when(evidence.graphImportBundle(anyString(), anyString())).thenReturn(validReceipt());
        when(evidence.shownNow(anyString(), org.mockito.ArgumentMatchers.isNull(), anyString(),
                org.mockito.ArgumentMatchers.any(), anyString())).thenReturn(true);
        var service = new CompanyIssueImpactService(GraphReadFixtures.reader(NOW, pinned -> DisclosureExclusions.NONE), evidence);

        var result = service.getImpactPath(HYNIX, HBM_SUPPLY, null, null, null, "request-1");

        assertEquals("available", result.pathStatus());
        assertEquals("direct", result.pathType());
        assertEquals("available", result.impact().status());
        assertEquals("positive", result.impact().results().get(0).label());
    }

    private static StrictJson.Obj validReceipt() {
        return StrictJson.parseObject("""
                {
                  "relations": [{"id":"rel-fixture-02","type":"INVOLVES",
                    "source":"iss-fixture-hbm-supply","target":"KRX:000660",
                    "sourceRefs":[{"kind":"s3-relation","jobId":"rel-job-1","id":"candidate-1"}]}],
                  "impacts": [{"edgeId":"rel-fixture-02","issueId":"iss-fixture-hbm-supply",
                    "companyId":"KRX:000660","sourceRelation":{"jobId":"rel-job-1","relationCandidateId":"candidate-1"},
                    "impactCandidateId":"impact-1","status":"verified","code":"verified","label":"positive",
                    "targetVerdict":"ALLOW","effects":{"positive":["%s"],"negative":[],"neutral":[],"uncertain":[]},
                    "verifier":"fixture","verifierRequestDigest":"digest","proposal":{}}]
                }
                """.formatted(EVIDENCE_ID));
    }
}
