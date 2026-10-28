package com.zoop.admin.ai;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.math.BigDecimal;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import com.zoop.common.exception.CustomException;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.jdbc.core.namedparam.SqlParameterSource;

class AiUsageServiceTest {
    private static final Instant NOW = Instant.parse("2026-10-28T12:00:00Z");

    @Test
    void aggregatesDocumentRequestsAndConfirmedExecutionDataWithoutInventingCost() {
        var jdbc = mock(NamedParameterJdbcTemplate.class);
        when(jdbc.queryForMap(anyString(), any(SqlParameterSource.class))).thenAnswer(invocation -> {
            String sql = invocation.getArgument(0);
            SqlParameterSource params = invocation.getArgument(1);
            String stage = params.hasValue("stage") ? String.valueOf(params.getValue("stage")) : "summary";
            if (sql.contains("FROM chat_jobs")) return chatRequestRow();
            if (sql.contains("FROM briefing_attempts")) return briefingRequestRow();
            if (sql.contains("FROM document_analyses")) return requestRow(stage);
            return executionRow();
        });
        when(jdbc.query(anyString(), any(SqlParameterSource.class), any(RowMapper.class))).thenReturn(List.of());

        var response = new AiUsageService(jdbc, Clock.fixed(NOW, ZoneOffset.UTC)).getUsage("24h");

        assertEquals("partial", response.availability());
        assertEquals("24h", response.window());
        assertEquals(5, response.features().size());
        var news = response.features().get(1);
        assertEquals("news-analysis", news.feature());
        assertEquals(3L, news.requests());
        assertEquals(1L, news.succeeded());
        assertEquals(1L, news.failed());
        assertEquals(2L, news.usage().modelCalls());
        assertEquals(120L, news.usage().inputTokens());
        assertEquals(30L, news.usage().outputTokens());
        assertEquals(2L, news.usage().retries());
        assertNull(news.cost().actual());
        assertNull(news.cost().estimated());
        assertEquals("unavailable", news.cost().status());
        assertEquals("briefing", response.features().get(2).feature());
        assertEquals("partial", response.features().get(2).availability());
        org.junit.jupiter.api.Assertions.assertFalse(response.unavailableMetrics().contains("briefing"));
        org.junit.jupiter.api.Assertions.assertTrue(response.unavailableMetrics().contains("briefing.metrics"));
    }

    @Test
    void aggregatesChatRequestsRetriesAndAllStageExecutionsIncludingDetachedLedgerRows() {
        var jdbc = mock(NamedParameterJdbcTemplate.class);
        when(jdbc.queryForMap(anyString(), any(SqlParameterSource.class))).thenAnswer(invocation -> {
            String sql = invocation.getArgument(0);
            if (sql.contains("FROM chat_jobs")) return chatRequestRow();
            if (sql.contains("FROM briefing_attempts")) return briefingRequestRow();
            if (sql.contains("FROM document_analyses")) return requestRow("summary");
            Map<String, Object> row = executionRow();
            return row;
        });
        when(jdbc.query(anyString(), any(SqlParameterSource.class), any(RowMapper.class))).thenReturn(List.of());

        var response = new AiUsageService(jdbc, Clock.fixed(NOW, ZoneOffset.UTC)).getUsage("24h");
        var chat = response.features().get(0);

        assertEquals("chatbot", chat.feature());
        assertEquals("ledger-db", chat.source()); // OpenAPI AiFeature.source (A-ADM-04b)
        assertEquals(4L, chat.requests());
        assertEquals(3L, chat.succeeded());
        assertEquals(1L, chat.failed());
        assertEquals(2L, chat.usage().modelCalls()); // stage executions, across retries
        assertEquals(2L, chat.usage().retries()); // one per retried attempt, regardless of stage count
        assertEquals("partial", chat.availability()); // cost remains unknown without ledger pricing
    }

    @Test
    void preservesConfirmedActualChatCostWhenEstimateIsUnavailable() {
        var jdbc = mock(NamedParameterJdbcTemplate.class);
        when(jdbc.queryForMap(anyString(), any(SqlParameterSource.class))).thenAnswer(invocation -> {
            String sql = invocation.getArgument(0);
            if (sql.contains("FROM chat_jobs")) return chatRequestRow();
            if (sql.contains("FROM briefing_attempts")) return briefingRequestRow();
            if (sql.contains("FROM document_analyses")) return requestRow("summary");
            Map<String, Object> row = executionRow();
            row.put("missing_actual", 0L);
            row.put("actual_cost", new BigDecimal("0.25"));
            row.put("currencies", 1L);
            row.put("currency", "USD");
            return row;
        });
        when(jdbc.query(anyString(), any(SqlParameterSource.class), any(RowMapper.class))).thenReturn(List.of());

        var chat = new AiUsageService(jdbc, Clock.fixed(NOW, ZoneOffset.UTC)).getUsage("7d").features().get(0);
        assertEquals(new BigDecimal("0.25"), chat.cost().actual());
        assertNull(chat.cost().estimated());
        assertEquals("unavailable", chat.cost().status());
        org.junit.jupiter.api.Assertions.assertTrue(chat.unavailableMetrics().contains("cost.estimated"));
    }

    @Test
    void uncertainProviderOutcomesMakeTheAffectedTotalsNull() {
        var jdbc = mock(NamedParameterJdbcTemplate.class);
        when(jdbc.queryForMap(anyString(), any(SqlParameterSource.class))).thenAnswer(invocation -> {
            String sql = invocation.getArgument(0);
            SqlParameterSource params = invocation.getArgument(1);
            String stage = params.hasValue("stage") ? String.valueOf(params.getValue("stage")) : "summary";
            if (sql.contains("FROM chat_jobs")) return chatRequestRow();
            if (sql.contains("FROM briefing_attempts")) return briefingRequestRow();
            if (sql.contains("FROM document_analyses")) return requestRow(stage);
            Map<String, Object> row = executionRow();
            row.put("uncertain_calls", 1L);
            return row;
        });
        when(jdbc.query(anyString(), any(SqlParameterSource.class), any(RowMapper.class))).thenReturn(List.of());

        var response = new AiUsageService(jdbc, Clock.fixed(NOW, ZoneOffset.UTC)).getUsage("7d");
        var news = response.features().get(1);

        assertNull(news.usage().modelCalls());
        assertNull(news.usage().inputTokens());
        assertNull(news.usage().outputTokens());
        assertEquals("partial", news.availability());
        assertEquals("7d", response.window());
    }

    @Test
    void aggregatesBriefingAttemptRequestsSeparatelyFromOutlookAndModelExecutions() {
        var jdbc = mock(NamedParameterJdbcTemplate.class);
        when(jdbc.queryForMap(anyString(), any(SqlParameterSource.class))).thenAnswer(invocation -> {
            String sql = invocation.getArgument(0);
            SqlParameterSource params = invocation.getArgument(1);
            if (sql.contains("FROM chat_jobs")) return chatRequestRow();
            if (sql.contains("FROM briefing_attempts")) {
                if (sql.contains("WHERE purpose='generation'")) return briefingRequestRow();
                assertEquals("briefing-outlook", params.getValue("feature"));
                return outlookRequestRow();
            }
            if (sql.contains("FROM document_analyses")) return requestRow("summary");
            Map<String, Object> row = executionRow();
            if (params.hasValue("feature") && "briefing".equals(params.getValue("feature"))) row.put("retries", 1L);
            return row;
        });
        when(jdbc.query(anyString(), any(SqlParameterSource.class), any(RowMapper.class))).thenReturn(List.of());

        var response = new AiUsageService(jdbc, Clock.fixed(NOW, ZoneOffset.UTC)).getUsage("7d");
        var briefing = response.features().get(2);
        var outlook = response.features().get(4);

        assertEquals("briefing", briefing.feature());
        assertEquals(2L, briefing.requests());
        assertEquals(1L, briefing.succeeded());
        assertEquals(1L, briefing.failed());
        assertEquals(2L, briefing.usage().modelCalls());
        assertEquals(1L, briefing.usage().retries());
        assertEquals("briefing-outlook", outlook.feature());
        assertEquals(1L, outlook.requests());
        assertEquals(1L, outlook.succeeded());
        assertEquals(0L, outlook.failed());
    }

    @Test
    void doesNotReportZeroBriefingRequestsWhenPublishedHistoryHasNoUsageAttempt() {
        var jdbc = mock(NamedParameterJdbcTemplate.class);
        when(jdbc.queryForMap(anyString(), any(SqlParameterSource.class))).thenAnswer(invocation -> {
            String sql = invocation.getArgument(0);
            if (sql.contains("FROM chat_jobs")) return chatRequestRow();
            if (sql.contains("FROM briefing_attempts")) {
                if (sql.contains("WHERE purpose='generation'")) {
                    Map<String, Object> row = briefingRequestRow();
                    row.put("unrecorded_publications", 1L);
                    return row;
                }
                return outlookRequestRow();
            }
            if (sql.contains("FROM document_analyses")) return requestRow("summary");
            return executionRow();
        });
        when(jdbc.query(anyString(), any(SqlParameterSource.class), any(RowMapper.class))).thenReturn(List.of());

        var response = new AiUsageService(jdbc, Clock.fixed(NOW, ZoneOffset.UTC)).getUsage("all");
        var briefing = response.features().get(2);

        assertEquals("partial", briefing.availability());
        assertNull(briefing.requests());
        assertNull(briefing.succeeded());
        assertNull(briefing.failed());
        org.junit.jupiter.api.Assertions.assertTrue(briefing.unavailableMetrics().contains("requests"));
    }

    @Test
    void rejectsUnsupportedWindows() {
        var service = new AiUsageService(mock(NamedParameterJdbcTemplate.class), Clock.fixed(NOW, ZoneOffset.UTC));
        assertThrows(CustomException.class, () -> service.getUsage("90d"));
    }

    private static Map<String, Object> requestRow(String stage) {
        Map<String, Object> row = new HashMap<>();
        row.put("requests", 3L);
        row.put("succeeded", stage.equals("summary") ? 1L : 2L);
        row.put("failed", 1L);
        row.put("retries", 2L);
        row.put("latency_avg", 100d);
        row.put("latency_p95", 150d);
        row.put("latency_max", 200d);
        return row;
    }

    private static Map<String, Object> chatRequestRow() {
        Map<String, Object> row = new HashMap<>();
        row.put("requests", 4L);
        row.put("succeeded", 3L);
        row.put("failed", 1L);
        row.put("retries", 2L);
        row.put("latency_avg", 100d);
        row.put("latency_p95", 150d);
        row.put("latency_max", 200d);
        return row;
    }

    private static Map<String, Object> briefingRequestRow() {
        Map<String, Object> row = new HashMap<>();
        row.put("requests", 2L);
        row.put("succeeded", 1L);
        row.put("failed", 1L);
        row.put("latency_avg", 1_200d);
        row.put("latency_p95", 1_500d);
        row.put("latency_max", 1_500d);
        return row;
    }

    private static Map<String, Object> outlookRequestRow() {
        Map<String, Object> row = new HashMap<>();
        row.put("requests", 1L);
        row.put("succeeded", 1L);
        row.put("failed", 0L);
        row.put("latency_avg", 800d);
        row.put("latency_p95", 800d);
        row.put("latency_max", 800d);
        return row;
    }

    private static Map<String, Object> executionRow() {
        Map<String, Object> row = new HashMap<>();
        row.put("sent_calls", 2L);
        row.put("uncertain_calls", 0L);
        row.put("replay_calls", 1L);
        row.put("retries", 0L);
        row.put("missing_input", 0L);
        row.put("missing_output", 0L);
        row.put("input_tokens", 120L);
        row.put("output_tokens", 30L);
        row.put("missing_actual", 2L);
        row.put("missing_estimate", 2L);
        row.put("actual_cost", null);
        row.put("estimated_cost", null);
        row.put("currencies", 0L);
        row.put("currency", null);
        return row;
    }
}
