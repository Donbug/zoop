package com.zoop.briefing.controller;

import java.time.Instant;
import java.time.LocalDate;
import java.util.List;

import io.swagger.v3.oas.annotations.media.Schema;
import tools.jackson.databind.JsonNode;

/** Documentation projections for JSON snapshots; their shape mirrors docs/api/openapi.yaml. */
public final class BriefingHttpSchemas {
    private BriefingHttpSchemas() { }

    @Schema(name = "BriefingResponse", requiredProperties = {"id", "date", "edition", "status", "scheduledAt", "publishedAt",
            "generatedAt", "dataWindow", "dataAsOf", "graphVersion", "items", "marketSummary", "marketVariables",
            "sinceMorning", "emptyReason", "corrections", "notice", "references", "metadata", "outlook"})
    public record BriefingResponse(String id, LocalDate date,
            @Schema(allowableValues = {"morning", "evening"}) String edition,
            @Schema(allowableValues = {"published", "not_ready", "generating", "failed", "suspended"}) String status,
            Instant scheduledAt, @Schema(nullable = true) Instant publishedAt, @Schema(nullable = true) Instant generatedAt,
            @Schema(nullable = true) BriefingWindow dataWindow, @Schema(nullable = true) Instant dataAsOf,
            @Schema(nullable = true) String graphVersion, List<BriefingItem> items,
            @Schema(oneOf = {AnalysisSummary.class, Unavailable.class}) JsonNode marketSummary,
            @Schema(oneOf = {MarketVariables.class, Unavailable.class}) JsonNode marketVariables,
            @Schema(nullable = true, oneOf = {SinceMorning.class, Unavailable.class}) JsonNode sinceMorning,
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
    public record AnalysisSummary(String text, List<String> evidenceIds, Instant generatedAt, String resultVersion) { }
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
            @Schema(nullable = true) Double value, @Schema(nullable = true) String valueKind,
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
}
