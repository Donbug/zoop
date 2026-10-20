package com.zoop.briefing.controller;

import java.time.Instant;
import java.time.LocalDate;
import java.math.BigDecimal;
import java.util.List;

import io.swagger.v3.oas.annotations.media.Schema;
import tools.jackson.databind.JsonNode;

/** Documentation projections for JSON snapshots; their shape mirrors docs/api/openapi.yaml. */
public final class BriefingHttpSchemas {
    private BriefingHttpSchemas() { }

    @Schema(name = "BriefingResponse", requiredProperties = {"id", "date", "edition", "status", "scheduledAt", "publishedAt",
            "generatedAt", "dataWindow", "dataAsOf", "graphVersion", "items", "marketSummary", "marketVariables",
            "sinceMorning", "previousComparison", "emptyReason", "corrections", "notice", "references", "metadata", "outlook"})
    public record BriefingResponse(String id, LocalDate date,
            @Schema(allowableValues = {"morning", "evening"}) String edition,
            @Schema(allowableValues = {"published", "not_ready", "generating", "failed", "suspended"}) String status,
            Instant scheduledAt, @Schema(nullable = true) Instant publishedAt, @Schema(nullable = true) Instant generatedAt,
            @Schema(nullable = true) BriefingWindow dataWindow, @Schema(nullable = true) Instant dataAsOf,
            @Schema(nullable = true) String graphVersion, List<BriefingItem> items,
            @Schema(oneOf = {AnalysisSummary.class, Unavailable.class}) JsonNode marketSummary,
            @Schema(oneOf = {MarketVariables.class, Unavailable.class}) JsonNode marketVariables,
            @Schema(nullable = true, oneOf = {SinceMorning.class, Unavailable.class}) JsonNode sinceMorning,
            @Schema(nullable = true, oneOf = {PreviousComparison.class, Unavailable.class},
                    description = "직전 발행 회차와 사건 ID 기준 포함 여부 비교입니다. 전망 정확도 평가는 제공하지 않습니다.") JsonNode previousComparison,
            @Schema(nullable = true, allowableValues = {"no_issues_in_window"}) String emptyReason,
            List<BriefingCorrection> corrections, @Schema(nullable = true) BriefingNotice notice,
            BriefingReferences references, BriefingMetadata metadata, @Schema(nullable = true) BriefingOutlook outlook) { }

    @Schema(name = "BriefingRoundsResponse", requiredProperties = {"items", "nextCursor"})
    public record BriefingRoundsResponse(List<BriefingRoundRef> items, @Schema(nullable = true) String nextCursor) { }

    @Schema(name = "BriefingRoundRef", requiredProperties = {"id", "date", "edition", "status", "publishedAt"})
    public record BriefingRoundRef(String id, LocalDate date, @Schema(allowableValues = {"morning", "evening"}) String edition,
            @Schema(allowableValues = {"published", "suspended"}) String status, @Schema(nullable = true) Instant publishedAt) { }

    @Schema(name = "BriefingGraphBasis", requiredProperties = {"roundId", "date", "edition", "status", "message", "reason",
            "publishedAt", "dataAsOf", "graphVersion", "keyIssueIds", "companyIds", "correctionCount"})
    public record BriefingGraphBasis(String roundId, LocalDate date, @Schema(allowableValues = {"morning", "evening"}) String edition,
            @Schema(allowableValues = {"available", "suspended", "unavailable", "not_published"}) String status,
            @Schema(nullable = true) String message, @Schema(nullable = true) String reason,
            @Schema(nullable = true) Instant publishedAt, @Schema(nullable = true) Instant dataAsOf,
            @Schema(nullable = true) String graphVersion, List<String> keyIssueIds, List<String> companyIds, long correctionCount) { }

    @Schema(name = "BriefingItem", requiredProperties = {"title", "eventId", "eventTime", "timePrecision", "companies", "evidenceCount",
            "sourceSupport", "matchedCompanyIds", "rank", "reason", "evidenceIds", "summary", "reportedAt", "documentSentiments"})
    public record BriefingItem(String title, String eventId, @Schema(nullable = true) String eventTime,
            String timePrecision, List<CompanyLink> companies, int evidenceCount, SourceSupportOut sourceSupport,
            List<String> matchedCompanyIds, int rank, String reason, List<String> evidenceIds,
            @Schema(oneOf = {AnalysisSummary.class, Unavailable.class}) JsonNode summary,
            @Schema(nullable = true) String reportedAt, List<DocumentSentimentRef> documentSentiments) { }

    @Schema(name = "BriefingItemDetail", requiredProperties = {"roundId", "eventId", "title", "summary", "selectionReason",
            "claims", "companies", "evidence", "limitations", "metadata"})
    public record BriefingItemDetail(String roundId, String eventId, String title,
            @Schema(oneOf = {AnalysisSummary.class, Unavailable.class}) JsonNode summary, String selectionReason,
            List<BriefingClaim> claims, List<CompanyLink> companies, List<BriefingItemEvidence> evidence,
            List<String> limitations, BriefingMetadata metadata) { }

    @Schema(name = "BriefingClaim", requiredProperties = {"text", "type", "evidenceIds"})
    public record BriefingClaim(String text, @Schema(allowableValues = {"fact", "plan", "outlook"}) String type,
            List<String> evidenceIds) { }

    @Schema(name = "BriefingItemEvidence", requiredProperties = {"id", "quote", "documentId", "documentVersion", "title",
            "publisher", "url", "publishedAt", "quoteVerified", "sourceKind", "bodySha256", "bodyContext"})
    public record BriefingItemEvidence(String id, String quote, String documentId, String documentVersion, String title,
            String publisher, String url, @Schema(nullable = true) Instant publishedAt, boolean quoteVerified,
            @Schema(allowableValues = {"news", "disclosure"}) String sourceKind, String bodySha256,
            @Schema(nullable = true) BriefingBodyContext bodyContext) { }

    @Schema(name = "BriefingBodyContext", requiredProperties = {"text", "start", "end", "quoteStart", "quoteEnd", "offsetUnit"},
            description = "동일 버전 원문에서 보존한 인용 주변 문맥입니다. 모든 위치는 원문 전체 기준 Unicode code point이며 끝 위치는 제외합니다.")
    public record BriefingBodyContext(String text, int start, int end, int quoteStart, int quoteEnd,
            @Schema(allowableValues = {"unicode_code_point"}) String offsetUnit) { }

    @Schema(name = "CompanyLink")
    public record CompanyLink(String id, String name, @Schema(nullable = true) String role, boolean roleUnconfirmed,
            @Schema(allowableValues = {"INVOLVES", "STRUCTURALLY_RELATED_TO"}) String relationType) { }
    @Schema(name = "SourceSupportOut")
    public record SourceSupportOut(int articleCount, @Schema(nullable = true) Integer knownLineageCount,
            List<String> unknownLineageArticles, @Schema(nullable = true) Integer independentSourceCount, List<List<String>> duplicateGroups) { }
    @Schema(name = "DocumentSentimentRef")
    public record DocumentSentimentRef(String articleId, DocumentSentiment sentiment) { }
    @Schema(name = "DocumentSentiment")
    public record DocumentSentiment(String label, String companyId, String rationale, List<String> quotes, Instant judgedAt,
            String model, String promptVersion) { }
    @Schema(name = "AnalysisSummary", requiredProperties = {"text", "evidenceIds", "generatedAt", "resultVersion"})
    public record AnalysisSummary(String text, List<String> evidenceIds, Instant generatedAt, String resultVersion,
            @Schema(nullable = true, description = "검증된 시장 요약의 구조화된 전망·비교입니다. 기존 이슈 요약과 이전 발행본에는 없을 수 있습니다.") MarketOutlookAnalysis analysis) { }

    @Schema(name = "MarketOutlookAnalysis", requiredProperties = {"schemaVersion", "edition", "cutoff", "mode", "scopeNote", "previousPublication", "coverage", "claims", "forecasts", "forecastEvaluations"})
    public record MarketOutlookAnalysis(String schemaVersion, @Schema(allowableValues = {"morning", "evening"}) String edition,
            Instant cutoff, @Schema(allowableValues = {"morning_update", "evening_review"}) String mode, String scopeNote,
            MarketPreviousPublication previousPublication, MarketCoverage coverage, List<MarketOutlookClaim> claims,
            List<MarketForecast> forecasts, List<MarketForecastEvaluation> forecastEvaluations) { }

    @Schema(name = "MarketPreviousPublication", requiredProperties = {"status", "kind"})
    public record MarketPreviousPublication(@Schema(allowableValues = {"available", "unavailable"}) String status, String kind,
            @Schema(nullable = true) String roundId, @Schema(nullable = true) LocalDate date,
            @Schema(nullable = true) String edition, @Schema(nullable = true) Instant cutoff,
            @Schema(nullable = true) String resultVersion, @Schema(nullable = true) String reason) { }

    @Schema(name = "MarketCoverage", requiredProperties = {"documents", "newDocuments", "backgroundDocuments", "companyNames", "marketRepresentative", "sectorPriceFeedAvailable"})
    public record MarketCoverage(int documents, int newDocuments, int backgroundDocuments, List<String> companyNames,
            boolean marketRepresentative, boolean sectorPriceFeedAvailable) { }

    @Schema(name = "MarketOutlookClaim", requiredProperties = {"claimId", "kind", "text", "evidenceIds", "indicatorIds", "previousPublicationIds", "previousForecastIds", "evaluationIds", "targetId", "direction", "conditions", "counterFactors", "updateAction"})
    public record MarketOutlookClaim(String claimId,
            @Schema(allowableValues = {"fact", "interpretation", "forecast", "forecast_update", "result_comparison"}) String kind,
            String text, List<String> evidenceIds, List<String> indicatorIds, List<String> previousPublicationIds,
            List<String> previousForecastIds, List<String> evaluationIds, @Schema(nullable = true) String targetId,
            @Schema(nullable = true, allowableValues = {"up", "down", "flat", "uncertain"}) String direction,
            List<String> conditions, List<String> counterFactors,
            @Schema(nullable = true, allowableValues = {"maintain", "strengthen", "weaken", "withdraw"}) String updateAction) { }

    @Schema(name = "MarketForecast", requiredProperties = {"forecastId", "text", "direction", "conditions", "counterFactors", "evidenceIds", "indicatorIds", "target"})
    public record MarketForecast(String forecastId, String text, String direction, List<String> conditions,
            List<String> counterFactors, List<String> evidenceIds, List<String> indicatorIds, MarketForecastTarget target) { }

    @Schema(name = "MarketForecastTarget", requiredProperties = {"targetId", "indicatorId", "valueKind", "baselineDate", "baselineValue", "targetDate", "targetEnd", "calendarRef", "rule"})
    public record MarketForecastTarget(String targetId, @Schema(allowableValues = {"kospi", "kosdaq"}) String indicatorId,
            String valueKind, LocalDate baselineDate, BigDecimal baselineValue, LocalDate targetDate,
            Instant targetEnd, String calendarRef, String rule) { }

    @Schema(name = "MarketForecastEvaluation", requiredProperties = {"evaluationId", "forecastId", "target", "rule", "status", "reason", "actualValue", "actualDirection", "directionMatched"})
    public record MarketForecastEvaluation(String evaluationId, String forecastId, MarketForecastTarget target, String rule,
            @Schema(allowableValues = {"evaluated", "unavailable"}) String status, @Schema(nullable = true) String reason,
            @Schema(nullable = true) BigDecimal actualValue, @Schema(nullable = true) String actualDirection,
            @Schema(nullable = true) Boolean directionMatched) { }
    @Schema(name = "Unavailable", requiredProperties = {"status", "reason"})
    public record Unavailable(@Schema(allowableValues = {"unavailable"}) String status, String reason) { }
    @Schema(name = "BriefingWindow", requiredProperties = {"start", "end", "openStart"})
    public record BriefingWindow(@Schema(nullable = true) Instant start, Instant end, boolean openStart) { }
    @Schema(name = "BriefingReferences", requiredProperties = {"eventIds", "evidenceIds", "companyIds"})
    public record BriefingReferences(List<String> eventIds, List<String> evidenceIds, List<String> companyIds) { }
    @Schema(name = "BriefingMetadata", requiredProperties = {"source", "asOf", "graphVersion", "schedule", "selection", "requestId", "partial", "failures"})
    public record BriefingMetadata(String source, Instant asOf, @Schema(nullable = true) String graphVersion, BriefingSchedule schedule,
            BriefingSelection selection, String requestId, boolean partial, List<SectionFailure> failures) { }
    @Schema(name = "BriefingSchedule")
    public record BriefingSchedule(String morning, String evening, boolean confirmed) { }
    @Schema(name = "BriefingSelection")
    public record BriefingSelection(@Schema(allowableValues = {"market"}) String basis, @Schema(nullable = true) String reason) { }
    @Schema(name = "SectionFailure")
    public record SectionFailure(String section, String code, String message, boolean retryable, @Schema(nullable = true) Instant asOf) { }
    @Schema(name = "BriefingOutlook")
    public record BriefingOutlook(String label, String rationale, List<String> issueIds, Instant judgedAt, String model, String promptVersion) { }
    @Schema(name = "BriefingCorrection", requiredProperties = {"id", "eventId", "original", "corrected", "reason", "createdAt"})
    public record BriefingCorrection(long id, @Schema(nullable = true) String eventId, @Schema(nullable = true) String original,
            String corrected, String reason, Instant createdAt) { }
    @Schema(name = "BriefingNotice")
    public record BriefingNotice(@Schema(allowableValues = {"not_ready", "failed", "suspended"}) String kind,
            String message, @Schema(nullable = true) String reason, @Schema(nullable = true) Instant at) { }
    @Schema(name = "MarketVariables")
    public record MarketVariables(@Schema(allowableValues = {"available"}) String status, Instant referenceAt,
            Instant rateCutoffAt, Instant collectedAt, List<MarketIndicator> indicators) { }
    @Schema(name = "MarketIndicator")
    public record MarketIndicator(@Schema(allowableValues = {"kospi", "kosdaq", "usdkrw"}) String id, String label,
            @Schema(allowableValues = {"pt", "KRW"}) String unit,
            @Schema(allowableValues = {"ok", "delayed", "unavailable", "failed"}) String status,
            @Schema(nullable = true) Double value,
            @Schema(nullable = true, allowableValues = {"close", "latest", "reference"},
                    description = "close: 시장 종가, latest: 마감 전 관측값, reference: 은행 고시 기준환율. date-only 고시값의 observedAt은 null입니다.") String valueKind,
            @Schema(nullable = true) LocalDate observedDate, @Schema(nullable = true) Instant observedAt,
            @Schema(nullable = true) IndicatorBaseline baseline, @Schema(nullable = true) Double change,
            @Schema(nullable = true) Double changeRate, @Schema(nullable = true) QuoteSourceOut source,
            @Schema(nullable = true) String reasonCode, @Schema(nullable = true) String reason) { }
    @Schema(name = "IndicatorBaseline")
    public record IndicatorBaseline(double value, LocalDate date, @Schema(nullable = true) String at) { }
    @Schema(name = "QuoteSourceOut")
    public record QuoteSourceOut(String provider, String name, boolean official, @Schema(nullable = true) String delayNote,
            String symbol, @Schema(nullable = true) String url) { }
    @Schema(name = "SinceMorning")
    public record SinceMorning(@Schema(allowableValues = {"available"}) String status, String morningRoundId,
            @Schema(nullable = true) Instant morningPublishedAt, Instant morningDataAsOf, List<SinceMorningItem> items) { }
    @Schema(name = "SinceMorningItem")
    public record SinceMorningItem(String title, String eventId, @Schema(nullable = true) String eventTime, String timePrecision,
            @Schema(nullable = true) String reportedAt, List<String> companyNames,
            @Schema(allowableValues = {"new", "continuing", "dropped"}) String change,
            @Schema(nullable = true) Integer rank, @Schema(nullable = true) Integer morningRank,
            @Schema(nullable = true) Integer evidenceCount, @Schema(nullable = true) Integer morningEvidenceCount) { }

    @Schema(name = "PreviousComparison")
    public record PreviousComparison(@Schema(allowableValues = {"available"}) String status, String previousRoundId,
            Instant previousPublishedAt, Instant previousDataAsOf,
            @Schema(allowableValues = {"event_identity"}) String comparisonBasis, Unavailable forecastEvaluation,
            List<PreviousComparisonItem> items) { }

    @Schema(name = "PreviousComparisonItem")
    public record PreviousComparisonItem(String title, String eventId, @Schema(nullable = true) String eventTime,
            String timePrecision, @Schema(nullable = true) String reportedAt, List<String> companyNames,
            @Schema(allowableValues = {"new", "continuing", "dropped"}) String change,
            @Schema(nullable = true) Integer rank, @Schema(nullable = true) Integer previousRank,
            @Schema(nullable = true) Integer evidenceCount, @Schema(nullable = true) Integer previousEvidenceCount) { }
}
