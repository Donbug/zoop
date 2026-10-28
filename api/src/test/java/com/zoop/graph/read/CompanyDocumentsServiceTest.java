package com.zoop.graph.read;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.atLeastOnce;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.doReturn;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.verify;
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
        var snapshotEvidence = GraphReadFixtures.snapshot("fixture-2026-10-08").evidence();
        when(evidence.read(anyString(), any(), any(), any(), any(), any())).thenAnswer(call -> {
            String evidenceId = call.getArgument(0);
            var span = snapshotEvidence.stream().filter(item -> item.evidenceId().equals(evidenceId)).findFirst().orElseThrow();
            String selectedVersion = call.getArgument(2);
            String requestedAsOf = call.getArgument(3);
            var metadata = requestedAsOf == null ? null : new Metadata("public_graph_snapshot", Instant.parse(requestedAsOf),
                    selectedVersion, "req-1", false, List.of());
            return new EvidenceResponse(evidenceId, "quote", span.start(), span.end(), span.articleId(),
                    span.articleVersion(), null, true, List.of(), metadata, null, span.articleVersion(), null, null, null, null);
        });
        analyses = mock(CompanyDocumentAnalysisReader.class);
        var noAnalysis = new CompanyDocumentAnalysisReader.Visible(null, null,
                new CompanyDocumentAnalysisReader.Status(
                        new CompanyDocumentAnalysisReader.StageStatus("not_requested", null),
                        new CompanyDocumentAnalysisReader.StageStatus("not_requested", null)), null, null);
        when(analyses.read(any(), any(), anyString(), anyString())).thenReturn(noAnalysis);
        when(analyses.read(any(), any(), anyString(), anyString(), eq(true))).thenReturn(noAnalysis);
        when(analyses.read(any(), any(), anyString(), anyString(), eq(false))).thenReturn(noAnalysis);
        service = new CompanyDocumentsService(GraphReadFixtures.reader(NOW, pinned -> DisclosureExclusions.NONE), jdbc,
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
    void articleExclusionHidesOnlyTheExactVersionFromItsPinnedGraph() {
        var exclusions = new DisclosureExclusions(4, Set.of(), Set.of(), Set.of(),
                Set.of(new DisclosureExclusions.ArticleTarget("art-hbm-supply", "v1")));
        service = new CompanyDocumentsService(GraphReadFixtures.reader(NOW, ignored -> exclusions), jdbc,
                registry, evidence, analyses, JsonMapper.builder().build());

        var result = list(null, null, null, null);

        assertTrue(result.items().stream().noneMatch(item -> item.id().equals("art-hbm-supply")));
        assertTrue(result.items().stream().anyMatch(item -> item.id().equals("art-hbm-equip")));
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
        var timeline = new EventListService(GraphReadFixtures.reader(NOW, pinned -> DisclosureExclusions.NONE), jdbc,
                JsonMapper.builder().build()).list(COMPANY, 1, null, null, null, null,
                        "fixture-2026-10-08", asOf);
        Set<String> timelineIds = timeline.items().stream().map(item -> item.id()).collect(Collectors.toSet());
        assertEquals(timeline.metadata().graphVersion(), documents.metadata().graphVersion());
        assertEquals(Instant.parse(timeline.metadata().asOf()), documents.metadata().asOf());
        for (var document : documents.items()) {
            for (var event : document.events()) assertTrue(timelineIds.contains(event.eventId()));
        }
        verify(analyses, atLeastOnce()).read(any(), any(), eq(COMPANY), eq("req-1"), eq(true));
    }

    @Test
    void articleVersionsAreJoinedByExactMentionAndNewestVersionWinsPerArticle() {
        var source = GraphReadFixtures.snapshot("fixture-2026-10-08");
        String articleId = "art-hbm-supply";
        String newEvidenceId = "ev-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
        var newArticle = new PublicGraphSnapshot.Article(articleId, "v2", "새 제목", "https://example.invalid/v2",
                "2026-09-24T01:00:00Z");
        var oldIssue = source.issues().stream().filter(issue -> issue.issueId().equals(GraphReadFixtures.HBM_SUPPLY))
                .findFirst().orElseThrow();
        String newIssueId = "iss-fixture-hbm-supply-v2";
        var newIssue = new PublicGraphSnapshot.Issue(newIssueId, "새 버전 사건", oldIssue.eventTime(), oldIssue.timePrecision(),
                oldIssue.period(), oldIssue.assertionStatus(), oldIssue.action(), oldIssue.target(), oldIssue.geography(),
                oldIssue.geographyPolicyVersion(), List.of(), List.of(articleId), List.of(newEvidenceId),
                List.of(new PublicGraphSnapshot.MentionRef("men-v2", articleId, "v2")), null, "2026-09-24T01:00:00Z");
        var baseRelation = source.relations().stream().filter(relation -> relation.source().equals(oldIssue.issueId())
                && relation.target().equals(COMPANY)).findFirst().orElseThrow();
        var newRelation = new PublicGraphSnapshot.Relation("rel-fixture-v2", baseRelation.relationType(), newIssueId,
                baseRelation.target(), baseRelation.role(), baseRelation.assertionStatus(), List.of(newEvidenceId), List.of());
        var snapshot = new PublicGraphSnapshot(source.snapshotFormat(), source.versionId(), source.sourceBundleId(),
                source.companies(), java.util.stream.Stream.concat(source.issues().stream(), java.util.stream.Stream.of(newIssue)).toList(),
                java.util.stream.Stream.concat(source.relations().stream(), java.util.stream.Stream.of(newRelation)).toList(),
                java.util.stream.Stream.concat(source.articles().stream(), java.util.stream.Stream.of(newArticle)).toList(),
                java.util.stream.Stream.concat(source.evidence().stream(), java.util.stream.Stream.of(
                        new PublicGraphSnapshot.Evidence(newEvidenceId, articleId, "v2", 0, 40))).toList());
        PublicGraphReader reader = mock(PublicGraphReader.class);
        when(reader.read(any(), any(), any())).thenReturn(new PublicGraphReader.Pinned(
                new SelectedGraphVersion(GraphReadFixtures.record("fixture-2026-10-08", true), NOW, false),
                DisplayGraph.of(snapshot)));
        when(registry.findArticle(articleId)).thenReturn(Optional.of(new ArticleRow(articleId, "news", "test", "v2", "available")));
        when(registry.findVersion(articleId, "v2")).thenReturn(Optional.of(new VersionRow(articleId, "v2", "새 제목",
                "publisher-v2", "https://example.invalid/v2", Instant.parse("2026-09-24T01:00:00Z"), null,
                "datetime", null, null, NOW)));
        EvidenceResponse visibleV2 = new EvidenceResponse(newEvidenceId, "새 인용", 0, 40, articleId, "v2", null,
                true, List.of(newIssueId), null, null, "v2", null, null, null, null);
        doReturn(visibleV2).when(evidence).read(eq(newEvidenceId), any(), any(), any(), any(), any());
        service = new CompanyDocumentsService(reader, jdbc, registry, evidence, analyses, JsonMapper.builder().build());

        var result = list(null, null, null, null);
        var document = result.items().stream().filter(item -> item.id().equals(articleId)).findFirst().orElseThrow();
        assertEquals("v2", document.documentVersion());
        assertEquals("새 제목", document.title());
        assertEquals(List.of(newIssueId), document.events().stream().map(CompanyDocumentsService.EventRef::eventId).toList());
        assertEquals(List.of(newEvidenceId), document.quotes().stream().map(CompanyDocumentsService.Quote::evidenceId).toList());

        when(reader.read(any(), any(), any())).thenReturn(new PublicGraphReader.Pinned(
                new SelectedGraphVersion(GraphReadFixtures.record("fixture-2026-10-08", true), NOW, false),
                DisplayGraph.of(snapshot), new DisclosureExclusions(3, Set.of(), Set.of(), Set.of(),
                        Set.of(new DisclosureExclusions.ArticleTarget(articleId, "v2")))));
        var withNewestVersionExcluded = list(null, null, null, null).items().stream()
                .filter(item -> item.id().equals(articleId)).findFirst().orElseThrow();
        assertEquals("v1", withNewestVersionExcluded.documentVersion(),
                "only the exact excluded article version is hidden; the other eligible version remains selectable");
    }

    @Test
    void deniedSourceGrantHidesDocumentAndRegistryFailurePropagates() {
        var spans = GraphReadFixtures.snapshot("fixture-2026-10-08").evidence().stream()
                .filter(span -> span.articleId().equals("art-hbm-supply")).toList();
        spans.forEach(span -> doThrow(new CustomException(ErrorCode.EVIDENCE_UNAVAILABLE))
                .when(evidence).read(eq(span.evidenceId()), any(), any(), any(), any(), any()));
        assertTrue(list(null, null, null, null).items().stream().noneMatch(item -> item.id().equals("art-hbm-supply")));

        doThrow(new CustomException(ErrorCode.SOURCE_UNAVAILABLE)).when(evidence)
                .read(eq(spans.get(0).evidenceId()), any(), any(), any(), any(), any());
        assertEquals(ErrorCode.SOURCE_UNAVAILABLE, assertThrows(CustomException.class,
                () -> list(null, null, null, null)).getErrorCode());
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
    @Test
    void roundDocumentsAndCursorKeepOnlySelectedIssuesAndRejectAnotherRound() {
        var basis = new com.zoop.graph.version.BriefingGraphLookup.Basis("round", "fixture-2026-10-08", NOW,
                java.util.Map.of(GraphReadFixtures.HBM_SUPPLY, List.of(COMPANY), GraphReadFixtures.HBM_EQUIP, List.of(HANMI)));
        var reader = new PublicGraphReader(new com.zoop.graph.version.GraphVersionSelector(GraphReadFixtures.repository(),
                java.time.Clock.fixed(NOW, java.time.ZoneOffset.UTC), (id, request) -> basis),
                new com.zoop.graph.snapshot.FixtureGraphSnapshotStore(getClass().getClassLoader()), pinned -> DisclosureExclusions.NONE);
        service = new CompanyDocumentsService(reader, jdbc, registry, evidence, analyses, JsonMapper.builder().build());
        var first = service.list(COMPANY, null, null, null, "round", null, null, null, 1, "req-1");
        assertNotNull(first.nextCursor());
        var second = service.list(COMPANY, null, null, null, "round", null, null, first.nextCursor(), 1, "req-1");
        assertEquals(first.metadata().asOf(), second.metadata().asOf());
        assertTrue(java.util.stream.Stream.concat(first.items().stream(), second.items().stream())
                .flatMap(d -> d.events().stream()).allMatch(e -> basis.keyIssueIds().contains(e.eventId())));
        assertEquals(ErrorCode.INVALID_CURSOR, assertThrows(CustomException.class, () ->
                service.list(COMPANY, null, null, null, "other", null, null, first.nextCursor(), 1, "req-1")).getErrorCode());
        assertEquals(ErrorCode.INVALID_CURSOR, assertThrows(CustomException.class, () ->
                service.list(COMPANY, null, null, null, null, null, null, first.nextCursor(), 1, "req-1")).getErrorCode());
        verify(evidence, atLeastOnce()).read(anyString(), eq("round"), eq(basis.graphVersion()), eq(NOW.toString()), eq(COMPANY), eq("req-1"));
    }

}
