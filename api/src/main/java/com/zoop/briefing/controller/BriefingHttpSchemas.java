package com.zoop.briefing.controller;

import java.time.Instant;
import java.time.LocalDate;
import java.math.BigDecimal;
import java.util.List;
import java.util.Map;

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
            @Schema(description = "선정 기업별 조건부 사업 전망. 과거 발행본에는 없을 수 있습니다.", implementation = CompanyOutlooks.class) JsonNode companyOutlooks,
            @Schema(nullable = true, description = "출근 오늘 집중·퇴근 장 평가/아침 기업 점검/다음 거래일 관찰. 원문 대조 편집 검토이며 자동 모델 검증으로 표시하지 않습니다.", implementation = EditionReview.class) JsonNode editionReview,
            @Schema(nullable = true, description = "토스 보존 시세로 계산한 회차별 기업 흐름과 기사 전후 관측. 사업 판단·인과·예측 적중과 구분합니다.", implementation = BriefingPriceContext.class) JsonNode companyPriceContext,
            @Schema(nullable = true, description = "실제 가격과 원문으로 새로 생성·독립 검증한 v5 기업 전망. 기존 편집 검토본과 구분합니다.", implementation = AiPriceOutlooks.class) JsonNode aiPriceOutlooks,
            @Schema(nullable = true, description = "근거·실제 직전 판단에 결속된 산업 판단 갱신. selected와 이전 기업 watch를 구분하고 자동 검증 및 편집 범위를 표시합니다.", implementation = JudgmentUpdate.class) JsonNode judgmentUpdate,
            @Schema(oneOf = {MarketVariables.class, Unavailable.class}) JsonNode marketVariables,
            @Schema(nullable = true, oneOf = {SinceMorning.class, Unavailable.class}) JsonNode sinceMorning,
            @Schema(nullable = true, oneOf = {PreviousComparison.class, Unavailable.class},
                    description = "직전 발행 회차와 사건 ID 기준 포함 여부 비교입니다. 전망 정확도 평가는 제공하지 않습니다.") JsonNode previousComparison,
            @Schema(nullable = true, allowableValues = {"no_issues_in_window"}) String emptyReason,
            List<BriefingCorrection> corrections, @Schema(nullable = true) BriefingNotice notice,
            BriefingReferences references, BriefingMetadata metadata, @Schema(nullable = true) BriefingOutlook outlook,
            @Schema(nullable = true, description = "선택적 조용한 회차 정책. 핵심·참고·복기·수집부족을 구분하며 원 발행 문안을 바꾸지 않습니다.") BriefingContinuity continuity) { }


    @Schema(name = "AiPriceOutlooks")
    public record AiPriceOutlooks(String schemaVersion, String model, String promptVersion, String verificationMode, String status,
            String roundId, LocalDate date, String edition, Instant cutoff, String resultVersion, Instant generatedAt,
            String inputSha256, String reviewVersion, String priceContextVersion, List<AiPriceCompany> companies,
            @Schema(nullable = true) String generationRequestDigest, @Schema(nullable = true) String verificationRequestDigest,
            @Schema(nullable = true) String projectionSha256, @Schema(nullable = true) String historyNote,
            @Schema(nullable = true) String supersedesResultVersion) { }
    public record AiPriceCompany(String companyId, String companyName, String role, String assessment,
            CompanyStatement impact, CompanyStatement outlook, List<CompanyStatement> conditions, List<CompanyStatement> risks,
            JsonNode comparison, JsonNode previous) { }

    @Schema(name = "BriefingPriceContext")
    public record BriefingPriceContext(String schemaVersion, String status, String roundId, LocalDate date, String edition,
            Instant cutoff, String reviewVersion, String resultVersion, Instant generatedAt, String authorship,
            String scopeNote, List<PriceContextCompany> companies,
            @Schema(nullable = true) String outlookIntegrationVersion, @Schema(nullable = true) PriceMarketReference marketReference) { }
    public record PriceContextPoint(String value, Instant observedAt, String kind) { }
    public record PriceContextDay(@Schema(nullable = true) String baselineDate, @Schema(nullable = true) String baselineClose,
            @Schema(nullable = true) String changeRatePercent, String kind, String open, String high, String low, String closeOrLast,
            @Schema(nullable = true) String volume, Instant from, Instant to) { }
    public record PriceContextNews(String evidenceId, Instant publishedAt, String timing, String status, Integer postNewsBars,
            @Schema(nullable = true) PriceContextPoint before, @Schema(nullable = true) String changeRatePercent, String observation) { }
    public record PriceContextMorning(String status, String observation, @Schema(nullable = true) PriceContextPoint before,
            @Schema(nullable = true) String changeRatePercent) { }
    public record PriceContextCompany(String companyId, String companyName, String currency, String provider, Instant cutoff,
            List<String> responseSha256s, String status, @Schema(nullable = true) String reason, LocalDate sessionDate,
            String exchangeTimezone, Boolean completeSession, Integer barCount, PriceContextPoint latest, PriceContextDay day,
            String summary, String flow, List<PriceContextNews> news, PriceContextMorning sinceMorning, String interpretation, String limitation,
            @Schema(nullable = true) PriceAwareOutlook outlook) { }
    public record PriceAwareOutlook(String schemaVersion, String authorship, String stance, CompanyStatement businessJudgment,
            String priceObservation, String nextCheck, String takeaway, String text, String marketNote, List<String> evidenceIds) { }
    public record PriceMarketReference(String status, String snapshotSha256, List<PriceMarketIndicator> indicators, String note) { }
    public record PriceMarketIndicator(String id, String label, BigDecimal value, String unit, String valueKind, LocalDate observedDate,
            @Schema(nullable = true) Instant observedAt, String status, JsonNode source, @Schema(nullable = true) LocalDate baselineDate,
            @Schema(nullable = true) String changeRatePercent, String text) { }
    @Schema(name = "EditionReview")
    public record EditionReview(String schemaVersion, String status, String verificationMode, String reviewer, Instant reviewedAt,
            String resultVersion, String roundId, String date, String edition, Instant cutoff, String analysisVersion, String scopeNote,
            JsonNode previousReview, JsonNode sources, JsonNode marketVariables, JsonNode capabilities,
            String headline, EditionStatement summary, EditionStatement marketInterpretation, EditionStatement comparison,
            EditionStatement nextSession, List<EditionCompanyReview> companies) { }
    public record EditionCompanyReview(String companyId, String companyName, String role, List<String> sourceIds, JsonNode previous, JsonNode price,
            String stance, CompanyStatement title, CompanyStatement takeaway, CompanyStatement newInformation, CompanyStatement judgment,
            List<CompanyStatement> watch, CompanyStatement positive, CompanyStatement negative, List<EditionConditionCheck> checks) { }
    public record EditionStatement(String text, List<String> evidenceIds) { }
    public record EditionConditionCheck(String condition, String status, EditionStatement observation) { }

    @Schema(name = "JudgmentUpdate")
    public record JudgmentUpdate(String schemaVersion, String status, String roundId, String edition, Instant cutoff,
            String previousRoundId, Instant previousCutoff, String companyResultVersion, String previousResultVersion,
            String resultVersion, Instant generatedAt, String scopeNote, CompanyStatement conclusion, CompanyStatement industryChange,
            CompanyStatement limits, List<JudgmentCompany> companies, Map<String, JsonNode> sources, JsonNode editorialReview, String reason) { }
    public record JudgmentCompany(String companyId, String companyName, String role, String decision, List<String> sourceIds,
            JsonNode previousJudgment, String previousResultVersion, CompanyStatement newEvidence, CompanyStatement reason,
            CompanyStatement strengthenIf, CompanyStatement weakenIf, CompanyStatement topic, CompanyStatement title, CompanyStatement description) { }

    @Schema(name = "BriefingContinuity")
    public record BriefingContinuity(String schemaVersion, String roundId, Instant cutoff,
            @Schema(allowableValues = {"core", "reference", "recap", "coverage_limited", "validation_failed"}) String mode,
            @Schema(nullable = true, allowableValues = {"1", "2"}) Integer importanceFloor, String message,
            ContinuityCoverage coverage, List<ContinuityReference> references, ContinuityRecap recap,
            List<ContinuityCondition> watchConditions, ContinuityForecast forecast) { }
    public record ContinuityCoverage(@Schema(allowableValues = {"registered_scope", "limited", "insufficient"}) String status,
            int confirmedDocuments, String message) { }
    public record ContinuityReference(String issueId, String title, int importance, String label,
            List<ContinuityCompany> companies, List<tools.jackson.databind.JsonNode> sources) { }
    public record ContinuityCompany(String id, String name) { }
    public record ContinuityRecap(String status, @Schema(nullable = true) String previousRoundId,
            @Schema(nullable = true) Instant dataAsOf, @Schema(nullable = true) LocalDate date,
            @Schema(nullable = true) String edition, String message, List<BriefingItem> items) { }
    public record ContinuityCondition(String text, String kind, @Schema(nullable = true) String companyName,
            @Schema(nullable = true) String previousRoundId) { }
    public record ContinuityForecast(String status, String message) { }

    @Schema(name = "BriefingRecap", requiredProperties = {"roundId", "graphVersion", "dataAsOf", "status", "reason", "message", "previous"})
    public record BriefingRecap(String roundId, @Schema(nullable = true) String graphVersion,
            @Schema(nullable = true) Instant dataAsOf,
            @Schema(allowableValues = {"available", "unavailable", "not_applicable"}) String status,
            @Schema(nullable = true) String reason, String message,
            @Schema(nullable = true, description = "고정 참조의 과거 발행 원문. 새 이슈 또는 이번 회차 재평가가 아닙니다.") BriefingResponse previous) { }

    @Schema(name = "CompanyOutlooks", requiredProperties = {"schemaVersion", "roundId", "edition", "cutoff", "status", "resultVersion", "generatedAt", "scopeNote", "companies"})
    public record CompanyOutlooks(String schemaVersion, String roundId, String edition, Instant cutoff,
            @Schema(allowableValues = {"PASS", "WITHHELD"}) String status, String resultVersion, Instant generatedAt,
            String scopeNote, List<CompanyOutlook> companies, String reason,
            @Schema(description = "기존 기업 전망·짧은 읽기를 재생성하지 않고 연결한 회차 시세 보완본의 버전. 과거 발행본에서는 생략.") String priceVersion) { }

    @Schema(name = "CompanyStatement", requiredProperties = {"text", "evidenceIds"})
    public record CompanyStatement(String text, List<String> evidenceIds) { }
    @Schema(name = "CompanyComparison", requiredProperties = {"text", "evidenceIds", "status", "previousResultVersion"})
    public record CompanyComparison(String text, List<String> evidenceIds,
            @Schema(allowableValues = {"updated", "compared", "unavailable"}) String status,
            @Schema(nullable = true) String previousResultVersion) { }
    @Schema(name = "CompanyOutlookSource", requiredProperties = {"evidenceId", "documentId", "documentVersion", "bodySha256", "quote", "title", "url", "publishedAt"})
    public record CompanyOutlookSource(String evidenceId, String documentId, String documentVersion, String bodySha256,
            String quote, String title, String url, Instant publishedAt) { }
    @Schema(name = "CompanyOutlook", requiredProperties = {"companyId", "companyName", "issueIds", "facts", "assessment", "impact", "outlook", "conditions", "risks", "comparison", "previous", "observedMovement", "sources"})
    public record CompanyOutlook(String companyId, String companyName, List<String> issueIds, List<CompanyStatement> facts,
            @Schema(allowableValues = {"positive", "negative", "mixed", "watch"}) String assessment,
            CompanyStatement impact, CompanyStatement outlook, List<CompanyStatement> conditions, List<CompanyStatement> risks,
            CompanyComparison comparison, JsonNode previous, JsonNode observedMovement, List<CompanyOutlookSource> sources,
            CompanyShortReading reading, CompanyPrice price, CompanyBriefingCard card) { }

    @Schema(name = "CompanyBriefingCard", requiredProperties = {"schemaVersion", "status", "resultVersion"},
            description = "전문을 보존하고 별도 생성·독립 검증한 카드입니다. PASS일 때 주제12자·제목32자·보조 설명64자 이내 문안을 표시합니다.")
    public record CompanyBriefingCard(@Schema(allowableValues = {"zoop-company-card-v1"}) String schemaVersion,
            @Schema(allowableValues = {"PASS", "WITHHELD"}) String status, String resultVersion,
            CompanyStatement topic, CompanyStatement title, CompanyStatement description) { }

    @Schema(name = "CompanyShortReading", requiredProperties = {"status", "resultVersion"},
            description = "검증된 전문과 별도로 생성·검증한 짧은 읽기입니다. PASS일 때만 제공합니다. v2는 판단·새 사실·다음 확인·배경·이전 판단 비교를 구분합니다.")
    public record CompanyShortReading(@Schema(allowableValues = {"PASS", "WITHHELD"}) String status, String resultVersion,
            CompanyStatement brief, CompanyStatement watch, CompanyStatement change,
            @Schema(description = "v2의 버전 표기. 기존 v1에서는 생략.", allowableValues = {"zoop-company-reading-v2"}) String schemaVersion,
            CompanyStatement fact, CompanyStatement background) { }
    @Schema(name = "CompanyPricePoint", requiredProperties = {"value", "observedAt", "sessionDate", "kind"})
    public record CompanyPricePoint(String value, Instant observedAt, LocalDate sessionDate,
            @Schema(allowableValues = {"five_minute_close", "daily_close"}) String kind) { }
    @Schema(name = "CompanyPriceSource", requiredProperties = {"companyId", "interval", "url", "httpStatus", "sha256", "bytes", "collectedAt"})
    public record CompanyPriceSource(String companyId, String interval, String url, int httpStatus, String sha256, long bytes, Instant collectedAt,
            @Schema(description = "새 회차 시세 수집의 요청 시작 UTC Unix 초. 구 기록에서는 생략.") Long period1,
            @Schema(description = "요청 종료 UTC Unix 초(미포함). 가격 관측은 별도로 회차 마감 이하만 허용.") Long period2) { }
    @Schema(name = "CompanyPrice", requiredProperties = {"companyId", "cutoff", "currency", "exchangeTimezone", "source", "official", "note", "sources", "status", "reason", "latest", "baseline", "comparisonStatus", "change", "changeRate"},
            description = "회차 마감 전 완료된 정규장 관측값입니다. 출근은 전일 종가 대비, 퇴근은 같은 날 09:20 기준 대비이며 전망 적중률이 아닙니다.")
    public record CompanyPrice(String companyId, Instant cutoff, String currency, String exchangeTimezone, String source,
            boolean official, String note, List<CompanyPriceSource> sources, String status,
            @Schema(nullable = true, description = "eligible_price_missing: 정상 조회 후 적격 관측 없음; provider_request_failed: 관측이 없고 공급자 HTTP 요청 실패; provider_history_unverified: 이력 검증 실패") String reason, @Schema(nullable = true) CompanyPricePoint latest,
            @Schema(nullable = true) CompanyPricePoint baseline, String baselineKind, String comparisonStatus,
            @Schema(nullable = true) String change, @Schema(nullable = true) String changeRate) { }

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
            @Schema(nullable = true) String graphVersion, List<String> keyIssueIds, List<String> companyIds, long correctionCount,
            @Schema(nullable = true, allowableValues = {"snapshot_not_recorded", "snapshot_unavailable", "briefing_targets_unavailable"})
            String unavailableReason,
            @Schema(nullable = true, allowableValues = {"publication_snapshot", "reconstructed"}) String graphOrigin,
            @Schema(nullable = true) Instant reconstructedAt) { }

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
            LocalDate previousDate, @Schema(allowableValues = {"morning", "evening"}) String previousEdition,
            @Schema(allowableValues = {"event_identity"}) String comparisonBasis, Unavailable forecastEvaluation,
            List<PreviousComparisonItem> items) { }

    @Schema(name = "PreviousComparisonItem")
    public record PreviousComparisonItem(String title, String eventId, @Schema(nullable = true) String eventTime,
            String timePrecision, @Schema(nullable = true) String reportedAt, List<String> companyNames,
            @Schema(allowableValues = {"new", "continuing", "dropped"}) String change,
            @Schema(nullable = true) Integer rank, @Schema(nullable = true) Integer previousRank,
            @Schema(nullable = true) Integer evidenceCount, @Schema(nullable = true) Integer previousEvidenceCount) { }
}
