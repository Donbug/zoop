package com.zoop.briefing.replay;

import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.node.ArrayNode;
import tools.jackson.databind.node.ObjectNode;

/** Independent import checks: model bytes, same-company history, exact sources and edition cutoff. */
final class BriefingCompanyOutlookRules {
    static final String SCHEMA = "zoop-company-outlooks-v1";
    static final String VERSION = "company-outlook-v1";
    private BriefingCompanyOutlookRules() { }

    static Map<String, StrictJson.Obj> rows(StrictJson.Obj layer) {
        require(SCHEMA.equals(layer.string("schemaVersion")) && !layer.string("authorizationRef").isBlank(), "layer");
        Map<String, StrictJson.Obj> out = new LinkedHashMap<>(); Instant last = Instant.MIN;
        require(!layer.objects("rounds").isEmpty() && layer.objects("rounds").size() <= 4, "round_count");
        for (StrictJson.Obj row : layer.objects("rounds")) {
            Instant cutoff = Instant.parse(row.string("cutoff")); require(cutoff.isAfter(last), "chronology"); last = cutoff;
            require(out.putIfAbsent(row.string("roundId"), row) == null, "duplicate_round");
        }
        return out;
    }

    static ObjectNode apply(StrictJson.Obj row, ObjectNode payload, StrictJson.Obj effective, StrictJson.Obj market,
            Map<String, BriefingPresentationRules.Evidence> evidence, List<StrictJson.Obj> history,
            Map<String, JsonNode> receipts, Path output, Set<String> owned) {
        StrictJson.Obj frozen = row.object("frozen");
        require(SCHEMA.equals(frozen.string("schemaVersion")) && VERSION.equals(frozen.string("promptVersion")), "schema");
        for (String field : List.of("roundId", "date", "edition", "cutoff")) {
            String value = switch (field) { case "roundId" -> payload.path("id").stringValue();
                case "cutoff" -> market.string("cutoff"); default -> payload.path(field).stringValue(); };
            require(value.equals(frozen.string(field)) && value.equals(row.string(field)), "round_binding");
        }
        require(effective.string("resultSha256").equals(frozen.string("newsResultSha256")), "news_binding");
        Instant cutoff = Instant.parse(row.string("cutoff"));
        Set<String> companyIds = new HashSet<>(); Map<String, String> names = new LinkedHashMap<>();
        Map<String, Set<String>> issues = new LinkedHashMap<>();
        for (JsonNode item : payload.path("items")) for (JsonNode company : item.path("companies")) {
            String id = company.path("id").stringValue(); companyIds.add(id); names.put(id, company.path("name").stringValue());
            issues.computeIfAbsent(id, ignored -> new HashSet<>()).add(item.path("eventId").stringValue());
        }
        Map<String, StrictJson.Obj> targets = new LinkedHashMap<>(); Set<String> usedSources = new HashSet<>();
        for (StrictJson.Obj target : frozen.objects("targets")) {
            String id = target.string("companyId");
            require(companyIds.contains(id) && targets.putIfAbsent(id, target) == null
                    && issues.get(id).equals(Set.copyOf(target.strings("issueIds"))), "company_issue_binding");
            ObjectNode expectedPrevious = previous(id, row, history);
            require(expectedPrevious.equals(target.object("previous").node()), "same_company_history");
            require("unavailable".equals(target.object("observedMovement").string("status"))
                    && "cutoff_bound_company_price_feed_missing".equals(target.object("observedMovement").string("reason")), "unobserved_prices");
            ArrayNode facts = StrictJson.newObject().putArray("items"); Set<String> allowed = new HashSet<>();
            for (StrictJson.Obj selected : effective.objects("selected")) if (issues.get(id).contains(selected.string("issueId"))) {
                boolean linked = selected.objects("companyLinks").stream().anyMatch(c -> id.equals(c.string("companyId")) && target.string("companyName").equals(c.string("name")));
                require(linked, "company_link"); selected.objects("sources").forEach(s -> allowed.add(s.string("evidenceId")));
                StrictJson.Obj generated = effective.object("result").objects("items").stream().filter(i -> i.string("issueId").equals(selected.string("issueId"))).findFirst().orElseThrow();
                for (StrictJson.Obj c : generated.objects("claims")) {
                    ObjectNode fact = facts.addObject().put("text", c.string("text")); fact.set("evidenceIds", c.array("evidenceIds").deepCopy());
                }
            }
            require(facts.equals(target.array("facts")), "fact_projection");
            for (StrictJson.Obj doc : market.object("marketContext").objects("documents")) {
                List<String> companyNames = doc.strings("companyNames");
                if (companyNames.contains(target.string("companyName")) || (id.equals("NASDAQ:GOOGL") && companyNames.contains("Alphabet")))
                    doc.objects("sources").forEach(s -> allowed.add(s.string("evidenceId")));
            }
            List<String> sourceIds = target.strings("sourceIds");
            require(!sourceIds.isEmpty() && sourceIds.size() <= 24 && allowed.containsAll(sourceIds)
                    && new HashSet<>(sourceIds).size() == sourceIds.size(), "foreign_company_sources");
            for (String sourceId : sourceIds) {
                StrictJson.Obj saved = frozen.object("sources").object(sourceId); var actual = evidence.get(sourceId);
                require(actual != null && sourceId.equals(saved.string("evidenceId")) && actual.documentId().equals(saved.string("documentId"))
                        && actual.version().equals(saved.string("documentVersion")) && actual.bodySha256().equals(saved.string("bodySha256"))
                        && actual.quote().equals(saved.string("quote")) && actual.title().equals(saved.string("title"))
                        && actual.url().equals(saved.string("url")) && Instant.parse(actual.publishedAt()).equals(Instant.parse(saved.string("publishedAt")))
                        && !Instant.parse(saved.string("publishedAt")).isAfter(cutoff), "source_provenance");
                usedSources.add(sourceId);
            }
        }
        require(targets.keySet().equals(companyIds) && usedSources.equals(Set.copyOf(frozen.object("sources").node().propertyNames())), "coverage");
        List<StrictJson.Obj> attempts = row.objects("attempts"); require(!attempts.isEmpty() && attempts.size() <= 2, "attempt_count");
        for (StrictJson.Obj attempt : attempts) {
            StrictJson.Obj generation = call(attempt.string("generationRequestDigest"), "generation", frozen, receipts, output, owned);
            require(generation.node().equals(attempt.object("draft").node()), "generated_draft_bytes");
            if (attempt.has("verificationRequestDigest")) {
                StrictJson.Obj verification = call(attempt.string("verificationRequestDigest"), "verification", frozen, receipts, output, owned);
                require(verification.node().equals(attempt.object("verification").node()), "verification_bytes");
                StrictJson.Obj request = StrictJson.parseObject(read(output.resolve("calls/" + attempt.string("verificationRequestDigest") + ".request.json")));
                StrictJson.Obj input = StrictJson.parseObject(request.string("input"));
                require(input.object("draft").node().equals(attempt.object("draft").node()), "verified_draft_binding");
            }
        }
        ObjectNode versionInput = (ObjectNode) row.node().deepCopy();
        for (String field : List.of("roundId", "date", "edition", "cutoff", "frozen", "generatedAt", "resultVersion")) versionInput.remove(field);
        require(("company-v1-" + Canonical.digest(versionInput)).equals(row.string("resultVersion")), "result_version");
        ObjectNode result = StrictJson.newObject().put("schemaVersion", SCHEMA).put("roundId", row.string("roundId"))
                .put("edition", row.string("edition")).put("cutoff", row.string("cutoff")).put("status", row.string("status"))
                .put("resultVersion", row.string("resultVersion")).put("generatedAt", row.string("generatedAt")).put("scopeNote", frozen.string("scopeNote"));
        Instant.parse(row.string("generatedAt")); ArrayNode companies = result.putArray("companies");
        if ("WITHHELD".equals(row.string("status"))) {
            require(row.isNull("draft"), "withheld_draft"); result.put("reason", "기업 전망의 근거 검증을 통과하지 않아 표시하지 않습니다."); return result;
        }
        require("PASS".equals(row.string("status")), "status");
        StrictJson.Obj last = attempts.getLast();
        require(last.object("draft").node().equals(row.object("draft").node())
                && last.string("generationRequestDigest").equals(row.string("generationRequestDigest"))
                && last.string("verificationRequestDigest").equals(row.string("verificationRequestDigest")), "final_attempt");
        for (String digest : List.of(row.string("generationRequestDigest"), row.string("verificationRequestDigest")))
            require(!Instant.parse(StrictJson.Obj.of(receipts.get(digest)).string("finishedAt")).isAfter(Instant.parse(row.string("generatedAt"))), "completion_clock");
        Set<String> checked = new HashSet<>();
        for (StrictJson.Obj check : last.object("verification").objects("checks"))
            require(check.bool("supported") && checked.add(check.string("companyId")) && !check.string("reason").isBlank(), "semantic_verification");
        require(checked.equals(companyIds), "verification_coverage");
        Set<String> actualCompanies = new HashSet<>();
        for (StrictJson.Obj draft : row.object("draft").objects("companies")) {
            String id = draft.string("companyId"); StrictJson.Obj target = targets.get(id);
            require(target != null && actualCompanies.add(id) && Set.of("positive", "negative", "mixed", "watch").contains(draft.string("assessment")), "company_output");
            Set<String> allowed = Set.copyOf(target.strings("sourceIds"));
            statement(draft.object("impact"), allowed); statement(draft.object("outlook"), allowed);
            for (String field : List.of("conditions", "risks")) {
                require(!draft.objects(field).isEmpty() && draft.objects(field).size() <= 3, "conditions_risks");
                draft.objects(field).forEach(s -> statement(s, allowed));
            }
            StrictJson.Obj comparison = draft.object("comparison"), prior = target.object("previous"); statement(comparison, allowed);
            String expectedStatus = "available".equals(prior.string("status")) ? ("morning".equals(row.string("edition")) ? "updated" : "compared") : "unavailable";
            require(expectedStatus.equals(comparison.string("status")) && java.util.Objects.equals(
                    prior.has("resultVersion") ? prior.string("resultVersion") : null, comparison.stringOrNull("previousResultVersion")), "comparison");
            ObjectNode company = (ObjectNode) draft.node().deepCopy(); company.put("companyName", names.get(id));
            for (String field : List.of("issueIds", "facts", "observedMovement", "previous")) company.set(field, target.raw(field).deepCopy());
            ArrayNode refs = company.putArray("sources"); for (String sourceId : target.strings("sourceIds")) refs.add(frozen.object("sources").raw(sourceId).deepCopy());
            companies.add(company);
        }
        require(actualCompanies.equals(companyIds), "output_coverage"); return result;
    }

    static ObjectNode previous(String company, StrictJson.Obj current, List<StrictJson.Obj> history) {
        for (int index = history.size() - 1; index >= 0; index--) {
            StrictJson.Obj row = history.get(index);
            if (!"PASS".equals(row.string("status")) || ("evening".equals(current.string("edition"))
                    && (!row.string("date").equals(current.string("date")) || !"morning".equals(row.string("edition"))))) continue;
            for (StrictJson.Obj c : row.object("draft").objects("companies")) if (company.equals(c.string("companyId"))) {
                ObjectNode out = StrictJson.newObject().put("status", "available").put("roundId", row.string("roundId"))
                        .put("cutoff", row.string("cutoff")).put("resultVersion", row.string("resultVersion")); out.set("judgment", c.node().deepCopy()); return out;
            }
        }
        return StrictJson.newObject().put("status", "unavailable").put("reason", "evening".equals(current.string("edition"))
                ? "same_day_morning_company_judgment_missing" : "previous_company_judgment_missing");
    }

    private static StrictJson.Obj call(String digest, String phase, StrictJson.Obj frozen, Map<String, JsonNode> receipts, Path output, Set<String> owned) {
        return recordedCall(digest, phase, frozen, receipts, output, owned, "company_outlook_", VERSION);
    }

    static StrictJson.Obj recordedCall(String digest, String phase, StrictJson.Obj frozen, Map<String, JsonNode> receipts,
            Path output, Set<String> owned, String stage, String promptVersion) {
        require(digest.matches("[0-9a-f]{64}") && (owned.add(digest) || owned.contains(digest)), "call_ownership");
        StrictJson.Obj receipt = StrictJson.Obj.of(receipts.get(digest));
        byte[] requestBytes = read(output.resolve("calls/" + digest + ".request.json")), responseBytes = read(output.resolve("calls/" + digest + ".response.json"));
        require(digest.equals(Canonical.sha256(requestBytes)) && receipt.string("responseSha256").equals(Canonical.sha256(responseBytes))
                && (stage + phase).equals(receipt.string("stage")) && receipt.bool("usageKnown")
                && receipt.count("httpStatus") == 200 && "completed".equals(receipt.string("status")), "recording");
        StrictJson.Obj request = StrictJson.parseObject(requestBytes), response = StrictJson.parseObject(responseBytes);
        require(BriefingCompanySchemas.format(stage, phase, frozen).equals(request.object("text").object("format").node()), "response_schema");
        require("gpt-6-luna".equals(request.string("model")) && !request.bool("store")
                && "gpt-6-luna".equals(receipt.string("model")) && receipt.string("responseId").equals(response.string("id"))
                && "completed".equals(response.string("status")), "model");
        require(request.string("instructions").equals(resource(promptVersion, phase + ".md")), "prompt_bytes");
        require(StrictJson.parseObject(request.string("input")).object("frozen").node().equals(frozen.node()), "frozen_input");
        require(response.object("usage").raw("input_tokens").equals(receipt.raw("inputTokens"))
                && response.object("usage").raw("output_tokens").equals(receipt.raw("outputTokens")), "usage");
        StringBuilder text = new StringBuilder();
        for (StrictJson.Obj item : response.objects("output")) if ("message".equals(item.string("type")))
            for (StrictJson.Obj content : item.objects("content")) { require("output_text".equals(content.string("type")), "response_type"); text.append(content.string("text")); }
        return StrictJson.parseObject(text.toString());
    }
    private static String resource(String version, String name) {
        try (var stream = BriefingCompanyOutlookRules.class.getResourceAsStream("/briefing/prompts/" + version + "/" + name)) {
            require(stream != null, "prompt_missing"); return new String(stream.readAllBytes(), java.nio.charset.StandardCharsets.UTF_8);
        } catch (java.io.IOException error) { throw new IllegalArgumentException("Company prompt unavailable", error); }
    }
    private static void statement(StrictJson.Obj s, Set<String> allowed) {
        require(!s.string("text").isBlank() && s.string("text").length() <= 700 && !s.strings("evidenceIds").isEmpty()
                && allowed.containsAll(s.strings("evidenceIds")) && new HashSet<>(s.strings("evidenceIds")).size() == s.strings("evidenceIds").size(), "statement");
    }
    private static byte[] read(Path path) {
        try { require(Files.isRegularFile(path, java.nio.file.LinkOption.NOFOLLOW_LINKS) && Files.size(path) <= 8_000_000, "file"); return Files.readAllBytes(path); }
        catch (java.io.IOException error) { throw new IllegalArgumentException("Company recording unavailable", error); }
    }
    private static void require(boolean value, String reason) {
        if (!value) throw new IllegalArgumentException("Briefing company outlook rejected: " + reason);
    }
}
