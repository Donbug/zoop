package com.zoop.graph.exclusion;

import java.util.Map;

import com.zoop.common.json.StrictJson;
import com.zoop.graph.exclusion.ExclusionResult.VersionChange;
import tools.jackson.databind.node.ArrayNode;
import tools.jackson.databind.node.ObjectNode;

/**
 * The result document of a run ({@code zoop-disclosure-exclusion-1}): the outcome, the app exclusion revision and per version
 * what moved, as counts. It says in so many words what an exclusion is not: the snapshot, the activation pointer and the readers
 * outside the graph read are unchanged.
 */
final class ExclusionResultWriter {
    private ExclusionResultWriter() {
    }

    static byte[] toBytes(ExclusionResult result) {
        if (result.replay()) {
            ObjectNode stored = (ObjectNode) StrictJson.parseObject(result.recorded()).node();
            stored.put("replayed", true);
            return StrictJson.write(stored);
        }
        ObjectNode root = StrictJson.newObject();
        root.put("schemaVersion", ExclusionRequestParser.SCHEMA_VERSION);
        root.put("status", result.succeeded() ? "succeeded" : "failed");
        root.put("action", result.action());
        if (!result.succeeded()) {
            root.putObject("failure").put("code", result.failure().failure().code());
            return StrictJson.write(root);
        }
        root.put("outcome", result.outcome());
        root.put("replayed", false);
        root.put("revision", result.revision());
        root.put("scope", "per-graph-version");
        root.put("snapshots", "unchanged");
        root.put("activation", "unchanged");
        root.put("graphRead", "issues-relations-evidence");
        root.put("notApplied", "article exclusions filter company document lists by exact article version; S1 analysis and "
                + "published briefing body/details do not use graph exclusions; briefing graph basis, public graph, evidence and "
                + "chat apply their graph read rules; caches and Neo4j are outside this backend");
        ArrayNode versions = root.putArray("versions");
        for (VersionChange version : result.versions()) {
            ObjectNode node = versions.addObject();
            node.put("graphVersionId", version.graphVersionId());
            if (version.handoffId() == null) {
                node.putNull("handoffId");
            } else {
                node.put("handoffId", version.handoffId());
            }
            node.put("exposed", version.exposed());
            counts(node.putObject("changed"), version.changed());
            counts(node.putObject("unchanged"), version.unchanged());
        }
        return StrictJson.write(root);
    }

    private static void counts(ObjectNode node, Map<String, Integer> counts) {
        for (String kind : ExclusionRequest.Target.KINDS) {
            node.put(kind, counts.getOrDefault(kind, 0));
        }
    }
}
