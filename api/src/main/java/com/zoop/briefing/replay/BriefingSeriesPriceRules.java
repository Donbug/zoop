package com.zoop.briefing.replay;

import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import java.nio.file.Path;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.time.Instant;
import java.util.*;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.node.ObjectNode;

/** Non-AI price enrichment is bound to the unmodified completed series and original outlook. */
final class BriefingSeriesPriceRules {
    static final String SCHEMA = "zoop-series-company-prices-v1";
    private BriefingSeriesPriceRules() { }

    static Map<String, StrictJson.Obj> rows(StrictJson.Obj bundle, String authorization,
            Map<String, StrictJson.Obj> companies, Path output) {
        StrictJson.Obj enrichment = bundle.object("marketEnrichment");
        if (!enrichment.has("seriesCompanyPrices")) return Map.of();
        StrictJson.Obj layer = enrichment.object("seriesCompanyPrices");
        require(SCHEMA.equals(layer.string("schemaVersion")) && authorization.equals(layer.string("authorizationRef")), "authorization");
        ObjectNode original = (ObjectNode) bundle.node().deepCopy();
        ((ObjectNode) original.path("marketEnrichment")).remove("seriesCompanyPrices");
        try {
            Path baseline = output.resolve("prices-baseline.json");
            require(Files.isRegularFile(baseline, LinkOption.NOFOLLOW_LINKS) && Files.size(baseline) <= 25_000_000, "base_file");
            byte[] bytes = Files.readAllBytes(baseline);
            require(Canonical.sha256(bytes).equals(layer.string("baseBundleSha256"))
                    && original.equals(StrictJson.parseObject(bytes).node()), "base_bundle");
        } catch (java.io.IOException error) { throw new IllegalArgumentException("Series price baseline unavailable", error); }
        // The explicit request range is part of every receipt and the layer identity.
        long[] range = BriefingCompanyPriceRules.period(layer);
        Map<String, StrictJson.Obj> rows = new LinkedHashMap<>();
        for (StrictJson.Obj row : layer.objects("rounds")) {
            String id = row.string("roundId");
            require(rows.putIfAbsent(id, row) == null && companies.containsKey(id), "round_identity");
            ObjectNode digest = (ObjectNode) row.node().deepCopy(); digest.remove("resultVersion");
            require(("company-prices-v1-" + Canonical.digest(digest)).equals(row.string("resultVersion")), "version");
            StrictJson.Obj company = companies.get(id);
            require("PASS".equals(company.string("status")) && company.string("resultVersion").equals(row.string("companyResultVersion"))
                    && Instant.parse(company.string("cutoff")).equals(Instant.parse(row.string("cutoff"))), "outlook_binding");
            Set<String> expected = new HashSet<>(); company.object("frozen").objects("targets").forEach(t -> expected.add(t.string("companyId")));
            require(expected.equals(Set.copyOf(row.object("prices").node().propertyNames())), "company_coverage");
            Instant recorded = Instant.parse(row.string("recordedAt")), cutoff = Instant.parse(row.string("cutoff"));
            require(!recorded.isBefore(cutoff) && !recorded.isBefore(Instant.parse(company.string("generatedAt")))
                    && !recorded.isAfter(Instant.now().plusSeconds(60))
                    && range[0] < cutoff.getEpochSecond() && cutoff.getEpochSecond() < range[1], "recorded_clock");
            for (String cid : expected) for (StrictJson.Obj source : row.object("prices").object(cid).objects("sources")) {
                require(source.has("period1") && source.has("period2")
                        && Arrays.equals(range, BriefingCompanyPriceRules.period(source))
                        && !Instant.parse(source.string("collectedAt")).isAfter(recorded), "receipt_range_or_clock");
            }
        }
        Set<String> expectedRounds = new HashSet<>(); companies.forEach((id,c) -> { if ("PASS".equals(c.string("status"))) expectedRounds.add(id); });
        require(rows.size() <= 14 && rows.keySet().equals(expectedRounds), "round_coverage");
        return rows;
    }

    static void apply(StrictJson.Obj row, ObjectNode projection, Path output) {
        Instant cutoff = Instant.parse(row.string("cutoff"));
        for (JsonNode node : projection.path("companies")) {
            ObjectNode company = (ObjectNode) node; String cid = company.path("companyId").stringValue();
            company.set("price", BriefingCompanyPriceRules.apply(row.object("prices").object(cid), cid, cutoff, output));
        }
        projection.put("priceVersion", row.string("resultVersion"));
    }
    private static void require(boolean condition, String reason) {
        if (!condition) throw new IllegalArgumentException("Series price rejected: " + reason);
    }
}
