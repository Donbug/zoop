package com.zoop.briefing.replay;

import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.time.Instant;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.node.ArrayNode;
import tools.jackson.databind.node.ObjectNode;

/** Source-bound presentation additions applied only after the original recovery has passed all checks. */
final class BriefingPresentationRules {
    static final String SCHEMA = "zoop-briefing-presentation-enrichment-v1";
    static final String DERIVED_MODE = "verified_issue_claims_and_indicators_v1";
    static final String DERIVED_SCOPE = "검증된 핵심 이슈 문장과 회차 지표를 묶은 요약입니다. 전체 적격 기업·업종 분석과 새 전망 생성은 포함하지 않습니다.";
    record Layer(byte[] baseBytes, StrictJson.Obj baseBundle, StrictJson.Obj root, Map<String, StrictJson.Obj> rounds) { }
    record Evidence(String id, String documentId, String version, String bodySha256, String body, String quote,
            int start, int end, String title, String publisher, String url, String publishedAt, String kind) { }
    record Previous(ObjectNode payload, String publishedAt, String cutoff) { }

    static Layer load(StrictJson.Obj bundle, Path output, String inbox) {
        return load(bundle, output, inbox, 400);
    }

    static Layer load(StrictJson.Obj bundle, Path output, String inbox, int maximumPaidCalls) {
        if (!bundle.has("presentationEnrichment")) return null;
        StrictJson.Obj layer = bundle.object("presentationEnrichment");
        require(SCHEMA.equals(layer.string("schemaVersion")) && inbox.equals(layer.string("userInboxRef"))
                && layer.string("runId").matches("[A-Za-z0-9_-]{1,96}")
                && !layer.string("runId").equals(bundle.string("runId")), "layer_identity");
        byte[] bytes = read(output.resolve("base-presentation-bundle.json"));
        require(Canonical.sha256(bytes).equals(layer.string("baseBundleSha256")), "base_bytes_digest");
        ObjectNode base = (ObjectNode) bundle.node().deepCopy(); base.remove("presentationEnrichment");
        require(base.equals(StrictJson.parseObject(bytes).node()), "base_json_unchanged");
        require(base.has("briefingRecovery") && !layer.string("runId").equals(base.path("briefingRecovery").path("runId").stringValue()), "recovery_base_required");
        Map<String, StrictJson.Obj> rounds = new LinkedHashMap<>();
        for (StrictJson.Obj row : layer.objects("rounds")) require(rounds.putIfAbsent(row.string("roundId"), row) == null, "duplicate_round");
        require(maximumPaidCalls >= 1 && maximumPaidCalls <= 512, "reservation_limit");
        if (layer.has("maximumPaidCallsIncludingPrior")) require(layer.count("maximumPaidCallsIncludingPrior") <= maximumPaidCalls, "reservation_limit");
        return new Layer(bytes, StrictJson.Obj.of(base), layer, rounds);
    }

    static void roundBinding(StrictJson.Obj record, StrictJson.Obj effective, StrictJson.Obj original) {
        for (String field : List.of("roundId", "date", "edition"))
            require(record.string(field).equals(original.string(field)), "round_identity");
        require("SELECTED".equals(effective.string("status"))
                && effective.string("resultSha256").equals(record.string("baseResultSha256")), "effective_result_binding");
    }

    /** Every exposed field is reconstructed from verified publication data; only exact surrounding spans are supplied. */
    static void details(ObjectNode payload, ObjectNode snapshot, StrictJson.Obj generation, StrictJson.Obj supplied,
            Map<String, Evidence> evidence) {
        ObjectNode details = snapshot.putObject("itemDetails"); Set<String> expected = new HashSet<>();
        Map<String, StrictJson.Obj> generated = new LinkedHashMap<>();
        for (StrictJson.Obj item : generation.objects("items")) generated.put(item.string("issueId"), item);
        for (JsonNode rawItem : payload.path("items")) {
            StrictJson.Obj item = StrictJson.Obj.of(rawItem); String event = item.string("eventId"); expected.add(event);
            StrictJson.Obj input = supplied.object(event);
            input.keys(Set.of("evidence"), Set.of("eventId"));
            if (input.has("eventId")) require(event.equals(input.string("eventId")), "detail_event_identity");
            ObjectNode detail = details.putObject(event).put("roundId", payload.path("id").stringValue()).put("eventId", event)
                    .put("title", item.string("title")).put("selectionReason", item.string("reason"));
            detail.set("summary", item.object("summary").node().deepCopy()); detail.set("companies", item.array("companies").deepCopy());
            detail.set("claims", generated.get(event).array("claims").deepCopy()); detail.set("metadata", payload.path("metadata").deepCopy());
            ArrayNode limitations = detail.putArray("limitations");
            for (JsonNode failure : payload.path("metadata").path("failures")) limitations.add(failure.path("message").isString()
                    ? failure.path("message").stringValue() : failure.path("reason").isString() ? failure.path("reason").stringValue() : failure.path("code").stringValue());
            Map<String, StrictJson.Obj> contexts = new LinkedHashMap<>();
            for (StrictJson.Obj value : input.objects("evidence")) {
                value.exactly(Set.of("id", "bodyContext")); require(contexts.putIfAbsent(value.string("id"), value) == null, "duplicate_evidence_context");
            }
            require(contexts.keySet().equals(Set.copyOf(item.strings("evidenceIds"))), "detail_evidence_coverage");
            ArrayNode values = detail.putArray("evidence");
            for (String id : item.strings("evidenceIds")) {
                Evidence source = evidence.get(id); require(source != null, "detail_evidence_identity");
                require(Canonical.sha256(source.body()).equals(source.bodySha256()) && ("sha256-" + source.bodySha256()).equals(source.version())
                        && slice(source.body(), source.start(), source.end()).equals(source.quote()), "detail_source_binding");
                ObjectNode value = values.addObject().put("id", id).put("quote", source.quote()).put("documentId", source.documentId())
                        .put("documentVersion", source.version()).put("title", source.title()).put("publisher", source.publisher())
                        .put("url", source.url()).put("quoteVerified", true).put("sourceKind", source.kind()).put("bodySha256", source.bodySha256());
                if (source.publishedAt() == null) value.putNull("publishedAt"); else value.put("publishedAt", source.publishedAt());
                StrictJson.Obj context = contexts.get(id);
                if (context.isNull("bodyContext")) value.putNull("bodyContext");
                else { validateContext(context.object("bodyContext"), source); value.set("bodyContext", context.object("bodyContext").node().deepCopy()); }
            }
        }
        require(Set.copyOf(supplied.node().propertyNames()).equals(expected), "detail_item_coverage");
    }

    static void validateContext(StrictJson.Obj context, Evidence source) {
        context.exactly(Set.of("text", "start", "end", "quoteStart", "quoteEnd", "offsetUnit"));
        int start = context.count("start"), end = context.count("end");
        require("unicode_code_point".equals(context.string("offsetUnit")) && start <= source.start() && end >= source.end()
                && source.start() == context.count("quoteStart") && source.end() == context.count("quoteEnd")
                && end - start <= 2000 && slice(source.body(), start, end).equals(context.string("text")), "body_context_exact_span");
    }

    /** A deterministic projection of verified material, explicitly distinct from a newly generated AI analysis. */
    static ObjectNode derivedSummary(ObjectNode snapshot, StrictJson.Obj generation, StrictJson.Obj market, Instant generatedAt) {
        require(market.isNull("summaryResult") && market.isNull("summaryResultSha256") && market.objects("receipts").isEmpty(), "derived_has_no_model_result");
        ObjectNode lineage = StrictJson.newObject().put("generationMode", DERIVED_MODE).put("digestScheme", "app-json-sha256-v1").put("scopeNote", DERIVED_SCOPE)
                .put("newsResultSha256", market.string("newsResultSha256")).put("marketSnapshotSha256", market.string("marketSnapshotSha256"));
        ArrayNode claims = lineage.putArray("claims"), indicatorLines = lineage.putArray("indicators");
        Set<String> evidence = new java.util.LinkedHashSet<>(); List<String> texts = new java.util.ArrayList<>();
        for (StrictJson.Obj item : generation.objects("items")) {
            List<StrictJson.Obj> values = item.objects("claims");
            for (int index = 0; index < values.size() && claims.size() < 6; index++) {
                StrictJson.Obj claim = values.get(index); ObjectNode saved = claims.addObject().put("issueId", item.string("issueId")).put("claimIndex", index);
                for (String field : List.of("text", "type", "evidenceIds")) saved.set(field, claim.raw(field).deepCopy());
                evidence.addAll(claim.strings("evidenceIds")); texts.add(claim.string("text"));
            }
        }
        require(!claims.isEmpty() && !evidence.isEmpty(), "derived_verified_claims_required");
        Map<String, StrictJson.Obj> variables = new LinkedHashMap<>();
        for (StrictJson.Obj value : market.object("marketSnapshot").object("marketVariables").objects("indicators")) variables.put(value.string("id"), value);
        for (String id : List.of("kospi", "kosdaq", "usdkrw")) {
            StrictJson.Obj value = variables.get(id); require(value != null, "derived_three_indicators");
            String label = switch (id) { case "kospi" -> "KOSPI"; case "kosdaq" -> "KOSDAQ"; default -> "원/달러 환율"; };
            String text;
            if (Set.of("ok", "delayed").contains(value.string("status"))) {
                String kind = switch (value.string("valueKind")) { case "close" -> "종가"; case "reference" -> "은행고시 기준환율"; default -> "관측값"; };
                text = label + " " + value.string("observedDate") + " " + kind + " "
                        + value.raw("value").decimalValue().stripTrailingZeros().toPlainString() + ("usdkrw".equals(id) ? "원" : "pt") + ".";
            } else text = label + ": 당시 사용 가능한 값이 없습니다.";
            ObjectNode saved = indicatorLines.addObject().put("id", id).put("text", text);
            for (String field : List.of("status", "value", "observedDate", "valueKind")) saved.set(field, value.raw(field).deepCopy());
            texts.add(text);
        }
        texts.add(DERIVED_SCOPE);
        ObjectNode summary = snapshot.putObject("marketSummary").put("text", String.join("\n", texts)).put("generatedAt", generatedAt.toString())
                .put("resultVersion", "derived-v1-" + Canonical.sha256(Canonical.appBytes(lineage)));
        ArrayNode refs = summary.putArray("evidenceIds"); evidence.forEach(refs::add);
        return lineage;
    }

    /** Identity comparison describes membership in stored key-issue sets; it does not score a market forecast. */
    static ObjectNode comparison(ObjectNode payload, Previous previous, boolean morning) {
        if (previous == null) return StrictJson.newObject().put("status", "unavailable").put("reason", "비교할 이전 발행 브리핑이 없습니다.");
        ObjectNode result = StrictJson.newObject().put("status", "available");
        result.put(morning ? "morningRoundId" : "previousRoundId", previous.payload().path("id").stringValue())
                .put(morning ? "morningPublishedAt" : "previousPublishedAt", previous.publishedAt())
                .put(morning ? "morningDataAsOf" : "previousDataAsOf", previous.cutoff());
        if (!morning) {
            result.put("previousDate", previous.payload().path("date").stringValue())
                    .put("previousEdition", previous.payload().path("edition").stringValue());
            result.put("comparisonBasis", "event_identity");
            result.putObject("forecastEvaluation").put("status", "unavailable").put("reason", "검증 가능한 전망·성과 입력이 없어 전망 정확도를 평가하지 않았습니다.");
        }
        Map<String, StrictJson.Obj> old = new LinkedHashMap<>(), current = new LinkedHashMap<>();
        for (JsonNode value : previous.payload().path("items")) { StrictJson.Obj item = StrictJson.Obj.of(value); old.put(item.string("eventId"), item); }
        for (JsonNode value : payload.path("items")) { StrictJson.Obj item = StrictJson.Obj.of(value); current.put(item.string("eventId"), item); }
        ArrayNode items = result.putArray("items");
        for (var entry : current.entrySet()) items.add(compareItem(entry.getValue(), old.get(entry.getKey()), morning));
        for (var entry : old.entrySet()) if (!current.containsKey(entry.getKey())) items.add(compareItem(null, entry.getValue(), morning));
        return result;
    }
    private static ObjectNode compareItem(StrictJson.Obj current, StrictJson.Obj old, boolean morning) {
        StrictJson.Obj item = current == null ? old : current;
        ObjectNode value = StrictJson.newObject();
        for (String field : List.of("title", "eventId", "eventTime", "timePrecision", "reportedAt")) value.set(field, item.raw(field).deepCopy());
        value.put("change", current == null ? "dropped" : old == null ? "new" : "continuing");
        ArrayNode companies = value.putArray("companyNames"); item.objects("companies").forEach(company -> companies.add(company.string("name")));
        if (current == null) value.putNull("rank").putNull("evidenceCount"); else value.put("rank", current.count("rank")).put("evidenceCount", current.count("evidenceCount"));
        String rank = morning ? "morningRank" : "previousRank", count = morning ? "morningEvidenceCount" : "previousEvidenceCount";
        if (old == null) value.putNull(rank).putNull(count); else value.put(rank, old.count("rank")).put(count, old.count("evidenceCount"));
        return value;
    }
    static void suppliedComparison(StrictJson.Obj record, String field, ObjectNode computed) {
        if (!record.has(field) || record.isNull(field)) return;
        ObjectNode compatible = computed.deepCopy();
        for (String optional : List.of("previousDate", "previousEdition"))
            if (!record.object(field).has(optional)) compatible.remove(optional);
        require(compatible.equals(record.raw(field)), "comparison_not_derived_from_publication");
    }
    private static String slice(String body, int start, int end) {
        require(start >= 0 && end > start && end <= body.codePointCount(0, body.length()), "body_span_bounds");
        return body.substring(body.offsetByCodePoints(0, start), body.offsetByCodePoints(0, end));
    }
    private static byte[] read(Path path) {
        try { require(Files.isRegularFile(path, LinkOption.NOFOLLOW_LINKS) && path.getParent().equals(path.getParent().toRealPath())
                    && Files.size(path) <= 128 * 1024 * 1024, "base_file"); return Files.readAllBytes(path); }
        catch (IOException error) { throw new IllegalArgumentException("Presentation base unavailable", error); }
    }
    private static void require(boolean valid, String code) { if (!valid) throw new IllegalArgumentException("Briefing presentation rejected: " + code); }
}
