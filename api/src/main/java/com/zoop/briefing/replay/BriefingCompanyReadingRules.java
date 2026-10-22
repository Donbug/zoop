package com.zoop.briefing.replay;

import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import java.nio.file.Path;
import java.time.Instant;
import java.util.*;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.node.ObjectNode;

/** A new short-reading version adds to, and never rewrites, the validated full company analysis. */
final class BriefingCompanyReadingRules {
    static final String SCHEMA = "zoop-company-reading-v1";
    private BriefingCompanyReadingRules() { }
    static Map<String, StrictJson.Obj> rows(StrictJson.Obj layer) {
        require(SCHEMA.equals(layer.string("schemaVersion")) && !layer.string("authorizationRef").isBlank(), "layer");
        Map<String, StrictJson.Obj> out = new LinkedHashMap<>();
        require(!layer.objects("rounds").isEmpty() && layer.objects("rounds").size() <= 4, "round_count");
        for (StrictJson.Obj row : layer.objects("rounds")) require(out.putIfAbsent(row.string("roundId"), row) == null, "duplicate_round");
        return out;
    }
    static void apply(StrictJson.Obj row, StrictJson.Obj original, ObjectNode projection,
            Map<String, JsonNode> receipts, Set<String> owned, Path output) {
        StrictJson.Obj frozen = row.object("frozen");
        ObjectNode expected = StrictJson.newObject().put("schemaVersion", SCHEMA).put("roundId", original.string("roundId"))
                .put("edition", original.string("edition")).put("cutoff", original.string("cutoff"))
                .put("companyResultVersion", original.string("resultVersion"));
        expected.set("draft", original.raw("draft").deepCopy());
        expected.set("targets", original.object("frozen").raw("targets").deepCopy());
        expected.set("sources", original.object("frozen").raw("sources").deepCopy());
        require("PASS".equals(original.string("status")) && expected.equals(frozen.node())
                && original.string("roundId").equals(row.string("roundId"))
                && original.string("cutoff").equals(row.string("cutoff")), "full_analysis_binding");
        ObjectNode version = (ObjectNode) row.node().deepCopy(); version.remove("resultVersion");
        require(("reading-v1-" + Canonical.digest(version)).equals(row.string("resultVersion")), "version");
        Set<String> ids = new HashSet<>(); frozen.objects("targets").forEach(t -> ids.add(t.string("companyId")));
        require(ids.equals(Set.copyOf(row.object("prices").node().propertyNames())), "price_company_coverage");
        List<StrictJson.Obj> attempts = row.objects("attempts"); require(!attempts.isEmpty() && attempts.size() <= 2, "attempt_count");
        Instant generated = Instant.parse(row.string("generatedAt"));
        for (StrictJson.Obj attempt : attempts) {
            for (String phase : List.of("generation", "verification")) {
                String key = phase + "RequestDigest"; if (!attempt.has(key)) continue;
                String digest = attempt.string(key);
                StrictJson.Obj actual = BriefingCompanyOutlookRules.recordedCall(digest, phase, frozen, receipts, output, owned,
                        "company_reading_", "company-reading-v1");
                require(actual.node().equals(attempt.object(phase.equals("generation") ? "draft" : "verification").node()), "recorded_response");
                require(!Instant.parse(StrictJson.Obj.of(receipts.get(digest)).string("finishedAt")).isAfter(generated), "completion_clock");
                if (phase.equals("verification")) {
                    try {
                        StrictJson.Obj request = StrictJson.parseObject(java.nio.file.Files.readAllBytes(output.resolve("calls/" + digest + ".request.json")));
                        require(StrictJson.parseObject(request.string("input")).object("draft").node().equals(attempt.object("draft").node()), "verification_draft");
                    } catch (java.io.IOException error) { throw new IllegalArgumentException("Reading request missing", error); }
                }
            }
        }
        boolean passed = "PASS".equals(row.string("status")); require(passed || "WITHHELD".equals(row.string("status")), "status");
        Map<String, StrictJson.Obj> shortTexts = new LinkedHashMap<>();
        if (passed) {
            StrictJson.Obj last = attempts.getLast();
            require(last.object("draft").node().equals(row.object("draft").node())
                    && row.string("generationRequestDigest").equals(last.string("generationRequestDigest"))
                    && row.string("verificationRequestDigest").equals(last.string("verificationRequestDigest")), "final_attempt");
            Set<String> checks = new HashSet<>();
            for (StrictJson.Obj check : last.object("verification").objects("checks"))
                require(checks.add(check.string("companyId")) && check.bool("supported") && !check.string("reason").isBlank(), "semantic_check");
            require(checks.equals(ids), "verification_coverage");
            for (StrictJson.Obj c : row.object("draft").objects("companies")) {
                require(shortTexts.putIfAbsent(c.string("companyId"), c) == null, "duplicate_company");
                StrictJson.Obj target = frozen.objects("targets").stream().filter(t -> t.string("companyId").equals(c.string("companyId"))).findFirst().orElseThrow();
                Set<String> allowed = Set.copyOf(target.strings("sourceIds"));
                for (String field : List.of("brief", "watch", "change")) {
                    StrictJson.Obj s = c.object(field); int max = switch (field) { case "brief" -> 70; case "watch" -> 50; default -> 60; };
                    String text = s.string("text");
                    require(!text.isBlank() && text.codePointCount(0, text.length()) <= max && !s.strings("evidenceIds").isEmpty()
                            && allowed.containsAll(s.strings("evidenceIds")) && Set.copyOf(s.strings("evidenceIds")).size() == s.strings("evidenceIds").size(), "short_statement");
                }
            }
            require(shortTexts.keySet().equals(ids), "short_company_coverage");
        } else require(row.isNull("draft"), "withheld_projection");
        for (JsonNode node : projection.path("companies")) {
            ObjectNode c = (ObjectNode) node; String id = c.path("companyId").stringValue();
            ObjectNode reading = c.putObject("reading").put("status", row.string("status")).put("resultVersion", row.string("resultVersion"));
            if (passed) for (String field : List.of("brief", "watch", "change")) reading.set(field, shortTexts.get(id).raw(field).deepCopy());
            c.set("price", BriefingCompanyPriceRules.apply(row.object("prices").object(id), id, Instant.parse(row.string("cutoff")), output));
        }
        projection.put("readingVersion", row.string("resultVersion"));
    }
    private static void require(boolean value, String reason) {
        if (!value) throw new IllegalArgumentException("Company short reading rejected: " + reason);
    }
}
