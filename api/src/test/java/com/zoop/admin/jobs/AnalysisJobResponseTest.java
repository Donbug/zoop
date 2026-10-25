package com.zoop.admin.jobs;

import static com.zoop.admin.jobs.AnalysisJobResponse.*;
import static org.junit.jupiter.api.Assertions.*;

import org.junit.jupiter.api.Test;
import tools.jackson.databind.json.JsonMapper;

class AnalysisJobResponseTest {
    private final JsonMapper mapper = JsonMapper.builder().build();

    @Test
    void legacyOutputOmitsOnlyPlanRunAndPreservesOtherExplicitNullFields() {
        var json = mapper.valueToTree(job("ingest", null));
        assertFalse(json.has("planRun"));
        for (String nullable : new String[]{"startedAt", "finishedAt", "retryOf", "ingest", "report", "flush", "error", "ledgerBefore", "ledgerAfter"}) {
            assertTrue(json.has(nullable), nullable);
            assertTrue(json.get(nullable).isNull(), nullable);
        }
    }

    @Test
    void analyzePlanRequiresTheClosedNonNullSummaryAndKeepsUnknownTotalNull() {
        var run = new PlanRunOut("s2plan-" + "a".repeat(64), "b".repeat(64), null, null, null, null,
                "awaiting_admission", null, 0, null, "ai_processing_handoff", false);
        var json = mapper.valueToTree(job("analyze_plan", run));
        assertTrue(json.get("planRun").isObject());
        assertTrue(json.get("planRun").get("totalUnits").isNull());
        assertFalse(json.get("planRun").get("publicChanged").booleanValue());
        assertThrows(IllegalArgumentException.class, () -> job("ingest", run));
        assertThrows(IllegalArgumentException.class, () -> job("analyze_plan", null));
    }

    private static JobOut job(String kind, PlanRunOut run) {
        return new JobOut("job-authored1", kind, "작업", "queued", "운영 확인", "admin-authored", "2026-10-24T00:00:00Z",
                null, null, null, null, false, false, new RetryState(false,"in_progress","진행 중",null),
                null, null, null, null, null, null, run);
    }
}
