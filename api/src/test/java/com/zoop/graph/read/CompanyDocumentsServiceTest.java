package com.zoop.graph.read;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.doReturn;
import static org.mockito.Mockito.when;

import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.common.response.Metadata;
import com.zoop.document.evidence.service.EvidenceService;
import com.zoop.document.evidence.dto.EvidenceResponse;
import com.zoop.document.repository.ArticleRow;
import com.zoop.document.repository.DocumentRegistryRepository;
import com.zoop.document.repository.VersionRow;
import com.zoop.graph.snapshot.PublicGraphSnapshot;
import com.zoop.graph.version.SelectedGraphVersion;
import java.time.Instant;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import java.util.Set;
import java.util.stream.Collectors;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.jdbc.core.namedparam.SqlParameterSource;
import tools.jackson.databind.json.JsonMapper;

class CompanyDocumentsServiceTest {
    private static final String COMPANY = "KRX:000660";
    private static final String HANMI = "KRX:042700";
    private static final Instant NOW = Instant.parse("2026-10-16T12:00:00Z");
    private CompanyDocumentsService service;
    private EvidenceService evidence;
    private NamedParameterJdbcTemplate jdbc;
    private DocumentRegistryRepository registry;
    private CompanyDocumentAnalysisReader analyses;

    @BeforeEach
    void setUp() {
        jdbc = mock(NamedParameterJdbcTemplate.class);
        when(jdbc.queryForObject(anyString(), any(SqlParameterSource.class), eq(Integer.class))).thenReturn(1);
        registry = mock(DocumentRegistryRepository.class);
        var snapshot = GraphReadFixtures.snapshot("fixture-2026-10-08");
        for (var item : snapshot.articles()) {
            when(registry.findArticle(item.articleId())).thenReturn(Optional.of(
                    new ArticleRow(item.articleId(), "news", "test", item.version(), "available")));
            boolean day = item.publishedAt() != null && item.publishedAt().length() == 10;
            when(registry.findVersion(item.articleId(), item.version())).thenReturn(Optional.of(new VersionRow(
                    item.articleId(), item.version(), item.title(), "publisher", item.url(),
                    day || item.publishedAt() == null ? null : Instant.parse(item.publishedAt()),
                    day ? LocalDate.parse(item.publishedAt()) : null,
                    day ? "day" : item.publishedAt() == null ? "unknown" : "datetime", null, null, NOW)));
        }
        evidence = mock(EvidenceService.class);
        when(evidence.read(anyString(), any(), any(), any(), any(), any()))
                .thenThrow(new CustomException(ErrorCode.EVIDENCE_UNAVAILABLE));
        analyses = mock(CompanyDocumentAnalysisReader.class);
        when(analyses.read(any(), any(), anyString(), anyString())).thenReturn(
                new CompanyDocumentAnalysisReader.Visible(null, null,
                        new CompanyDocumentAnalysisReader.Status(
                                new CompanyDocumentAnalysisReader.StageStatus("not_requested", null),
                                new CompanyDocumentAnalysisReader.StageStatus("not_requested", null)), null, null));
        service = new CompanyDocumentsService(GraphReadFixtures.reader(NOW, () -> DisclosureExclusions.NONE), jdbc,
                registry, evidence, analyses, JsonMapper.builder().build());
    }

    private CompanyDocumentsService.Response list(String from, String to, String cursor, Integer limit) {
        return service.list(COMPANY, null, from, to, null, null, null, cursor, limit, "req-1");
    }

    @Test
    void directCompanyDocumentsAreDistinctAndSorted() {
        var result = list(null, null, null, null);
        List<String> ids = result.items().stream().map(CompanyDocumentsService.Document::id).toList();
        assertEquals(ids.size(), ids.stream().distinct().count());
        assertEquals("fixture-2026-10-08", result.metadata().graphVersion());
        assertEquals(NOW, result.metadata().asOf());
        assertNull(result.nextCursor());
        assertNotNull(result.items().get(0).events());
    }

    @Test
    void cursorKeepsTheFirstPageVersionAndTime() {
        var first = list(null, null, null, 1);
        List<String> ids = new ArrayList<>(first.items().stream().map(CompanyDocumentsService.Document::id).toList());
        String cursor = first.nextCursor();
        assertNotNull(cursor);
        while (cursor != null) {
            var next = list(null, null, cursor, null);
            assertEquals(first.metadata().graphVersion(), next.metadata().graphVersion());
            assertEquals(first.metadata().asOf(), next.metadata().asOf());
            ids.addAll(next.items().stream().map(CompanyDocumentsService.Document::id).toList());
            cursor = next.nextCursor();
        }
        assertEquals(list(null, null, null, null).items().stream().map(CompanyDocumentsService.Document::id).toList(), ids);
    }

    @Test
    void dateOnlyPublicationOverlapsItsWholeKstDay() {
        // HANMI's direct INVOLVES edge was already visible that day. HYNIX's structural basis was verified later.
        var result = service.list(HANMI, null, "2026-09-25T12:00:00+09:00",
                "2026-09-25T12:00:00+09:00", null, null, null, null, null, "req-1");
        assertEquals(List.of("art-hbm-equip"), result.items().stream().map(CompanyDocumentsService.Document::id).toList());
        assertNull(result.items().get(0).publishedAt());
    }

    @Test
    void toExcludesAnIssueUntilItsCompanyLinkWasVerified() {
        assertEquals(List.of(), list("2026-09-25", "2026-09-25", null, null).items().stream()
                .map(CompanyDocumentsService.Document::id).filter("art-hbm-equip"::equals).toList());
        assertEquals(List.of("art-hbm-equip"), list("2026-09-25", "2026-09-29", null, null).items()
                .stream().map(CompanyDocumentsService.Document::id).toList());
    }

    @Test
    void boundedRangeExcludesUnknownPublicationTime() {
        var source = GraphReadFixtures.snapshot("fixture-2026-10-08");
        var changedArticles = source.articles().stream().map(article -> article.articleId().equals("art-hbm-supply")
                ? new PublicGraphSnapshot.Article(article.articleId(), article.version(), article.title(), article.url(), null)
                : article).toList();
        var changedIssues = source.issues().stream().map(issue -> issue.issueId().equals(GraphReadFixtures.HBM_SUPPLY)
                ? new PublicGraphSnapshot.Issue(issue.issueId(), issue.label(), issue.eventTime(), issue.timePrecision(),
                        issue.period(), issue.assertionStatus(), issue.action(), issue.target(), issue.geography(),
                        issue.geographyPolicyVersion(), issue.geographyEvidenceIds(), issue.articleIds(), issue.evidenceIds(),
                        issue.mentions(), issue.representativeMentionId(), null)
                : issue).toList();
        var snapshot = new PublicGraphSnapshot(source.snapshotFormat(), source.versionId(), source.sourceBundleId(),
                source.companies(), changedIssues, source.relations(), changedArticles, source.evidence());
        PublicGraphReader reader = mock(PublicGraphReader.class);
        when(reader.read(any(), any(), any())).thenReturn(new PublicGraphReader.Pinned(
                new SelectedGraphVersion(GraphReadFixtures.record("fixture-2026-10-08", true), NOW, false),
                DisplayGraph.of(snapshot)));
        service = new CompanyDocumentsService(reader, jdbc, registry, evidence, analyses, JsonMapper.builder().build());
        assertEquals(List.of("art-hbm-supply"), list(null, null, null, null).items().stream()
                .map(CompanyDocumentsService.Document::id).filter("art-hbm-supply"::equals).toList());
        assertEquals(List.of(), list("2026-09-22", "2026-09-22", null, null).items());
    }

    @Test
    void exactToInstantIsIncludedAndLaterDocumentsAreExcluded() {
        var result = list("2026-09-22T01:00:00Z", "2026-09-22T01:00:00Z", null, null);
        assertEquals(List.of("art-hbm-supply"), result.items().stream().map(CompanyDocumentsService.Document::id).toList());
        assertEquals(List.of(), list(null, "2026-09-22T00:59:59Z", null, null).items());
    }

    @Test
    void onlyEvidenceTheEvidenceEndpointWouldServeIsQuoted() {
        var span = GraphReadFixtures.snapshot("fixture-2026-10-08").evidence().stream()
                .filter(item -> item.articleId().equals("art-hbm-supply")).findFirst().orElseThrow();
        EvidenceResponse visible = mock(EvidenceResponse.class);
        when(visible.articleId()).thenReturn("art-hbm-supply");
        when(visible.articleVersion()).thenReturn("v1");
        when(visible.eventIds()).thenReturn(List.of(GraphReadFixtures.HBM_SUPPLY));
        when(visible.quote()).thenReturn("검증된 인용");
        when(visible.quoteVerified()).thenReturn(true);
        doReturn(visible).when(evidence).read(eq(span.evidenceId()), any(), any(), any(), any(), any());
        var document = list("2026-09-22", "2026-09-22", null, null).items().get(0);
        assertEquals(List.of(span.evidenceId()), document.quotes().stream()
                .map(CompanyDocumentsService.Quote::evidenceId).toList());
        assertEquals("검증된 인용", document.quotes().get(0).quote());
    }

    @Test
    void aPinnedDocumentOnlyExposesQuotesFromTheSameEvidenceSnapshot() {
        var span = GraphReadFixtures.snapshot("fixture-2026-10-08").evidence().stream()
                .filter(item -> item.articleId().equals("art-hbm-supply")).findFirst().orElseThrow();
        EvidenceResponse visible = mock(EvidenceResponse.class);
        when(visible.articleId()).thenReturn("art-hbm-supply");
        when(visible.articleVersion()).thenReturn("v1");
        when(visible.eventIds()).thenReturn(List.of(GraphReadFixtures.HBM_SUPPLY));
        when(visible.metadata()).thenReturn(new Metadata("public_graph_snapshot", NOW,
                "fixture-2026-10-08", "req-1", false, List.of()));
        doReturn(visible).when(evidence).read(eq(span.evidenceId()), any(), any(), any(), any(), any());
        var matching = service.list(COMPANY, null, null, null, null, "fixture-2026-10-08", NOW.toString(),
                null, null, "req-1");
        assertEquals(List.of(span.evidenceId()), matching.items().stream()
                .filter(item -> item.id().equals("art-hbm-supply")).findFirst().orElseThrow().quotes().stream()
                .map(CompanyDocumentsService.Quote::evidenceId).toList());
        when(visible.metadata()).thenReturn(new Metadata("public_graph_snapshot", NOW.plusSeconds(1),
                "fixture-2026-10-08", "req-1", false, List.of()));
        var mismatched = service.list(COMPANY, null, null, null, null, "fixture-2026-10-08", NOW.toString(),
                null, null, "req-1");
        assertEquals(List.of(), mismatched.items().stream()
                .filter(item -> item.id().equals("art-hbm-supply")).findFirst().orElseThrow().quotes());
    }

    @Test
    void documentEventIdsMatchTheSamePinnedCompanyTimeline() {
        String asOf = NOW.toString();
        var documents = service.list(COMPANY, null, null, null, null, "fixture-2026-10-08", asOf,
                null, null, "req-1");
        var timeline = new EventListService(GraphReadFixtures.reader(NOW, () -> DisclosureExclusions.NONE), jdbc,
                JsonMapper.builder().build()).list(COMPANY, 1, null, null, null, null,
                        "fixture-2026-10-08", asOf);
        Set<String> timelineIds = timeline.items().stream().map(item -> item.id()).collect(Collectors.toSet());
        assertEquals(timeline.metadata().graphVersion(), documents.metadata().graphVersion());
        assertEquals(Instant.parse(timeline.metadata().asOf()), documents.metadata().asOf());
        for (var document : documents.items()) {
            for (var event : document.events()) assertTrue(timelineIds.contains(event.eventId()));
        }
    }

    @Test
    void cursorCannotBeUsedWithDifferentFilters() {
        String cursor = list(null, null, null, 1).nextCursor();
        assertEquals(ErrorCode.INVALID_CURSOR, assertThrows(CustomException.class,
                () -> list("2026-09-01", null, cursor, 1)).getErrorCode());
    }

    @Test
    void withdrawingAnEarlierDocumentDoesNotSkipTheNextPage() {
        var original = list(null, null, null, null).items().stream().map(CompanyDocumentsService.Document::id).toList();
        var first = list(null, null, null, 1);
        String firstId = first.items().get(0).id();
        when(registry.findArticle(firstId)).thenReturn(Optional.of(
                new ArticleRow(firstId, "news", "test", "v1", "withheld")));
        var second = list(null, null, first.nextCursor(), 1);
        assertEquals(original.get(1), second.items().get(0).id());
    }

    @Test
    void roundAndBadCursorDoNotFallBackToLatest() {
        assertEquals(ErrorCode.VERSION_UNAVAILABLE, assertThrows(CustomException.class,
                () -> service.list(COMPANY, null, null, null, "brf-1", null, null, null, 1, "req"))
                .getErrorCode());
        assertEquals(ErrorCode.INVALID_CURSOR, assertThrows(CustomException.class,
                () -> list(null, null, "not-a-cursor", 1)).getErrorCode());
    }

    @Test
    void missingCompanyAndInvalidKindHaveContractErrors() {
        when(jdbc.queryForObject(anyString(), any(SqlParameterSource.class), eq(Integer.class))).thenReturn(0);
        assertEquals(ErrorCode.RESOURCE_NOT_FOUND, assertThrows(CustomException.class,
                () -> list(null, null, null, null)).getErrorCode());
        assertEquals(ErrorCode.INVALID_REQUEST, assertThrows(CustomException.class,
                () -> service.list(COMPANY, "filing", null, null, null, null, null, null, null, "req"))
                .getErrorCode());
    }
}
