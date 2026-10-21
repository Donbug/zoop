package com.zoop.briefing.query;

import java.time.Instant;
import java.util.HashSet;
import java.util.Objects;
import java.util.Set;

import com.zoop.briefing.storage.BriefingRound;
import com.zoop.briefing.storage.BriefingRoundRepository;
import com.zoop.common.json.StrictJson;
import tools.jackson.databind.JsonNode;

/** Reject corrupt stored details; this reader never reconstructs claims or fetches a newer source. */
final class BriefingItemDetailValidator {
    private BriefingItemDetailValidator() { }

    static void validate(BriefingRound round, JsonNode itemNode, JsonNode detailNode, BriefingRoundRepository repository) {
        var item = StrictJson.Obj.of(itemNode);
        var detail = StrictJson.Obj.of(detailNode).exactly(Set.of("roundId", "eventId", "title", "summary",
                "selectionReason", "claims", "companies", "evidence", "limitations", "metadata"));
        same(round.id(), detail.string("roundId"));
        for (String field : Set.of("eventId", "title", "summary", "companies")) same(item.raw(field), detail.raw(field));
        same(item.string("reason"), detail.string("selectionReason"));
        same(round.payload().path("metadata"), detail.raw("metadata"));
        Set<String> allowed = new HashSet<>(item.strings("evidenceIds"));
        check(!detail.objects("claims").isEmpty());
        for (var claim : detail.objects("claims")) {
            claim.exactly(Set.of("text", "type", "evidenceIds"));
            nonBlank(claim.string("text"));
            check(Set.of("fact", "plan", "outlook").contains(claim.string("type")));
            var refs = claim.strings("evidenceIds");
            check(!refs.isEmpty() && new HashSet<>(refs).size() == refs.size() && allowed.containsAll(refs));
        }
        detail.strings("limitations").forEach(BriefingItemDetailValidator::nonBlank);
        Set<String> disclosed = new HashSet<>();
        for (var evidence : detail.objects("evidence")) {
            evidence.exactly(Set.of("id", "quote", "documentId", "documentVersion", "title", "publisher", "url",
                    "publishedAt", "quoteVerified", "sourceKind", "bodySha256", "bodyContext"));
            String id = evidence.string("id");
            check(allowed.contains(id) && disclosed.add(id) && evidence.bool("quoteVerified"));
            var source = repository.findItemEvidence(id).orElseThrow(StrictJson.Malformed::new);
            same(source.documentId(), evidence.string("documentId"));
            same(source.documentVersion(), evidence.string("documentVersion"));
            same(source.quote(), evidence.string("quote"));
            same(source.title(), evidence.string("title"));
            same(source.publisher(), evidence.string("publisher"));
            same(source.url(), evidence.string("url"));
            String published = evidence.stringOrNull("publishedAt");
            same(source.publishedAt(), published == null ? null : Instant.parse(published));
            same(source.sourceKind(), evidence.string("sourceKind"));
            same(source.bodySha256(), evidence.string("bodySha256"));
            check(StrictJson.SHA256.matcher(evidence.string("bodySha256")).matches());
            if (!evidence.isNull("bodyContext")) {
                var context = evidence.object("bodyContext").exactly(Set.of("text", "start", "end", "quoteStart", "quoteEnd", "offsetUnit"));
                same("unicode_code_point", context.string("offsetUnit"));
                int start = context.count("start"), end = context.count("end");
                int quoteStart = context.count("quoteStart"), quoteEnd = context.count("quoteEnd");
                String text = context.string("text");
                int length = text.codePointCount(0, text.length());
                check(end > start && length == end - start && length <= 2000
                        && start <= quoteStart && quoteStart < quoteEnd && quoteEnd <= end);
                check(source.start() == quoteStart && source.end() == quoteEnd);
                same(source.quote(), text.substring(text.offsetByCodePoints(0, quoteStart - start),
                        text.offsetByCodePoints(0, quoteEnd - start)));
            }
        }
        same(allowed, disclosed);
    }

    private static void nonBlank(String value) { check(!value.isBlank()); }
    private static void same(Object expected, Object actual) { check(Objects.equals(expected, actual)); }
    private static void check(boolean condition) { if (!condition) throw new StrictJson.Malformed(); }
}
