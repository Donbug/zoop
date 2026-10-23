package com.zoop.briefing.query;

import java.time.Clock;
import java.time.Instant;
import java.time.LocalDate;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Optional;
import java.util.Set;
import java.util.function.Consumer;

import com.zoop.briefing.storage.BriefingChange;
import com.zoop.briefing.storage.BriefingHistoryEntry;
import com.zoop.briefing.storage.BriefingRound;
import com.zoop.briefing.storage.BriefingRoundRepository;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.dao.DataAccessResourceFailureException;
import tools.jackson.databind.json.JsonMapper;
import tools.jackson.databind.node.ObjectNode;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

class BriefingQueryServiceTest {
    private static final Instant MORNING = Instant.parse("2026-10-16T00:20:00Z");
    private static final LocalDate DATE = LocalDate.of(2026, 10, 16);
    private final JsonMapper mapper = JsonMapper.builder().build();
    private final BriefingRoundRepository repository = mock(BriefingRoundRepository.class);
    private final BriefingContentAccess access = mock(BriefingContentAccess.class);
    private final BriefingQueryService service = new BriefingQueryService(repository,
            Clock.fixed(Instant.parse("2026-10-19T01:00:00Z"), ZoneOffset.UTC), access);

    @BeforeEach void setup() {
        when(repository.changes(anyString())).thenReturn(List.of());
        when(access.mayRead(any(), anyString())).thenReturn(true);
    }

    private BriefingRound round(String edition, String status, Consumer<ObjectNode> transform) {
        Instant scheduled = edition.equals("morning") ? MORNING : MORNING.plusSeconds(29400);
        String id = "brf-" + DATE + "-" + edition;
        var payload = mapper.createObjectNode().put("id", id).put("date", DATE.toString()).put("edition", edition)
                .put("scheduledAt", scheduled.toString()).put("generatedAt", scheduled.plusSeconds(5).toString())
                .put("graphVersion", "g-original").put("reviewRevision", 0).put("ruleRevision", 0)
                .put("selectedFrom", 1).putNull("emptyReason").putNull("marketVariables").putNull("outlook");
        payload.putObject("dataWindow").putNull("start").put("end", scheduled.toString()).put("openStart", true);
        var references = payload.putObject("references");
        references.putArray("eventIds").add("event-original"); references.putArray("evidenceIds").add("e-original");
        references.putArray("companyIds").add("company-original");
        var item = payload.putArray("items").addObject().put("title", "저장된 이슈 제목").put("eventId", "event-original")
                .putNull("eventTime").put("timePrecision", "unknown").put("evidenceCount", 1).put("rank", 1)
                .put("reason", "저장된 선정 이유").put("reportedAt", "2026-10-16");
        item.putArray("companies").addObject().put("id", "company-original").put("name", "원본 기업")
                .putNull("role").put("roleUnconfirmed", true).put("relationType", "INVOLVES");
        item.putArray("evidenceIds").add("e-original"); item.putArray("matchedCompanyIds"); item.putArray("documentSentiments");
        item.putObject("summary").put("text", "저장된 근거 기반 요약").put("generatedAt", scheduled.plusSeconds(5).toString())
                .put("resultVersion", "result-original").putArray("evidenceIds").add("e-original");
        var support = item.putObject("sourceSupport").put("articleCount", 1).putNull("knownLineageCount").putNull("independentSourceCount");
        support.putArray("unknownLineageArticles").add("article-original"); support.putArray("duplicateGroups");
        var metadata = payload.putObject("metadata").put("source", "synthetic-test").put("asOf", scheduled.toString())
                .put("graphVersion", "g-original").put("requestId", "stored-request").put("partial", false);
        metadata.putObject("schedule").put("morning", "07:40").put("evening", "18:10").put("confirmed", true);
        metadata.putObject("selection").put("basis", "market").putNull("reason"); metadata.putArray("failures");
        var snapshot = mapper.createObjectNode();
        snapshot.putObject("marketSummary").put("status", "unavailable").put("reason", "발행 당시 생산자 미연결");
        transform.accept(payload);
        return new BriefingRound(id, DATE, edition, scheduled, null, scheduled, true, status,
                List.of("published", "suspended").contains(status) ? scheduled.plusSeconds(10) : null,
                scheduled.plusSeconds(5), "g-original", payload, snapshot,
                edition.equals("evening") ? mapper.createObjectNode().put("status", "unavailable").put("reason", "출근 원본 없음") : null);
    }

    private BriefingRound published() { return round("morning", "published", ignored -> { }); }

    private BriefingRound authoredAnalysis(Consumer<ObjectNode> transform) {
        var row = published();
        var summary = ((ObjectNode) row.publicSnapshot()).putObject("marketSummary").put("text", "확인된 기업 사실\n조건부 해석\n수집 범위 한정")
                .put("generatedAt", row.generatedAt().toString()).put("resultVersion", "authored-outlook");
        summary.putArray("evidenceIds").add("e-original");
        var analysis = summary.putObject("analysis").put("schemaVersion", "zoop-market-outlook-analysis-v1").put("edition", "morning")
                .put("cutoff", MORNING.toString()).put("mode", "morning_update").put("scopeNote", "수집 범위 한정");
        analysis.putObject("previousPublication").put("status", "unavailable").put("kind", "simulated_previous_output")
                .put("reason", "immediate_previous_summary_withheld");
        analysis.putObject("coverage").put("documents", 3).put("newDocuments", 1).put("backgroundDocuments", 2)
                .put("marketRepresentative", false).put("sectorPriceFeedAvailable", false).putArray("companyNames").add("원본 기업");
        var claims = analysis.putArray("claims");
        for (String kind : List.of("fact", "interpretation")) {
            var claim = claims.addObject().put("claimId", "market:claim:" + claims.size()).put("kind", kind)
                    .put("text", "fact".equals(kind) ? "확인된 기업 사실" : "조건부 해석")
                    .putNull("targetId").putNull("direction").putNull("updateAction");
            for (String field : List.of("evidenceIds", "indicatorIds", "previousPublicationIds", "previousForecastIds", "evaluationIds", "conditions", "counterFactors")) claim.putArray(field);
            claim.withArray("evidenceIds").add("e-original");
        }
        analysis.putArray("forecasts"); analysis.putArray("forecastEvaluations");
        transform.accept(analysis); return row;
    }

    @Test void structuredMarketAnalysisRestoresSameVerifiedTextWithoutInvokingProducer() {
        var row = authoredAnalysis(ignored -> { }); when(repository.find(DATE, "morning")).thenReturn(Optional.of(row));
        var result = service.get(DATE, "morning", "request");
        assertEquals("morning_update", result.at("/marketSummary/analysis/mode").asString());
        assertEquals("조건부 해석", result.at("/marketSummary/analysis/claims/1/text").asString());
        assertEquals("immediate_previous_summary_withheld", result.at("/marketSummary/analysis/previousPublication/reason").asString());
        assertEquals(row.publicSnapshot().path("marketSummary"), result.path("marketSummary"));
    }

    @Test void alteredAnalysisTextCutoffForeignEvidenceOrFabricatedEvaluationCannotBeDisclosed() {
        List<Consumer<ObjectNode>> changes = List.of(
                a -> ((ObjectNode) a.at("/claims/0")).put("text", "생성 기록에 없는 새 전망"),
                a -> a.put("cutoff", MORNING.plusSeconds(1).toString()),
                a -> ((ObjectNode) a.get("coverage")).put("marketRepresentative", true),
                a -> ((ObjectNode) a.get("coverage")).put("backgroundDocuments", 3),
                a -> ((tools.jackson.databind.node.ArrayNode) a.at("/claims/0/evidenceIds")).add("foreign-evidence"),
                a -> a.putArray("forecastEvaluations").addObject().put("evaluationId", "invented-evaluation"));
        for (var change : changes) {
            var row = authoredAnalysis(change); when(repository.find(DATE, "morning")).thenReturn(Optional.of(row));
            assertUnavailable(() -> service.get(DATE, "morning", "request"));
        }
    }

    @Test void restoresRealNestedDtoAndCorrectionsWithoutChangingOriginal() {
        var row = published(); when(repository.find(DATE, "morning")).thenReturn(Optional.of(row));
        when(repository.changes(row.id())).thenReturn(List.of(new BriefingChange(1, "correction", "event-original", "원문",
                "정정문", "검증된 정정 사유", MORNING.plusSeconds(20), null)));
        var result = service.get(DATE, "morning", "transport-request");
        assertEquals("published", result.path("status").asString());
        assertEquals("저장된 이슈 제목", result.path("items").get(0).path("title").asString());
        assertEquals("원본 기업", result.path("items").get(0).path("companies").get(0).path("name").asString());
        assertEquals("정정문", result.path("corrections").get(0).path("corrected").asString());
        assertEquals("event-original", result.path("corrections").get(0).path("eventId").asString());
        assertEquals("transport-request", result.path("metadata").path("requestId").asString());
        assertEquals("stored-request", row.payload().path("metadata").path("requestId").asString());
        assertEquals("07:40", result.path("metadata").path("schedule").path("morning").asString());
        assertEquals("g-original", result.path("graphVersion").asString());
        assertEquals("unavailable", result.path("marketVariables").path("status").asString());
    }

    private BriefingRound marketRound(Consumer<ObjectNode> transform) {
        return round("morning", "published", payload -> {
            var market = payload.putObject("marketVariables").put("status", "available")
                    .put("referenceAt", MORNING.toString()).put("rateCutoffAt", MORNING.toString())
                    .put("collectedAt", MORNING.toString());
            var indicators = market.putArray("indicators");
            ObjectNode fx = null;
            for (String id : List.of("kospi", "kosdaq", "usdkrw")) {
                boolean bank = "usdkrw".equals(id);
                var indicator = indicators.addObject().put("id", id).put("label", id)
                        .put("unit", bank ? "KRW" : "pt").put("status", "delayed").put("value", 1300.0)
                        .put("valueKind", "close").put("observedDate", DATE.minusDays(1).toString())
                        .putNull("observedAt").putNull("change").putNull("changeRate").putNull("baseline")
                        .putNull("reason").putNull("reasonCode");
                indicator.putObject("source").put("provider", bank ? "naver" : "yahoo")
                        .put("symbol", bank ? "FX_USDKRW" : id).put("name", "Synthetic source")
                        .put("official", false).putNull("delayNote").put("url", bank
                                ? "https://api.stock.naver.com/marketindex/exchange/FX_USDKRW/prices?pageSize=40&page=1"
                                : "https://example.invalid/index");
                if (bank) fx = indicator;
            }
            transform.accept(fx);
        });
    }

    @Test void legacyBankReferenceIsProjectedWithoutChangingStoredPublication() {
        var row = marketRound(ignored -> { }); var original = row.payload().deepCopy();
        when(repository.find(DATE, "morning")).thenReturn(Optional.of(row));
        var result = service.get(DATE, "morning", "request");
        assertEquals("reference", result.path("marketVariables").path("indicators").get(2).path("valueKind").asString());
        assertEquals("close", result.path("marketVariables").path("indicators").get(0).path("valueKind").asString());
        assertEquals(original, row.payload());
        ((ObjectNode) result.path("marketVariables").path("indicators").get(2)).put("value", 0.0);
        assertEquals(original, row.payload());
        assertEquals(1300.0, service.get(DATE, "morning", "again").path("marketVariables").path("indicators").get(2).path("value").doubleValue());
    }

    @Test void explicitReferenceIsAcceptedAndUnknownCloseOrLatestAreNotRelabeled() {
        for (String mode : List.of("reference", "foreign_close", "latest")) {
            var row = marketRound(fx -> {
                if ("reference".equals(mode)) fx.put("valueKind", "reference");
                if ("foreign_close".equals(mode)) ((ObjectNode) fx.get("source")).put("url", "https://example.invalid/fx");
                if ("latest".equals(mode)) fx.put("valueKind", "latest").put("observedAt", MORNING.minusSeconds(1).toString());
            });
            when(repository.find(DATE, "morning")).thenReturn(Optional.of(row));
            String expected = "foreign_close".equals(mode) ? "close" : mode;
            assertEquals(expected, service.get(DATE, "morning", "request").path("marketVariables").path("indicators").get(2).path("valueKind").asString());
        }
    }

    @Test void bankReferenceCannotBeAssignedToAnIndex() {
        var row = marketRound(ignored -> { });
        ((ObjectNode) row.payload().path("marketVariables").path("indicators").get(0)).put("valueKind", "reference");
        when(repository.find(DATE, "morning")).thenReturn(Optional.of(row));
        assertUnavailable(() -> service.get(DATE, "morning", "request"));
    }

    @Test void latestComesFromDatabaseEvenAcrossNonGenerationDays() {
        var row = published(); when(repository.latest(null, "morning")).thenReturn(Optional.of(row));
        var result = service.get(null, "morning", "request");
        assertEquals(DATE.toString(), result.path("date").asString());
        verify(repository, never()).find(any(), any());
    }

    @Test void noRowsReturnsNotReadyWithCurrentScheduleWithoutWriting() {
        when(repository.latest(null, "morning")).thenReturn(Optional.empty());
        var result = service.get(null, "morning", "request");
        assertEquals("not_ready", result.path("status").asString());
        assertEquals("09:20", result.path("metadata").path("schedule").path("morning").asString());
        assertEquals("17:30", result.path("metadata").path("schedule").path("evening").asString());
        assertTrue(result.path("items").isEmpty()); assertTrue(result.path("dataWindow").isNull());
        verifyNoInteractions(access);
    }

    @Test void suspendedOriginalNeverLeaksAndActualSuspensionReasonIsShown() {
        var row = round("morning", "suspended", p -> { });
        when(repository.find(DATE, "morning")).thenReturn(Optional.of(row));
        when(repository.changes(row.id())).thenReturn(List.of(new BriefingChange(2, "suspension", null, null, null,
                "원천 제공 중단", MORNING.plusSeconds(30), true)));
        var result = service.get(DATE, "morning", "request");
        assertEquals("suspended", result.path("status").asString());
        assertEquals("원천 제공 중단", result.path("notice").path("reason").asString());
        assertTrue(result.path("items").isEmpty()); assertTrue(result.path("references").path("evidenceIds").isEmpty());
        assertTrue(result.path("outlook").isNull()); assertEquals("unavailable", result.path("marketSummary").path("status").asString());
        verifyNoInteractions(access);
    }

    @Test void unpublishedStatesAreTranslatedWithoutReturningStoredContent() {
        for (String state : List.of("scheduled", "missing", "generating", "verifying", "failed")) {
            var row = round("morning", state, p -> { });
            when(repository.find(DATE, "morning")).thenReturn(Optional.of(row));
            var result = service.get(DATE, "morning", "request");
            assertEquals(state.equals("failed") ? "failed" : Set.of("generating", "verifying").contains(state) ? "generating" : "not_ready",
                    result.path("status").asString());
            assertTrue(result.path("items").isEmpty()); assertTrue(result.path("corrections").isEmpty());
        }
        verifyNoInteractions(access);
    }

    @Test void currentGrantDenialCannotFallBackToPublishedSnapshot() {
        var row = published(); when(repository.find(DATE, "morning")).thenReturn(Optional.of(row));
        when(access.mayRead(row, "request")).thenReturn(false);
        assertUnavailable(() -> service.get(DATE, "morning", "request"));
    }

    @Test void malformedNestedPublicationIdentityRankAndSummaryAreRejected() {
        List<Consumer<ObjectNode>> invalid = List.of(
                p -> p.put("id", "other-round"),
                p -> p.put("graphVersion", "newest-graph"),
                p -> p.putObject("dataWindow").putNull("start").put("end", MORNING.plusSeconds(60).toString()).put("openStart", true),
                p -> ((ObjectNode) p.path("items").get(0)).put("rank", 2),
                p -> ((ObjectNode) p.path("items").get(0)).remove("sourceSupport"),
                p -> ((ObjectNode) p.path("items").get(0)).putObject("summary").put("fixture", "not-a-contract"),
                p -> ((ObjectNode) p.path("metadata")).put("graphVersion", "newest-graph"),
                p -> p.put("generatedAt", "invalid-private-data"));
        for (var change : invalid) {
            var row = round("morning", "published", change);
            when(repository.find(DATE, "morning")).thenReturn(Optional.of(row));
            assertUnavailable(() -> service.get(DATE, "morning", "request"));
        }
    }

    @Test void eveningRestoresSavedComparisonWithoutReadingMorningAgain() {
        var row = round("evening", "published", p -> { });
        when(repository.find(DATE, "evening")).thenReturn(Optional.of(row));
        var result = service.get(DATE, "evening", "request");
        assertEquals("출근 원본 없음", result.path("sinceMorning").path("reason").asString());
        verify(repository, never()).find(DATE, "morning");
    }

    @Test void graphBasisCannotAdvertiseNewestOrUnconnectedGraph() {
        var row = published(); when(repository.findById(row.id())).thenReturn(Optional.of(row));
        var result = service.graphBasis(row.id(), "request");
        assertEquals("unavailable", result.path("status").asString());
        assertEquals("g-original", result.path("graphVersion").asString());
        assertTrue(result.path("keyIssueIds").isEmpty()); assertTrue(result.path("companyIds").isEmpty());
        when(repository.findById("missing")).thenReturn(Optional.empty());
        assertEquals(ErrorCode.RESOURCE_NOT_FOUND, assertThrows(CustomException.class, () -> service.graphBasis("missing", "request")).getErrorCode());
    }

    @Test void historyUsesMetadataOnlyAndKeepsStableCursor() {
        var first = new BriefingHistoryEntry("evening", DATE, "evening", MORNING.plusSeconds(29400), "published", MORNING.plusSeconds(29410));
        var second = new BriefingHistoryEntry("morning", DATE, "morning", MORNING, "suspended", MORNING.plusSeconds(10));
        when(repository.history(null, null, 2)).thenReturn(List.of(first, second));
        var page = service.history(null, 1); String cursor = page.path("nextCursor").asString();
        when(repository.history(first.scheduledAt(), first.id(), 2)).thenReturn(List.of(second));
        assertEquals("morning", service.history(cursor, 1).path("items").get(0).path("id").asString());
        assertEquals(ErrorCode.INVALID_CURSOR, assertThrows(CustomException.class, () -> service.history(cursor, 2)).getErrorCode());
        verifyNoInteractions(access); verify(repository, never()).find(any(), any()); verify(repository, never()).changes(anyString());
    }

    @Test void roundGraphLookupUsesCanonicalPublishedIssueCompanyPairsAndCurrentRights() {
        var row = published();
        when(repository.findById(row.id())).thenReturn(Optional.of(row));
        var lookup = new PublishedBriefingGraphLookup(repository, access,
                com.zoop.briefing.replay.BriefingReplayReadPolicy.disabled());
        var basis = lookup.resolve(row.id(), "request");
        assertEquals("g-original", basis.graphVersion());
        assertEquals(MORNING, basis.dataAsOf());
        assertEquals(List.of("event-original"), basis.keyIssueIds());
        assertEquals(List.of("company-original"), basis.companyIds());
        assertEquals(List.of("company-original"), basis.issueCompanies().get("event-original"));
        when(access.mayRead(row, "request")).thenReturn(false);
        assertUnavailable(() -> lookup.resolve(row.id(), "request"));
    }

    @Test void malformedPublishedPayloadCannotBeUsedToBypassTheBriefingReadGateViaGraph() {
        var row = round("morning", "published", p -> ((ObjectNode) p.path("items").get(0)).put("rank", 4));
        when(repository.findById(row.id())).thenReturn(Optional.of(row));
        var lookup = new PublishedBriefingGraphLookup(repository, access,
                com.zoop.briefing.replay.BriefingReplayReadPolicy.disabled());
        assertUnavailable(() -> lookup.resolve(row.id(), "request"));
    }

    @Test void databaseOutageIs503RatherThanAnEmptySuccessfulRound() {
        when(repository.find(DATE, "morning")).thenThrow(new DataAccessResourceFailureException("private-db-details"));
        assertUnavailable(() -> service.get(DATE, "morning", "request"));
    }

    private void assertUnavailable(Runnable action) {
        assertEquals(ErrorCode.SOURCE_UNAVAILABLE, assertThrows(CustomException.class, action::run).getErrorCode());
    }
}
