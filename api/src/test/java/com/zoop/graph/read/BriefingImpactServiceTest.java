package com.zoop.graph.read;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

import com.zoop.briefing.impact.BriefingImpacts.Assessment;
import com.zoop.briefing.query.BriefingQueryService;
import com.zoop.briefing.storage.BriefingRound;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.common.response.Metadata;
import com.zoop.document.evidence.dto.EvidenceArticle;
import com.zoop.document.evidence.dto.EvidenceResponse;
import com.zoop.document.evidence.service.EvidenceService;
import com.zoop.graph.publication.GraphPublicationReader.Publication;
import com.zoop.graph.version.BriefingGraphLookup;
import com.zoop.graph.version.GraphVersionRecord;
import com.zoop.graph.version.SelectedGraphVersion;
import java.time.Instant;
import java.time.LocalDate;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

class BriefingImpactServiceTest {
    private static final Instant NOW = Instant.parse("2026-10-31T00:00:00Z");
    private static final String EVENT = "public:issue:supply-2026q3";
    private final BriefingQueryService briefings = mock(BriefingQueryService.class);
    private final PublicGraphReader graphs = mock(PublicGraphReader.class);
    private final EvidenceService evidence = mock(EvidenceService.class);
    private final BriefingImpactService service = new BriefingImpactService(briefings, graphs, evidence);
    private Publication publication;

    @BeforeEach
    void setUp() throws Exception {
        publication = S3ImpactRowsTest.composed();
        when(briefings.impactBasis("round", EVENT, "r")).thenReturn(new BriefingRound("round", LocalDate.of(2026, 10, 31),
                "morning", NOW, NOW.minusSeconds(3600), NOW, false, "published", NOW, NOW,
                publication.versionId(), null, null, null));
        pin("snapshot");
        when(evidence.graphPublication(publication.versionId(), "r")).thenReturn(publication);
        when(evidence.readImpactCitation(anyString(), eq("round"), eq(publication.versionId()), eq(NOW), eq("r")))
                .thenAnswer(call -> citation(call.getArgument(0)));
    }

    @Test
    void mappedPublicationKeepsEachOriginalAssessmentAndItsSourceProvenance() {
        var result = service.get("round", EVENT, publication.versionId(), "r");
        assertEquals("available", result.status());
        var assessments = result.companies().getFirst().assessments();
        assertEquals(8, assessments.size());
        assertEquals(8, assessments.stream().map(Assessment::id).distinct().count());
        assertEquals(List.of("negative", "negative", "positive", "positive", "undetermined", "undetermined"), assessments.stream()
                .filter(a -> a.label() != null).map(Assessment::label).sorted().toList());
        assertTrue(assessments.stream().allMatch(a -> a.provenance().executionMode().equals("replay")));
        assertTrue(assessments.stream().flatMap(a -> a.evidence().stream()).allMatch(e -> e.quote().equals("retained quote")));
    }

    @Test
    void currentCitationWithdrawalWithholdsEveryDependentAssessmentAcrossLeaves() {
        doReturn(null).when(evidence).readImpactCitation(anyString(), eq("round"), eq(publication.versionId()), eq(NOW), eq("r"));
        var result = service.get("round", EVENT, publication.versionId(), "r");
        assertEquals("unavailable", result.status());
        var assessments = result.companies().getFirst().assessments();
        assertEquals(8, assessments.size());
        assertTrue(assessments.stream().allMatch(a -> a.status().equals("withheld") && a.label() == null && a.evidence().isEmpty()));
    }

    @Test
    void currentAuthorityOutageIsNotReportedAsAnAbsentAssessment() {
        doThrow(new CustomException(ErrorCode.SOURCE_UNAVAILABLE)).when(evidence)
                .readImpactCitation(anyString(), eq("round"), eq(publication.versionId()), eq(NOW), eq("r"));
        assertEquals(ErrorCode.SOURCE_UNAVAILABLE, assertThrows(CustomException.class,
                () -> service.get("round", EVENT, publication.versionId(), "r")).getErrorCode());
    }

    @Test
    void preservedFixtureRoundReportsUnrecordedNativeProof() {
        pin("fixture");
        var result = service.get("round", EVENT, publication.versionId(), "r");
        assertEquals("s3_receipt_not_recorded", result.reason());
        assertTrue(result.companies().isEmpty());
        verifyNoInteractions(evidence);
    }

    private void pin(String kind) {
        var selected = new SelectedGraphVersion(new GraphVersionRecord(publication.versionId(), 4, kind,
                "artifact", "uri", "a".repeat(64), true), NOW, true,
                new BriefingGraphLookup.Basis("round", publication.versionId(), NOW, Map.of(EVENT, List.of("KRX:005930"))));
        when(graphs.read("round", publication.versionId(), NOW, "r"))
                .thenReturn(new PublicGraphReader.Pinned(selected, DisplayGraph.of(publication.snapshot())));
    }

    private EvidenceResponse citation(String id) {
        var span = publication.snapshot().evidence().stream().filter(e -> e.evidenceId().equals(id)).findFirst().orElseThrow();
        return new EvidenceResponse(id, "retained quote", span.start(), span.end(), span.articleId(), span.articleVersion(),
                new EvidenceArticle("Retained article", null, "https://example.invalid/article", NOW), true, List.of(EVENT),
                new Metadata("test", NOW, publication.versionId(), "r", false, List.of()),
                null, null, null, null, null, null);
    }
}
