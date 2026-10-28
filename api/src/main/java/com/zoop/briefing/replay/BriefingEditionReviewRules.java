package com.zoop.briefing.replay;

import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import java.nio.file.Path;
import java.time.*;
import java.util.*;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.node.ArrayNode;
import tools.jackson.databind.node.ObjectNode;

/** AM focus / PM review share sources, not outcome labels. Editorial review never impersonates a model verifier. */
public final class BriefingEditionReviewRules {
    static final String SCHEMA = "zoop-edition-review-v1";
    static final String SCOPE = "원발행 시각 기준 과거 시뮬레이션·원문 대조 편집본입니다. 나중에 조회한 보존 자료이며 당시 본문 동일성·주가 인과·예측 적중은 입증하지 않습니다.";
    private BriefingEditionReviewRules() { }

    static ObjectNode reference(StrictJson.Obj previous, StrictJson.Obj current) {
        if (previous == null) return null;
        StrictJson.Obj f = previous.object("frozen"); boolean evening = current.string("edition").equals("evening");
        boolean matches = evening ? f.string("edition").equals("morning") && f.string("date").equals(current.string("date"))
                : f.string("edition").equals("evening") && LocalDate.parse(f.string("date")).equals(LocalDate.parse(current.string("date")).minusDays(1));
        if (!matches) return null;
        ObjectNode ref = StrictJson.newObject();
        for (String k : List.of("resultVersion", "draft")) ref.set(k, previous.raw(k).deepCopy());
        for (String k : List.of("roundId", "date", "edition", "cutoff")) ref.set(k, f.raw(k).deepCopy());
        return ref;
    }
    static ObjectNode freeze(StrictJson.Obj current, StrictJson.Obj previous, String marketSnapshotSha, StrictJson.Obj proposed,
            Map<String, BriefingPresentationRules.Evidence> evidence, Path output) {
        require(marketSnapshotSha.matches("[0-9a-f]{64}"), "market_binding");
        ObjectNode ref = reference(previous, current), sources = ref == null ? StrictJson.newObject() : (ObjectNode) previous.object("frozen").raw("sources").deepCopy();
        Map<String, ObjectNode> targets = new LinkedHashMap<>();
        for (StrictJson.Obj t : current.object("frozen").objects("targets")) {
            ObjectNode target = StrictJson.newObject().put("companyId", t.string("companyId")).put("companyName", t.string("companyName")).put("role", "selected");
            target.set("sourceIds", t.raw("sourceIds").deepCopy()); target.putNull("previous"); targets.put(t.string("companyId"), target);
        }
        if (ref != null) for (StrictJson.Obj t : previous.object("frozen").objects("targets")) {
            String id = t.string("companyId"); ObjectNode target = targets.computeIfAbsent(id, k -> {
                ObjectNode n = StrictJson.newObject().put("companyId", id).put("companyName", t.string("companyName")).put("role", "tracked"); n.putArray("sourceIds"); n.putNull("previous"); return n;
            });
            for (String sid : t.strings("sourceIds")) if (!StrictJson.Obj.of(target).strings("sourceIds").contains(sid)) ((ArrayNode) target.path("sourceIds")).add(sid);
            target.set("previous", previous.object("draft").objects("companies").stream().filter(c -> id.equals(c.string("companyId"))).findFirst().orElseThrow().node().deepCopy());
        }
        for (String sid : current.object("frozen").object("sources").node().propertyNames()) {
            StrictJson.Obj saved = current.object("frozen").object("sources").object(sid); var actual = evidence.get(sid);
            require(actual != null && saved.string("documentId").equals(actual.documentId()) && saved.string("bodySha256").equals(actual.bodySha256()), "source_identity");
            ObjectNode value = (ObjectNode) saved.node().deepCopy(); value.put("fullBody", actual.body());
            require(!sources.has(sid) || sources.get(sid).equals(value), "source_conflict"); sources.set(sid, value);
        }
        int size = 0; for (String sid : sources.propertyNames()) {
            StrictJson.Obj source = StrictJson.Obj.of(sources.get(sid)); var actual = evidence.get(sid); String body = source.string("fullBody");
            require(actual != null && actual.body().equals(body) && source.string("bodySha256").equals(Canonical.sha256(body.getBytes(java.nio.charset.StandardCharsets.UTF_8)))
                    && body.contains(source.string("quote")) && body.codePointCount(0, body.length()) <= 100000
                    && !Instant.parse(source.string("publishedAt")).isAfter(Instant.parse(current.string("cutoff"))), "source_body_clock");
            size += body.codePointCount(0, body.length());
        }
        require(targets.size() <= 12 && size <= 256000, "tracking_capacity");
        Map<String, StrictJson.Obj> proposedTargets = new LinkedHashMap<>();
        for (StrictJson.Obj t : proposed.objects("targets")) require(proposedTargets.putIfAbsent(t.string("companyId"), t) == null, "duplicate_target");
        require(proposedTargets.keySet().equals(targets.keySet()), "target_coverage");
        for (var entry : targets.entrySet()) {
            StrictJson.Obj price = proposedTargets.get(entry.getKey()).object("price");
            BriefingCompanyPriceRules.apply(price, entry.getKey(), Instant.parse(current.string("cutoff")), output);
            entry.getValue().set("price", price.node().deepCopy());
        }
        ObjectNode frozen = StrictJson.newObject().put("schemaVersion", SCHEMA);
        for (String k : List.of("roundId", "date", "edition", "cutoff")) frozen.set(k, current.raw(k).deepCopy());
        frozen.put("analysisVersion", current.string("resultVersion"));
        if (ref == null) frozen.putNull("previousReview"); else frozen.set("previousReview", ref);
        var ts = frozen.putArray("targets"); targets.values().forEach(ts::add); frozen.set("sources", sources); frozen.put("marketSnapshotSha256", marketSnapshotSha);
        frozen.putObject("capabilities").put("intraday", "unavailable").put("sectors", "unavailable").put("flows", "unavailable").put("calendar", "unverified");
        frozen.put("scopeNote", SCOPE); return frozen;
    }
    static ObjectNode apply(StrictJson.Obj row, StrictJson.Obj current, StrictJson.Obj previous, JsonNode market, String marketSnapshotSha,
            Map<String, BriefingPresentationRules.Evidence> evidence, Path output) {
        require("REVIEWED".equals(row.string("status")) && "codex".equals(row.string("reviewer")) && "editorial_source_review".equals(row.string("verificationMode")), "editorial_mode");
        StrictJson.Obj f = row.object("frozen");
        try { require(freeze(current, previous, marketSnapshotSha, f, evidence, output).equals(f.node()), "frozen_binding"); }
        catch (StrictJson.Malformed e) { throw new IllegalArgumentException("Edition review frozen input malformed", e); }
        ObjectNode hash = (ObjectNode) row.node().deepCopy(); hash.remove("resultVersion");
        require(("edition-v1-" + Canonical.digest(hash)).equals(row.string("resultVersion")), "version");
        Instant.parse(row.string("reviewedAt"));
        try { validateDraft(row.object("draft"), f); }
        catch (StrictJson.Malformed e) { throw new IllegalArgumentException("Edition review draft malformed", e); }
        ObjectNode out = (ObjectNode) row.object("draft").node().deepCopy();
        out.put("schemaVersion", SCHEMA).put("status", "REVIEWED").put("reviewer", row.string("reviewer")).put("verificationMode", row.string("verificationMode"))
                .put("reviewedAt", row.string("reviewedAt")).put("resultVersion", row.string("resultVersion"));
        for (String k : List.of("roundId", "date", "edition", "cutoff", "analysisVersion", "scopeNote")) out.set(k, f.raw(k).deepCopy());
        out.set("previousReview", f.raw("previousReview").deepCopy()); out.set("sources", f.raw("sources").deepCopy());
        out.set("marketVariables", market.deepCopy()); out.set("capabilities", f.raw("capabilities").deepCopy());
        Map<String, StrictJson.Obj> ts = new HashMap<>(); f.objects("targets").forEach(t -> ts.put(t.string("companyId"), t));
        for (JsonNode c : out.path("companies")) {
            ObjectNode value = (ObjectNode) c; StrictJson.Obj target = ts.get(c.path("companyId").stringValue());
            for (String k : List.of("companyName", "role", "sourceIds", "previous", "price")) value.set(k, target.raw(k).deepCopy());
        }
        return out;
    }
    static void validateDraft(StrictJson.Obj draft, StrictJson.Obj f) {
        text(draft.string("headline"), 120); Set<String> all = Set.copyOf(f.object("sources").node().propertyNames());
        for (String k : List.of("summary", "marketInterpretation", "comparison", "nextSession")) statement(draft.object(k), all, k.equals("marketInterpretation") ? 700 : 600, false);
        Map<String, StrictJson.Obj> targets = new HashMap<>(); f.objects("targets").forEach(t -> targets.put(t.string("companyId"), t)); Set<String> seen = new HashSet<>();
        for (StrictJson.Obj c : draft.objects("companies")) {
            String id = c.string("companyId"); require(targets.containsKey(id) && seen.add(id), "company_coverage"); StrictJson.Obj target = targets.get(id);
            require(Set.of("priority_watch", "watch", "cautious_watch", "deferred").contains(c.string("stance")), "stance"); Set<String> own = Set.copyOf(target.strings("sourceIds"));
            for (String k : List.of("title", "takeaway", "newInformation", "judgment", "positive", "negative")) statement(c.object(k), own, switch(k) { case "title" -> 40; case "takeaway" -> 100; case "positive", "negative" -> 300; default -> 600; }, true);
            require(!c.objects("watch").isEmpty() && c.objects("watch").size() <= 3, "watch"); c.objects("watch").forEach(s -> statement(s, own, 240, true));
            List<String> previousConditions = target.isNull("previous") ? List.of() : target.object("previous").objects("watch").stream().map(s -> s.string("text")).toList();
            require(c.objects("checks").stream().map(s -> s.string("condition")).toList().equals(previousConditions), "previous_condition_coverage");
            Set<String> retained = new HashSet<>(); c.objects("watch").forEach(w -> retained.add(w.string("text")));
            for (StrictJson.Obj check : c.objects("checks")) {
                require(!check.string("status").equals("not_observed") || retained.contains(check.string("condition")), "unresolved_condition_dropped");
                require(Set.of("confirmed", "contradicted", "not_observed").contains(check.string("status")), "check_status");
                statement(check.object("observation"), own, 400, !check.string("status").equals("not_observed"));
                if (!check.string("status").equals("not_observed")) require(check.object("observation").strings("evidenceIds").stream().anyMatch(sid -> {
                    Instant at = Instant.parse(f.object("sources").object(sid).string("publishedAt"));
                    return at.isAfter(Instant.parse(f.object("previousReview").string("cutoff"))) && !at.isAfter(Instant.parse(f.string("cutoff")));
                }), "condition_new_evidence");
            }
        }
        require(seen.equals(targets.keySet()), "company_coverage");
    }
    public static void validateProjection(JsonNode node, String id, String edition, Instant cutoff, JsonNode actualMarket, String analysisVersion, Set<String> selected) {
        StrictJson.Obj value = StrictJson.Obj.of(node);
        require(SCHEMA.equals(value.string("schemaVersion")) && "REVIEWED".equals(value.string("status")) && "editorial_source_review".equals(value.string("verificationMode"))
                && id.equals(value.string("roundId")) && edition.equals(value.string("edition")) && cutoff.equals(Instant.parse(value.string("cutoff"))), "projection_binding");
        require(value.raw("marketVariables").equals(actualMarket) && analysisVersion.equals(value.string("analysisVersion")), "projection_market_analysis");
        Set<String> actualSelected = new HashSet<>();
        for (StrictJson.Obj c : value.objects("companies")) if ("selected".equals(c.string("role"))) actualSelected.add(c.string("companyId"));
        require(actualSelected.equals(selected), "projection_selection");
        if (!value.isNull("previousReview")) require(Instant.parse(value.object("previousReview").string("cutoff")).isBefore(cutoff), "projection_previous_clock");
        for (String sid : value.object("sources").node().propertyNames()) {
            StrictJson.Obj source = value.object("sources").object(sid);
            require(source.string("bodySha256").equals(Canonical.sha256(source.string("fullBody").getBytes(java.nio.charset.StandardCharsets.UTF_8)))
                    && !Instant.parse(source.string("publishedAt")).isAfter(cutoff), "projection_source");
        }
        for (String capability : List.of("intraday", "sectors", "flows")) require("unavailable".equals(value.object("capabilities").string(capability)), "projection_capability");
        require("unverified".equals(value.object("capabilities").string("calendar")), "projection_calendar");
        ObjectNode f = (ObjectNode) value.node().deepCopy(); var targets = f.putArray("targets");
        for (StrictJson.Obj c : value.objects("companies")) {
            require(Set.of("selected", "tracked").contains(c.string("role")), "role"); targets.add(c.node().deepCopy());
            StrictJson.Obj price = c.object("price"); require(c.string("companyId").equals(price.string("companyId")) && cutoff.equals(Instant.parse(price.string("cutoff"))), "price_cutoff");
            if (!price.isNull("latest")) require(!Instant.parse(price.object("latest").string("observedAt")).isAfter(cutoff), "future_price");
        }
        validateDraft(value, StrictJson.Obj.of(f));
    }
    private static void text(String value, int max) { require(!value.isBlank() && value.codePointCount(0, value.length()) <= max, "text"); }
    private static void statement(StrictJson.Obj s, Set<String> allowed, int max, boolean required) {
        text(s.string("text"), max); List<String> ids = s.strings("evidenceIds");
        require((!required || !ids.isEmpty()) && ids.size() <= 6 && Set.copyOf(ids).size() == ids.size() && allowed.containsAll(ids), "statement");
    }
    private static void require(boolean ok, String why) { if (!ok) throw new IllegalArgumentException("Edition review rejected: " + why); }
}
