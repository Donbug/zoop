package com.zoop.admin.insights;

import java.sql.Timestamp;
import java.nio.charset.StandardCharsets;
import java.util.Base64;
import java.util.UUID;

import com.zoop.auth.service.MemberSessionService;
import com.zoop.common.exception.CustomException;
import com.zoop.telemetry.dto.TelemetryBatchRequest;
import com.zoop.telemetry.TelemetryService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import tools.jackson.databind.ObjectMapper;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

@SpringBootTest(properties = {
        "ZOOP_AUTH_CSRF_ACTIVE_KEY_ID=test",
        "ZOOP_AUTH_CSRF_KEYS=test=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        "zoop.ai.client.enabled=false"
})
@EnabledIfEnvironmentVariable(named = "DB_URL", matches = "jdbc:postgresql:.*")
@Tag("auth-postgres")
@org.springframework.transaction.annotation.Transactional
class InsightsPostgresTest {
    @Autowired JdbcTemplate jdbc;
    @Autowired ObjectMapper mapper;
    @Autowired MemberSessionService sessions;
    @Autowired TelemetryService telemetry;
    @Autowired AdminInsightsService insights;

    private String principal;

    @BeforeEach
    void createGuestAnalyticsPrincipal() {
        var issued = sessions.issueGuest(null, "issue130-test-" + UUID.randomUUID());
        principal = sessions.analyticsPrincipal(issued.token());
    }

    @Test
    void telemetryBatchIsStoredOnceAndIdempotencyConflictsAreRejected() throws Exception {
        String view = "view-" + UUID.randomUUID().toString().substring(0, 12);
        String request = """
                {"events":[
                  {"type":"screen_view","screen":"main","viewId":"%s"},
                  {"type":"graph_node_select","targetId":"NASDAQ:NVDA","viewId":"%s"}
                ]}
                """.formatted(view, view);
        var body = mapper.readValue(request, TelemetryBatchRequest.class);
        String key = "k";

        assertEquals(2, telemetry.record(principal, key, body, "request-a").accepted());
        assertEquals(2, telemetry.record(principal, key, body, "request-b").accepted());
        assertEquals(2, jdbc.queryForObject("SELECT count(*) FROM telemetry_events WHERE principal_key=?",
                Integer.class, principal));

        var changed = mapper.readValue(
                "{\"events\":[{\"type\":\"screen_view\",\"screen\":\"ai\",\"viewId\":\"view-unique-123\"}]}",
                TelemetryBatchRequest.class);
        CustomException exception = assertThrows(CustomException.class,
                () -> telemetry.record(principal, key, changed, "request-c"));
        assertEquals("IDEMPOTENCY_CONFLICT", exception.getErrorCode().name());
        assertEquals(2, jdbc.queryForObject("SELECT count(*) FROM telemetry_events WHERE principal_key=?",
                Integer.class, principal));
    }

    @Test
    void summaryUsesDistinctViewRatesAndOverviewConnectsCurrentFeedback() throws Exception {
        String view = "view-" + UUID.randomUUID().toString().substring(0, 12);
        var body = mapper.readValue("""
                {"events":[
                  {"type":"screen_view","screen":"main","viewId":"%s"},
                  {"type":"graph_node_select","targetId":"NASDAQ:NVDA","viewId":"%s"},
                  {"type":"graph_edge_select","targetId":"edge-1234abcd","viewId":"%s"}
                ]}
                """.formatted(view, view, view), TelemetryBatchRequest.class);
        telemetry.record(principal, "summary-" + UUID.randomUUID(), body, "summary-request");

        var summary = insights.summary("7d", "summary-request");
        var nodeCtr = summary.metrics().stream().filter(metric -> metric.key().equals("nodeCtr")).findFirst().orElseThrow();
        var edgeCtr = summary.metrics().stream().filter(metric -> metric.key().equals("edgeCtr")).findFirst().orElseThrow();
        assertEquals(1L, nodeCtr.numerator());
        assertEquals(1L, nodeCtr.denominator());
        assertEquals(1L, edgeCtr.numerator());
        assertEquals(1L, edgeCtr.denominator());
        assertTrue(nodeCtr.sampleHidden());
        assertEquals(1L, summary.trend().stream().filter(day -> day.date().equals(
                summary.asOf().atZone(java.time.ZoneId.of("Asia/Seoul")).toLocalDate()))
                .findFirst().orElseThrow().edgeSelections());
        var overview = insights.overview("overview-request");
        assertEquals("available", overview.feedback().availability());
        assertEquals(null, overview.feedback().unavailableReason());
        assertEquals(0L, overview.feedback().up());
    }

    @Test
    void telemetryRejectsPersonalDataInRoundIdentifier() throws Exception {
        var body = mapper.readValue("""
                {"events":[{"type":"briefing_issue_open","targetId":"issue-123",
                  "roundId":"user@example.com","viewId":"view-unique-123"}]}
                """, TelemetryBatchRequest.class);

        CustomException exception = assertThrows(CustomException.class,
                () -> telemetry.record(principal, "privacy-" + UUID.randomUUID(), body, "privacy-request"));

        assertEquals("INVALID_REQUEST", exception.getErrorCode().name());
        assertEquals(0, jdbc.queryForObject("SELECT count(*) FROM telemetry_events WHERE principal_key=?",
                Integer.class, principal));
    }

    @Test
    void telemetryAcceptsIdentifierLengthAllowedByContract() throws Exception {
        String targetId = "n".repeat(300);
        var body = mapper.readValue("""
                {"events":[{"type":"graph_node_select","targetId":"%s","viewId":"view-long-id-01"}]}
                """.formatted(targetId), TelemetryBatchRequest.class);

        assertEquals(1, telemetry.record(principal, "k", body, "long-target-request").accepted());
    }

    @Test
    void aiQuestionCountCountsEventsWhileRateUsesDistinctSubmittedViews() throws Exception {
        var beforeMetrics = insights.summary("7d", "ai-count-before").metrics();
        var beforeCount = beforeMetrics.stream().filter(metric -> metric.key().equals("aiQuestions"))
                .findFirst().orElseThrow().count();
        var beforeRate = beforeMetrics.stream().filter(metric -> metric.key().equals("aiQuestionRate"))
                .findFirst().orElseThrow();
        String aiView = "view-ai-" + UUID.randomUUID().toString().substring(0, 8);
        String noScreenView = "view-no-" + UUID.randomUUID().toString().substring(0, 8);
        var body = mapper.readValue("""
                {"events":[
                  {"type":"screen_view","screen":"ai","viewId":"%s"},
                  {"type":"ai_question","targetId":null,"viewId":"%s"},
                  {"type":"ai_question","targetId":null,"viewId":"%s"},
                  {"type":"ai_question","targetId":null,"viewId":"%s"},
                  {"type":"ai_question","targetId":null,"viewId":"%s"}
                ]}
                """.formatted(aiView, aiView, aiView, aiView, noScreenView), TelemetryBatchRequest.class);
        telemetry.record(principal, "ai-count-" + UUID.randomUUID(), body, "ai-count-request");

        var metrics = insights.summary("7d", "ai-count-request").metrics();
        var count = metrics.stream().filter(metric -> metric.key().equals("aiQuestions")).findFirst().orElseThrow();
        var rate = metrics.stream().filter(metric -> metric.key().equals("aiQuestionRate")).findFirst().orElseThrow();

        assertEquals(beforeCount + 4L, count.count());
        assertEquals(beforeRate.numerator() + 1L, rate.numerator());
        assertEquals(beforeRate.denominator() + 1L, rate.denominator());
        assertEquals(rate.denominator() < 5, rate.sampleHidden());
    }

    @Test
    void companyCursorReadsTheOriginalAggregateSnapshotAfterCatalogChanges() {
        var first = insights.companies("7d", null, 1, "snapshot-first");
        assertTrue(first.nextCursor() != null);
        String snapshotId = new String(Base64.getUrlDecoder().decode(first.nextCursor()), StandardCharsets.UTF_8)
                .split("\\|", -1)[0];
        String secondCompanyId = jdbc.queryForObject("""
                SELECT company_id FROM admin_insights_company_snapshot_rows
                WHERE snapshot_id=? AND ordinal=1
                """, String.class, snapshotId);
        String originalName = jdbc.queryForObject("SELECT name FROM companies WHERE id=?", String.class, secondCompanyId);
        Long originalNodeViews = jdbc.queryForObject("""
                SELECT node_views FROM admin_insights_company_snapshot_rows
                WHERE snapshot_id=? AND ordinal=1
                """, Long.class, snapshotId);
        String latePrincipal = "late-snapshot-" + UUID.randomUUID();
        String lateView = "late-view-" + UUID.randomUUID().toString().substring(0, 12);

        try {
            jdbc.update("UPDATE companies SET name=? WHERE id=?", "late-catalog-change", secondCompanyId);
            jdbc.update("""
                    INSERT INTO telemetry_events
                        (principal_key,event_type,screen,target_id,round_id,view_id,occurred_at)
                    VALUES (?, 'graph_node_select', NULL, ?, NULL, ?, ?)
                    """, latePrincipal, secondCompanyId, lateView,
                    Timestamp.from(first.asOf().minusMillis(1)));
            var second = insights.companies("7d", first.nextCursor(), 1, "snapshot-second");

            assertEquals(first.asOf(), second.asOf());
            assertEquals(secondCompanyId, second.items().getFirst().companyId());
            assertEquals(originalName, second.items().getFirst().name());
            assertEquals(originalNodeViews, second.items().getFirst().nodeViews());
        } finally {
            jdbc.update("DELETE FROM telemetry_events WHERE principal_key=?", latePrincipal);
            jdbc.update("UPDATE companies SET name=? WHERE id=?", originalName, secondCompanyId);
        }
    }
}
