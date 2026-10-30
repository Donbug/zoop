package com.zoop.graph.importer;

import java.util.Map;
import java.util.TreeMap;

import com.zoop.common.json.StrictJson;
import com.zoop.graph.importer.GraphHandoffResult.RuleFacts;
import com.zoop.graph.importer.GraphHandoffResult.StoredFileFact;
import tools.jackson.databind.node.ArrayNode;
import tools.jackson.databind.node.ObjectNode;

/**
 * The result document of a run ({@code zoop-graph-handoff-import-1}); it holds no text, no path and no secret. A success says in
 * so many words what it is not: the version is not published, not activated and not readable through the public API, its
 * structural relations are manual operator assertions, its quotes are integrity-checked and not semantically verified, and no
 * activation path exists yet.
 */
final class GraphHandoffResultWriter {
    private GraphHandoffResultWriter() {
    }

    static byte[] toBytes(GraphHandoffResult result) {
        ObjectNode root = StrictJson.newObject();
        root.put("schemaVersion", GraphHandoffRequestParser.SCHEMA_VERSION);
        root.put("status", result.succeeded() ? "succeeded" : "failed");
        if (result.failure() != null) {
            GraphHandoffException failure = result.failure();
            ObjectNode node = root.putObject("failure");
            node.put("code", failure.failure().code());
            if (failure.cliCode() != null) {
                switch (failure.failure()) {
                    case HANDOFF_REFUSED, HANDOFF_WITHHELD -> node.put("handoffCode", failure.cliCode());
                    default -> node.put("ingestionCode", failure.cliCode());
                }
            }
            if (failure.observation() >= 0) {
                node.put("observation", failure.observation());
            }
            return StrictJson.write(root);
        }
        GraphHandoffResult.Staged staged = result.staged();
        root.put("handoffId", staged.handoffId());
        root.put("graphVersionId", staged.versionId());
        root.put("outcome", staged.outcome().wire());
        root.put("publication", "not-published");
        root.put("activation", "not-activated");
        root.put("active", false);
        root.put("publicRead", "unavailable");
        root.put("nextActivation", "unsupported");
        ObjectNode digests = root.putObject("digests");
        digests.put("manifest", staged.manifestDigest());
        digests.put("bundle", staged.bundleDigest());
        digests.put("content", staged.contentDigest());
        ObjectNode provenance = root.putObject("provenance");
        provenance.put("sourceKind", staged.sourceKind());
        provenance.put("executionMode", staged.executionMode());
        provenance.put("recordingKind", staged.recordingKind());
        ObjectNode origins = provenance.putObject("relationOrigins");
        for (Map.Entry<String, Integer> origin : new TreeMap<>(staged.origins()).entrySet()) {
            origins.put(origin.getKey(), origin.getValue());
        }
        ObjectNode approvals = provenance.putObject("approvalBases");
        for (Map.Entry<String, Integer> approval : new TreeMap<>(staged.approvalBases()).entrySet()) {
            approvals.put(approval.getKey(), approval.getValue());
        }
        provenance.put("structuralRelationOrigin", "manual-operator-review");
        root.put("quoteVerification", "quote-integrity-only");
        ObjectNode counts = root.putObject("counts");
        counts.put("companies", staged.companies());
        counts.put("issues", staged.issues());
        counts.put("relations", staged.relations());
        counts.put("articles", staged.articles());
        counts.put("evidence", staged.evidence());
        ObjectNode evidence = root.putObject("evidenceRows");
        evidence.put("registered", staged.evidenceRegistered());
        evidence.put("existing", staged.evidenceExisting());
        RuleFacts facts = staged.rules();
        ObjectNode rules = root.putObject("publicationRules");
        if (facts.ruleRevision() == null) {
            rules.putNull("ruleRevision");
        } else {
            rules.put("ruleRevision", facts.ruleRevision());
        }
        rules.put("reviewRevision", facts.reviewRevision());
        ArrayNode applied = rules.putArray("applied");
        facts.applied().forEach(applied::add);
        ObjectNode stored = rules.putObject("stored");
        stored.put("issues", facts.storedIssues());
        stored.put("relations", facts.storedRelations());
        stored.put("articles", facts.storedArticles());
        stored.put("evidence", facts.storedEvidence());
        ObjectNode hidden = rules.putObject("hidden");
        hidden.put("issues", facts.hiddenIssues());
        hidden.put("relations", facts.hiddenRelations());
        ObjectNode byRule = rules.putObject("byRule");
        facts.byRule().forEach((id, hits) -> {
            ObjectNode node = byRule.putObject(id);
            node.put("issues", hits.issues());
            node.put("relations", hits.relations());
        });
        file(root.putObject("snapshot"), staged.snapshot());
        file(root.putObject("receipt"), staged.receipt());
        if (staged.bundleSnapshot() == null) {
            root.putNull("bundleSnapshot");
        } else {
            file(root.putObject("bundleSnapshot"), staged.bundleSnapshot());
        }
        ObjectNode composition = root.putObject("composition");
        ArrayNode sources = composition.putArray("sources");
        staged.sources().forEach(sources::add);
        // Only a staged import added a source; a re-import of the same pins composed nothing.
        if (staged.outcome() == GraphHandoffResult.Outcome.STAGED) {
            composition.put("newSource", staged.handoffId());
        } else {
            composition.putNull("newSource");
        }
        return StrictJson.write(root);
    }

    private static void file(ObjectNode node, StoredFileFact fact) {
        node.put("artifactId", fact.artifactId());
        node.put("sha256", fact.sha256());
        node.put("bytes", fact.bytes());
        node.put("file", fact.file());
    }
}
