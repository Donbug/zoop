package com.zoop.briefing.query;

import java.time.Instant;
import java.util.*;
import org.springframework.jdbc.core.JdbcTemplate;
import tools.jackson.databind.JsonNode;

/** Read contract for saved relative-priority views. Never selects, repairs, or calls a model. */
public final class BriefingPriorityRules {
    private static final Set<String> DIRECTIONS = Set.of("positive", "negative", "mixed", "watch");
    private BriefingPriorityRules() { }

    public static void validate(JsonNode value, String round, Instant cutoff, boolean personal,
            Set<String> allowedCompanies, Set<String> allowedEvidence) {
        keys(value, personal ? "schemaVersion roundId cutoff resultVersion companyIds candidateCount status minimumIssues items"
                : "schemaVersion roundId cutoff resultVersion generationVersion minimumIssues minimumShortfall candidateCount legacyAnalysisScopeWarning status items");
        same(text(value, "schemaVersion"), personal ? "personal-relative-priority-view-v1" : "common-relative-priority-view-v1");
        same(text(value, "roundId"), round); same(time(value, "cutoff"), cutoff); text(value, "resultVersion");
        var items = array(value, "items"); check(items.size() <= 3);
        integer(value, "candidateCount"); // Tracking/reference cards need not belong to the current candidate count.
        int minimum = value.has("minimumIssues") ? integer(value, "minimumIssues") : 0; check(minimum <= 3);
        if (!personal) {
            check(minimum >= 1 && integer(value, "minimumShortfall") == Math.max(0, minimum - items.size()));
            if (value.has("legacyAnalysisScopeWarning")) check(value.get("legacyAnalysisScopeWarning").isBoolean());
            if (value.has("generationVersion")) text(value, "generationVersion");
        } else same(strings(value, "companyIds"), allowedCompanies);
        String status = choice(value, "status", personal ? Set.of("available", "collection_insufficient", "no_companies")
                : Set.of("available", "collection_insufficient"));
        check(!"no_companies".equals(status) || allowedCompanies.isEmpty() && items.isEmpty());
        Set<String> seen = new HashSet<>();
        for (var item : items) {
            keys(item, personal ? "issueId kind title topicTag reason originRoundId originCutoff connections sources priorAnalysis price aiAnalyses analysisOmittedReason"
                    : "issueId kind importance title topicTag reason whyNow originRoundId originCutoff companies sources prices aiAnalyses analysisResultVersion analysisWithheldReason");
            String issue = text(item, "issueId"); check(seen.add(issue)); text(item, "title"); text(item, "reason");
            String kind = choice(item, "kind", personal ? Set.of("new_issue", "related_reference", "previous_issue")
                    : Set.of("core", "relative_issue", "related_reference", "previous_issue"));
            text(item, "originRoundId"); Instant origin = time(item, "originCutoff"); check(!origin.isAfter(cutoff));
            if (!personal) { check(integer(item, "importance") <= 3); text(item, "whyNow"); }
            Set<String> companies = new HashSet<>();
            for (var company : array(item, personal ? "connections" : "companies")) {
                keys(company, "companyId name reason"); String id = text(company, "companyId");
                check(companies.add(id) && allowedCompanies.contains(id)); text(company, "name"); text(company, "reason");
            }
            check(!companies.isEmpty()); Set<String> sources = new HashSet<>();
            for (var source : array(item, "sources")) {
                keys(source, "evidenceId quote url publishedAt publishedDate availableAt eligibilityBasis"); String id = text(source, "evidenceId");
                check(sources.add(id) && allowedEvidence.contains(id)); text(source, "quote");
                check(text(source, "url").matches("https?://[^\\s]+"));
                Instant published = sourceAvailable(source); check(!published.isAfter(cutoff));
                if ("previous_issue".equals(kind)) check(!published.isAfter(origin));
            }
            check(!sources.isEmpty());
            Set<String> analyzed = new HashSet<>();
            if (item.has("aiAnalyses")) for (var analysis : array(item, "aiAnalyses")) {
                analysis(analysis, personal, round, cutoff, issue, companies, sources);
                check(analyzed.add(text(analysis, "companyId")));
                if (!personal) same(text(analysis, "resultVersion"), text(item, "analysisResultVersion"));
            }
            for (String optional : List.of("topicTag", "analysisOmittedReason", "analysisWithheldReason"))
                if (item.has(optional)) text(item, optional);
            if (personal) {
                // Preserved pre-existing prose remains distinct from the newly verified business analysis.
                for (var prior : array(item, "priorAnalysis")) {
                    keys(prior, "companyName takeaway positive negative conditions");
                    for (String key : List.of("companyName", "takeaway", "positive", "negative")) check(field(prior, key).isString());
                    for (var condition : array(prior, "conditions")) check(condition.isString() && !condition.asString().isBlank());
                }
                if (!field(item, "price").isNull()) price(item.get("price"), cutoff);
            } else for (var price : array(item, "prices")) price(price, cutoff);
        }
    }

    private static void analysis(JsonNode a, boolean personal, String round, Instant cutoff, String issue,
            Set<String> companies, Set<String> sources) {
        keys(a, "companyId companyName roundId cutoff resultVersion verificationMode direction keyPoint confirmedFact businessImpact companyConnection forMyStocks outlook nextCheck positive negative priceObservation previousChange evidenceIds judgmentBasis comparison");
        check(personal ? !a.has("companyConnection") : !a.has("forMyStocks"));
        check(companies.contains(text(a, "companyId"))); text(a, "companyName");
        same(text(a, "roundId"), round); same(time(a, "cutoff"), cutoff); text(a, "resultVersion");
        same(text(a, "verificationMode"), "separate_request_same_model"); choice(a, "direction", DIRECTIONS);
        for (String key : List.of("keyPoint", "confirmedFact", "businessImpact", personal ? "forMyStocks" : "companyConnection", "outlook", "nextCheck")) text(a, key);
        for (String key : List.of("positive", "negative", "priceObservation")) nullableText(a, key);
        var previous = field(a, "previousChange"); keys(previous, "status text"); text(previous, "text");
        choice(previous, "status", Set.of("unavailable", "maintained", "strengthened", "weakened"));
        Set<String> evidence = strings(a, "evidenceIds"); check(!evidence.isEmpty() && sources.containsAll(evidence));
        var basis = field(a, "judgmentBasis"); keys(basis, "promptVersion directionReason confidence effectSizeStatus");
        same(text(basis, "promptVersion"), personal ? "personal-impact-relative-v3" : "common-impact-relative-v1");
        text(basis, "directionReason"); choice(basis, "confidence", Set.of("limited", "moderate", "high"));
        choice(basis, "effectSizeStatus", Set.of("unquantified", "quantified"));
        if (personal) {
            var comparison = field(a, "comparison"); keys(comparison, "status baseline");
            String status = choice(comparison, "status", Set.of("newly_selected", "same_issue_company"));
            var before = field(comparison, "baseline");
            if ("newly_selected".equals(status)) check(before.isNull());
            else {
                keys(before, "issueId companyId roundId cutoff resultVersion direction businessImpact outlook");
                same(text(before, "issueId"), issue); same(text(before, "companyId"), text(a, "companyId"));
                same(text(before, "roundId"), round); same(time(before, "cutoff"), cutoff);
                check(!text(before, "resultVersion").equals(text(a, "resultVersion")));
                choice(before, "direction", DIRECTIONS); text(before, "businessImpact"); text(before, "outlook");
            }
        } else check(!a.has("comparison"));
    }

    public static void summary(JsonNode summary, String round, Instant cutoff, Set<String> evidence) {
        keys(summary, "schemaVersion roundId cutoff resultVersion text evidenceIds");
        same(text(summary, "schemaVersion"), "briefing-priority-summary-v1");
        same(text(summary, "roundId"), round); same(time(summary, "cutoff"), cutoff);
        text(summary, "resultVersion"); text(summary, "text");
        var refs = strings(summary, "evidenceIds"); check(!refs.isEmpty() && evidence.containsAll(refs));
    }

    /** A display quote/link/time must be the same preserved evidence as the authorized database source. */
    public static boolean storedSourcesMatch(JsonNode priority, JdbcTemplate jdbc) {
        for (var item : array(priority, "items")) for (var source : array(item, "sources")) {
            Integer count = jdbc.queryForObject("""
                SELECT count(*) FROM evidence e
                JOIN article_versions v ON v.article_id=e.article_id AND v.version=e.article_version
                JOIN articles a ON a.id=e.article_id
                WHERE e.id=? AND e.quote=? AND v.url=? AND v.published_at IS NOT DISTINCT FROM ?::timestamptz
                AND a.access_status='available' AND e.quote_verified IS TRUE
                AND e.verification_artifact_id IS NOT NULL AND e.text_artifact_id=v.text_artifact_id
                AND e.input_kind='body' AND e.offset_unit='unicode_code_point'
                """, Integer.class, text(source,"evidenceId"), text(source,"quote"), text(source,"url"), source.path("publishedAt").isNull()?null:text(source,"publishedAt"));
            if (count == null || count != 1) return false;
            if(source.path("publishedAt").isNull()){
                Integer clocks=jdbc.queryForObject("SELECT count(*) FROM evidence e JOIN article_versions v ON v.article_id=e.article_id AND v.version=e.article_version WHERE e.id=? AND v.publication_precision='day' AND v.published_date=?::date AND v.collected_at=?::timestamptz",Integer.class,text(source,"evidenceId"),text(source,"publishedDate"),text(source,"availableAt"));
                if(clocks==null || clocks!=1)return false;
            }
        }
        return true;
    }

    public static Instant sourceAvailable(JsonNode source) {
        if(!field(source,"publishedAt").isNull())return time(source,"publishedAt");
        same(text(source,"eligibilityBasis"),"first_observed");
        var day=java.time.LocalDate.parse(text(source,"publishedDate"));var observed=time(source,"availableAt");
        check(!day.isAfter(observed.atZone(java.time.ZoneId.of("Asia/Seoul")).toLocalDate()));
        return observed;
    }

    private static void price(JsonNode p, Instant cutoff) {
        keys(p, "companyName baseline latest changeRate currency observedAt");
        for (String k : List.of("companyName", "baseline", "latest", "changeRate", "currency")) text(p, k);
        check(!time(p, "observedAt").isAfter(cutoff));
    }
    public static Set<String> strings(JsonNode value, String key) {
        Set<String> out = new HashSet<>();
        for (var s : array(value, key)) { check(s.isString() && !s.asString().isBlank() && out.add(s.asString())); }
        return out;
    }
    private static void keys(JsonNode n, String allowed) {
        check(n != null && n.isObject()); var keys = Set.of(allowed.split(" "));
        for (String key : n.propertyNames()) check(keys.contains(key));
    }
    private static JsonNode field(JsonNode n, String k) { JsonNode v = n.get(k); check(v != null); return v; }
    private static JsonNode array(JsonNode n, String k) { var v = field(n,k); check(v.isArray()); return v; }
    private static String text(JsonNode n, String k) { var v = field(n,k); check(v.isString() && !v.asString().isBlank()); return v.asString(); }
    private static void nullableText(JsonNode n, String k) { if (!field(n,k).isNull()) text(n,k); }
    private static Instant time(JsonNode n, String k) { return Instant.parse(text(n,k)); }
    private static int integer(JsonNode n, String k) { var v = field(n,k); check(v.isIntegralNumber() && v.canConvertToInt() && v.asInt() >= 0); return v.asInt(); }
    private static String choice(JsonNode n, String k, Set<String> options) { var v = text(n,k); check(options.contains(v)); return v; }
    private static void same(Object a,Object b) { check(Objects.equals(a,b)); }
    private static void check(boolean value) { if (!value) throw new IllegalArgumentException("Invalid briefing priority projection"); }
}
