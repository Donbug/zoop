package com.zoop.graph.read;

import static com.zoop.graph.read.GraphReadFixtures.HBM_SUPPLY;
import static com.zoop.graph.read.GraphReadFixtures.HBM_EQUIP;
import static com.zoop.graph.read.GraphReadFixtures.HYNIX;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.nullable;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

import com.zoop.common.json.StrictJson;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.document.evidence.service.EvidenceService;
import com.zoop.graph.version.GraphVersionRecord;
import com.zoop.graph.version.SelectedGraphVersion;
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
                nullable(Instant.class), anyString())).thenReturn(true);
        PublicGraphReader reader = mock(PublicGraphReader.class);
        var selected = new SelectedGraphVersion(new GraphVersionRecord("snapshot-test-version", 1, "snapshot",
                "artifact-test", "memory:test", "sha-test", true), NOW, false);
        when(reader.read(org.mockito.ArgumentMatchers.isNull(), org.mockito.ArgumentMatchers.isNull(),
                org.mockito.ArgumentMatchers.isNull(), anyString()))
                .thenReturn(new PublicGraphReader.Pinned(selected,
                        DisplayGraph.of(GraphReadFixtures.snapshot("fixture-2026-10-08"))));
        var service = new CompanyIssueImpactService(reader, evidence);

        var result = service.getImpactPath(HYNIX, HBM_SUPPLY, null, null, null, "request-1");

        assertEquals("available", result.pathStatus());
        assertEquals("direct", result.pathType());
        assertEquals("available", result.impact().status(), result.impact().reason());
        assertEquals("positive", result.impact().results().get(0).label());
    }

    @Test
    void fixtureVersionReportsUnrecordedImpactWithoutTryingToReadAReceipt() {
        EvidenceService evidence = mock(EvidenceService.class);
        var service = new CompanyIssueImpactService(GraphReadFixtures.reader(NOW, pinned -> DisclosureExclusions.NONE), evidence);

        var result = service.getImpactPath(HYNIX, HBM_SUPPLY, null, null, null, "request-fixture");

        assertEquals("direct", result.pathType());
        assertEquals("unavailable", result.impact().status());
        assertEquals("not_recorded", result.impact().reason());
        verifyNoInteractions(evidence);
    }

    @Test
    void fixtureVersionReportsUnrecordedBusinessPathWithoutTryingToReadAReceipt() {
        EvidenceService evidence = mock(EvidenceService.class);
        var service = new CompanyIssueImpactService(GraphReadFixtures.reader(NOW, pinned -> DisclosureExclusions.NONE), evidence);

        var result = service.getImpactPath(HYNIX, HBM_EQUIP, null, null, null, "request-fixture");

        assertEquals("structural", result.pathType());
        assertEquals("unavailable", result.businessPath().status());
        assertEquals("not_recorded", result.businessPath().reason());
        verifyNoInteractions(evidence);
    }

    @Test
    void businessReasonUsesKoreanLabelAndRejectsUnknownRelationType() {
        var basis = StrictJson.parseObject("""
                {"relationType":"SUPPLIES","businessScope":"HBM","productScope":"메모리"}
                """);

        assertEquals("공급 · HBM · 메모리", CompanyIssueImpactService.businessReason(basis));
        org.junit.jupiter.api.Assertions.assertThrows(com.zoop.common.exception.CustomException.class,
                () -> CompanyIssueImpactService.businessReason(StrictJson.parseObject("""
                        {"relationType":"UNKNOWN","businessScope":null,"productScope":null}
                        """)));
    }

    @Test
    void unreadableEvidenceDoesNotHideAnUnmatchedSourceReference() {
        EvidenceService evidence = mock(EvidenceService.class);
        when(evidence.graphImportBundle(anyString(), anyString())).thenReturn(receiptWithUnmatchedSourceRef());
        when(evidence.shownNow(anyString(), org.mockito.ArgumentMatchers.isNull(), anyString(),
                nullable(Instant.class), anyString())).thenReturn(false);
        PublicGraphReader reader = mock(PublicGraphReader.class);
        var selected = new SelectedGraphVersion(new GraphVersionRecord("snapshot-test-version", 1, "snapshot",
                "artifact-test", "memory:test", "sha-test", true), NOW, false);
        when(reader.read(org.mockito.ArgumentMatchers.isNull(), org.mockito.ArgumentMatchers.isNull(),
                org.mockito.ArgumentMatchers.isNull(), anyString()))
                .thenReturn(new PublicGraphReader.Pinned(selected,
                        DisplayGraph.of(GraphReadFixtures.snapshot("fixture-2026-10-08"))));
        var service = new CompanyIssueImpactService(reader, evidence);

        CustomException error = assertThrows(CustomException.class,
                () -> service.getImpactPath(HYNIX, HBM_SUPPLY, null, null, null, "request-corrupt"));

        assertEquals(ErrorCode.SOURCE_UNAVAILABLE, error.getErrorCode());
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

    private static StrictJson.Obj receiptWithUnmatchedSourceRef() {
        return StrictJson.parseObject("""
                {
                  "relations": [{"id":"rel-fixture-02","type":"INVOLVES",
                    "source":"iss-fixture-hbm-supply","target":"KRX:000660",
                    "sourceRefs":[{"kind":"s3-relation","jobId":"rel-job-1","id":"candidate-1"},
                      {"kind":"s3-relation","jobId":"rel-job-2","id":"candidate-2"}]}],
                  "impacts": [{"edgeId":"rel-fixture-02","issueId":"iss-fixture-hbm-supply",
                    "companyId":"KRX:000660","sourceRelation":{"jobId":"rel-job-1","relationCandidateId":"candidate-1"},
                    "impactCandidateId":"impact-1","status":"verified","code":"verified","label":"positive",
                    "targetVerdict":"ALLOW","effects":{"positive":["%s"],"negative":[],"neutral":[],"uncertain":[]},
                    "verifier":"fixture","verifierRequestDigest":"digest","proposal":{}}]
                }
                """.formatted(EVIDENCE_ID));
    }
}
