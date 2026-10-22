package com.zoop.briefing.replay;

import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.util.*;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.node.ObjectNode;

/** A second editorial assessment can reject reprints without changing native event/group decisions. */
final class BriefingEditorialRules {
    static final String COMPANY_POLICY = "accepted-issue-company-evidence-v1";
    private BriefingEditorialRules() { }

    static void archive(StrictJson.Obj archive, Path output) {
        if (!archive.has("editorialReview")) return;
        StrictJson.Obj layer = archive.object("editorialReview");
        require("zoop-editorial-freshness-v1".equals(layer.string("schemaVersion"))
                && Canonical.digest(layer.node()).equals(archive.object("identity").string("editorialReviewSha256")), "identity");
        StrictJson.Obj history = layer.object("history");
        require("zoop-editorial-history-v1".equals(history.string("schemaVersion")), "history_schema");
        Map<String, StrictJson.Obj> reports = new LinkedHashMap<>();
        for (StrictJson.Obj report : history.objects("reports")) {
            require(reports.putIfAbsent(report.string("reportId"), report) == null
                    && report.string("url").startsWith("https://") && !report.strings("companyIds").isEmpty()
                    && Canonical.sha256(report.string("body")).equals(report.string("bodySha256"))
                    && !report.string("quote").isBlank() && report.string("body").contains(report.string("quote")), "history_source");
            require(Set.of("verified_publisher_day", "verified_publisher_timestamp", "unverified_search_index").contains(report.string("clockStatus")), "clock_status");
            Instant.parse(report.string("availableBefore"));
        }
        Map<String, StrictJson.Obj> receipts = new LinkedHashMap<>();
        archive.objects("receipts").stream().filter(r -> "editorial_freshness".equals(r.string("stage")))
                .forEach(r -> require(receipts.putIfAbsent(r.string("requestDigest"), r) == null, "duplicate_receipt"));
        Set<String> owned = new HashSet<>(), windows = new HashSet<>();
        for (StrictJson.Obj row : layer.objects("rounds")) {
            StrictJson.Obj frozen = row.object("frozen");
            require(frozen.object("window").node().equals(row.object("window").node())
                    && windows.add(Canonical.digest(row.object("window").node())), "window");
            Instant from = Instant.parse(row.object("window").string("from")), to = Instant.parse(row.object("window").string("to"));
            require(from.isBefore(to), "window_order");
            Map<String, StrictJson.Obj> available = new LinkedHashMap<>();
            for (StrictJson.Obj report : frozen.objects("reports"))
                require(reports.containsKey(report.string("reportId")) && reports.get(report.string("reportId")).node().equals(report.node())
                        && !Instant.parse(report.string("availableBefore")).isAfter(from)
                        && available.putIfAbsent(report.string("reportId"), report) == null, "future_or_changed_history");
            Map<String, StrictJson.Obj> issues = new LinkedHashMap<>();
            for (StrictJson.Obj candidate : frozen.objects("issues")) {
                String id = candidate.string("issueId");
                require(issues.putIfAbsent(id, candidate) == null
                        && available.keySet().containsAll(candidate.strings("priorReportIds")), "review_issue");
                StrictJson.Obj original = archive.objects("issues").stream().filter(i -> id.equals(i.string("issueId"))).findFirst().orElseThrow();
                Map<String, StrictJson.Obj> expected = new LinkedHashMap<>(); Set<String> companies = new HashSet<>();
                for (StrictJson.Obj m : original.objects("mentions")) {
                    Instant time = Instant.parse(m.string("publishedAt"));
                    if (!time.isAfter(from) || time.isAfter(to)) continue;
                    m.objects("evidence").forEach(e -> expected.put(e.string("evidenceId"), e));
                    m.objects("companies").forEach(c -> companies.add(c.string("companyId")));
                }
                Set<String> seen = new HashSet<>();
                for (StrictJson.Obj proof : candidate.objects("newEvidence")) {
                    StrictJson.Obj e = expected.get(proof.string("evidenceId"));
                    require(e != null && seen.add(proof.string("evidenceId")) && e.string("quote").equals(proof.string("quote"))
                            && e.string("articleId").equals(proof.string("documentId")) && e.count("start") == proof.count("start")
                            && e.count("end") == proof.count("end") && !Instant.parse(proof.object("publicationClock").string("publishedAt")).isAfter(to), "current_quote");
                }
                require(seen.equals(expected.keySet()), "current_quote_population");
                for (String reportId : candidate.strings("priorReportIds"))
                    require(available.get(reportId).strings("companyIds").stream().anyMatch(companies::contains), "history_company");
                StrictJson.Obj decision = row.object("decisions").object(id);
                require(Set.of("REPEAT", "MATERIAL_UPDATE", "DISTINCT_EVENT", "UNCERTAIN").contains(decision.string("decision"))
                        && !decision.string("reason").isBlank() && seen.containsAll(decision.strings("deltaEvidenceIds"))
                        && new HashSet<>(decision.strings("deltaEvidenceIds")).size() == decision.strings("deltaEvidenceIds").size()
                        && (!decision.strings("deltaEvidenceIds").isEmpty()) == "MATERIAL_UPDATE".equals(decision.string("decision")), "delta");
            }
            if ("editorial-freshness-v3".equals(layer.string("promptVersion"))) {
                Set<String> expectedIssues = new HashSet<>();
                for (StrictJson.Obj issue : archive.objects("issues")) {
                    var asof = issue.objects("mentions").stream().filter(m -> !Instant.parse(m.string("publishedAt")).isAfter(to)).toList();
                    if (asof.stream().allMatch(BriefingGroupedSimulationRules::companyEligible)
                            && asof.stream().anyMatch(m -> Instant.parse(m.string("publishedAt")).isAfter(from))) expectedIssues.add(issue.string("issueId"));
                }
                require(issues.keySet().equals(expectedIssues), "review_population");
            }
            row.object("decisions").exactly(issues.keySet());
            if (issues.isEmpty()) { require(row.isNull("requestDigest"), "empty_receipt"); continue; }
            String digest = row.string("requestDigest");
            require(owned.add(digest) && receipts.containsKey(digest), "receipt_owner");
            var call = BriefingGroupedSimulationRules.recording(receipts.get(digest), output, true);
            ObjectNode actualInput = (ObjectNode) call.input().node().deepCopy();
            if (actualInput.has("editorialCorrection")) {
                StrictJson.Obj correction = call.input().object("editorialCorrection");
                String originalDigest = correction.string("originalRequestDigest");
                require(correction.count("attempt") == 1 && "editorial_delta_binding".equals(correction.string("failure"))
                        && receipts.containsKey(originalDigest) && owned.add(originalDigest)
                        && receipts.get(originalDigest).string("responseSha256").equals(correction.string("originalResponseSha256")), "correction_origin");
                var original = BriefingGroupedSimulationRules.recording(receipts.get(originalDigest), output, true);
                require(original.input().node().equals(frozen.node()) && original.answer().node().equals(correction.object("previousReply").node())
                        && row.objects("corrections").size() == 1 && row.objects("corrections").getFirst().node().equals(correction.node()), "correction_unchanged_inputs");
                actualInput.remove("editorialCorrection");
            } else require(!row.has("corrections") || row.objects("corrections").isEmpty(), "correction_missing_call");
            require(actualInput.equals(frozen.node()) && call.answer().node().equals(row.object("decisions").node()), "recorded_review");
            try {
                StrictJson.Obj request = StrictJson.parseObject(Files.readAllBytes(output.resolve("calls/" + digest + ".request.json")));
                require(Set.of("editorial-freshness-v1", "editorial-freshness-v2", "editorial-freshness-v3").contains(layer.string("promptVersion")), "prompt_version");
                byte[] prompt = BriefingEditorialRules.class.getResourceAsStream("/briefing/prompts/"+layer.string("promptVersion")+"/review.md").readAllBytes();
                require(Canonical.sha256(prompt).equals(Canonical.sha256(request.string("instructions"))), "review_prompt");
            } catch (java.io.IOException error) { throw new IllegalArgumentException("Editorial review missing", error); }
        }
        require(owned.equals(receipts.keySet()), "orphan_receipt");
    }

    static ObjectNode decision(StrictJson.Obj archive, StrictJson.Obj window, String issueId) {
        if (!archive.has("editorialReview")) return null;
        StrictJson.Obj row = archive.object("editorialReview").objects("rounds").stream()
                .filter(r -> r.object("window").node().equals(window.node())).findFirst().orElseThrow();
        if (row.object("decisions").has(issueId)) {
            ObjectNode out = (ObjectNode) row.object("decisions").object(issueId).node().deepCopy();
            out.put("reviewRequestDigest", row.string("requestDigest")); return out;
        }
        ObjectNode out = StrictJson.newObject().put("decision", "NOT_CHECKED").put("reason", "No matching earlier report in the bounded history; novelty is not proven.");
        out.putArray("deltaEvidenceIds"); out.putNull("reviewRequestDigest"); return out;
    }

    static SortedSet<String> companies(BriefingGroupedSimulationRules.Archive archive, String documentId, Instant cutoff) {
        SortedSet<String> names = new TreeSet<>();
        for (StrictJson.Obj issue : archive.issues().values()) for (StrictJson.Obj mention : issue.objects("mentions"))
            if (documentId.equals(mention.string("articleId")) && !Instant.parse(mention.string("publishedAt")).isAfter(cutoff)
                    && BriefingGroupedSimulationRules.companyEligible(mention) && "SUPPORTED".equals(mention.object("grounding").string("verdict")))
                mention.objects("companies").forEach(c -> names.add(c.string("name")));
        return names;
    }
    static void require(boolean condition, String reason) {
        if (!condition) throw new IllegalArgumentException("Editorial check rejected: " + reason);
    }
}
