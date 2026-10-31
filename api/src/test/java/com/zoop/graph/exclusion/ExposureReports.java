package com.zoop.graph.exclusion;

import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.UUID;

import com.zoop.common.json.StrictJson;
import tools.jackson.databind.node.ArrayNode;
import tools.jackson.databind.node.ObjectNode;

/** Synthetic {@code zoop-handoff-exposure-1} reports and exclusion requests, shaped exactly as the producer's closed schema. */
final class ExposureReports {
    static final String DIGEST_M = "a".repeat(64);
    static final String DIGEST_B = "b".repeat(64);
    static final String DIGEST_C = "c".repeat(64);
    static final String ARTICLE = "doc-" + "1".repeat(64);
    static final String ARTICLE_VERSION = "2".repeat(64);
    static final String EVIDENCE = "ev-" + "3".repeat(64);

    private ExposureReports() {
    }

    /** One handoff of a source-change report; {@code exposed=false} when every list is empty. */
    static ObjectNode handoff(String handoffId, List<String> issues, List<String> relations, boolean withArticleAndEvidence) {
        ObjectNode handoff = StrictJson.newObject();
        handoff.put("handoffId", handoffId);
        handoff.put("bundleSchema", "zoop-graph-handoff-bundle-7");
        handoff.put("manifestDigest", DIGEST_M);
        handoff.put("bundleDigest", DIGEST_B);
        handoff.put("contentDigest", DIGEST_C);
        handoff.put("bound", true);
        ArrayNode articles = handoff.putArray("articles");
        ArrayNode evidence = handoff.putArray("evidenceIds");
        if (withArticleAndEvidence) {
            ObjectNode article = articles.addObject();
            article.put("articleId", ARTICLE);
            article.put("articleVersion", ARTICLE_VERSION);
            article.put("documentId", "synthetic-document");
            article.put("documentVersion", "4".repeat(64));
            evidence.add(EVIDENCE);
        }
        ArrayNode issueNodes = handoff.putArray("issues");
        for (String issue : issues) {
            ObjectNode node = issueNodes.addObject();
            node.put("id", issue);
            node.putArray("reasons").add("source-document");
        }
        ArrayNode relationNodes = handoff.putArray("relations");
        for (String relation : relations) {
            ObjectNode node = relationNodes.addObject();
            node.put("id", relation);
            node.put("type", "INVOLVES");
            node.putArray("reasons").add("evidence");
        }
        handoff.put("exposed", !issues.isEmpty() || !relations.isEmpty() || withArticleAndEvidence);
        ObjectNode counts = handoff.putObject("counts");
        counts.put("articles", articles.size());
        counts.put("issues", issues.size());
        counts.put("relations", relations.size());
        counts.put("evidence", evidence.size());
        return handoff;
    }

    static ObjectNode report(ObjectNode... handoffs) {
        ObjectNode report = StrictJson.newObject();
        report.put("schemaVersion", "zoop-handoff-exposure-1");
        ObjectNode changed = report.putObject("changed");
        changed.put("kind", "source");
        changed.put("sourceId", "synthetic-source");
        report.put("cause", "source-change");
        ObjectNode identity = report.putObject("identity");
        identity.put("boundInSelection", true);
        identity.put("recordedInIngestion", true);
        ObjectNode scope = report.putObject("scope");
        scope.put("selection", "explicit");
        ArrayNode ids = scope.putArray("handoffIds");
        for (ObjectNode handoff : handoffs) {
            ids.add(handoff.get("handoffId").asString());
        }
        scope.putArray("notCovered").add("company documents");
        report.put("basis", "pinned handoff ledger");
        report.put("consistency", "shared locks on every opened ledger were held from the first read until this output");
        report.put("effect", "none: identity-only proposal for the selected handoffs; nothing was excluded, revised, overlaid, "
                + "activated or written, and an empty or smaller result never clears or narrows any existing exclusion");
        ArrayNode list = report.putArray("handoffs");
        for (ObjectNode handoff : handoffs) {
            list.add(handoff);
        }
        ObjectNode usage = report.putObject("usage");
        usage.put("providerCalls", 0);
        usage.put("modelCalls", 0);
        return report;
    }

    /** A new command every call: a fresh {@code requestId}. */
    static String requestId() {
        return "test-" + UUID.randomUUID();
    }

    static byte[] exclude(ObjectNode report) {
        return exclude(requestId(), report);
    }

    static byte[] exclude(String requestId, ObjectNode report) {
        ObjectNode request = StrictJson.newObject();
        request.put("schemaVersion", "zoop-disclosure-exclusion-1");
        request.put("requestId", requestId);
        request.put("action", "exclude");
        request.put("operator", "operator-a");
        request.put("reason", "권리 철회에 따른 공개 제외");
        request.set("report", report);
        return StrictJson.write(request);
    }

    /** The source change every synthetic report answers. */
    static ObjectNode sourceChange() {
        ObjectNode changed = StrictJson.newObject();
        changed.put("kind", "source");
        changed.put("sourceId", "synthetic-source");
        return changed;
    }

    /** An {@code exclude-query} for this change in these versions (none: the default versions). */
    static byte[] query(String requestId, ObjectNode changed, String... versionIds) {
        ObjectNode request = StrictJson.newObject();
        request.put("schemaVersion", "zoop-disclosure-exclusion-1");
        request.put("requestId", requestId);
        request.put("action", "exclude-query");
        request.put("operator", "operator-a");
        request.put("reason", "권리 철회에 따른 공개 제외");
        request.set("changed", changed);
        ArrayNode versions = request.putArray("graphVersionIds");
        for (String versionId : versionIds) {
            versions.add(versionId);
        }
        return StrictJson.write(request);
    }

    /** A lift decided on exclusion revision {@code expectedRevision}. */
    static byte[] lift(String versionId, long expectedRevision, String... issueIds) {
        return lift(versionId, expectedRevision, null, issueIds);
    }

    /** {@code laterVersions} null: the key is left out (the default, the named version only). */
    static byte[] lift(String versionId, long expectedRevision, Boolean laterVersions, String... issueIds) {
        ObjectNode request = StrictJson.newObject();
        if (laterVersions != null) request.put("laterVersions", laterVersions.booleanValue());
        request.put("schemaVersion", "zoop-disclosure-exclusion-1");
        request.put("requestId", requestId());
        request.put("action", "lift");
        request.put("operator", "operator-a");
        request.put("reason", "정정 확인 후 해제");
        request.put("graphVersionId", versionId);
        request.put("expectedRevision", expectedRevision);
        ArrayNode targets = request.putArray("targets");
        for (String id : issueIds) {
            ObjectNode target = targets.addObject();
            target.put("kind", "issue");
            target.put("id", id);
        }
        return StrictJson.write(request);
    }

    static byte[] utf8(String text) {
        return text.getBytes(StandardCharsets.UTF_8);
    }
}
