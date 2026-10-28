package com.zoop.briefing.query;

import java.time.Instant;
import java.time.LocalDate;
import java.util.HashSet;
import java.util.Objects;
import java.util.Set;

import com.zoop.briefing.storage.BriefingRound;
import tools.jackson.databind.JsonNode;

/** Validates the stored public DTO before disclosure. It does not repair or recalculate a publication. */
final class BriefingSnapshotValidator {
    private static final Set<String> PRECISIONS = Set.of("year", "month", "day", "datetime", "unknown");
    private static final Set<String> LABELS = Set.of("positive", "negative", "mixed", "undetermined");

    private BriefingSnapshotValidator() { }

    static void validate(BriefingRound row) {
        validate(row, false);
    }

    static void validate(BriefingRound row, boolean localReplay) {
        JsonNode p = object(row.payload());
        same(text(p, "id"), row.id()); same(text(p, "date"), row.date().toString());
        same(text(p, "edition"), row.edition());
        same(timestamp(p, "scheduledAt"), row.scheduledAt()); same(timestamp(p, "generatedAt"), row.generatedAt());
        same(localReplay ? nullableText(p, "graphVersion") : text(p, "graphVersion"), row.graphVersion());
        check(row.publishedAt() != null && row.generatedAt() != null && !row.publishedAt().isBefore(row.generatedAt()));
        nonNegativeRevision(p, "reviewRevision", false); nonNegativeRevision(p, "ruleRevision", true);
        int selectedFrom = integer(p, "selectedFrom", false);
        JsonNode window = object(field(p, "dataWindow"));
        same(nullableTimestamp(window, "start"), row.windowFrom()); same(timestamp(window, "end"), row.windowTo());
        check(bool(window, "openStart") == row.openStart() && row.openStart() == (row.windowFrom() == null));
        check(row.windowFrom() == null || row.windowFrom().isBefore(row.windowTo()));
        JsonNode references = object(field(p, "references"));
        Set<String> events = strings(references, "eventIds");
        Set<String> evidence = strings(references, "evidenceIds");
        Set<String> companies = strings(references, "companyIds");
        JsonNode items = array(p, "items");
        check(items.size() <= 3 && selectedFrom >= items.size());
        Set<String> selected = new HashSet<>();
        for (int position = 0; position < items.size(); position++) {
            JsonNode item = object(items.get(position));
            text(item, "title"); String event = text(item, "eventId");
            check(selected.add(event) && events.contains(event));
            check(integer(item, "rank", false) == position + 1);
            nullableText(item, "eventTime"); choice(item, "timePrecision", PRECISIONS);
            nullableReportedAt(item, "reportedAt"); integer(item, "evidenceCount", false); text(item, "reason");
            check(evidence.containsAll(strings(item, "evidenceIds")));
            check(strings(item, "matchedCompanyIds").isEmpty());
            for (JsonNode company : array(item, "companies")) {
                object(company); check(companies.contains(text(company, "id"))); text(company, "name");
                nullableText(company, "role"); bool(company, "roleUnconfirmed");
                choice(company, "relationType", Set.of("INVOLVES", "STRUCTURALLY_RELATED_TO"));
            }
            summary(field(item, "summary"), evidence);
            sourceSupport(object(field(item, "sourceSupport")));
            for (JsonNode sentiment : array(item, "documentSentiments")) {
                object(sentiment); text(sentiment, "articleId");
                JsonNode judgment = object(field(sentiment, "sentiment"));
                choice(judgment, "label", LABELS); text(judgment, "companyId"); text(judgment, "rationale");
                stringValues(judgment, "quotes"); timestamp(judgment, "judgedAt"); text(judgment, "model"); text(judgment, "promptVersion");
            }
        }
        String emptyReason = nullableText(p, "emptyReason");
        check(items.isEmpty() ? "no_issues_in_window".equals(emptyReason) : emptyReason == null);
        metadata(object(field(p, "metadata")), row.graphVersion(), localReplay);
        JsonNode outlook = field(p, "outlook");
        if (!outlook.isNull()) {
            object(outlook); choice(outlook, "label", LABELS); text(outlook, "rationale");
            check(events.containsAll(strings(outlook, "issueIds")));
            timestamp(outlook, "judgedAt"); text(outlook, "model"); text(outlook, "promptVersion");
        }
        JsonNode snapshot = object(row.publicSnapshot());
        summary(field(snapshot, "marketSummary"), evidence);
        marketAnalysis(field(snapshot, "marketSummary"), row);
        if (snapshot.has("companyOutlooks")) companyOutlooks(snapshot.get("companyOutlooks"), row, evidence);
        JsonNode market = field(p, "marketVariables");
        if (!market.isNull()) market(market, row.windowTo());
        if ("morning".equals(row.edition())) check(row.comparisonSnapshot() == null || row.comparisonSnapshot().isNull());
        else comparison(row.comparisonSnapshot());
        JsonNode previous = snapshot.get("previousComparison");
        if (previous != null && !previous.isNull()) previousComparison(previous, row);
    }

    private static void companyOutlooks(JsonNode layer, BriefingRound row, Set<String> evidence) {
        object(layer); same(text(layer, "schemaVersion"), "zoop-company-outlooks-v1");
        same(text(layer, "roundId"), row.id()); same(text(layer, "edition"), row.edition());
        check(Instant.parse(text(layer, "cutoff")).equals(row.windowTo())); timestamp(layer, "generatedAt"); text(layer, "resultVersion"); text(layer, "scopeNote");
        String status = choice(layer, "status", Set.of("PASS", "WITHHELD"));
        if ("WITHHELD".equals(status)) { check(array(layer, "companies").isEmpty()); text(layer, "reason"); return; }
        Set<String> expected = new HashSet<>(), actual = new HashSet<>();
        for (JsonNode item : row.payload().path("items")) for (JsonNode company : item.path("companies")) expected.add(text(company, "id"));
        for (JsonNode company : array(layer, "companies")) {
            check(actual.add(text(company, "companyId"))); text(company, "companyName");
            choice(company, "assessment", Set.of("positive", "negative", "mixed", "watch"));
            Set<String> ownSources = new HashSet<>();
            for (JsonNode source : array(company, "sources")) {
                String id = text(source, "evidenceId"); check(evidence.contains(id) && ownSources.add(id));
                text(source, "quote"); text(source, "documentId"); text(source, "documentVersion"); text(source, "bodySha256");
                text(source, "title"); String url = text(source, "url"); check(url.startsWith("https://") || url.startsWith("http://"));
                check(!Instant.parse(text(source, "publishedAt")).isAfter(row.windowTo()));
            }
            for (String field : java.util.List.of("impact", "outlook", "comparison")) companyStatement(field(company, field), ownSources);
            for (String field : java.util.List.of("facts", "conditions", "risks")) {
                check(!array(company, field).isEmpty()); for (JsonNode statement : array(company, field)) companyStatement(statement, ownSources);
            }
            choice(field(company, "comparison"), "status", Set.of("updated", "compared", "unavailable"));
            if (company.has("reading")) {
                JsonNode reading = object(field(company, "reading")); text(reading, "resultVersion");
                String schema = reading.has("schemaVersion") ? text(reading, "schemaVersion") : "zoop-company-reading-v1";
                check(Set.of("zoop-company-reading-v1", "zoop-company-reading-v2").contains(schema));
                boolean v2 = "zoop-company-reading-v2".equals(schema);
                if ("PASS".equals(choice(reading, "status", Set.of("PASS", "WITHHELD")))) {
                    for (String field : v2 ? java.util.List.of("brief", "fact", "watch", "background", "change") : java.util.List.of("brief", "watch", "change")) {
                        companyStatement(field(reading, field), ownSources);
                        String value = text(field(reading, field), "text");
                        int limit = v2 ? switch (field) { case "brief" -> 140; case "fact" -> 160; case "background" -> 240; default -> 180; }
                                : switch (field) { case "brief" -> 70; case "watch" -> 50; default -> 60; };
                        check(value.codePointCount(0, value.length()) <= limit);
                    }
                }
            }
            if (company.has("price")) companyPrice(object(field(company, "price")), text(company, "companyId"), row.windowTo());
        }
        check(actual.equals(expected));
    }
    private static void companyStatement(JsonNode statement, Set<String> sources) {
        object(statement); text(statement, "text"); Set<String> refs = strings(statement, "evidenceIds"); check(!refs.isEmpty() && sources.containsAll(refs));
    }

    private static void companyPrice(JsonNode price, String companyId, Instant cutoff) {
        same(text(price, "companyId"), companyId); same(timestamp(price, "cutoff"), cutoff);
        choice(price, "currency", Set.of("KRW", "USD")); bool(price, "official"); text(price, "source"); text(price, "note");
        String status = choice(price, "status", Set.of("available", "unavailable"));
        if ("unavailable".equals(status)) { check(field(price, "latest").isNull()); return; }
        JsonNode latest = object(field(price, "latest"));
        java.math.BigDecimal value = new java.math.BigDecimal(text(latest, "value")); check(value.signum() > 0);
        Instant observed = timestamp(latest, "observedAt"); check(!observed.isAfter(cutoff));
        choice(latest, "kind", Set.of("five_minute_close", "daily_close"));
        String comparison = choice(price, "comparisonStatus", Set.of("available", "unavailable", "no_new_session"));
        JsonNode baseline = field(price, "baseline");
        if (!baseline.isNull()) {
            object(baseline); check(!timestamp(baseline, "observedAt").isAfter(observed));
            java.math.BigDecimal before = new java.math.BigDecimal(text(baseline, "value")); check(before.signum() > 0);
            if ("available".equals(comparison)) {
                java.math.BigDecimal delta = value.subtract(before);
                check(delta.compareTo(new java.math.BigDecimal(text(price, "change"))) == 0);
                check(delta.multiply(java.math.BigDecimal.valueOf(100)).divide(before, 2, java.math.RoundingMode.HALF_UP)
                        .compareTo(new java.math.BigDecimal(text(price, "changeRate"))) == 0);
            } else if ("no_new_session".equals(comparison)) same(timestamp(baseline, "observedAt"), observed);
        } else check("unavailable".equals(comparison));
        if (!"available".equals(comparison)) check(field(price, "change").isNull() && field(price, "changeRate").isNull());
    }

    private static void metadata(JsonNode value, String graphVersion, boolean localReplay) {
        text(value, "source"); timestamp(value, "asOf");
        same(localReplay ? nullableText(value, "graphVersion") : text(value, "graphVersion"), graphVersion);
        if (localReplay) check(Set.of("zoop-briefing-development-replay", "zoop-briefing-publication-clock-simulation", "zoop-briefing-local-collection-validation")
                .contains(text(value, "source")));
        text(value, "requestId"); bool(value, "partial");
        JsonNode schedule = object(field(value, "schedule"));
        text(schedule, "morning"); text(schedule, "evening"); bool(schedule, "confirmed");
        JsonNode selection = object(field(value, "selection"));
        same(text(selection, "basis"), "market"); nullableText(selection, "reason");
        for (JsonNode failure : array(value, "failures")) {
            object(failure); text(failure, "section"); text(failure, "code"); text(failure, "message");
            bool(failure, "retryable"); nullableTimestamp(failure, "asOf");
        }
    }

    private static void summary(JsonNode value, Set<String> references) {
        object(value);
        if (value.has("status")) {
            same(text(value, "status"), "unavailable"); text(value, "reason");
            check(!value.has("text"));
        } else {
            text(value, "text"); Set<String> cited = strings(value, "evidenceIds");
            check(!cited.isEmpty() && references.containsAll(cited));
            timestamp(value, "generatedAt"); text(value, "resultVersion");
        }
    }

    /** Optional outlook is a structured view of the same verified text, never a second producer. */
    private static void marketAnalysis(JsonNode summary, BriefingRound row) {
        JsonNode analysis = summary.get("analysis");
        if (analysis == null || analysis.isNull()) return; // Existing publications retain their original DTO.
        check(!summary.has("status")); object(analysis);
        same(text(analysis, "schemaVersion"), "zoop-market-outlook-analysis-v1");
        same(text(analysis, "edition"), row.edition()); same(timestamp(analysis, "cutoff"), row.windowTo());
        same(text(analysis, "mode"), "morning".equals(row.edition()) ? "morning_update" : "evening_review");
        JsonNode coverage = object(field(analysis, "coverage"));
        check(integer(coverage, "documents", false) == integer(coverage, "newDocuments", false) + integer(coverage, "backgroundDocuments", false));
        strings(coverage, "companyNames"); check(!bool(coverage, "marketRepresentative") && !bool(coverage, "sectorPriceFeedAvailable"));
        JsonNode previous = object(field(analysis, "previousPublication"));
        same(text(previous, "kind"), "simulated_previous_output");
        boolean available = "available".equals(choice(previous, "status", Set.of("available", "unavailable")));
        Set<String> publications = new HashSet<>();
        if (available) {
            publications.add(text(previous, "roundId")); text(previous, "resultVersion"); LocalDate.parse(text(previous, "date"));
            same(text(previous, "edition"), "morning".equals(row.edition()) ? "evening" : "morning");
            same(timestamp(previous, "cutoff"), row.windowFrom());
        } else text(previous, "reason");
        Set<String> evidence = strings(summary, "evidenceIds"), claims = new HashSet<>(), forecastClaims = new HashSet<>();
        Set<String> forecastIds = new HashSet<>();
        StringBuilder verifiedText = new StringBuilder();
        for (JsonNode claim : array(analysis, "claims")) {
            object(claim); String id = text(claim, "claimId"); check(claims.add(id));
            verifiedText.append(text(claim, "text")).append('\n');
            String kind = choice(claim, "kind", Set.of("fact", "interpretation", "forecast", "forecast_update", "result_comparison"));
            check(evidence.containsAll(strings(claim, "evidenceIds")));
            strings(claim, "indicatorIds"); Set<String> priorForecasts = strings(claim, "previousForecastIds"); strings(claim, "evaluationIds");
            check(publications.containsAll(strings(claim, "previousPublicationIds")));
            stringValues(claim, "conditions"); stringValues(claim, "counterFactors");
            if ("forecast".equals(kind)) {
                check(!strings(claim, "evidenceIds").isEmpty()); check(!array(claim, "counterFactors").isEmpty());
                forecastClaims.add(text(claim, "targetId")); choice(claim, "direction", Set.of("up", "down", "flat", "uncertain"));
            } else check(field(claim, "targetId").isNull() && field(claim, "direction").isNull()
                    && array(claim, "conditions").isEmpty() && array(claim, "counterFactors").isEmpty());
            if ("forecast_update".equals(kind)) {
                check("morning".equals(row.edition()) && available && !priorForecasts.isEmpty());
                choice(claim, "updateAction", Set.of("maintain", "strengthen", "weaken", "withdraw"));
            } else check(field(claim, "updateAction").isNull());
            if ("result_comparison".equals(kind)) check("evening".equals(row.edition()) && available);
        }
        check(claims.size() >= 2 && claims.size() <= 8);
        verifiedText.append(text(analysis, "scopeNote")); same(verifiedText.toString(), text(summary, "text"));
        Set<String> forecastTargets = new HashSet<>();
        for (JsonNode forecast : array(analysis, "forecasts")) {
            object(forecast); check(forecastIds.add(text(forecast, "forecastId"))); text(forecast, "text");
            choice(forecast, "direction", Set.of("up", "down", "flat", "uncertain"));
            check(evidence.containsAll(strings(forecast, "evidenceIds"))); strings(forecast, "indicatorIds");
            stringValues(forecast, "conditions"); check(!array(forecast, "counterFactors").isEmpty()); stringValues(forecast, "counterFactors");
            JsonNode target = object(field(forecast, "target")); forecastTargets.add(text(target, "targetId"));
            check(timestamp(target, "targetEnd").isAfter(row.windowTo())); marketTarget(target);
        }
        check(forecastTargets.equals(forecastClaims));
        Set<String> evaluations = new HashSet<>();
        for (JsonNode evaluation : array(analysis, "forecastEvaluations")) {
            object(evaluation); check(available && evaluations.add(text(evaluation, "evaluationId"))); text(evaluation, "forecastId");
            JsonNode target = object(field(evaluation, "target")); marketTarget(target);
            same(text(evaluation, "rule"), text(target, "rule"));
            String status = choice(evaluation, "status", Set.of("evaluated", "unavailable"));
            if ("unavailable".equals(status)) {
                text(evaluation, "reason"); check(field(evaluation, "actualValue").isNull() && field(evaluation, "actualDirection").isNull()
                        && field(evaluation, "directionMatched").isNull());
            } else {
                check(!timestamp(target, "targetEnd").isAfter(row.windowTo()) && field(evaluation, "reason").isNull());
                check(field(evaluation, "actualValue").isNumber()); bool(evaluation, "directionMatched");
                choice(evaluation, "actualDirection", Set.of("up", "down", "flat"));
            }
        }
        for (JsonNode claim : array(analysis, "claims")) check(evaluations.containsAll(strings(claim, "evaluationIds")));
    }

    private static void marketTarget(JsonNode target) {
        choice(target, "indicatorId", Set.of("kospi", "kosdaq")); same(text(target, "valueKind"), "close");
        same(text(target, "rule"), "close_vs_baseline_v1"); text(target, "targetId"); text(target, "calendarRef");
        check(field(target, "baselineValue").isNumber());
        LocalDate baseline = LocalDate.parse(text(target, "baselineDate")), date = LocalDate.parse(text(target, "targetDate"));
        check(baseline.isBefore(date)); timestamp(target, "targetEnd");
    }

    private static void sourceSupport(JsonNode value) {
        integer(value, "articleCount", false); integer(value, "knownLineageCount", true);
        integer(value, "independentSourceCount", true); strings(value, "unknownLineageArticles");
        for (JsonNode group : array(value, "duplicateGroups")) stringArray(group);
    }

    private static void market(JsonNode value, Instant cutoff) {
        object(value); same(text(value, "status"), "available");
        same(timestamp(value, "referenceAt"), cutoff);
        check(!timestamp(value, "rateCutoffAt").isAfter(cutoff)); timestamp(value, "collectedAt");
        JsonNode indicators = array(value, "indicators"); Set<String> ids = new HashSet<>();
        for (JsonNode indicator : indicators) {
            object(indicator); String id = text(indicator, "id");
            check(Set.of("kospi", "kosdaq", "usdkrw").contains(id) && ids.add(id)); text(indicator, "label");
            same(text(indicator, "unit"), "usdkrw".equals(id) ? "KRW" : "pt");
            String status = choice(indicator, "status", Set.of("ok", "delayed", "unavailable", "failed"));
            JsonNode quote = field(indicator, "value"); numberOrNull(quote);
            String kind = nullableText(indicator, "valueKind"); check(kind == null || Set.of("close", "latest", "reference").contains(kind));
            check(!"reference".equals(kind) || "usdkrw".equals(id));
            String date = nullableText(indicator, "observedDate"); if (date != null) LocalDate.parse(date);
            Instant at = nullableTimestamp(indicator, "observedAt"); check(at == null || !at.isAfter(cutoff));
            numberOrNull(field(indicator, "change")); numberOrNull(field(indicator, "changeRate"));
            nullableText(indicator, "reason");
            String reasonCode = nullableText(indicator, "reasonCode");
            check(reasonCode == null || Set.of("not_connected", "unsupported_symbol", "no_data", "auth_failed",
                    "temporary_failure", "format_changed", "internal").contains(reasonCode));
            JsonNode baseline = field(indicator, "baseline");
            if (!baseline.isNull()) {
                object(baseline); check(field(baseline, "value").isNumber()); LocalDate.parse(text(baseline, "date"));
                nullableReportedAt(baseline, "at");
            }
            JsonNode source = field(indicator, "source");
            if (!source.isNull()) {
                object(source); choice(source, "provider", Set.of("toss", "yahoo", "naver"));
                text(source, "name"); bool(source, "official"); nullableText(source, "delayNote");
                text(source, "symbol"); nullableText(source, "url");
            }
            if (Set.of("ok", "delayed").contains(status)) check(!quote.isNull() && kind != null && date != null && !source.isNull());
            else check(quote.isNull());
        }
        check(ids.equals(Set.of("kospi", "kosdaq", "usdkrw")));
    }

    private static void comparison(JsonNode value) {
        object(value);
        if ("unavailable".equals(text(value, "status"))) { text(value, "reason"); return; }
        same(text(value, "status"), "available"); text(value, "morningRoundId");
        nullableTimestamp(value, "morningPublishedAt"); timestamp(value, "morningDataAsOf");
        for (JsonNode item : array(value, "items")) {
            object(item); text(item, "title"); text(item, "eventId"); nullableText(item, "eventTime");
            choice(item, "timePrecision", PRECISIONS); nullableReportedAt(item, "reportedAt"); stringValues(item, "companyNames");
            choice(item, "change", Set.of("new", "continuing", "dropped"));
            integer(item, "rank", true); integer(item, "morningRank", true);
            integer(item, "evidenceCount", true); integer(item, "morningEvidenceCount", true);
        }
    }

    private static void previousComparison(JsonNode value, BriefingRound row) {
        object(value);
        if ("unavailable".equals(text(value, "status"))) { text(value, "reason"); return; }
        same(text(value, "status"), "available"); check(!row.id().equals(text(value, "previousRoundId")));
        // Receipt wall clocks need not follow historical replay order; authority checks the stored prior timestamp.
        timestamp(value, "previousPublishedAt");
        check(timestamp(value, "previousDataAsOf").isBefore(row.windowTo()));
        if (value.has("previousDate") || value.has("previousEdition")) {
            LocalDate.parse(text(value, "previousDate")); choice(value, "previousEdition", Set.of("morning", "evening"));
        }
        same(text(value, "comparisonBasis"), "event_identity");
        JsonNode evaluation = object(field(value, "forecastEvaluation"));
        same(text(evaluation, "status"), "unavailable"); text(evaluation, "reason");
        Set<String> events = new HashSet<>();
        for (JsonNode item : array(value, "items")) {
            object(item); text(item, "title"); check(events.add(text(item, "eventId"))); nullableText(item, "eventTime");
            choice(item, "timePrecision", PRECISIONS); nullableReportedAt(item, "reportedAt"); stringValues(item, "companyNames");
            String change = choice(item, "change", Set.of("new", "continuing", "dropped"));
            int rank = integer(item, "rank", true), oldRank = integer(item, "previousRank", true);
            int count = integer(item, "evidenceCount", true), oldCount = integer(item, "previousEvidenceCount", true);
            check("dropped".equals(change) ? rank == -1 && count == -1 : rank > 0 && count >= 0);
            check("new".equals(change) ? oldRank == -1 && oldCount == -1 : oldRank > 0 && oldCount >= 0);
        }
    }

    private static JsonNode field(JsonNode value, String name) {
        JsonNode result = value.get(name); check(result != null); return result;
    }
    private static JsonNode object(JsonNode value) { check(value != null && value.isObject()); return value; }
    private static JsonNode array(JsonNode value, String name) { JsonNode result = field(value, name); check(result.isArray()); return result; }
    private static String text(JsonNode value, String name) {
        JsonNode result = field(value, name); check(result.isString() && !result.stringValue().isBlank()); return result.stringValue();
    }
    private static String nullableText(JsonNode value, String name) {
        JsonNode result = field(value, name); if (result.isNull()) return null; check(result.isString()); return result.stringValue();
    }
    private static boolean bool(JsonNode value, String name) { JsonNode result = field(value, name); check(result.isBoolean()); return result.booleanValue(); }
    private static int integer(JsonNode value, String name, boolean nullable) {
        JsonNode result = field(value, name); if (nullable && result.isNull()) return -1;
        check(result.isIntegralNumber() && result.canConvertToInt() && result.intValue() >= 0); return result.intValue();
    }
    private static void nonNegativeRevision(JsonNode value, String name, boolean nullable) {
        JsonNode result = field(value, name); if (nullable && result.isNull()) return;
        check(result.isIntegralNumber() && result.canConvertToLong() && result.longValue() >= 0);
    }
    private static Set<String> strings(JsonNode value, String name) { return stringArray(array(value, name)); }
    private static void stringValues(JsonNode value, String name) {
        for (JsonNode item : array(value, name)) check(item.isString() && !item.stringValue().isBlank());
    }
    private static Set<String> stringArray(JsonNode array) {
        check(array.isArray()); Set<String> values = new HashSet<>();
        for (JsonNode value : array) { check(value.isString() && !value.stringValue().isBlank()); check(values.add(value.stringValue())); }
        return values;
    }
    private static String choice(JsonNode value, String name, Set<String> choices) { String result = text(value, name); check(choices.contains(result)); return result; }
    private static Instant timestamp(JsonNode value, String name) { return Instant.parse(text(value, name)); }
    private static Instant nullableTimestamp(JsonNode value, String name) { String result = nullableText(value, name); return result == null ? null : Instant.parse(result); }
    private static void nullableReportedAt(JsonNode value, String name) {
        String result = nullableText(value, name);
        if (result != null) { if (result.length() == 10) LocalDate.parse(result); else Instant.parse(result); }
    }
    private static void numberOrNull(JsonNode value) { check(value.isNull() || (value.isNumber() && Double.isFinite(value.doubleValue()))); }
    private static void same(Object left, Object right) { check(Objects.equals(left, right)); }
    private static void check(boolean valid) { if (!valid) throw new IllegalArgumentException("Invalid stored briefing snapshot"); }
}
