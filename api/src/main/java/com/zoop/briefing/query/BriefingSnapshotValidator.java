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
        JsonNode market = field(p, "marketVariables");
        if (!market.isNull()) market(market, row.windowTo());
        if ("morning".equals(row.edition())) check(row.comparisonSnapshot() == null || row.comparisonSnapshot().isNull());
        else comparison(row.comparisonSnapshot());
        JsonNode previous = snapshot.get("previousComparison");
        if (previous != null && !previous.isNull()) previousComparison(previous, row);
    }

    private static void metadata(JsonNode value, String graphVersion, boolean localReplay) {
        text(value, "source"); timestamp(value, "asOf");
        same(localReplay ? nullableText(value, "graphVersion") : text(value, "graphVersion"), graphVersion);
        if (localReplay) check(Set.of("zoop-briefing-development-replay", "zoop-briefing-publication-clock-simulation")
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
