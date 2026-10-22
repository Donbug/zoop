package com.zoop.briefing.replay;

import com.zoop.common.json.StrictJson;
import java.util.*;
import tools.jackson.databind.JsonNode;

/** A normal empty publication must follow the recorded producer path; a held result is not an empty result. */
final class BriefingSimulationEmptyRules {
    private static final String IMPORTANCE = "round_simulation_importance", SELECTION = "round_simulation_selection";
    private static final Set<String> NOVELTY = Set.of("round_simulation_novelty", "round_simulation_novelty_verification");
    private BriefingSimulationEmptyRules() { }

    static void validate(StrictJson.Obj round, Map<String, JsonNode> receipts, Map<String, StrictJson.Obj> requests,
            Map<String, StrictJson.Obj> outputs, Map<String, StrictJson.Obj> sources) {
        boolean v2 = round.object("identity").has("qualityPolicy")
                && "novelty-recovery-v2".equals(round.object("identity").string("qualityPolicy"));
        for (JsonNode value : receipts.values()) {
            String stage = StrictJson.Obj.of(value).string("stage");
            require(Set.of(IMPORTANCE, SELECTION).contains(stage) || v2 && NOVELTY.contains(stage), "stage");
        }
        if (sources.isEmpty()) {
            require(receipts.isEmpty(), "empty_window_has_no_calls");
            return;
        }
        Map<String, StrictJson.Obj> assessments = new LinkedHashMap<>();
        for (String digest : receipts.keySet()) {
            if (!IMPORTANCE.equals(StrictJson.Obj.of(receipts.get(digest)).string("stage"))) continue;
            require(outputs.containsKey(digest), "importance_completed_recording_required");
            StrictJson.Obj request = requests.get(digest), answer = outputs.get(digest);
            Set<String> batch = new HashSet<>();
            for (StrictJson.Obj document : request.objects("documents")) {
                String id = document.string("documentId"); StrictJson.Obj source = sources.get(id);
                require(source != null && batch.add(id) && source.string("bodySha256").equals(document.string("bodySha256"))
                        && source.string("url").equals(document.string("url")), "importance_source");
                String body = source.string("body"); int length = body.codePointCount(0, body.length());
                List<String> excerpts = List.of(slice(body, 0, Math.min(1050, length)),
                        slice(body, length > 1400 ? length - 350 : Math.min(1050, length), length));
                require(excerpts.equals(document.strings("excerpts")), "importance_excerpts");
            }
            require(!batch.isEmpty(), "importance_batch");
            Map<String, StrictJson.Obj> normalized = assessments(answer.raw("assessments"));
            require(normalized.keySet().equals(batch), "importance_batch_coverage");
            normalized.forEach((id, assessment) -> require(assessments.putIfAbsent(id, assessment) == null, "importance_duplicate"));
        }
        require(assessments.keySet().equals(sources.keySet()), "importance_coverage");
        List<StrictJson.Obj> ranked = new ArrayList<>();
        for (StrictJson.Obj assessment : assessments.values()) {
            int importance = assessment.count("importance"), priority = assessment.count("priority");
            String state = assessment.string("status");
            require(importance <= 3 && priority <= 100 && Set.of("ELIGIBLE", "HOLD", "REJECT").contains(state), "assessment");
            if (Set.of("ELIGIBLE", "HOLD").contains(state) && importance >= 2) ranked.add(assessment);
        }
        ranked.sort(Comparator.<StrictJson.Obj>comparingInt(a -> a.count("importance")).reversed()
                .thenComparing(Comparator.<StrictJson.Obj>comparingInt(a -> a.count("priority")).reversed())
                .thenComparing(a -> a.string("documentId")));
        List<String> candidates = new ArrayList<>(); Set<String> events = new HashSet<>();
        for (StrictJson.Obj assessment : ranked) {
            String event = assessment.string("eventKey").toLowerCase(Locale.ROOT).replace("ß", "ss").replace("ς", "σ")
                    .replaceAll("(?U)\\s+", " ").strip();
            if (!event.isEmpty() && events.add(event)) candidates.add(assessment.string("documentId"));
            if (candidates.size() == 12) break;
        }
        if (v2 && !candidates.isEmpty()) {
            require(round.has("noveltyAudit"), "novelty_required");
            StrictJson.Obj audit = round.object("noveltyAudit");
            require(audit.objects("decisions").stream().map(d -> d.string("documentId")).toList().equals(candidates), "novelty_candidate_coverage");
            Set<String> kept = Set.copyOf(audit.strings("keptDocumentIds"));
            candidates = candidates.stream().filter(kept::contains).toList();
        } else require(!round.has("noveltyAudit"), "unexpected_novelty");
        List<String> selections = receipts.keySet().stream()
                .filter(key -> SELECTION.equals(StrictJson.Obj.of(receipts.get(key)).string("stage"))).toList();
        require(!round.has("selectionCorrections") || round.objects("selectionCorrections").isEmpty(), "failed_correction");
        if (candidates.isEmpty()) {
            require(selections.isEmpty(), "unexpected_selection");
            return;
        }
        require(selections.size() == 1 && outputs.containsKey(selections.getFirst()), "selection_completed_recording_required");
        StrictJson.Obj selection = requests.get(selections.getFirst());
        require(selection.count("maximumIssues") == 3 && selection.objects("documents").stream()
                .map(d -> d.string("documentId")).toList().equals(candidates), "selection_candidate_coverage");
        for (StrictJson.Obj document : selection.objects("documents")) {
            String id = document.string("documentId");
            require(sources.get(id).string("body").equals(document.string("body"))
                    && assessments.get(id).node().equals(document.object("assessment").node()), "selection_source");
        }
        require(outputs.get(selections.getFirst()).objects("selected").isEmpty(), "selection_not_empty");
    }

    private static Map<String, StrictJson.Obj> assessments(JsonNode node) {
        Map<String, StrictJson.Obj> result = new LinkedHashMap<>();
        if (node.isObject()) for (String key : node.propertyNames()) {
            StrictJson.Obj item = StrictJson.Obj.of(node.get(key));
            require(key.equals(item.string("documentId")), "assessment_id"); result.put(key, item);
        } else {
            require(node.isArray(), "assessment_shape");
            for (JsonNode value : node) {
                StrictJson.Obj item = StrictJson.Obj.of(value);
                require(result.putIfAbsent(item.string("documentId"), item) == null, "assessment_duplicate_id");
            }
        }
        return result;
    }
    private static String slice(String value, int start, int end) {
        return value.substring(value.offsetByCodePoints(0, start), value.offsetByCodePoints(0, end));
    }
    private static void require(boolean value, String reason) {
        if (!value) throw new IllegalArgumentException("Briefing replay rejected: simulation_empty_" + reason);
    }
}
