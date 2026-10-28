package com.zoop.graph.read;

import static com.zoop.graph.read.GraphReadFixtures.AI_ACCEL;
import static com.zoop.graph.read.GraphReadFixtures.HBM_EQUIP;
import static com.zoop.graph.read.GraphReadFixtures.HBM_SUPPLY;
import static com.zoop.graph.read.GraphReadFixtures.HYNIX;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.common.json.StrictJson;
import com.zoop.document.evidence.service.EvidenceService;
import com.zoop.document.repository.DocumentRegistryRepository;
import com.zoop.document.repository.VersionRow;
import com.zoop.graph.importer.MentionIds;
import com.zoop.graph.read.dto.EventDetail;
import com.zoop.graph.read.dto.EventDetail.MentionOut;
import com.zoop.graph.snapshot.PublicGraphSnapshot;
import com.zoop.graph.snapshot.PublicGraphSnapshot.Issue;
import com.zoop.graph.snapshot.PublicGraphSnapshot.MentionRef;
import com.zoop.graph.version.GraphVersionRecord;
import com.zoop.graph.version.GraphVersionRepository;
import com.zoop.graph.version.GraphVersionSelector;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Optional;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

class EventDetailServiceTest {
    private static final Instant NOW = Instant.parse("2026-10-16T00:00:00Z");
    private static final String EUV = "iss-fixture-euv-export";
    private static final String EUV_ARTICLE = "art-euv-export";
    private static final String VISIBLE_EVIDENCE = "ev-63f463a0464041f09503f04f07ff1f660a0a5628a3507b4732a44ec95cbc5bd8";
    private static final String M1 = MentionIds.of(EUV_ARTICLE, "v1", "m1");
    private static final String M2 = MentionIds.of(EUV_ARTICLE, "v1", "m2");

    private EvidenceService receipts;
    private DocumentRegistryRepository registry;

    @BeforeEach
    void setUp() {
        receipts = mock(EvidenceService.class);
        registry = mock(DocumentRegistryRepository.class);
        when(registry.findVersion(anyString(), anyString())).thenReturn(Optional.empty());
    }

    private EventDetailService fixtures() {
        return new EventDetailService(GraphReadFixtures.reader(NOW, pinned -> DisclosureExclusions.NONE), receipts, registry);
    }

    // ---- synthetic fixture version: snapshot facts only --------------------------------------------------------------

    @Test
    void aFixtureEventCarriesItsSnapshotFactsWithoutReadingAReceipt() {
        EventDetail detail = fixtures().get(EUV, null, null, null, "req-1");

        assertEquals(EUV, detail.id());
        assertEquals("2026-09", detail.eventTime());
        assertEquals("month", detail.timePrecision());
        assertEquals("2026Q4", detail.period());
        assertEquals(3, detail.evidenceIds().size());
        assertEquals(List.of(), detail.mentions(), "a fixture has no receipt to read mentions from");
        assertEquals(List.of(), detail.fieldDecisions());
        assertEquals(List.of(EUV_ARTICLE), detail.articles().stream().map(EventDetail.ArticleOut::id).toList());
        assertNull(detail.articles().get(0).relationType(), "no mentions, so no reporting relation can be told");
        assertEquals("fixture-2026-10-08", detail.metadata().graphVersion());
        verifyNoInteractions(receipts);
    }

    @Test
    void relationsAndCompaniesComeFromTheIssuesEdgesWithTheGraphsEdgeIds() {
        EventDetail detail = fixtures().get(EUV, null, null, null, "req-1");

        assertEquals(3, detail.relations().size());
        assertTrue(detail.relations().stream().allMatch(r -> r.edgeId().equals(
                DisplayGraph.edgeId(r.relationType(), r.source(), r.target()))));
        assertEquals(List.of("INVOLVES", "STRUCTURALLY_RELATED_TO", "STRUCTURALLY_RELATED_TO"),
                detail.companies().stream().map(EventDetail.CompanyLink::relationType).toList());
        EventDetail.CompanyLink involved = detail.companies().get(0);
        assertTrue(involved.roleUnconfirmed(), "the handoff produces no confirmed roles");
        assertFalse(detail.companies().get(1).roleUnconfirmed(), "no role, nothing to confirm");
    }

    @Test
    void followsPointsBackToTheEarlierEventAndForwardToTheLaterOne() {
        EventDetail later = fixtures().get(HBM_EQUIP, null, null, null, "r");
        EventDetail earlier = fixtures().get(HBM_SUPPLY, null, null, null, "r");

        assertEquals(List.of(HBM_SUPPLY), later.follows().previous().stream().map(EventDetail.FollowRef::id).toList());
        assertEquals(List.of(), later.follows().next());
        assertEquals(List.of(HBM_EQUIP), earlier.follows().next().stream().map(EventDetail.FollowRef::id).toList());
    }

    @Test
    void summaryIsUnavailableApprovalIsNullAndTheResponseSaysWhy() {
        EventDetail detail = fixtures().get(EUV, null, null, null, "r");

        assertEquals(new EventDetail.Unavailable("unavailable", EventDetailService.SUMMARY_UNAVAILABLE), detail.summary());
        assertNull(detail.approval());
        assertTrue(detail.metadata().partial());
        assertEquals("summary", detail.metadata().failures().get(0).section());
    }

    @Test
    void aFixtureSourceSupportCountsVisibleArticlesAndKnowsNoLineage() {
        EventDetail.SourceSupportOut support = fixtures().get(EUV, null, null, null, "r").sourceSupport();

        assertEquals(1, support.articleCount());
        assertNull(support.knownLineageCount(), "unknown, not zero");
        assertEquals(List.of(EUV_ARTICLE), support.unknownLineageArticles());
        assertNull(support.independentSourceCount());
    }

    @Test
    void anEventMissingFromThePinnedVersionIsNotFoundAndNeverLookedUpElsewhere() {
        // ai-accel exists only in the 10-08 version; asOf pins 10-01.
        var error = assertThrows(CustomException.class,
                () -> fixtures().get(AI_ACCEL, null, null, "2026-10-05T00:00:00Z", "r"));
        assertEquals(ErrorCode.RESOURCE_NOT_FOUND, error.getErrorCode());
        assertEquals(ErrorCode.RESOURCE_NOT_FOUND, assertThrows(CustomException.class,
                () -> fixtures().get(HYNIX, null, null, null, "r")).getErrorCode(), "a company id is not an event");
    }

    @Test
    void selectorRulesPassThrough() {
        assertEquals(ErrorCode.VERSION_UNAVAILABLE, assertThrows(CustomException.class,
                () -> fixtures().get(EUV, "brf-2026-09-17-morning", null, null, "r")).getErrorCode());
        assertEquals(ErrorCode.INVALID_REQUEST, assertThrows(CustomException.class,
                () -> fixtures().get(EUV, null, null, "yesterday", "r")).getErrorCode());
    }

    @Test
    void anExcludedEventIsNotFound() {
        var service = new EventDetailService(GraphReadFixtures.reader(NOW,
                pinned -> new DisclosureExclusions(1, java.util.Set.of(EUV), java.util.Set.of(), java.util.Set.of())),
                receipts, registry);
        assertEquals(ErrorCode.RESOURCE_NOT_FOUND,
                assertThrows(CustomException.class, () -> service.get(EUV, null, null, null, "r")).getErrorCode());
    }

    // ---- imported version: receipt mentions, verdicts and support -------------------------------------------------------

    @Test
    void anImportedEventShowsReceiptMentionsWithOperatorHeldValuesRemoved() {
        EventDetail detail = imported(bundle(false)).get(EUV, null, null, null, "req-i");

        assertEquals(List.of(M1, M2), detail.mentions().stream().map(MentionOut::mentionId).toList());
        MentionOut allowed = detail.mentions().get(0);
        assertEquals("2026-09", allowed.eventTime(), "an ALLOW verdict keeps the value");
        assertEquals("2026Q4", allowed.period());
        assertEquals(List.of(VISIBLE_EVIDENCE), allowed.evidenceIds());
        MentionOut held = detail.mentions().get(1);
        assertNull(held.eventTime(), "HOLD on eventTime");
        assertEquals("unknown", held.timePrecision());
        assertNull(held.period(), "REJECT on period");
        assertFalse(detail.toString().contains("2026-10-HELD"), "a held value never leaves");
        assertFalse(detail.toString().contains("2027-REJECTED"), "a rejected value never leaves");
    }

    @Test
    void knownReceiptFormatsKeepEventMetadataAndTheSameFieldAndHeadGates() {
        for (String schema : List.of("zoop-graph-handoff-bundle-5", "zoop-graph-handoff-bundle-6",
                "zoop-graph-handoff-bundle-7")) {
            String json = bundle(false).node().toString().replace("zoop-graph-handoff-bundle-5", schema);
            EventDetailService service = imported(StrictJson.parseObject(json));
            EventDetail detail = service.get(EUV, null, "gv-imported", null, "req-compatible");

            assertEquals(EUV, detail.id(), schema);
            assertEquals("gv-imported", detail.metadata().graphVersion(), schema);
            assertEquals("req-compatible", detail.metadata().requestId(), schema);
            assertEquals(List.of(M1, M2), detail.mentions().stream().map(MentionOut::mentionId).toList(), schema);
            assertEquals(1, detail.sourceSupport().articleCount(), schema);
            assertNull(detail.mentions().get(1).eventTime(), schema);
            assertNull(detail.mentions().get(1).period(), schema);
            assertEquals(List.of(new EventDetail.FieldOutcome("eventTime", "HOLD", "unstated"),
                    new EventDetail.FieldOutcome("period", "REJECT", "contradicted")),
                    detail.fieldDecisions().get(1).outcomes(), schema);
            assertNull(detail.approval(), schema);
            assertEquals(new EventDetail.Unavailable("unavailable", EventDetailService.SUMMARY_UNAVAILABLE),
                    detail.summary(), schema);
            assertEquals("SUMMARY_NOT_PRODUCED", detail.metadata().failures().get(0).code(), schema);

            when(receipts.shownNow(eq(VISIBLE_EVIDENCE), anyString(), any(), anyString())).thenReturn(false);
            assertEquals(ErrorCode.RESOURCE_NOT_FOUND, assertThrows(CustomException.class,
                    () -> service.get(EUV, null, "gv-imported", null, "req-withdrawn")).getErrorCode(), schema);
        }
    }

    @Test
    void participantsKeepS2TextAndOnlyAMappedCompanyId() {
        MentionOut first = imported(bundle(false)).get(EUV, null, null, null, "r").mentions().get(0);

        assertEquals("NASDAQ:ASML", first.participants().get(0).companyId());
        assertTrue(first.participants().get(0).roleUnconfirmed());
        assertNull(first.participants().get(1).companyId());
        assertFalse(first.participants().get(1).roleUnconfirmed());
    }

    @Test
    void fieldDecisionsListVerdictsPerMentionWithoutTheJudgedValues() {
        List<EventDetail.FieldDecisionOut> decisions = imported(bundle(false)).get(EUV, null, null, null, "r").fieldDecisions();

        assertEquals(List.of(M1, M2), decisions.stream().map(EventDetail.FieldDecisionOut::mentionId).toList());
        assertNull(decisions.get(0).candidateId());
        assertEquals(List.of(new EventDetail.FieldOutcome("eventTime", "HOLD", "unstated"),
                new EventDetail.FieldOutcome("period", "REJECT", "contradicted")), decisions.get(1).outcomes());
    }

    @Test
    void articleRelationAndPublisherComeFromMentionsAndTheStoredVersion() {
        when(registry.findVersion(EUV_ARTICLE, "v1")).thenReturn(Optional.of(new VersionRow(EUV_ARTICLE, "v1", "t",
                "합성일보", "u", null, null, "datetime", "raw", "text", NOW)));

        EventDetail.ArticleOut reporting = imported(bundle(false)).get(EUV, null, null, null, "r").articles().get(0);
        EventDetail.ArticleOut background = imported(bundle(true)).get(EUV, null, null, null, "r").articles().get(0);

        assertEquals("합성일보", reporting.publisher());
        assertEquals("REPORTS", reporting.relationType(), "one mention reports the event");
        assertEquals("PROVIDES_BACKGROUND", background.relationType(), "every mention is background");
    }

    @Test
    void sourceSupportIsCopiedFromTheHandoffWhenAllItsArticlesAreVisible() {
        EventDetail.SourceSupportOut support = imported(bundle(false)).get(EUV, null, null, null, "r").sourceSupport();

        assertEquals(new EventDetail.SourceSupportOut(1, 0, List.of(EUV_ARTICLE), null, List.of()), support);
    }

    @Test
    void whenAsOfHidArticlesTheHandoffCountedOnlyTheVisiblePartOfSourceSupportIsShown() {
        // The handoff counted a second article (art-hidden) that this read no longer shows.
        String counted = bundle(false).node().toString()
                .replace("\"articleCount\":1", "\"articleCount\":2")
                .replace("\"unknownLineageArticles\":[\"" + EUV_ARTICLE + "\"]",
                        "\"unknownLineageArticles\":[\"" + EUV_ARTICLE + "\",\"art-hidden\"]")
                .replace("\"duplicateGroups\":[]", "\"duplicateGroups\":[[\"" + EUV_ARTICLE + "\",\"art-hidden\"]]");

        EventDetail.SourceSupportOut support = imported(StrictJson.parseObject(counted))
                .get(EUV, null, null, null, "r").sourceSupport();

        assertEquals(1, support.articleCount());
        assertNull(support.knownLineageCount(), "it depended on the hidden article");
        assertEquals(List.of(EUV_ARTICLE), support.unknownLineageArticles());
        assertNull(support.independentSourceCount());
        assertEquals(List.of(), support.duplicateGroups(), "a group of one is no duplicate");
    }

    @Test
    void aMatchingArticleCountNeverLetsAHiddenListedArticleThrough() {
        // Same count as the visible articles, yet the lists name art-hidden, which this read does not show.
        String counted = bundle(false).node().toString()
                .replace("\"knownLineageCount\":0", "\"knownLineageCount\":1")
                .replace("\"unknownLineageArticles\":[\"" + EUV_ARTICLE + "\"]", "\"unknownLineageArticles\":[\"art-hidden\"]")
                .replace("\"independentSourceCount\":null", "\"independentSourceCount\":1")
                .replace("\"duplicateGroups\":[]", "\"duplicateGroups\":[[\"" + EUV_ARTICLE + "\",\"art-hidden\"]]");

        EventDetail.SourceSupportOut support = imported(StrictJson.parseObject(counted))
                .get(EUV, null, null, null, "r").sourceSupport();

        assertEquals(new EventDetail.SourceSupportOut(1, null, List.of(), null, List.of()), support,
                "no hidden id in either list, and the counts that may include it are unknown");
    }

    @Test
    void anUnreadableReceiptIsUnavailable() {
        when(receipts.graphImportBundle(anyString(), anyString()))
                .thenThrow(new CustomException(ErrorCode.SOURCE_UNAVAILABLE));
        CustomException failure = assertThrows(CustomException.class,
                () -> imported(null).get(EUV, null, null, null, "r"));
        assertEquals(ErrorCode.SOURCE_UNAVAILABLE, failure.getErrorCode());
        assertTrue(failure.isRetryable());
    }

    @Test
    void aMalformedPinnedReceiptIsUnavailableWithoutRetryingIt() {
        when(receipts.graphImportBundle(anyString(), anyString()))
                .thenThrow(new CustomException(ErrorCode.SOURCE_UNAVAILABLE, false));

        CustomException failure = assertThrows(CustomException.class,
                () -> imported(null).get(EUV, null, null, null, "r"));

        assertEquals(ErrorCode.SOURCE_UNAVAILABLE, failure.getErrorCode());
        assertFalse(failure.isRetryable());
    }

    @Test
    void aReceiptThatDoesNotKnowTheIssueIsUnavailable() {
        EventDetailService service = imported(StrictJson.parseObject(
                "{\"schemaVersion\":\"zoop-graph-handoff-bundle-5\",\"issues\":[]}"));
        assertEquals(ErrorCode.SOURCE_UNAVAILABLE, assertThrows(CustomException.class,
                () -> service.get(EUV, null, null, null, "r")).getErrorCode());
    }

    // ---- current rights, exclusions, article versions and old receipts (PR #278 review) --------------------------------

    private static final String TSM_EVIDENCE = "ev-2efb74012127277470344892d9ba439c77a42180b4538d86c319d643bfefbc62";
    private static final String SAMSUNG_EVIDENCE = "ev-d2cb5acbc5dc430d53378e9dcdc47549436b0a7c48011ef79314fd1e188cd50e";
    private static final String EQUIP_M = MentionIds.of("art-hbm-equip", "v1", "e1");
    private static final String SUPPLY_M = MentionIds.of("art-hbm-supply", "v1", "s1");
    private static final String[] EQUIP_EV = {"ev-e194f2923147a4df39496036f54d7a335eaea21b9706941a05417c2aa2c7833c",
            "ev-fd9d18853fde470f24184b7db11e534270c580072fc0ca877323825a751c94bf"};
    private static final String[] SUPPLY_EV = {"ev-912843a071ee90c12ee7e909c65f06ce748d2a35c7c29c6c871faac130e4f395",
            "ev-bb3008cb36e9b51c0d2fd77af059259332b1887cc04862e185a496c3dcc9e421"};

    @Test
    void aWithdrawnCitationTakesItsRelationAndCompanyButNotTheEvent() {
        EventDetailService service = imported(bundle(false));
        when(receipts.shownNow(eq(TSM_EVIDENCE), anyString(), any(), anyString())).thenReturn(false);

        EventDetail detail = service.get(EUV, null, null, null, "r");

        assertFalse(detail.evidenceIds().contains(TSM_EVIDENCE));
        assertTrue(detail.relations().stream().noneMatch(r -> r.target().equals("NYSE:TSM")));
        assertTrue(detail.companies().stream().noneMatch(c -> c.id().equals("NYSE:TSM")));
        assertEquals(List.of(M1, M2), detail.mentions().stream().map(MentionOut::mentionId).toList(),
                "their own citation is still readable");
    }

    @Test
    void whenTheRepresentativeMentionsEvidenceIsWithdrawnAtAPastAsOfTheEventIsNotFound() {
        EventDetailService service = imported(bundle(false));
        // Both mentions cite only VISIBLE_EVIDENCE (the other id is not in this version): withdrawing it leaves no head.
        when(receipts.shownNow(eq(VISIBLE_EVIDENCE), anyString(), any(), anyString())).thenReturn(false);
        Instant past = Instant.parse("2026-10-01T00:00:00Z");

        assertEquals(ErrorCode.RESOURCE_NOT_FOUND, assertThrows(CustomException.class,
                () -> service.get(EUV, null, null, "2026-10-01T00:00:00Z", "r")).getErrorCode());
        // Judged at the pinned version and the requested asOf, the same gates a citation read uses.
        verify(receipts).shownNow(VISIBLE_EVIDENCE, "gv-imported", past, "r");
    }

    @Test
    void aCitationThatCannotBeVerifiedNowIsUnavailableNotNotFound() {
        EventDetailService service = imported(bundle(false));
        // The store or registry behind a citation cannot be read: a passing outage, not a withdrawal.
        when(receipts.shownNow(eq(TSM_EVIDENCE), anyString(), any(), anyString()))
                .thenThrow(new CustomException(ErrorCode.SOURCE_UNAVAILABLE));

        assertEquals(ErrorCode.SOURCE_UNAVAILABLE, assertThrows(CustomException.class,
                () -> service.get(EUV, null, null, null, "r")).getErrorCode());
    }

    @Test
    void aMentionWithOneOfItsTwoCitationsWithdrawnIsLeftOutWhole() {
        EventDetailService service = imported(bundle(false));
        // m2 cites two real evidence ids; only the second is withdrawn. Its text may rest on that one, so m2 goes whole.
        when(receipts.shownNow(eq(SAMSUNG_EVIDENCE), anyString(), any(), anyString())).thenReturn(false);

        EventDetail detail = service.get(EUV, null, null, null, "r");

        assertEquals(List.of(M1), detail.mentions().stream().map(MentionOut::mentionId).toList());
        assertEquals(List.of(M1), detail.fieldDecisions().stream().map(EventDetail.FieldDecisionOut::mentionId).toList());
        assertFalse(detail.toString().contains("m2 title"));
        assertTrue(detail.relations().stream().noneMatch(r -> r.target().equals("KRX:005930")));
    }

    @Test
    void aRepresentativeThatLostOneOfTwoRealCitationsToAnExclusionClosesTheEvent() {
        // m1 (the representative) cites two real evidence ids; the exclusion store removes one of them.
        String twoCitations = bundle(false).node().toString().replace("\"evidenceIds\":[\"" + VISIBLE_EVIDENCE + "\"]}",
                "\"evidenceIds\":[\"" + VISIBLE_EVIDENCE + "\",\"" + TSM_EVIDENCE + "\"]}");
        EventDetailService service = imported(StrictJson.parseObject(twoCitations), List.of(),
                new DisclosureExclusions(1, java.util.Set.of(), java.util.Set.of(), java.util.Set.of(TSM_EVIDENCE)));

        assertEquals(ErrorCode.RESOURCE_NOT_FOUND, assertThrows(CustomException.class,
                () -> service.get(EUV, null, null, null, "r")).getErrorCode());
    }

    @Test
    void aUnanimousEventWithoutARepresentativeIsShownAndNeedsEveryMention() {
        // A normal unanimous event: no representative, every mention gives the same head values.
        EventDetailService service = imported(bundle(false), List.of(), DisclosureExclusions.NONE, null);
        assertEquals(List.of(M1, M2), service.get(EUV, null, null, null, "r").mentions().stream()
                .map(MentionOut::mentionId).toList());

        // Its head rests on all of them: one mention no longer wholly shown closes it, never a first mention in its place.
        when(receipts.shownNow(eq(SAMSUNG_EVIDENCE), anyString(), any(), anyString())).thenReturn(false);
        assertEquals(ErrorCode.RESOURCE_NOT_FOUND, assertThrows(CustomException.class,
                () -> service.get(EUV, null, null, null, "r")).getErrorCode());
    }

    @Test
    void aFollowedEventThatCannotBeShownLeavesFollowsAndRelations() {
        EventDetailService service = imported(hbmBundle());
        // The label follows would carry is the snapshot's headline of supply, not the receipt mention's title.
        String supplyLabel = GraphReadFixtures.snapshot("fixture-2026-10-08").issues().stream()
                .filter(i -> i.issueId().equals(HBM_SUPPLY)).findFirst().orElseThrow().label();
        // Both shown: equipment (unanimous) follows supply, and its label is in the response.
        EventDetail shown = service.get(HBM_EQUIP, null, null, null, "r");
        assertEquals(List.of(HBM_SUPPLY), shown.follows().previous().stream().map(EventDetail.FollowRef::id).toList());
        assertEquals(List.of(supplyLabel), shown.follows().previous().stream().map(EventDetail.FollowRef::title).toList());

        // Supply's citation is withdrawn: its own detail is closed, and equipment no longer names it.
        when(receipts.shownNow(eq(SUPPLY_EV[0]), anyString(), any(), anyString())).thenReturn(false);
        assertEquals(ErrorCode.RESOURCE_NOT_FOUND, assertThrows(CustomException.class,
                () -> service.get(HBM_SUPPLY, null, null, null, "r")).getErrorCode());
        EventDetail equipment = service.get(HBM_EQUIP, null, null, null, "r");
        assertEquals(List.of(), equipment.follows().previous());
        assertTrue(equipment.relations().stream().noneMatch(r -> r.relationType().equals("FOLLOWS")));
        assertFalse(equipment.toString().contains(supplyLabel), "supply's headline does not leave through equipment");
    }

    @Test
    void anExcludedCitationLeavesTheDetailLikeTheGraph() {
        EventDetail detail = imported(bundle(false), List.of(),
                new DisclosureExclusions(1, java.util.Set.of(), java.util.Set.of(), java.util.Set.of(TSM_EVIDENCE)))
                .get(EUV, null, null, null, "r");

        assertFalse(detail.evidenceIds().contains(TSM_EVIDENCE));
        assertTrue(detail.relations().stream().noneMatch(r -> r.target().equals("NYSE:TSM")));
        verify(receipts, never()).shownNow(eq(TSM_EVIDENCE), anyString(), any(), anyString());
    }

    @Test
    void anotherVersionOfTheSameArticleIsNotThisEventsArticle() {
        // Another issue may cite art-euv-export v2; this one cites only v1.
        var v2 = new PublicGraphSnapshot.Article(EUV_ARTICLE, "v2", "later text", "https://example.invalid/v2",
                "2026-09-29T00:00:00Z");

        EventDetail detail = imported(bundle(false), List.of(v2), DisclosureExclusions.NONE).get(EUV, null, null, null, "r");

        assertEquals(List.of("v1"), detail.articles().stream().map(a -> a.url().endsWith("/v2") ? "v2" : "v1").toList());
    }

    @Test
    void anUnsupportedReceiptSchemaIsUnavailableNotEmpty() {
        for (String schema : new String[] {"zoop-graph-handoff-bundle-1", "zoop-graph-handoff-bundle-2",
                "zoop-graph-handoff-bundle-3", "zoop-graph-handoff-bundle-4", "zoop-graph-handoff-bundle-8",
                "zoop-graph-handoff-bundle-7-extra", "zoop-graph-handoff-bundle-70", ""}) {
            String old = bundle(false).node().toString().replace("zoop-graph-handoff-bundle-5", schema);
            assertEquals(ErrorCode.SOURCE_UNAVAILABLE, assertThrows(CustomException.class,
                    () -> imported(StrictJson.parseObject(old)).get(EUV, null, null, null, "r")).getErrorCode(), schema);
        }
        String unnamed = bundle(false).node().toString().replace("\"schemaVersion\":\"zoop-graph-handoff-bundle-5\",", "");
        assertEquals(ErrorCode.SOURCE_UNAVAILABLE, assertThrows(CustomException.class,
                () -> imported(StrictJson.parseObject(unnamed)).get(EUV, null, null, null, "r")).getErrorCode());
    }

    @Test
    void aCorruptReceiptVersionIsUnavailableNotEmpty() {
        for (String corrupt : List.of("null", "7", "true", "[]", "{}")) {
            String json = bundle(false).node().toString()
                    .replace("\"schemaVersion\":\"zoop-graph-handoff-bundle-5\"", "\"schemaVersion\":" + corrupt);
            assertEquals(ErrorCode.SOURCE_UNAVAILABLE, assertThrows(CustomException.class,
                    () -> imported(StrictJson.parseObject(json)).get(EUV, null, null, null, "r")).getErrorCode(), corrupt);
        }
    }

    @Test
    void anAsOfBeforeOneOfTheEventsArticlesHidesTheWholeEvent() {
        // The filter keeps an issue only when every article is published by asOf (GraphSnapshotFilter): never a partial head.
        assertEquals(ErrorCode.RESOURCE_NOT_FOUND, assertThrows(CustomException.class,
                () -> imported(bundle(false)).get(EUV, null, null, "2026-09-28T03:29:59Z", "r")).getErrorCode());
        assertEquals(EUV, imported(bundle(false)).get(EUV, null, null, "2026-09-28T03:30:00Z", "r").id());
    }

    /**
     * The 10-08 fixture served as an imported version (kind snapshot): the EUV issue's mention references are rewritten to the app
     * formula the import uses, so the receipt mentions below resolve to them.
     */
    private EventDetailService imported(StrictJson.Obj bundle) {
        return imported(bundle, List.of(), DisclosureExclusions.NONE);
    }

    private EventDetailService imported(StrictJson.Obj bundle, List<PublicGraphSnapshot.Article> extraArticles,
            DisclosureExclusions exclusions) {
        return imported(bundle, extraArticles, exclusions, M1);
    }

    /** euvRepresentative null: the EUV mentions agree on every head field (fieldProvenance.selection unanimous). */
    private EventDetailService imported(StrictJson.Obj bundle, List<PublicGraphSnapshot.Article> extraArticles,
            DisclosureExclusions exclusions, String euvRepresentative) {
        if (bundle != null) when(receipts.graphImportBundle(anyString(), anyString())).thenReturn(bundle);
        // Every citation is readable now unless a test withdraws one.
        when(receipts.shownNow(anyString(), anyString(), any(), anyString())).thenReturn(true);
        PublicGraphSnapshot base = GraphReadFixtures.snapshot("fixture-2026-10-08");
        List<Issue> issues = base.issues().stream().map(i -> switch (i.issueId()) {
            case EUV -> withMentions(i, List.of(new MentionRef(M1, EUV_ARTICLE, "v1"), new MentionRef(M2, EUV_ARTICLE, "v1")),
                    euvRepresentative);
            // As in the fixture: equipment is unanimous (no representative), supply has one.
            case HBM_EQUIP -> withMentions(i, List.of(new MentionRef(EQUIP_M, "art-hbm-equip", "v1")), null);
            case HBM_SUPPLY -> withMentions(i, List.of(new MentionRef(SUPPLY_M, "art-hbm-supply", "v1")), SUPPLY_M);
            default -> i;
        }).toList();
        PublicGraphSnapshot snapshot = new PublicGraphSnapshot(base.snapshotFormat(), base.versionId(), base.sourceBundleId(),
                base.companies(), issues, base.relations(),
                java.util.stream.Stream.concat(base.articles().stream(), extraArticles.stream()).toList(), base.evidence());
        GraphVersionRecord record = new GraphVersionRecord("gv-imported", 2, "snapshot", "artifact-gv", "artifact:gv",
                "a".repeat(64), true);
        GraphVersionRepository versions = new GraphVersionRepository() {
            public Optional<GraphVersionRecord> find(String id) { return Optional.of(record).filter(r -> r.id().equals(id)); }
            public Optional<GraphVersionRecord> active() { return Optional.of(record); }
            public Optional<String> activeVersionIdAt(Instant asOf) { return Optional.of(record.id()); }
            public boolean everActivated(String id) { return record.id().equals(id); }
            public Optional<Instant> firstActivatedAt(String id) {
                return record.id().equals(id) ? Optional.of(NOW) : Optional.empty();
            }
        };
        PublicGraphReader reader = new PublicGraphReader(new GraphVersionSelector(versions, Clock.fixed(NOW, ZoneOffset.UTC)),
                version -> snapshot, pinned -> exclusions);
        return new EventDetailService(reader, receipts, registry);
    }

    private static Issue withMentions(Issue i, List<MentionRef> mentions, String representative) {
        return new Issue(i.issueId(), i.label(), i.eventTime(), i.timePrecision(), i.period(), i.assertionStatus(), i.action(),
                i.target(), i.geography(), i.geographyPolicyVersion(), i.geographyEvidenceIds(), i.articleIds(), i.evidenceIds(),
                mentions, representative, i.latestPublishedAt());
    }

    /** Both HBM events as the receipt carries them: one mention each, citing every evidence id of its own event. */
    private static StrictJson.Obj hbmBundle() {
        String mention = """
                {"documentId":"%s","documentVersion":"dv1","mentionId":"%s","articleId":"%s","articleVersion":"v1",
                 "title":"%s","action":"supply","target":null,"eventTime":null,"timePrecision":"unknown","period":null,
                 "assertionStatus":"occurred","background":false,"participants":[],"evidenceIds":["%s","%s"]}""";
        String issue = """
                {"id":"%s","mentions":[%s],"fieldVerdicts":[],
                 "sourceSupport":{"articleCount":1,"knownLineageCount":null,"unknownLineageArticles":["%s"],
                   "independentSourceCount":null,"duplicateGroups":[]}}""";
        return StrictJson.parseObject("{\"schemaVersion\":\"zoop-graph-handoff-bundle-5\",\"issues\":["
                + issue.formatted(HBM_EQUIP, mention.formatted("de", "e1", "art-hbm-equip", "equip title", EQUIP_EV[0],
                        EQUIP_EV[1]), "art-hbm-equip") + ","
                + issue.formatted(HBM_SUPPLY, mention.formatted("ds", "s1", "art-hbm-supply", "supply title", SUPPLY_EV[0],
                        SUPPLY_EV[1]), "art-hbm-supply") + "]}");
    }

    /** The parts of an AI handoff bundle getEvent reads; values a verdict holds or rejects are marked so a leak is visible. */
    private static StrictJson.Obj bundle(boolean allBackground) {
        return StrictJson.parseObject("""
                {"schemaVersion":"zoop-graph-handoff-bundle-5","issues":[{"id":"%s",
                  "mentions":[
                    {"documentId":"d1","documentVersion":"dv1","mentionId":"m1","articleId":"%s","articleVersion":"v1",
                     "title":"m1 title","action":"export","target":"EUV","eventTime":"2026-09","timePrecision":"month",
                     "period":"2026Q4","assertionStatus":"occurred","background":%s,
                     "participants":[{"sourceCompanyId":"S1","companyId":"NASDAQ:ASML","name":"ASML","role":"supplier"},
                                     {"sourceCompanyId":"S2","companyId":null,"name":"Unknown Co","role":null}],
                     "evidenceIds":["%s"]},
                    {"documentId":"d1","documentVersion":"dv1","mentionId":"m2","articleId":"%s","articleVersion":"v1",
                     "title":"m2 title","action":"export","target":null,"eventTime":"2026-10-HELD","timePrecision":"month",
                     "period":"2027-REJECTED","assertionStatus":"announced","background":true,"participants":[],
                     "evidenceIds":["%s","%s"]},
                    {"documentId":"d9","documentVersion":"dv9","mentionId":"m9","articleId":"art-hidden","articleVersion":"v1",
                     "title":"not referenced by the snapshot","action":"x","target":null,"eventTime":null,
                     "timePrecision":"unknown","period":null,"assertionStatus":"unknown","background":false,
                     "participants":[],"evidenceIds":[]}],
                  "fieldVerdicts":[
                    {"documentId":"d1","documentVersion":"dv1","mentionId":"m1","field":"eventTime","value":"2026-09",
                     "decision":"ALLOW","reasonCode":"stated"},
                    {"documentId":"d1","documentVersion":"dv1","mentionId":"m2","field":"eventTime","value":"2026-10-HELD",
                     "decision":"HOLD","reasonCode":"unstated"},
                    {"documentId":"d1","documentVersion":"dv1","mentionId":"m2","field":"period","value":"2027-REJECTED",
                     "decision":"REJECT","reasonCode":"contradicted"}],
                  "sourceSupport":{"articleCount":1,"knownLineageCount":0,"unknownLineageArticles":["%s"],
                    "independentSourceCount":null,"duplicateGroups":[]}}]}
                """.formatted(EUV, EUV_ARTICLE, allBackground, VISIBLE_EVIDENCE, EUV_ARTICLE, VISIBLE_EVIDENCE,
                SAMSUNG_EVIDENCE, EUV_ARTICLE));
    }
}
