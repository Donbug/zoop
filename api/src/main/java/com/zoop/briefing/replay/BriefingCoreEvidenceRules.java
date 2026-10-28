package com.zoop.briefing.replay;

import com.zoop.common.json.StrictJson;
import java.nio.file.Path;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import tools.jackson.databind.node.ObjectNode;

/** Core eligibility uses the same completed semantic proof as references, never quote length. */
final class BriefingCoreEvidenceRules {
    static final String POLICY = "recorded-supported-event-exact-quote-v1";
    private BriefingCoreEvidenceRules() { }

    static boolean eligible(StrictJson.Obj candidate, Map<String, BriefingReferenceSupport.Proof> support) {
        return !candidate.objects("newMentions").isEmpty() && candidate.objects("newMentions").stream()
                .allMatch(m -> BriefingReferenceSupport.matches(m, support.get(m.string("mentionId"))));
    }

    static void frozen(StrictJson.Obj candidate, Map<String, BriefingReferenceSupport.Proof> support) {
        require(POLICY.equals(candidate.string("evidencePolicy")), "policy");
        ObjectNode expected = StrictJson.newObject();
        for (var mention : candidate.objects("newMentions")) {
            var proof = support.get(mention.string("mentionId"));
            if (BriefingReferenceSupport.matches(mention, proof)) expected.put(mention.string("mentionId"), proof.requestDigest());
        }
        require(expected.equals(candidate.object("semanticSupport").node()), "frozen_proof_binding");
    }

    static ObjectNode review(StrictJson.Obj round, Map<String, tools.jackson.databind.JsonNode> receipts,
            Path output, Map<String, BriefingReferenceSupport.Proof> support) {
        ObjectNode result = StrictJson.newObject().put("policy", POLICY).put("fixedMinimumCharacters", false)
                .put("selectionReexecuted", false).put("sourceSelectionStatus", round.string("selectionStatus"));
        var rows = result.putArray("candidates");
        if (!round.has("groupedSelectionRequestDigest") || round.isNull("groupedSelectionRequestDigest")) return result;
        String key = round.string("groupedSelectionRequestDigest");
        var receipt = StrictJson.Obj.of(receipts.get(key));
        // An unresolved reservation cannot be promoted into a semantic revalidation.
        if (!receipt.bool("usageKnown") || !"completed".equals(receipt.string("status"))) return result.put("status", "unavailable");
        var recorded = BriefingGroupedSimulationRules.recording(receipt, output, true);
        Set<String> selected = new HashSet<>(); round.objects("selected").forEach(i -> selected.add(i.string("issueId")));
        for (var candidate : recorded.input().objects("issues")) {
            boolean supported = eligible(candidate, support);
            String id = candidate.string("issueId");
            if (selected.contains(id)) require(supported, "selected_semantic_support_missing");
            var assessment = recorded.answer().object("assessments").object(id);
            Set<String> seen = new HashSet<>(); int characters = 0;
            for (var m : candidate.objects("newMentions")) for (var e : m.objects("evidence"))
                if (seen.add(e.string("evidenceId"))) characters += e.string("quote").codePointCount(0, e.string("quote").length());
            var row = rows.addObject().put("issueId", id).put("quoteCharacters", characters).put("semanticSupported", supported)
                    .put("importance", assessment.count("importance")).put("assessmentStatus", assessment.string("status"))
                    .put("selected", selected.contains(id));
            var digests = row.putArray("supportRequestDigests");
            candidate.objects("newMentions").stream().map(m -> support.get(m.string("mentionId"))).filter(java.util.Objects::nonNull)
                    .map(BriefingReferenceSupport.Proof::requestDigest).distinct().sorted().forEach(digests::add);
        }
        return result.put("status", "revalidated").put("sourceSelectionRequestDigest", key);
    }
    private static void require(boolean valid, String code) {
        if (!valid) throw new IllegalArgumentException("Core semantic evidence rejected: " + code);
    }
}
