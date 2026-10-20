package com.zoop.briefing.replay;

import com.zoop.common.json.StrictJson;
import java.util.List;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.node.ArrayNode;
import tools.jackson.databind.node.ObjectNode;

import static org.junit.jupiter.api.Assertions.*;

/** Authored structured projections and edition gates; no provider, network or database. */
class BriefingMarketOutlookTest {
    private ObjectNode context(String edition, boolean available) {
        ObjectNode value = StrictJson.newObject().put("edition", edition);
        value.putArray("forecastTargets"); value.putArray("forecastEvaluations");
        ObjectNode prior = value.putObject("previousPublication").put("status", available ? "available" : "unavailable")
                .put("kind", "simulated_previous_output");
        if (available) {
            prior.put("roundId", "actual-prior").put("date", "2026-10-07").put("edition", "morning".equals(edition) ? "evening" : "morning")
                    .put("cutoff", "2026-10-07T08:30:00Z");
            prior.putObject("summary").put("resultVersion", "verified-prior-version").put("text", "Private prior payload")
                    .putArray("forecasts");
        } else prior.put("reason", "immediate_previous_summary_withheld");
        ObjectNode coverage = value.putObject("coverage").put("documents", 3).put("newDocuments", 1).put("backgroundDocuments", 2)
                .put("marketRepresentative", false).put("sectorPriceFeedAvailable", false).put("bodyScope", "exact_prefix600_suffix300");
        coverage.putArray("companyNames").add("시험 기업");
        value.putArray("documents").addObject().put("wholePrivateBody", "Do not disclose");
        value.put("providerSecret", "Not a real credential; authored privacy marker");
        return value;
    }

    private ObjectNode summary(String... kinds) {
        ObjectNode value = StrictJson.newObject().put("policy", BriefingMarketContextRules.POLICY).put("scopeNote", "Authored limited scope.");
        value.putObject("verification").put("status", "PASS");
        ArrayNode claims = value.putArray("claims");
        for (String kind : kinds) {
            ObjectNode claim = claims.addObject().put("claimId", "market:claim:" + claims.size()).put("kind", kind).put("text", "Verified " + kind)
                    .putNull("targetId").putNull("direction").putNull("updateAction");
            for (String name : List.of("evidenceIds", "indicatorIds", "previousPublicationIds", "previousForecastIds", "evaluationIds", "conditions", "counterFactors")) claim.putArray(name);
            ((ArrayNode) claim.get("evidenceIds")).add("verified-source");
        }
        value.putArray("forecasts"); value.putArray("forecastEvaluations");
        return value;
    }

    private static ObjectNode target() {
        return StrictJson.newObject().put("targetId", "authored-target").put("indicatorId", "kospi").put("valueKind", "close")
                .put("baselineDate", "2026-10-06").put("baselineValue", 100).put("targetDate", "2026-10-07")
                .put("targetEnd", "2026-10-07T06:30:00Z").put("calendarRef", "authored-calendar").put("rule", "close_vs_baseline_v1");
    }

    @Test void projectionPreservesVerifiedStructureButOmitsFrozenBodiesAndPriorPayload() {
        ObjectNode context = context("morning", true), summary = summary("fact", "forecast");
        ObjectNode forecast = ((ArrayNode) summary.get("forecasts")).addObject().put("forecastId", "actual-forecast")
                .put("text", "A verified conditional outlook").put("direction", "uncertain");
        for (String name : List.of("conditions", "counterFactors", "evidenceIds", "indicatorIds")) forecast.putArray(name).add("authored-" + name);
        forecast.set("target", target()); forecast.put("rawDraft", "Do not disclose");
        ((ObjectNode) summary.path("claims").get(0)).put("rawDraft", "Do not disclose");
        ObjectNode evaluation = ((ArrayNode) summary.get("forecastEvaluations")).addObject().put("evaluationId", "actual-evaluation")
                .put("forecastId", "prior-forecast").put("rule", "close_vs_baseline_v1").put("status", "unavailable")
                .put("reason", "condition_outcomes_not_observed").putNull("actualValue").putNull("actualDirection").putNull("directionMatched");
        evaluation.set("target", target());
        byte[] before = StrictJson.write(context), beforeSummary = StrictJson.write(summary);
        ObjectNode result = BriefingMarketContextRules.analysis(StrictJson.Obj.of(summary), StrictJson.Obj.of(context), "2026-10-08T00:20:00Z");
        assertEquals("morning_update", result.path("mode").asString());
        assertEquals("verified-prior-version", result.at("/previousPublication/resultVersion").asString());
        assertFalse(result.path("previousPublication").has("summary"));
        assertEquals("Verified forecast", result.at("/claims/1/text").asString());
        assertEquals("2026-10-07", result.at("/forecasts/0/target/targetDate").asString());
        assertTrue(result.at("/forecastEvaluations/0/actualValue").isNull());
        String visible = new String(StrictJson.write(result), java.nio.charset.StandardCharsets.UTF_8);
        assertFalse(visible.contains("Do not disclose")); assertFalse(visible.contains("Private prior payload"));
        assertFalse(visible.contains("providerSecret")); assertFalse(result.path("coverage").has("bodyScope"));
        assertArrayEquals(before, StrictJson.write(context)); assertArrayEquals(beforeSummary, StrictJson.write(summary));
        ((ObjectNode) result.at("/claims/0")).put("text", "Client copy changed");
        assertEquals("Verified fact", summary.at("/claims/0/text").asString());
    }

    @Test void withheldDraftCannotBecomePublicAnalysis() {
        ObjectNode summary = summary("fact"); ((ObjectNode) summary.get("verification")).put("status", "WITHHELD");
        assertThrows(IllegalArgumentException.class, () -> BriefingMarketContextRules.analysis(StrictJson.Obj.of(summary), StrictJson.Obj.of(context("evening", false)), "2026-10-08T08:30:00Z"));
    }

    @Test void newOutlookRequiresForecastWhenTargetIsAvailable() {
        ObjectNode context = context("morning", false); ((ArrayNode) context.get("forecastTargets")).add(target());
        assertThrows(IllegalArgumentException.class, () -> BriefingMarketContextRules.outlookRequired(StrictJson.Obj.of(summary("fact", "interpretation")), StrictJson.Obj.of(context)));
        assertDoesNotThrow(() -> BriefingMarketContextRules.outlookRequired(StrictJson.Obj.of(summary("fact", "forecast")), StrictJson.Obj.of(context)));
    }

    @Test void morningMustUpdateAnActualPriorForecastWhileEveningMustCompareActualPriorPublication() {
        ObjectNode morning = context("morning", true);
        ((ArrayNode) morning.at("/previousPublication/summary/forecasts")).addObject().put("forecastId", "actual-prior-forecast");
        assertThrows(IllegalArgumentException.class, () -> BriefingMarketContextRules.outlookRequired(StrictJson.Obj.of(summary("fact", "interpretation")), StrictJson.Obj.of(morning)));
        assertDoesNotThrow(() -> BriefingMarketContextRules.outlookRequired(StrictJson.Obj.of(summary("fact", "forecast_update")), StrictJson.Obj.of(morning)));
        ObjectNode evening = context("evening", true);
        assertThrows(IllegalArgumentException.class, () -> BriefingMarketContextRules.outlookRequired(StrictJson.Obj.of(summary("fact", "forecast")), StrictJson.Obj.of(evening)));
        assertDoesNotThrow(() -> BriefingMarketContextRules.outlookRequired(StrictJson.Obj.of(summary("fact", "result_comparison")), StrictJson.Obj.of(evening)));
    }

    @Test void missingCalendarOrPriorSummaryDoesNotInventRequiredForecastOrComparison() {
        assertDoesNotThrow(() -> BriefingMarketContextRules.outlookRequired(StrictJson.Obj.of(summary("fact", "interpretation")), StrictJson.Obj.of(context("evening", false))));
        ObjectNode withheld = summary(); ((ObjectNode) withheld.get("verification")).put("status", "WITHHELD");
        ObjectNode context = context("evening", true); ((ArrayNode) context.get("forecastTargets")).add(target());
        assertDoesNotThrow(() -> BriefingMarketContextRules.outlookRequired(StrictJson.Obj.of(withheld), StrictJson.Obj.of(context)));
    }
}
