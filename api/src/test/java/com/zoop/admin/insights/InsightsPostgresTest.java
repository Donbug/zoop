package com.zoop.admin.insights;

import java.util.UUID;

import com.zoop.auth.service.MemberSessionService;
import com.zoop.common.exception.CustomException;
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
        var body = mapper.readTree(request);
        String key = "issue130-" + UUID.randomUUID();

        assertEquals(2, telemetry.record(principal, key, body, "request-a").accepted());
        assertEquals(2, telemetry.record(principal, key, body, "request-b").accepted());
        assertEquals(2, jdbc.queryForObject("SELECT count(*) FROM telemetry_events WHERE principal_key=?",
                Integer.class, principal));

        var changed = mapper.readTree("{\"events\":[{\"type\":\"screen_view\",\"screen\":\"ai\",\"viewId\":\"view-unique-123\"}]}");
        CustomException exception = assertThrows(CustomException.class,
                () -> telemetry.record(principal, key, changed, "request-c"));
        assertEquals("IDEMPOTENCY_CONFLICT", exception.getErrorCode().name());
        assertEquals(2, jdbc.queryForObject("SELECT count(*) FROM telemetry_events WHERE principal_key=?",
                Integer.class, principal));
    }

    @Test
    void summaryUsesDistinctViewRatesAndOverviewKeepsUnavailableFeedbackNull() {
        String view = "view-" + UUID.randomUUID().toString().substring(0, 12);
        var body = mapper.readTree("""
                {"events":[
                  {"type":"screen_view","screen":"main","viewId":"%s"},
                  {"type":"graph_node_select","targetId":"NASDAQ:NVDA","viewId":"%s"}
                ]}
                """.formatted(view, view));
        telemetry.record(principal, "summary-" + UUID.randomUUID(), body, "summary-request");

        var summary = insights.summary("7d", "summary-request");
        var nodeCtr = summary.metrics().stream().filter(metric -> metric.key().equals("nodeCtr")).findFirst().orElseThrow();
        assertEquals(1L, nodeCtr.numerator());
        assertEquals(1L, nodeCtr.denominator());
        assertTrue(nodeCtr.sampleHidden());
        var overview = insights.overview("overview-request");
        assertEquals("unavailable", overview.feedback().availability());
        assertEquals("not_integrated", overview.feedback().unavailableReason());
        assertEquals(null, overview.feedback().up());
    }
}
