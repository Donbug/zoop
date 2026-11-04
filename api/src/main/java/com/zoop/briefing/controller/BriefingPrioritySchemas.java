package com.zoop.briefing.controller;

import java.time.Instant;
import java.util.List;
import io.swagger.v3.oas.annotations.media.Schema;

/** Optional saved presentation projections. Publication/owner/source guards are applied before returning them. */
public final class BriefingPrioritySchemas {
    private BriefingPrioritySchemas() { }
    public record PrioritySource(String evidenceId, String quote, String url, Instant publishedAt) { }
    public record PriorityCompany(String companyId, String name, String reason) { }
    public record PriorityPrice(String companyName, String baseline, String latest, String changeRate, String currency, Instant observedAt) { }
    public record PriorityPreviousChange(String status, String text) { }
    public record PriorityJudgmentBasis(String promptVersion, String directionReason, String confidence, String effectSizeStatus) { }
    public record PriorityAnalysis(String companyId, String companyName, String roundId, Instant cutoff, String resultVersion,
        @Schema(allowableValues={"separate_request_same_model"}) String verificationMode,
        @Schema(allowableValues={"positive","negative","mixed","watch"}) String direction,
        String keyPoint, String confirmedFact, String businessImpact, String companyConnection, String forMyStocks,
        String outlook, String nextCheck, @Schema(nullable=true) String positive, @Schema(nullable=true) String negative,
        @Schema(nullable=true) String priceObservation, PriorityPreviousChange previousChange,
        List<String> evidenceIds, PriorityJudgmentBasis judgmentBasis, PriorityComparison comparison) { }
    public record PriorityComparisonBaseline(String issueId, String companyId, String roundId, Instant cutoff,
        String resultVersion, String direction, String businessImpact, String outlook) { }
    public record PriorityComparison(String status, @Schema(nullable=true) PriorityComparisonBaseline baseline) { }
    public record PriorityPriorAnalysis(String companyName, String takeaway, String positive, String negative, List<String> conditions) { }
    public record CommonPriorityItem(String issueId, String kind, int importance, String title, String topicTag,
        String reason, String whyNow, String originRoundId, Instant originCutoff, List<PriorityCompany> companies,
        List<PrioritySource> sources, List<PriorityPrice> prices, String analysisResultVersion, List<PriorityAnalysis> aiAnalyses,
        String analysisWithheldReason) { }
    public record CommonPriorityView(String schemaVersion, String roundId, Instant cutoff, String resultVersion,
        String generationVersion, int candidateCount, int minimumIssues, int minimumShortfall, String status,
        Boolean legacyAnalysisScopeWarning, List<CommonPriorityItem> items) { }
    public record PersonalPriorityItem(String issueId, String kind, String title, String topicTag, String reason,
        String originRoundId, Instant originCutoff, List<PriorityCompany> connections, List<PrioritySource> sources,
        List<PriorityPriorAnalysis> priorAnalysis, @Schema(nullable=true) PriorityPrice price, List<PriorityAnalysis> aiAnalyses,
        String analysisOmittedReason) { }
    public record PersonalPriorityView(String schemaVersion, String roundId, Instant cutoff, String resultVersion,
        List<String> companyIds, int candidateCount, Integer minimumIssues, String status, List<PersonalPriorityItem> items) { }
    public record PrioritySummary(String schemaVersion, String roundId, Instant cutoff, String resultVersion, String text, List<String> evidenceIds) { }
}
