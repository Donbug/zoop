package com.zoop.admin.ai;

import static com.zoop.admin.ai.AiUsageResponse.*;

import java.math.BigDecimal;
import java.sql.Timestamp;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import org.springframework.dao.DataAccessException;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/** FS068 administrator AI usage read model. */
@Service
public class AiUsageService {
    private static final String UNAVAILABLE_COST = "청구 내역 또는 적용 가능한 단가 자료가 없어요.";
    private final NamedParameterJdbcTemplate jdbc;
    private final Clock clock;

    public AiUsageService(NamedParameterJdbcTemplate jdbc, Clock clock) {
        this.jdbc = jdbc;
        this.clock = clock;
    }

    @Transactional(readOnly = true)
    public AiUsageResponse getUsage(String requestedWindow) {
        String window = requestedWindow == null ? "7d" : requestedWindow;
        if (!List.of("24h", "7d", "30d", "all").contains(window)) {
            throw new CustomException(ErrorCode.INVALID_REQUEST);
        }
        Instant asOf = clock.instant();
        Instant from = switch (window) {
            case "24h" -> asOf.minus(Duration.ofHours(24));
            case "7d" -> asOf.minus(Duration.ofDays(7));
            case "30d" -> asOf.minus(Duration.ofDays(30));
            default -> null;
        };

        List<String> unavailable = new ArrayList<>(List.of("briefing", "briefing-outlook", "daily", "members",
                "cost.actual", "cost.estimated"));
        List<Feature> features = new ArrayList<>();
        try {
            Feature chat = chatFeature(from, asOf);
            features.add(chat);
            if (!chat.availability().equals("complete")) unavailable.addAll(chat.unavailableMetrics().stream().map(m -> "chatbot." + m).toList());
        } catch (DataAccessException failure) {
            features.add(unavailable("chatbot", "AI 챗봇", "챗봇 질문·실행 기록을 조회하지 못했어요."));
            unavailable.add("chatbot");
        }
        Feature news = safeDocumentFeature("news-analysis", "뉴스 분석", "문서 요약·의미 검증", from, asOf, "summary");
        features.add(news);
        if (news.availability().equals("unavailable")) unavailable.add("news-analysis");
        else if (news.availability().equals("complete")) unavailable.remove("news-analysis");
        else unavailable.add("news-analysis.metrics");
        Feature briefing = safeBriefingFeature("briefing", "브리핑", "briefing", from, asOf);
        features.add(briefing);
        if (briefing.availability().equals("unavailable")) unavailable.add("briefing");
        else {
            unavailable.remove("briefing");
            if (!briefing.availability().equals("complete")) unavailable.add("briefing.metrics");
        }
        Feature sentiment = safeDocumentFeature("document-sentiment", "문서 기업 판정", "문서 감성·기업 판정", from, asOf,
                "sentiment");
        features.add(sentiment);
        if (sentiment.availability().equals("unavailable")) unavailable.add("document-sentiment");
        else if (sentiment.availability().equals("complete")) unavailable.remove("document-sentiment");
        else unavailable.add("document-sentiment.metrics");
        try {
            Feature outlook = briefingFeature("briefing-outlook", "브리핑 전망", "briefing-outlook", from, asOf);
            features.add(outlook);
            unavailable.remove("briefing-outlook");
            if (!outlook.availability().equals("complete")) unavailable.add("briefing-outlook.metrics");
        } catch (DataAccessException failure) {
            features.add(unavailable("briefing-outlook", "브리핑 전망", "브리핑 전망 사용량 기록을 조회하지 못했어요."));
            unavailable.add("briefing-outlook");
        }
        // Date-series, member counts and price catalog remain outside this slice.
        return new AiUsageResponse("partial", List.copyOf(unavailable), asOf, window, List.copyOf(features), List.of(),
                new Cost("unavailable", null, null, null, UNAVAILABLE_COST), null, null);
    }

    private Feature safeDocumentFeature(String feature, String label, String engine, Instant from, Instant asOf, String stage) {
        try {
            return documentFeature(feature, label, engine, from, asOf, stage);
        } catch (DataAccessException failure) {
            return unavailable(feature, label, "문서 분석 자료를 조회하지 못했어요.");
        }
    }

    private Feature safeBriefingFeature(String feature, String label, String ledgerFeature, Instant from, Instant asOf) {
        try {
            return briefingFeature(feature, label, ledgerFeature, from, asOf);
        } catch (DataAccessException failure) {
            return unavailable(feature, label, "브리핑 사용량 기록을 조회하지 못했어요.");
        }
    }

    private Feature briefingFeature(String feature, String label, String ledgerFeature, Instant from, Instant asOf) {
        var params = new MapSqlParameterSource("from", from == null ? null : Timestamp.from(from))
                .addValue("asOf", Timestamp.from(asOf)).addValue("feature", ledgerFeature);
        String requestSql = ledgerFeature.equals("briefing") ? """
                SELECT count(*) AS requests,
                       count(*) FILTER (WHERE status='completed' AND stages->>'outcome'='available') AS succeeded,
                       count(*) FILTER (WHERE status='failed' OR stages->>'outcome'='failed') AS failed,
                       (SELECT count(*) FROM briefing_rounds r
                         WHERE r.published_at IS NOT NULL AND r.published_at<=:asOf AND (:from IS NULL OR r.published_at>=:from)
                           AND NOT EXISTS (SELECT 1 FROM briefing_attempts old WHERE old.round_id=r.id AND old.purpose='generation'))
                           AS unrecorded_publications,
                       avg(extract(epoch FROM (finished_at-started_at))*1000)
                           FILTER (WHERE finished_at IS NOT NULL AND finished_at>=started_at) AS latency_avg,
                       percentile_cont(0.95) WITHIN GROUP (ORDER BY extract(epoch FROM (finished_at-started_at))*1000)
                           FILTER (WHERE finished_at IS NOT NULL AND finished_at>=started_at) AS latency_p95,
                       max(extract(epoch FROM (finished_at-started_at))*1000)
                           FILTER (WHERE finished_at IS NOT NULL AND finished_at>=started_at) AS latency_max
                  FROM briefing_attempts
                 WHERE purpose='generation' AND started_at<=:asOf AND (:from IS NULL OR started_at>=:from)
                """ : """
                SELECT count(*) AS requests,
                       count(*) FILTER (WHERE stages->'outlook'->>'outcome'='available') AS succeeded,
                       count(*) FILTER (WHERE stages->'outlook'->>'outcome'='failed') AS failed,
                       (SELECT count(*) FROM briefing_rounds r
                         WHERE r.published_at IS NOT NULL AND r.published_at<=:asOf AND (:from IS NULL OR r.published_at>=:from)
                           AND NOT EXISTS (SELECT 1 FROM briefing_attempts old WHERE old.round_id=r.id AND old.purpose='generation'))
                           AS unrecorded_publications,
                       avg(extract(epoch FROM (finished_at-(stages->'outlook'->>'requestedAt')::timestamptz))*1000)
                           FILTER (WHERE finished_at IS NOT NULL AND stages->'outlook'->>'requestedAt' IS NOT NULL
                               AND finished_at >= (stages->'outlook'->>'requestedAt')::timestamptz) AS latency_avg,
                       percentile_cont(0.95) WITHIN GROUP (ORDER BY extract(epoch FROM
                           (finished_at-(stages->'outlook'->>'requestedAt')::timestamptz))*1000)
                           FILTER (WHERE finished_at IS NOT NULL AND stages->'outlook'->>'requestedAt' IS NOT NULL
                               AND finished_at >= (stages->'outlook'->>'requestedAt')::timestamptz) AS latency_p95,
                       max(extract(epoch FROM (finished_at-(stages->'outlook'->>'requestedAt')::timestamptz))*1000)
                           FILTER (WHERE finished_at IS NOT NULL AND stages->'outlook'->>'requestedAt' IS NOT NULL
                               AND finished_at >= (stages->'outlook'->>'requestedAt')::timestamptz) AS latency_max
                  FROM briefing_attempts
                 WHERE stages ? 'outlook' AND stages->'outlook'->>'requestedAt' IS NOT NULL
                   AND (stages->'outlook'->>'requestedAt')::timestamptz<=:asOf
                   AND (:from IS NULL OR (stages->'outlook'->>'requestedAt')::timestamptz>=:from)
                """;
        Map<String, Object> requests = jdbc.queryForMap(requestSql, params);
        Map<String, Object> executions = jdbc.queryForMap("""
                SELECT count(*) FILTER (WHERE execution_mode='live' AND transmission_confirmed=true) AS sent_calls,
                       count(*) FILTER (WHERE execution_mode='live' AND transmission_confirmed IS NULL) AS uncertain_calls,
                       count(*) FILTER (WHERE execution_mode='replay') AS replay_calls,
                       count(DISTINCT retry_unit_id) FILTER (WHERE execution_mode='live' AND retry_unit_id IS NOT NULL) AS retries,
                       count(*) FILTER (WHERE execution_mode='live' AND transmission_confirmed=true AND input_tokens IS NULL) AS missing_input,
                       count(*) FILTER (WHERE execution_mode='live' AND transmission_confirmed=true AND output_tokens IS NULL) AS missing_output,
                       sum(input_tokens) FILTER (WHERE execution_mode='live' AND transmission_confirmed=true) AS input_tokens,
                       sum(output_tokens) FILTER (WHERE execution_mode='live' AND transmission_confirmed=true) AS output_tokens,
                       count(*) FILTER (WHERE execution_mode='live' AND transmission_confirmed=true AND actual_cost IS NULL) AS missing_actual,
                       count(*) FILTER (WHERE execution_mode='live' AND transmission_confirmed=true AND estimated_cost IS NULL) AS missing_estimate,
                       sum(actual_cost) FILTER (WHERE execution_mode='live' AND transmission_confirmed=true) AS actual_cost,
                       sum(estimated_cost) FILTER (WHERE execution_mode='live' AND transmission_confirmed=true) AS estimated_cost,
                       count(DISTINCT currency) FILTER (WHERE actual_cost IS NOT NULL OR estimated_cost IS NOT NULL) AS currencies,
                       min(currency) FILTER (WHERE actual_cost IS NOT NULL OR estimated_cost IS NOT NULL) AS currency
                  FROM ai_executions
                 WHERE feature=:feature AND briefing_attempt_id IS NOT NULL
                   AND started_at<=:asOf AND (:from IS NULL OR started_at>=:from)
                """, params);
        long uncertain = number(executions, "uncertain_calls"), sent = number(executions, "sent_calls");
        boolean usageComplete = uncertain == 0 && number(executions, "missing_input") == 0 && number(executions, "missing_output") == 0;
        List<String> missing = new ArrayList<>();
        if (uncertain > 0) missing.addAll(List.of("usage.modelCalls", "usage.inputTokens", "usage.outputTokens"));
        else {
            if (number(executions, "missing_input") > 0) missing.add("usage.inputTokens");
            if (number(executions, "missing_output") > 0) missing.add("usage.outputTokens");
        }
        if (uncertain > 0 || number(executions, "missing_actual") > 0 || executions.get("actual_cost") == null) missing.add("cost.actual");
        if (uncertain > 0 || number(executions, "missing_estimate") > 0 || executions.get("estimated_cost") == null) missing.add("cost.estimated");
        if (number(executions, "currencies") > 1) missing.addAll(List.of("cost.actual", "cost.estimated"));
        boolean hasLatency = requests.get("latency_avg") != null;
        boolean sourceIncomplete = number(requests, "unrecorded_publications") > 0;
        if (sourceIncomplete) missing.addAll(List.of("requests", "succeeded", "failed", "latencyMs"));
        if (!hasLatency && number(requests, "requests") > 0) missing.add("latencyMs");
        Latency latency = hasLatency && !sourceIncomplete ? new Latency(decimal(requests, "latency_avg"), decimal(requests, "latency_p95"), decimal(requests, "latency_max")) : null;
        String currency = number(executions, "currencies") == 1 ? (String) executions.get("currency") : null;
        boolean currencyKnown = number(executions, "currencies") <= 1;
        boolean actualKnown = uncertain == 0 && number(executions, "missing_actual") == 0 && currencyKnown;
        boolean estimateKnown = uncertain == 0 && number(executions, "missing_estimate") == 0 && currencyKnown;
        BigDecimal actual = actualKnown ? (BigDecimal) executions.get("actual_cost") : null;
        BigDecimal estimate = estimateKnown ? (BigDecimal) executions.get("estimated_cost") : null;
        Cost cost = new Cost(estimate != null ? "estimated" : "unavailable", actual, estimate, currency,
                actual != null || estimate != null ? "확인된 금액만 포함합니다." : UNAVAILABLE_COST);
        List<RecentError> errors = jdbc.query("""
                SELECT occurred_at, code FROM (
                    SELECT finished_at AS occurred_at, failure_reason AS code FROM briefing_attempts
                     WHERE (purpose=:purpose OR (:purpose='outlook' AND purpose='generation' AND stages ? 'outlook'))
                       AND status='failed' AND finished_at<=:asOf
                       AND (:from IS NULL OR started_at>=:from)
                    UNION ALL
                    SELECT finished_at AS occurred_at, error_code AS code FROM ai_executions
                     WHERE feature=:feature AND briefing_attempt_id IS NOT NULL AND status IN ('failed','unknown')
                       AND started_at<=:asOf AND (:from IS NULL OR started_at>=:from)
                ) errors WHERE occurred_at IS NOT NULL ORDER BY occurred_at DESC LIMIT 10
                """, params.addValue("purpose", ledgerFeature.equals("briefing") ? "generation" : "outlook"),
                (rs, row) -> new RecentError(rs.getTimestamp("occurred_at").toInstant(), rs.getString("code"), null));
        boolean complete = missing.isEmpty();
        List<String> missingMetrics = missing.stream().distinct().toList();
        return new Feature(complete ? "complete" : "partial", missingMetrics, feature, label,
                feature.equals("briefing") ? "브리핑 생성·검증" : "브리핑 전망 생성·검증", true,
                sourceIncomplete ? null : number(requests, "requests"), sourceIncomplete ? null : number(requests, "succeeded"),
                sourceIncomplete ? null : number(requests, "failed"), latency,
                new Usage(uncertain == 0 ? sent : null, usageComplete ? number(executions, "input_tokens") : null,
                        usageComplete ? number(executions, "output_tokens") : null, number(executions, "replay_calls"), number(executions, "retries")),
                cost, "ledger-db", List.copyOf(errors), missing.isEmpty() ? "" :
                        "일부 지표는 원천 기록이 없어 미제공입니다: " + String.join(", ", missingMetrics));
    }

    private Feature chatFeature(Instant from, Instant asOf) {
        var params = new MapSqlParameterSource("from", from == null ? null : Timestamp.from(from))
                .addValue("asOf", Timestamp.from(asOf));
        Map<String, Object> requests = jdbc.queryForMap("""
                SELECT count(*) AS requests,
                       count(*) FILTER (WHERE status = 'completed') AS succeeded,
                       count(*) FILTER (WHERE status = 'failed') AS failed,
                       (SELECT count(*) FROM chat_jobs j2 CROSS JOIN LATERAL jsonb_array_elements(j2.attempts) a
                         WHERE j2.created_at <= :asOf AND (:from IS NULL OR j2.created_at >= :from)
                           AND COALESCE((a ->> 'n')::integer, 1) > 1
                           AND COALESCE((a ->> 'modelCalled')::boolean, false)) AS retries,
                       avg(extract(epoch FROM (finished_at - created_at)) * 1000)
                           FILTER (WHERE status IN ('completed', 'failed')) AS latency_avg,
                       percentile_cont(0.95) WITHIN GROUP (ORDER BY extract(epoch FROM (finished_at - created_at)) * 1000)
                           FILTER (WHERE status IN ('completed', 'failed')) AS latency_p95,
                       max(extract(epoch FROM (finished_at - created_at)) * 1000)
                           FILTER (WHERE status IN ('completed', 'failed')) AS latency_max
                  FROM chat_jobs
                 WHERE created_at <= :asOf AND (:from IS NULL OR created_at >= :from)
                """, params);
        Map<String, Object> executions = jdbc.queryForMap("""
                SELECT count(*) FILTER (WHERE execution_mode = 'live'
                           AND (provider_send_state = 'sent' OR receipt_artifact_id IS NOT NULL)) AS sent_calls,
                       count(*) FILTER (WHERE execution_mode = 'live'
                           AND provider_send_state IS DISTINCT FROM 'sent' AND receipt_artifact_id IS NULL) AS uncertain_calls,
                       count(*) FILTER (WHERE execution_mode = 'replay') AS replay_calls,
                       count(*) FILTER (WHERE execution_mode = 'live'
                           AND (provider_send_state = 'sent' OR receipt_artifact_id IS NOT NULL) AND input_tokens IS NULL) AS missing_input,
                       count(*) FILTER (WHERE execution_mode = 'live'
                           AND (provider_send_state = 'sent' OR receipt_artifact_id IS NOT NULL) AND output_tokens IS NULL) AS missing_output,
                       sum(input_tokens) FILTER (WHERE execution_mode = 'live'
                           AND (provider_send_state = 'sent' OR receipt_artifact_id IS NOT NULL)) AS input_tokens,
                       sum(output_tokens) FILTER (WHERE execution_mode = 'live'
                           AND (provider_send_state = 'sent' OR receipt_artifact_id IS NOT NULL)) AS output_tokens,
                       count(*) FILTER (WHERE execution_mode = 'live'
                           AND (provider_send_state = 'sent' OR receipt_artifact_id IS NOT NULL) AND actual_cost IS NULL) AS missing_actual,
                       count(*) FILTER (WHERE execution_mode = 'live'
                           AND (provider_send_state = 'sent' OR receipt_artifact_id IS NOT NULL) AND estimated_cost IS NULL) AS missing_estimate,
                       sum(actual_cost) FILTER (WHERE execution_mode = 'live'
                           AND (provider_send_state = 'sent' OR receipt_artifact_id IS NOT NULL)) AS actual_cost,
                       sum(estimated_cost) FILTER (WHERE execution_mode = 'live'
                           AND (provider_send_state = 'sent' OR receipt_artifact_id IS NOT NULL)) AS estimated_cost,
                       count(DISTINCT currency) FILTER (WHERE actual_cost IS NOT NULL OR estimated_cost IS NOT NULL) AS currencies,
                       min(currency) FILTER (WHERE actual_cost IS NOT NULL OR estimated_cost IS NOT NULL) AS currency
                  FROM ai_executions
                 WHERE feature = 'chatbot' AND started_at <= :asOf AND (:from IS NULL OR started_at >= :from)
                """, params);
        long uncertain = number(executions, "uncertain_calls"), sent = number(executions, "sent_calls");
        boolean usageComplete = uncertain == 0 && number(executions, "missing_input") == 0 && number(executions, "missing_output") == 0;
        List<String> missing = new ArrayList<>();
        if (uncertain > 0) missing.addAll(List.of("usage.modelCalls", "usage.inputTokens", "usage.outputTokens"));
        else {
            if (number(executions, "missing_input") > 0) missing.add("usage.inputTokens");
            if (number(executions, "missing_output") > 0) missing.add("usage.outputTokens");
        }
        if (number(executions, "missing_actual") > 0 || uncertain > 0 || executions.get("actual_cost") == null) missing.add("cost.actual");
        if (number(executions, "missing_estimate") > 0 || uncertain > 0 || executions.get("estimated_cost") == null) missing.add("cost.estimated");
        if (number(executions, "currencies") > 1) missing.addAll(List.of("cost.actual", "cost.estimated"));
        boolean hasLatency = requests.get("latency_avg") != null;
        if (!hasLatency && number(requests, "requests") > 0) missing.add("latencyMs");
        Latency latency = hasLatency ? new Latency(decimal(requests, "latency_avg"), decimal(requests, "latency_p95"), decimal(requests, "latency_max")) : null;
        String currency = number(executions, "currencies") == 1 ? (String) executions.get("currency") : null;
        boolean actualKnown = number(executions, "missing_actual") == 0 && uncertain == 0 && number(executions, "currencies") == 1;
        boolean estimateKnown = number(executions, "missing_estimate") == 0 && uncertain == 0 && number(executions, "currencies") == 1;
        BigDecimal actual = actualKnown ? (BigDecimal) executions.get("actual_cost") : null;
        BigDecimal estimate = estimateKnown ? (BigDecimal) executions.get("estimated_cost") : null;
        Cost cost = new Cost(estimate != null ? "estimated" : "unavailable", actual, estimate, currency,
                actual != null || estimate != null ? "확인된 금액만 포함합니다." : UNAVAILABLE_COST);
        List<RecentError> errors = jdbc.query("""
                SELECT finished_at, failure ->> 'code' AS code FROM chat_jobs
                 WHERE status = 'failed' AND created_at <= :asOf AND (:from IS NULL OR created_at >= :from)
                 ORDER BY finished_at DESC LIMIT 10
                """, params, (rs, row) -> new RecentError(rs.getTimestamp("finished_at").toInstant(), rs.getString("code"), null));
        return new Feature(missing.isEmpty() ? "complete" : "partial", List.copyOf(missing), "chatbot", "AI 챗봇",
                "단계별 AI 모델 호출", true, number(requests, "requests"), number(requests, "succeeded"), number(requests, "failed"), latency,
                new Usage(uncertain == 0 ? sent : null, usageComplete ? number(executions, "input_tokens") : null,
                        usageComplete ? number(executions, "output_tokens") : null, number(executions, "replay_calls"), number(requests, "retries")),
                cost, "ledger-db", List.copyOf(errors), missing.isEmpty() ? "" : "일부 지표는 원천 기록이 없어 미제공입니다: " + String.join(", ", missing));
    }

    private Feature documentFeature(String feature, String label, String engine, Instant from, Instant asOf, String stage) {
        var params = new MapSqlParameterSource("stage", stage).addValue("from", from == null ? null : Timestamp.from(from))
                .addValue("asOf", Timestamp.from(asOf)).addValue("feature", feature);
        Map<String, Object> requests = jdbc.queryForMap("""
                SELECT count(*) AS requests,
                       count(*) FILTER (WHERE status = 'available') AS succeeded,
                       count(*) FILTER (WHERE status = 'failed') AS failed,
                       count(*) FILTER (WHERE request_no > 1) AS retries,
                       avg(extract(epoch FROM (updated_at - created_at)) * 1000)
                           FILTER (WHERE status IN ('available', 'failed') AND updated_at >= created_at) AS latency_avg,
                       percentile_cont(0.95) WITHIN GROUP (ORDER BY extract(epoch FROM (updated_at - created_at)) * 1000)
                           FILTER (WHERE status IN ('available', 'failed') AND updated_at >= created_at) AS latency_p95,
                       max(extract(epoch FROM (updated_at - created_at)) * 1000)
                           FILTER (WHERE status IN ('available', 'failed') AND updated_at >= created_at) AS latency_max
                  FROM document_analyses
                 WHERE stage = :stage AND status <> 'not_requested'
                   AND created_at <= :asOf AND (:from IS NULL OR created_at >= :from)
                """, params);
        Map<String, Object> executions = jdbc.queryForMap("""
                SELECT count(*) FILTER (WHERE execution_mode = 'live'
                           AND (provider_send_state = 'sent' OR receipt_artifact_id IS NOT NULL)) AS sent_calls,
                       count(*) FILTER (WHERE execution_mode = 'live'
                           AND provider_send_state IS DISTINCT FROM 'sent'
                           AND receipt_artifact_id IS NULL) AS uncertain_calls,
                       count(*) FILTER (WHERE execution_mode = 'replay') AS replay_calls,
                       count(*) FILTER (WHERE execution_mode = 'live'
                           AND (provider_send_state = 'sent' OR receipt_artifact_id IS NOT NULL)
                           AND input_tokens IS NULL) AS missing_input,
                       count(*) FILTER (WHERE execution_mode = 'live'
                           AND (provider_send_state = 'sent' OR receipt_artifact_id IS NOT NULL)
                           AND output_tokens IS NULL) AS missing_output,
                       sum(input_tokens) FILTER (WHERE execution_mode = 'live'
                           AND (provider_send_state = 'sent' OR receipt_artifact_id IS NOT NULL)) AS input_tokens,
                       sum(output_tokens) FILTER (WHERE execution_mode = 'live'
                           AND (provider_send_state = 'sent' OR receipt_artifact_id IS NOT NULL)) AS output_tokens,
                       count(*) FILTER (WHERE execution_mode = 'live'
                           AND (provider_send_state = 'sent' OR receipt_artifact_id IS NOT NULL)
                           AND actual_cost IS NULL) AS missing_actual,
                       count(*) FILTER (WHERE execution_mode = 'live'
                           AND (provider_send_state = 'sent' OR receipt_artifact_id IS NOT NULL)
                           AND estimated_cost IS NULL) AS missing_estimate,
                       sum(actual_cost) FILTER (WHERE execution_mode = 'live'
                           AND (provider_send_state = 'sent' OR receipt_artifact_id IS NOT NULL)) AS actual_cost,
                       sum(estimated_cost) FILTER (WHERE execution_mode = 'live'
                           AND (provider_send_state = 'sent' OR receipt_artifact_id IS NOT NULL)) AS estimated_cost,
                       count(DISTINCT currency) FILTER (WHERE actual_cost IS NOT NULL OR estimated_cost IS NOT NULL) AS currencies,
                       min(currency) FILTER (WHERE actual_cost IS NOT NULL OR estimated_cost IS NOT NULL) AS currency
                  FROM ai_executions
                 WHERE feature = :feature AND started_at <= :asOf AND (:from IS NULL OR started_at >= :from)
                """, params);

        long uncertain = number(executions, "uncertain_calls");
        long sent = number(executions, "sent_calls");
        boolean usageComplete = uncertain == 0 && number(executions, "missing_input") == 0
                && number(executions, "missing_output") == 0;
        Long calls = uncertain == 0 ? sent : null;
        Long input = usageComplete ? number(executions, "input_tokens") : null;
        Long output = usageComplete ? number(executions, "output_tokens") : null;
        Long retries = number(requests, "retries");
        List<String> missing = new ArrayList<>();
        if (uncertain > 0) missing.addAll(List.of("usage.modelCalls", "usage.inputTokens", "usage.outputTokens"));
        else {
            if (number(executions, "missing_input") > 0) missing.add("usage.inputTokens");
            if (number(executions, "missing_output") > 0) missing.add("usage.outputTokens");
        }
        if (number(executions, "missing_actual") > 0 || number(executions, "uncertain_calls") > 0) missing.add("cost.actual");
        if (number(executions, "missing_estimate") > 0 || number(executions, "uncertain_calls") > 0) missing.add("cost.estimated");
        if (number(executions, "currencies") > 1) missing.addAll(List.of("cost.actual", "cost.estimated"));
        boolean hasLatency = requests.get("latency_avg") != null;
        if (!hasLatency && number(requests, "requests") > 0) missing.add("latencyMs");
        Latency latency = hasLatency ? new Latency(decimal(requests, "latency_avg"), decimal(requests, "latency_p95"),
                decimal(requests, "latency_max")) : null;
        String currency = number(executions, "currencies") == 1 ? (String) executions.get("currency") : null;
        boolean currencyKnown = number(executions, "currencies") <= 1;
        boolean actualKnown = number(executions, "missing_actual") == 0 && uncertain == 0 && currencyKnown;
        boolean estimateKnown = number(executions, "missing_estimate") == 0 && uncertain == 0 && currencyKnown;
        if (executions.get("actual_cost") == null) missing.add("cost.actual");
        if (executions.get("estimated_cost") == null) missing.add("cost.estimated");
        Cost cost = new Cost(estimateKnown && executions.get("estimated_cost") != null ? "estimated" : "unavailable",
                actualKnown ? (BigDecimal) executions.get("actual_cost") : null,
                estimateKnown ? (BigDecimal) executions.get("estimated_cost") : null, currency,
                actualKnown && estimateKnown ? "확인된 청구액·단가만 포함합니다." : UNAVAILABLE_COST);
        List<RecentError> errors = jdbc.query("""
                SELECT updated_at, reason FROM document_analyses
                 WHERE stage = :stage AND status = 'failed' AND created_at <= :asOf
                   AND (:from IS NULL OR created_at >= :from)
                 ORDER BY updated_at DESC LIMIT 10
                """, params, (rs, row) -> new RecentError(rs.getTimestamp("updated_at").toInstant(), rs.getString("reason"), null));
        boolean complete = missing.isEmpty();
        return new Feature(complete ? "complete" : "partial", List.copyOf(missing), feature, label, engine, true,
                number(requests, "requests"), number(requests, "succeeded"), number(requests, "failed"), latency,
                new Usage(calls, input, output, number(executions, "replay_calls"), retries), cost, "document",
                List.copyOf(errors), note(missing, hasLatency));
    }

    private static Feature unavailable(String feature, String label, String note) {
        String source = switch (feature) {
            case "chatbot" -> "ledger-db";
            case "briefing", "briefing-outlook" -> "ledger-db";
            default -> "document";
        };
        return new Feature("unavailable", List.of("all"), feature, label, "아직 집계할 수 없어요", false, null, null, null,
                null, new Usage(null, null, null, null, null), new Cost("unavailable", null, null, null, note),
                source, null, note);
    }

    private static String note(List<String> missing, boolean hasLatency) {
        List<String> all = new ArrayList<>(missing);
        if (!hasLatency) all.add("latencyMs");
        return all.isEmpty() ? "" : "일부 지표는 원천 기록이 없어 미제공입니다: " + String.join(", ", all);
    }

    private static long number(Map<String, Object> row, String key) {
        Object value = row.get(key);
        return value instanceof Number n ? n.longValue() : 0L;
    }

    private static double decimal(Map<String, Object> row, String key) {
        Object value = row.get(key);
        return value instanceof Number n ? n.doubleValue() : 0d;
    }
}
