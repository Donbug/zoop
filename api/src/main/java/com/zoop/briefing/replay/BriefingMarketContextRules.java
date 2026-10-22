package com.zoop.briefing.replay;

import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import java.math.BigDecimal;
import java.time.Instant;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.node.ArrayNode;
import tools.jackson.databind.node.ObjectNode;

/** Internal historical context contract; never turns simulated predecessors into operating publications. */
final class BriefingMarketContextRules {
    static final String POLICY = "market_context_prior_briefing_v2";
    static final String ANALYSIS_SCHEMA = "zoop-market-outlook-analysis-v1";
    private BriefingMarketContextRules() { }

    static boolean contextual(StrictJson.Obj summary) {
        return summary.has("policy") && POLICY.equals(summary.string("policy"));
    }

    static final List<String> QUALITY_FLAGS = List.of("atomicClaim", "evidenceClauseCoverage", "qualifiersPreserved", "observableConditionsOnly");
    static final String ROLE_VERSION = "market-context-v2.4-outlook";
    static final List<String> ROLE_FLAGS = List.of("factUnitAppropriate", "comparisonElementsComplete", "evidenceClauseCoverage", "qualifiersPreserved", "observableConditionsOnly");

    static boolean roleVersion(String version) { return Set.of(ROLE_VERSION, "market-context-v2.5-outlook", "market-context-v2.6-outlook", "market-context-v2.7-outlook", "market-context-v2.8-outlook", "market-context-v2.9-outlook", BriefingMarketGroundingRules.VERSION).contains(version); }

    static List<String> qualityFlags(String version) {
        return BriefingMarketGroundingRules.version(version) ? BriefingMarketGroundingRules.FLAGS : roleVersion(version) ? ROLE_FLAGS : "market-context-v2.3-outlook".equals(version) ? QUALITY_FLAGS : List.of();
    }

    static List<String> requiredKinds(StrictJson.Obj context) {
        List<String> roles = new java.util.ArrayList<>();
        if (!context.objects("forecastTargets").isEmpty()) roles.add("forecast");
        StrictJson.Obj previous = context.object("previousPublication");
        if ("available".equals(previous.string("status"))) {
            if ("morning".equals(context.string("edition")) && !previous.object("summary").objects("forecasts").isEmpty()) roles.add("forecast_update");
            if ("evening".equals(context.string("edition"))) roles.add("result_comparison");
        }
        return roles;
    }

    /** Exact projection of required model slots, with no synthetic restoration of a missing forecast. */
    static ArrayNode generatedClaims(StrictJson.Obj draft, StrictJson.Obj context) {
        draft.exactly(Set.of("claims", "requiredClaims"));
        var roles = requiredKinds(context); StrictJson.Obj slots = draft.object("requiredClaims");
        slots.exactly(Set.copyOf(roles)); ArrayNode result = (ArrayNode) draft.array("claims").deepCopy();
        for (StrictJson.Obj claim : draft.objects("claims"))
            check(!Set.of("forecast_update", "result_comparison").contains(claim.string("kind")) || roles.contains(claim.string("kind")), "market_role_comparison_slot_required");
        for (String role : roles) {
            check(role.equals(slots.object(role).string("kind")), "market_role_slot_kind");
            result.add(slots.object(role).node().deepCopy());
        }
        return result;
    }

    static void roleClaims(StrictJson.Obj summary, StrictJson.Obj context) {
        for (StrictJson.Obj claim : summary.objects("claims")) {
            if (!"result_comparison".equals(claim.string("kind"))) continue;
            Set<String> expected = new HashSet<>();
            for (StrictJson.Obj evaluation : context.objects("forecastEvaluations"))
                if (claim.strings("previousForecastIds").contains(evaluation.string("forecastId"))) expected.add(evaluation.string("evaluationId"));
            check(new HashSet<>(claim.strings("evaluationIds")).equals(expected)
                    && (!expected.isEmpty() || claim.strings("previousForecastIds").isEmpty()), "market_role_comparison_evaluations");
            check(!claim.strings("previousForecastIds").isEmpty() || !claim.strings("evidenceIds").isEmpty()
                    || !claim.strings("indicatorIds").isEmpty(), "market_role_comparison_current_basis");
        }
    }

    /** v2.3+ anchor guards; older immutable recordings retain their original contract. */
    static void qualityClaims(StrictJson.Obj summary, StrictJson.Obj news, StrictJson.Obj broad) {
        Map<String, String> owners = new HashMap<>();
        for (StrictJson.Obj item : news.objects("selected"))
            for (StrictJson.Obj source : item.objects("sources"))
                if (source.has("documentId")) owners.put(source.string("evidenceId"), source.string("documentId"));
        for (StrictJson.Obj doc : broad.objects("documents"))
            for (StrictJson.Obj source : doc.objects("sources")) owners.put(source.string("evidenceId"), doc.string("documentId"));
        for (StrictJson.Obj claim : summary.objects("claims")) {
            if ("fact".equals(claim.string("kind"))) {
                Set<String> documents = new HashSet<>();
                for (String id : claim.strings("evidenceIds")) {
                    check(owners.containsKey(id) && !owners.get(id).isBlank(), "market_quality_fact_anchor"); documents.add(owners.get(id));
                }
                check(documents.size() + claim.strings("indicatorIds").size() == 1
                        && claim.strings("previousForecastIds").isEmpty() && claim.strings("previousPublicationIds").isEmpty()
                        && claim.strings("evaluationIds").isEmpty(), "market_quality_fact_anchor");
            }
            if ("forecast".equals(claim.string("kind")))
                check(claim.strings("conditions").isEmpty(), "market_quality_condition_observations_missing");
        }
    }

    /** Public, verified analysis only. The frozen request and document bodies stay private. */
    static ObjectNode analysis(StrictJson.Obj summary, StrictJson.Obj context, String cutoff) {
        check(contextual(summary) && "PASS".equals(summary.object("verification").string("status")), "analysis_requires_verified_result");
        ObjectNode result = StrictJson.newObject().put("schemaVersion", ANALYSIS_SCHEMA)
                .put("edition", context.string("edition")).put("cutoff", cutoff)
                .put("mode", "morning".equals(context.string("edition")) ? "morning_update" : "evening_review")
                .put("scopeNote", summary.string("scopeNote"));
        StrictJson.Obj previous = context.object("previousPublication");
        ObjectNode prior = result.putObject("previousPublication");
        for (String name : List.of("status", "kind", "roundId", "date", "edition", "cutoff", "reason"))
            if (previous.has(name)) prior.set(name, previous.raw(name).deepCopy());
        if ("available".equals(previous.string("status"))) prior.put("resultVersion", previous.object("summary").string("resultVersion"));
        ObjectNode coverage = result.putObject("coverage");
        for (String name : List.of("documents", "newDocuments", "backgroundDocuments", "companyNames", "marketRepresentative", "sectorPriceFeedAvailable"))
            coverage.set(name, context.object("coverage").raw(name).deepCopy());
        var claims = result.putArray("claims");
        for (StrictJson.Obj claim : summary.objects("claims")) claims.add(project(claim, List.of("claimId", "kind", "text", "evidenceIds", "indicatorIds",
                "previousPublicationIds", "previousForecastIds", "evaluationIds", "targetId", "direction", "conditions", "counterFactors", "updateAction")));
        var forecasts = result.putArray("forecasts");
        for (StrictJson.Obj forecast : summary.objects("forecasts")) {
            ObjectNode value = project(forecast, List.of("forecastId", "text", "direction", "conditions", "counterFactors", "evidenceIds", "indicatorIds"));
            value.set("target", publicTarget(forecast.object("target"))); forecasts.add(value);
        }
        var evaluations = result.putArray("forecastEvaluations");
        for (StrictJson.Obj evaluation : summary.objects("forecastEvaluations")) {
            ObjectNode value = project(evaluation, List.of("evaluationId", "forecastId", "rule", "status", "reason", "actualValue", "actualDirection", "directionMatched"));
            value.set("target", publicTarget(evaluation.object("target"))); evaluations.add(value);
        }
        return result;
    }

    private static ObjectNode project(StrictJson.Obj source, List<String> fields) {
        ObjectNode result = StrictJson.newObject();
        for (String name : fields) result.set(name, source.raw(name).deepCopy());
        return result;
    }

    private static ObjectNode publicTarget(StrictJson.Obj target) {
        return project(target, List.of("targetId", "indicatorId", "valueKind", "baselineDate", "baselineValue", "targetDate", "targetEnd", "calendarRef", "rule"));
    }

    static Set<String> evidence(StrictJson.Obj context) {
        Set<String> result = new HashSet<>();
        for (StrictJson.Obj document : context.objects("documents")) for (StrictJson.Obj citation : document.objects("sources"))
            check(result.add(citation.string("evidenceId")), "duplicate_evidence");
        return result;
    }

    /** New outlook executions must fulfill the requested edition purpose; old recordings remain valid. */
    static void outlookRequired(StrictJson.Obj summary, StrictJson.Obj context) {
        if (!"PASS".equals(summary.object("verification").string("status"))) return;
        Set<String> kinds = new HashSet<>(); summary.objects("claims").forEach(c -> kinds.add(c.string("kind")));
        if (!context.objects("forecastTargets").isEmpty()) check(kinds.contains("forecast"), "outlook_forecast_required");
        if ("morning".equals(context.string("edition")) && !priorForecasts(context).isEmpty())
            check(kinds.contains("forecast_update"), "outlook_update_required");
        if ("evening".equals(context.string("edition")) && "available".equals(context.object("previousPublication").string("status")))
            check(kinds.contains("result_comparison"), "outlook_comparison_required");
    }

    static void previous(StrictJson.Obj record, List<StrictJson.Obj> records) {
        StrictJson.Obj context = record.object("marketContext"), prior = context.object("previousPublication");
        check("simulated_previous_output".equals(prior.string("kind")), "previous_kind");
        Instant from = Instant.parse(context.object("window").string("from"));
        String expected = "morning".equals(record.string("edition")) ? "evening" : "morning";
        List<StrictJson.Obj> matches = records.stream().filter(r -> expected.equals(r.string("edition"))
                && from.equals(Instant.parse(r.string("cutoff")))).toList();
        check(matches.size() <= 1, "previous_ambiguous");
        boolean available = !matches.isEmpty() && !matches.getFirst().isNull("summaryResult")
                && "PASS".equals(matches.getFirst().object("summaryResult").object("verification").string("status"));
        check(available == "available".equals(prior.string("status")), "previous_availability");
        if (available) {
            StrictJson.Obj old = matches.getFirst();
            check(old.string("roundId").equals(prior.string("roundId"))
                    && old.string("date").equals(prior.string("date")) && old.string("edition").equals(prior.string("edition"))
                    && old.string("summaryResultSha256").equals(prior.string("summaryResultSha256"))
                    && old.object("summaryResult").node().equals(prior.object("summary").node())
                    && Instant.parse(prior.string("cutoff")).equals(from), "previous_original_binding");
        } else check(!prior.string("reason").isBlank(), "previous_unavailable_reason");
    }

    static Map<String, StrictJson.Obj> priorForecasts(StrictJson.Obj context) {
        Map<String, StrictJson.Obj> result = new LinkedHashMap<>();
        StrictJson.Obj prior = context.object("previousPublication");
        if (!"available".equals(prior.string("status"))) return result;
        StrictJson.Obj summary = prior.object("summary");
        if (summary.has("forecasts")) for (StrictJson.Obj forecast : summary.objects("forecasts"))
            {
                StrictJson.Obj old = result.putIfAbsent(forecast.string("forecastId"), forecast);
                check(old == null || old.node().equals(forecast.node()), "previous_forecast_duplicate");
            }
        return result;
    }

    static void targetsAndEvaluations(StrictJson.Obj context, StrictJson.Obj snapshot) {
        Map<String, StrictJson.Obj> indicators = new HashMap<>();
        snapshot.object("marketVariables").objects("indicators").forEach(i -> indicators.put(i.string("id"), i));
        Map<String, StrictJson.Obj> targets = new LinkedHashMap<>();
        for (StrictJson.Obj target : context.objects("forecastTargets")) {
            check(!context.isNull("sessionCalendar"), "target_without_calendar");
            StrictJson.Obj indicator = indicators.get(target.string("indicatorId"));
            check(Set.of("kospi", "kosdaq").contains(target.string("indicatorId")) && indicator != null
                    && Set.of("ok", "delayed").contains(indicator.string("status"))
                    && "close".equals(target.string("valueKind")) && "close".equals(indicator.string("valueKind"))
                    && "close_vs_baseline_v1".equals(target.string("rule"))
                    && target.string("baselineDate").equals(indicator.string("observedDate"))
                    && target.raw("baselineValue").decimalValue().compareTo(indicator.raw("value").decimalValue()) == 0
                    && Instant.parse(target.string("targetEnd")).isAfter(Instant.parse(snapshot.object("round").string("cutoff"))),
                    "forecast_target_basis");
            check(targets.putIfAbsent(target.string("targetId"), target) == null, "target_duplicate");
            ObjectNode value = (ObjectNode) target.node().deepCopy(); value.remove("targetId");
            check(("market-target-" + identityDigest(value).substring(0, 32)).equals(target.string("targetId")), "target_id");
            StrictJson.Obj calendar = context.object("sessionCalendar");
            check("zoop-market-session-calendar-v1".equals(calendar.string("schemaVersion")), "calendar_schema");
            List<StrictJson.Obj> days = calendar.objects("sessions");
            for (StrictJson.Obj day : days) check(!Instant.parse(day.string("availableAt"))
                    .isAfter(Instant.parse(snapshot.object("round").string("cutoff"))), "calendar_asof");
            List<StrictJson.Obj> current = days.stream().filter(d -> context.string("date").equals(d.string("date"))).toList();
            check(current.size() == 1 && current.getFirst().bool("tradingDay"), "calendar_current_day");
            String expected = "morning".equals(context.string("edition")) ? context.string("date") : current.getFirst().string("nextTradingDate");
            List<StrictJson.Obj> end = days.stream().filter(d -> target.string("targetDate").equals(d.string("date"))).toList();
            check(expected.equals(target.string("targetDate")) && end.size() == 1 && end.getFirst().bool("tradingDay")
                    && target.string("targetEnd").equals(end.getFirst().string("closeAt"))
                    && target.string("calendarRef").equals(end.getFirst().string("sourceRef")), "calendar_target");
        }
        Map<String, StrictJson.Obj> prior = priorForecasts(context);
        Set<String> accounted = new HashSet<>();
        Map<String, JsonNode> seenEvaluations = new HashMap<>();
        for (StrictJson.Obj evaluation : context.objects("forecastEvaluations")) {
            String id = evaluation.string("forecastId"); StrictJson.Obj forecast = prior.get(id);
            JsonNode duplicate = seenEvaluations.putIfAbsent(id, evaluation.node());
            if (duplicate != null) { check(duplicate.equals(evaluation.node()), "evaluation_conflicting_duplicate"); continue; }
            check(forecast != null && accounted.add(id), "evaluation_owner");
            StrictJson.Obj target = forecast.object("target");
            check(target.node().equals(evaluation.object("target").node()) && target.string("rule").equals(evaluation.string("rule")), "evaluation_target");
            StrictJson.Obj observed = indicators.get(target.string("indicatorId"));
            String reason = !forecast.strings("conditions").isEmpty() ? "condition_outcomes_not_observed"
                    : "uncertain".equals(forecast.string("direction")) ? "direction_not_testable"
                    : Instant.parse(target.string("targetEnd")).isAfter(Instant.parse(snapshot.object("round").string("cutoff"))) ? "target_period_not_finished"
                    : observed == null || !Set.of("ok", "delayed").contains(observed.string("status"))
                        || !target.string("valueKind").equals(observed.string("valueKind"))
                        || !target.string("targetDate").equals(observed.string("observedDate")) ? "exact_target_observation_missing" : null;
            if (reason != null) check("unavailable".equals(evaluation.string("status")) && reason.equals(evaluation.string("reason"))
                    && evaluation.isNull("actualValue") && evaluation.isNull("actualDirection") && evaluation.isNull("directionMatched"), "evaluation_unavailable");
            else {
                BigDecimal actual = observed.raw("value").decimalValue(), baseline = target.raw("baselineValue").decimalValue();
                int sign = actual.compareTo(baseline); String direction = sign > 0 ? "up" : sign < 0 ? "down" : "flat";
                check("evaluated".equals(evaluation.string("status")) && evaluation.isNull("reason")
                        && actual.compareTo(evaluation.raw("actualValue").decimalValue()) == 0
                        && direction.equals(evaluation.string("actualDirection"))
                        && evaluation.bool("directionMatched") == direction.equals(forecast.string("direction")), "evaluation_result");
            }
            ObjectNode value = (ObjectNode) evaluation.node().deepCopy(); value.remove("evaluationId");
            check(("market-evaluation-" + identityDigest(value).substring(0, 32)).equals(evaluation.string("evaluationId")), "evaluation_id");
        }
        check(accounted.equals(prior.keySet()), "evaluation_coverage");
    }

    static void claims(StrictJson.Obj summary, StrictJson.Obj context) {
        Map<String, StrictJson.Obj> prior = priorForecasts(context), targets = new HashMap<>(), evaluations = new HashMap<>();
        context.objects("forecastTargets").forEach(t -> targets.put(t.string("targetId"), t));
        context.objects("forecastEvaluations").forEach(e -> evaluations.put(e.string("evaluationId"), e));
        for (StrictJson.Obj claim : summary.objects("claims")) {
            String kind = claim.string("kind");
            check(Set.of("fact", "interpretation", "forecast", "forecast_update", "result_comparison").contains(kind), "claim_kind");
            StrictJson.Obj publication = context.object("previousPublication");
            Set<String> publications = "available".equals(publication.string("status")) ? Set.of(publication.string("roundId")) : Set.of();
            check(publications.containsAll(claim.strings("previousPublicationIds")), "claim_publication_reference");
            check(prior.keySet().containsAll(claim.strings("previousForecastIds"))
                    && evaluations.keySet().containsAll(claim.strings("evaluationIds")), "claim_previous_reference");
            for (String id : claim.strings("evaluationIds"))
                check(claim.strings("previousForecastIds").contains(evaluations.get(id).string("forecastId")), "claim_evaluation_owner");
            if ("forecast".equals(kind)) check(targets.containsKey(claim.string("targetId"))
                    && Set.of("up", "down", "flat", "uncertain").contains(claim.string("direction"))
                    && !claim.strings("evidenceIds").isEmpty() && !claim.strings("counterFactors").isEmpty(), "claim_forecast_basis");
            else check(claim.isNull("targetId") && claim.isNull("direction") && claim.strings("conditions").isEmpty()
                    && claim.strings("counterFactors").isEmpty(), "claim_nonforecast_target");
            if ("forecast_update".equals(kind)) check("morning".equals(context.string("edition"))
                    && !claim.strings("previousForecastIds").isEmpty()
                    && (!claim.strings("evidenceIds").isEmpty() || !claim.strings("indicatorIds").isEmpty())
                    && Set.of("maintain", "strengthen", "weaken", "withdraw").contains(claim.string("updateAction")), "claim_update");
            else check(claim.isNull("updateAction"), "claim_update_action");
            if ("result_comparison".equals(kind)) check("evening".equals(context.string("edition"))
                    && (!claim.strings("previousForecastIds").isEmpty() || !claim.strings("previousPublicationIds").isEmpty()), "claim_comparison");
        }
        for (StrictJson.Obj check : summary.object("verification").objects("checks"))
            if ("PASS".equals(summary.object("verification").string("status")))
                check(check.bool("comparisonAppropriate") && check.bool("forecastAppropriate"), "comparison_forecast_verification");
        check(summary.array("forecastEvaluations").equals(context.array("forecastEvaluations")), "saved_evaluations");
        List<StrictJson.Obj> expected = summary.objects("claims").stream().filter(c -> "forecast".equals(c.string("kind"))).toList();
        List<StrictJson.Obj> forecasts = summary.objects("forecasts");
        boolean passed = "PASS".equals(summary.object("verification").string("status"));
        check(forecasts.size() == (passed ? expected.size() : 0), "saved_forecast_count");
        for (int index = 0; index < forecasts.size(); index++) {
            StrictJson.Obj forecast = forecasts.get(index), claim = expected.get(index);
            check(forecast.object("target").node().equals(targets.get(claim.string("targetId")).node()), "saved_forecast_target");
            for (String field : List.of("text", "direction", "conditions", "counterFactors", "evidenceIds", "indicatorIds"))
                check(forecast.raw(field).equals(claim.raw(field)), "saved_forecast_content");
            ObjectNode value = (ObjectNode) forecast.node().deepCopy(); value.remove("forecastId");
            ObjectNode identity = StrictJson.newObject().put("version", summary.string("resultVersion")); identity.set("value", value);
            check(("market-forecast-" + identityDigest(identity).substring(0, 32)).equals(forecast.string("forecastId")), "saved_forecast_id");
        }
    }

    private static String identityDigest(JsonNode node) {
        return Canonical.digest(numericText(node));
    }

    private static JsonNode numericText(JsonNode node) {
        if (node.isObject()) {
            ObjectNode result = StrictJson.newObject();
            for (String name : node.propertyNames()) result.set(name, numericText(node.get(name)));
            return result;
        }
        if (node.isArray()) {
            var result = StrictJson.newArray(); for (JsonNode value : node) result.add(numericText(value)); return result;
        }
        if (node.isNumber()) return new tools.jackson.databind.node.StringNode(node.decimalValue().stripTrailingZeros().toPlainString());
        return node;
    }

    private static void check(boolean condition, String reason) {
        if (!condition) throw new IllegalArgumentException("market_context_" + reason);
    }
}
