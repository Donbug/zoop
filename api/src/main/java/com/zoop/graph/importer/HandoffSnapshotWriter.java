package com.zoop.graph.importer;

import java.time.Instant;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.TreeSet;

import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import com.zoop.graph.importer.HandoffBundle.Article;
import com.zoop.graph.importer.HandoffBundle.Basis;
import com.zoop.graph.importer.HandoffBundle.Company;
import com.zoop.graph.importer.HandoffBundle.Evidence;
import com.zoop.graph.importer.HandoffBundle.Issue;
import com.zoop.graph.importer.HandoffBundle.Relation;
import com.zoop.graph.importer.HandoffExportParser.VerifiedHandoff;
import com.zoop.graph.snapshot.PublicGraphSnapshot;
import tools.jackson.databind.node.ArrayNode;
import tools.jackson.databind.node.ObjectNode;

/**
 * Writes the two immutable artifacts of one import, both in the app's deterministic canonical JSON so that a repeated import of
 * the same pins produces the same bytes.
 *
 * <p>The <b>snapshot</b> is the existing {@code snapshotFormat 1} read projection ({@link PublicGraphSnapshot}), not a second
 * format and not the retained source. It carries only what the public graph reads show: companies (id and label, no catalog
 * appearance), issues
 * (label, event time at its stated precision, action, target, geography and its evidence, articles and evidence of the issue,
 * latest publication time), relations (type, endpoints, role, assertion status, evidence, validity basis), article versions
 * (title, URL, publication time at its stated precision) and evidence spans. {@code period}, the issue-level assertion status,
 * source events, representatives, decisions, source references, per-basis countries and every other producer field are NOT in
 * it; they stay in the receipt, which is the complete provenance.
 *
 * <p>The <b>receipt</b> is the {@code verification_receipt} artifact: the complete original manifest and bundle, the producer's
 * own receipt and attempts, and what this app verified (and did not). Evidence rows point at it as their verification artifact.
 */
final class HandoffSnapshotWriter {
    static final String RECEIPT_SCHEMA = "zoop-graph-handoff-import-receipt-1";
    static final String IMPORTER = "zoop-graph-handoff-import-1";

    private HandoffSnapshotWriter() {
    }

    /** {@code gv-} + SHA-256 of the handoff id: always within the 120 characters of {@code graph_versions.id}. */
    static String versionId(String handoffId) {
        return "gv-" + Canonical.sha256(handoffId);
    }

    static byte[] snapshot(String versionId, HandoffBundle bundle) {
        Map<String, Article> articleByKey = new HashMap<>();
        Map<String, String> publishedByKey = new HashMap<>();
        for (Article article : bundle.articles()) {
            String key = article.articleId() + "\n" + article.articleVersion();
            articleByKey.put(key, article);
            publishedByKey.put(key, switch (article.precision()) {
                case "datetime" -> HandoffTime.instantText(article.publishedAt());
                case "day" -> HandoffTime.day(article.publishedAt());
                default -> null;
            });
        }
        Map<String, Evidence> evidenceById = new HashMap<>();
        for (Evidence evidence : bundle.evidence()) {
            evidenceById.put(evidence.id(), evidence);
        }

        ObjectNode root = StrictJson.newObject();
        root.put("snapshotFormat", PublicGraphSnapshot.FORMAT);
        root.put("versionId", versionId);
        root.put("sourceBundleId", bundle.handoffId());

        ArrayNode companies = root.putArray("companies");
        for (Company company : bundle.companies()) {
            // Only what the bundle states (id, label). brandColor and logoUrl are optional appearance and are left out, never
            // copied from the catalog: the bytes of a snapshot are decided by the verified bundle alone, so a retry after a lost
            // commit reproduces the files of the first attempt even if the catalog changed in between.
            ObjectNode node = companies.addObject();
            node.put("companyId", company.id());
            node.put("label", company.label());
        }

        ArrayNode issues = root.putArray("issues");
        for (Issue issue : bundle.issues()) {
            TreeSet<String> articleIds = new TreeSet<>();
            Map<String, String> published = new HashMap<>();
            for (String evidenceId : issue.evidenceIds()) {
                Evidence evidence = evidenceById.get(evidenceId);
                String key = evidence.articleId() + "\n" + evidence.articleVersion();
                articleIds.add(evidence.articleId());
                published.put(key, publishedByKey.get(key));
            }
            ObjectNode node = issues.addObject();
            node.put("issueId", issue.id());
            node.put("label", issue.title());
            node.put("eventTime", HandoffTime.eventTime(issue.eventTime(), issue.timePrecision()));
            node.put("timePrecision", issue.timePrecision());
            node.put("action", issue.action());
            node.put("target", issue.target());
            node.put("geography", issue.geography());
            node.put("geographyPolicyVersion", issue.geographyPolicyVersion());
            strings(node.putArray("geographyEvidenceIds"), issue.geographyEvidenceIds());
            strings(node.putArray("articleIds"), List.copyOf(articleIds));
            strings(node.putArray("evidenceIds"), issue.evidenceIds());
            node.put("latestPublishedAt", latestPublished(published.values()));
        }

        ArrayNode relations = root.putArray("relations");
        for (Relation relation : bundle.relations()) {
            ObjectNode node = relations.addObject();
            node.put("relationId", relation.id());
            node.put("relationType", relation.type());
            node.put("source", relation.source());
            node.put("target", relation.target());
            node.put("role", relation.role());
            node.put("assertionStatus", relation.assertionStatus());
            strings(node.putArray("evidenceIds"), relation.evidenceIds());
            ArrayNode basis = node.putArray("basis");
            for (Basis item : relation.basis()) {
                ObjectNode basisNode = basis.addObject();
                basisNode.put("verifiedAt", HandoffTime.instantText(item.verifiedAt()));
                basisNode.put("validFrom", HandoffTime.dayOrNull(item.validFrom()));
                basisNode.put("validUntil", HandoffTime.dayOrNull(item.validUntil()));
            }
        }

        ArrayNode articles = root.putArray("articles");
        for (Article article : bundle.articles()) {
            ObjectNode node = articles.addObject();
            node.put("articleId", article.articleId());
            node.put("version", article.articleVersion());
            node.put("title", article.title());
            node.put("url", article.url());
            node.put("publishedAt", publishedByKey.get(article.articleId() + "\n" + article.articleVersion()));
        }

        ArrayNode evidence = root.putArray("evidence");
        for (Evidence item : bundle.evidence()) {
            ObjectNode node = evidence.addObject();
            node.put("evidenceId", item.id());
            node.put("articleId", item.articleId());
            node.put("articleVersion", item.articleVersion());
            node.put("start", item.start());
            node.put("end", item.end());
        }
        return Canonical.bytes(root);
    }

    /**
     * The latest publication time of an issue's articles for the snapshot filter, which asks "published by asOf" of the issue and of
     * each article. {@code null} when any of them has no publication time (an unknown time never counts before an asOf). A date and an
     * instant are compared by when each starts to count ({@link HandoffTime#effective}); a tie keeps the larger text, so the result
     * never depends on iteration order.
     */
    static String latestPublished(Iterable<String> published) {
        String latest = null;
        Instant latestAt = null;
        for (String value : published) {
            if (value == null) {
                return null;
            }
            Instant at = HandoffTime.effective(value);
            if (latestAt == null || at.isAfter(latestAt) || (at.equals(latestAt) && value.compareTo(latest) > 0)) {
                latest = value;
                latestAt = at;
            }
        }
        return latest;
    }

    /**
     * The retained {@code verification_receipt}: everything the producer handed over, unchanged, and a closed statement of what the
     * app verified. {@code quoteIntegrity} is a byte-exact statement about the app's own text and the bundle's
     * {@code quoteSha256}; it says nothing about whether a quote supports a claim ({@code semanticTruth}), and nothing here makes
     * the version public.
     */
    static byte[] receipt(VerifiedHandoff handoff) {
        ObjectNode root = StrictJson.newObject();
        root.put("schemaVersion", RECEIPT_SCHEMA);
        root.put("handoffId", handoff.bundle().handoffId());
        root.put("manifestDigest", handoff.manifestDigest());
        root.put("bundleDigest", handoff.bundleDigest());
        root.put("contentDigest", handoff.contentDigest());
        root.set("manifest", handoff.manifestNode());
        root.set("bundle", handoff.bundleNode());
        ObjectNode producer = root.putObject("producer");
        producer.set("receipt", handoff.receiptNode());
        producer.set("attempts", handoff.attemptsNode());
        ObjectNode app = root.putObject("appVerification");
        app.put("importer", IMPORTER);
        ArrayNode checks = app.putArray("checks");
        for (String check : List.of("expected_manifest_and_bundle_digests_equal_canonical_hashes",
                "closed_bundle_schema_and_semantic_references", "ingestion_export_require_store_every_observation",
                "rights_rechecked_before_commit", "article_version_title_url_publication_equal_bundle",
                "app_text_equals_ingestion_export_text", "evidence_quote_sha256_equals_app_text_code_point_span",
                "company_ids_exist_with_equal_label", "evidence_ids_follow_app_formula_without_collision")) {
            checks.add(check);
        }
        app.put("quoteIntegrity", "app-text-code-point-span-sha256-equals-bundle-quoteSha256");
        app.put("semanticTruth", "not-verified");
        app.put("structuralRelations", "manual-operator-review");
        app.put("publication", "not-published");
        app.put("activation", "none");
        return Canonical.bytes(root);
    }

    private static void strings(ArrayNode array, List<String> values) {
        for (String value : values) {
            array.add(value);
        }
    }
}
