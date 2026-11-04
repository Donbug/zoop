package com.zoop.graph.read;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.doReturn;
import static org.mockito.Mockito.when;

import com.zoop.common.response.Metadata;
import com.zoop.document.evidence.dto.EvidenceArticle;
import com.zoop.document.evidence.dto.EvidenceResponse;
import com.zoop.document.evidence.service.EvidenceService;
import com.zoop.graph.publication.GraphPublicationReader.Publication;
import com.zoop.graph.version.GraphVersionRecord;
import com.zoop.graph.version.SelectedGraphVersion;
import java.time.Instant;
import java.util.List;
import org.junit.jupiter.api.Test;

class CompanyIssueImpactAssessmentServiceTest {
    private static final Instant NOW = Instant.parse("2026-10-31T00:00:00Z");

    @Test
    void returnsOnlyVerifiedRowsForTheSelectedDirectRelationAndKeepsSourceRowsSeparate() throws Exception {
        Publication publication = S3ImpactRowsTest.composed();
        String verifiedRelationId = S3ImpactRows.read(publication, publication.snapshot().relations()).stream()
                .filter(row -> "verified".equals(row.status())).findFirst().orElseThrow().relationId();
        var relation = publication.snapshot().relations().stream()
                .filter(r -> verifiedRelationId.equals(r.relationId())).findFirst().orElseThrow();
        var graphs = mock(PublicGraphReader.class);
        var evidence = mock(EvidenceService.class);
        var selected = new SelectedGraphVersion(new GraphVersionRecord(publication.versionId(), 4, "snapshot",
                "artifact", "uri", "a".repeat(64), true), NOW, false, null);
        when(graphs.read(null, publication.versionId(), null, "request"))
                .thenReturn(new PublicGraphReader.Pinned(selected, DisplayGraph.of(publication.snapshot())));
        when(evidence.graphPublication(publication.versionId(), "request")).thenReturn(publication);
        when(evidence.readImpactCitation(anyString(), isNull(), eq(publication.versionId()), isNull(), eq("request")))
                .thenAnswer(call -> citation(publication, call.getArgument(0)));

        var result = new CompanyIssueImpactAssessmentService(graphs, evidence)
                .get(relation.target(), relation.source(), null, publication.versionId(), null, "request");

        assertEquals("available", result.status());
        assertEquals(relation.target(), result.companyId());
        assertEquals(relation.source(), result.issueId());
        assertTrue(result.results().size() >= 1);
        assertTrue(result.results().stream().allMatch(row -> row.status().equals("verified")));
        assertTrue(result.results().stream().allMatch(row -> row.provenance().executionMode().equals("replay")));
        assertEquals(result.results().size(), result.results().stream().map(row -> row.impactId()).distinct().count());
    }

    @Test
    void withholdsAllResultsWhenOneVerifiedCitationHasLostCurrentRights() throws Exception {
        Publication publication = S3ImpactRowsTest.composed();
        var verified = S3ImpactRows.read(publication, publication.snapshot().relations()).stream()
                .filter(row -> "verified".equals(row.status())).findFirst().orElseThrow();
        var relation = publication.snapshot().relations().stream()
                .filter(r -> verified.relationId().equals(r.relationId())).findFirst().orElseThrow();
        String deniedId = verified.effects().keySet().iterator().next();
        var graphs = mock(PublicGraphReader.class);
        var evidence = mock(EvidenceService.class);
        var selected = new SelectedGraphVersion(new GraphVersionRecord(publication.versionId(), 4, "snapshot",
                "artifact", "uri", "a".repeat(64), true), NOW, false, null);
        when(graphs.read(null, publication.versionId(), null, "request"))
                .thenReturn(new PublicGraphReader.Pinned(selected, DisplayGraph.of(publication.snapshot())));
        when(evidence.graphPublication(publication.versionId(), "request")).thenReturn(publication);
        when(evidence.readImpactCitation(anyString(), isNull(), eq(publication.versionId()), isNull(), eq("request")))
                .thenAnswer(call -> citation(publication, call.getArgument(0)));
        doReturn(null).when(evidence).readImpactCitation(eq(deniedId), isNull(), eq(publication.versionId()), isNull(), eq("request"));

        var result = new CompanyIssueImpactAssessmentService(graphs, evidence)
                .get(relation.target(), relation.source(), null, publication.versionId(), null, "request");

        assertEquals("unavailable", result.status());
        assertEquals("evidence_unavailable", result.reason());
        assertTrue(result.results().isEmpty());
        assertTrue(result.metadata().partial());
    }

    private static EvidenceResponse citation(Publication publication, String id) {
        var item = publication.snapshot().evidence().stream().filter(row -> id.equals(row.evidenceId())).findFirst().orElseThrow();
        return new EvidenceResponse(id, "retained quote", item.start(), item.end(), item.articleId(), item.articleVersion(),
                new EvidenceArticle("Retained article", null, "https://example.invalid/article", NOW), true, List.of(),
                new Metadata("test", NOW, publication.versionId(), "request", false, List.of()),
                null, null, null, null, null, null);
    }
}
