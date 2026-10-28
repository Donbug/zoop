package com.zoop.briefing.replay;

import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import java.nio.file.Path;
import java.time.*;
import java.util.*;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.node.*;

/** v5 is a new model result; the old editorial judgment and price projection remain immutable. */
public final class BriefingAiPriceOutlookRules {
    public static final String SCHEMA = "zoop-ai-price-outlooks-v1";
    private BriefingAiPriceOutlookRules() { }
    private static void require(boolean value, String reason) {
        if (!value) throw new IllegalArgumentException("AI price outlook rejected: " + reason);
    }
    private static ObjectNode movement(StrictJson.Obj price) {
        var out = StrictJson.newObject();
        for (var k : List.of("companyId", "status", "currency", "provider", "cutoff", "responseSha256s")) out.set(k, price.raw(k).deepCopy());
        if (!"available".equals(price.string("status"))) { out.set("reason", price.raw("reason").deepCopy()); return out; }
        for (var k : List.of("sessionDate", "exchangeTimezone", "completeSession", "barCount", "latest", "day")) out.set(k, price.raw(k).deepCopy());
        var news = out.putArray("news");
        for (var n : price.objects("news")) {
            var item = news.addObject();
            for (var k : List.of("evidenceId", "publishedAt", "timing", "status", "postNewsBars", "before", "changeRatePercent")) item.set(k, n.raw(k).deepCopy());
        }
        var am = (ObjectNode) price.raw("sinceMorning").deepCopy(); am.remove("observation"); out.set("sinceMorning", am); return out;
    }
    private static ObjectNode previous(String id, StrictJson.Obj current, List<StrictJson.Obj> history) {
        for (int i = history.size() - 1; i >= 0; i--) {
            var row = history.get(i);
            if (!"PASS".equals(row.string("status"))) continue;
            if ("evening".equals(current.string("edition")) && (!"morning".equals(row.string("edition")) || !row.string("date").equals(current.string("date")))) continue;
            if ("morning".equals(current.string("edition")) && (!"evening".equals(row.string("edition")) || !LocalDate.parse(current.string("date")).minusDays(1).toString().equals(row.string("date")))) continue;
            for (var c : row.object("draft").objects("companies")) if (id.equals(c.string("companyId"))) {
                var p = StrictJson.newObject().put("status", "available").put("kind", "verified_ai_price_outlook")
                        .put("roundId", row.string("roundId")).put("cutoff", row.string("cutoff")).put("resultVersion", row.string("resultVersion"));
                p.set("judgment", c.node().deepCopy()); return p;
            }
        }
        return StrictJson.newObject().put("status", "unavailable").put("reason", "evening".equals(current.string("edition"))
                ? "same_day_morning_company_judgment_missing" : "previous_company_judgment_missing");
    }
    private static void statement(StrictJson.Obj s, Set<String> allowed) {
        var text = s.string("text"); var ids = s.strings("evidenceIds");
        require(!text.isBlank() && text.codePointCount(0, text.length()) <= 420 && !ids.isEmpty() && ids.size() <= 6
                && new HashSet<>(ids).size() == ids.size() && allowed.containsAll(ids), "statement");
    }
    public static ObjectNode apply(StrictJson.Obj row, StrictJson.Obj review, StrictJson.Obj prices, List<StrictJson.Obj> history,
            Map<String, JsonNode> receipts, Path root, Set<String> owned) {
        var f = row.object("frozen");
        require("company-outlook-v5".equals(f.string("promptVersion")) && "edition-bound-v2".equals(f.string("comparisonContract")), "version");
        for (var k : List.of("roundId", "date", "edition", "cutoff")) require(f.string(k).equals(review.string(k)) && row.string(k).equals(review.string(k)), "round");
        require(f.string("reviewVersion").equals(review.string("resultVersion")) && f.string("priceContextVersion").equals(prices.string("resultVersion"))
                && f.object("sources").node().equals(review.object("sources").node()), "input_binding");
        var market = (ObjectNode) prices.raw("marketReference").deepCopy();
        for (var i : StrictJson.Obj.of(market).objects("indicators")) ((ObjectNode) i.node()).remove("text");
        require(market.equals(f.raw("marketReference")), "market_binding");
        var fs = (ObjectNode) f.node().deepCopy(); fs.remove("inputSha256");
        require(Canonical.sha256(Canonical.appBytes(fs)).equals(f.string("inputSha256")), "input_hash");
        var targets = new LinkedHashMap<String, StrictJson.Obj>();
        for (var t : f.objects("targets")) require(targets.putIfAbsent(t.string("companyId"), t) == null, "duplicate_target");
        require(targets.size() == review.objects("companies").size(), "coverage");
        for (var c : review.objects("companies")) {
            var id = c.string("companyId"); var t = targets.get(id);
            require(t != null && c.string("companyName").equals(t.string("companyName")) && c.string("role").equals(t.string("role"))
                    && c.raw("sourceIds").equals(t.raw("sourceIds")), "company_binding");
            var p = prices.objects("companies").stream().filter(x -> id.equals(x.string("companyId"))).findFirst().orElseThrow();
            require(movement(p).equals(t.raw("observedMovement")), "real_price_binding");
            var facts = StrictJson.newObject().putArray("items");
            for (var sid : c.object("newInformation").strings("evidenceIds")) {
                var s = review.object("sources").object(sid);
                require(!Instant.parse(s.string("publishedAt")).isAfter(Instant.parse(review.string("cutoff"))), "future_source");
                var fact = facts.addObject().put("text", s.string("quote")); fact.putArray("evidenceIds").add(sid);
            }
            require(facts.equals(t.raw("facts")), "facts");
            if (!history.isEmpty()) require(previous(id, row, history).equals(t.raw("previous")), "previous_ai_result");
            else if (c.isNull("previous")) require("unavailable".equals(t.object("previous").string("status")), "first_previous");
            else {
                var prev = t.object("previous");
                require("preserved_editorial_review".equals(prev.string("kind")) && c.raw("previous").equals(prev.raw("judgment"))
                        && review.object("previousReview").string("resultVersion").equals(prev.string("resultVersion")), "editorial_previous");
            }
        }
        var attempts = row.objects("attempts"); require(!attempts.isEmpty() && attempts.size() <= 2, "attempts");
        for (var a : attempts) {
            var draft = BriefingCompanyOutlookRules.recordedCall(a.string("generationRequestDigest"), "generation", f, receipts, root, owned, "company_outlook_", "company-outlook-v5");
            require(draft.node().equals(a.raw("draft")), "generated_bytes");
            if (a.has("verificationRequestDigest")) {
                var v = BriefingCompanyOutlookRules.recordedCall(a.string("verificationRequestDigest"), "verification", f, receipts, root, owned, "company_outlook_", "company-outlook-v5");
                require(v.node().equals(a.raw("verification")), "verified_bytes");
                try {
                    var q = StrictJson.parseObject(java.nio.file.Files.readAllBytes(root.resolve("calls/" + a.string("verificationRequestDigest") + ".request.json")));
                    require(StrictJson.parseObject(q.string("input")).raw("draft").equals(a.raw("draft")), "verified_draft");
                } catch (java.io.IOException e) { throw new IllegalArgumentException("Missing verification request", e); }
            }
        }
        var hashInput = (ObjectNode) row.node().deepCopy(); hashInput.remove("resultVersion");
        require(("ai-price-v1-" + Canonical.sha256(Canonical.appBytes(hashInput))).equals(row.string("resultVersion")), "result_hash");
        var out = StrictJson.newObject().put("schemaVersion", SCHEMA).put("model", "gpt-6-luna").put("promptVersion", "company-outlook-v5")
                .put("verificationMode", "independent_model").put("status", row.string("status")).put("resultVersion", row.string("resultVersion"))
                .put("generatedAt", row.string("generatedAt")).put("inputSha256", f.string("inputSha256"))
                .put("reviewVersion", f.string("reviewVersion")).put("priceContextVersion", f.string("priceContextVersion"));
        for (var k : List.of("roundId", "date", "edition", "cutoff")) out.put(k, row.string(k));
        var companies = out.putArray("companies");
        if ("WITHHELD".equals(row.string("status"))) { require(row.isNull("draft"), "withheld"); return out; }
        require("PASS".equals(row.string("status")), "status");
        var last = attempts.getLast();
        require(last.raw("draft").equals(row.raw("draft")) && last.string("generationRequestDigest").equals(row.string("generationRequestDigest"))
                && last.string("verificationRequestDigest").equals(row.string("verificationRequestDigest")), "final_attempt");
        var checked = new HashSet<String>();
        for (var v : last.object("verification").objects("checks")) require(v.bool("supported") && !v.string("reason").isBlank() && checked.add(v.string("companyId")), "verification");
        require(checked.equals(targets.keySet()), "verified_coverage");
        var seen = new HashSet<String>();
        for (var c : row.object("draft").objects("companies")) {
            var t = targets.get(c.string("companyId")); require(t != null && seen.add(c.string("companyId")), "output_company");
            require(Set.of("positive", "negative", "mixed", "watch").contains(c.string("assessment")), "assessment");
            var allowed = Set.copyOf(t.strings("sourceIds"));
            for (var k : List.of("impact", "outlook", "comparison")) statement(c.object(k), allowed);
            for (var k : List.of("conditions", "risks")) { require(c.objects(k).size() >= 1 && c.objects(k).size() <= 3, "conditions"); c.objects(k).forEach(s -> statement(s, allowed)); }
            var prev = t.object("previous"); var cmp = c.object("comparison");
            require(Objects.equals(prev.has("resultVersion") ? prev.string("resultVersion") : null, cmp.stringOrNull("previousResultVersion"))
                    && ("available".equals(prev.string("status")) ? "morning".equals(row.string("edition")) ? "updated" : "compared" : "unavailable").equals(cmp.string("status")), "comparison");
            var item = (ObjectNode) c.node().deepCopy();
            item.put("companyName", t.string("companyName")).put("role", t.string("role")); item.set("previous", prev.node().deepCopy()); companies.add(item);
        }
        require(seen.equals(targets.keySet()), "output_coverage");
        out.put("generationRequestDigest", row.string("generationRequestDigest")).put("verificationRequestDigest", row.string("verificationRequestDigest"));
        out.put("projectionSha256", Canonical.sha256(Canonical.appBytes(out))); return out;
    }
    public static void validateProjection(StrictJson.Obj out, StrictJson.Obj review, StrictJson.Obj prices) {
        require(SCHEMA.equals(out.string("schemaVersion")) && "company-outlook-v5".equals(out.string("promptVersion"))
                && "gpt-6-luna".equals(out.string("model")) && "independent_model".equals(out.string("verificationMode")), "public_identity");
        for (var k : List.of("roundId", "date", "edition", "cutoff")) require(out.string(k).equals(review.string(k)), "public_round");
        require(review.string("resultVersion").equals(out.string("reviewVersion")) && prices.string("resultVersion").equals(out.string("priceContextVersion")), "public_binding");
        if ("WITHHELD".equals(out.string("status"))) { require(out.objects("companies").isEmpty(), "public_withheld"); return; }
        var copy = (ObjectNode) out.node().deepCopy(); copy.remove("projectionSha256");
        require("PASS".equals(out.string("status")) && Canonical.sha256(Canonical.appBytes(copy)).equals(out.string("projectionSha256")), "public_hash");
        require(out.objects("companies").size() == review.objects("companies").size(), "public_coverage");
    }
}
