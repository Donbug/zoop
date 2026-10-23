package com.zoop.graph.importer;

import java.time.Instant;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;
import java.util.TreeSet;

import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import com.zoop.common.json.StrictJson.Obj;
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
 * <p>The <b>snapshot</b> is the app's current read projection ({@code snapshotFormat 3}, {@link PublicGraphSnapshot}), not a
 * second format and not the retained source. It carries what the public graph reads show: companies (id and label, no catalog
 * appearance), issues (label, event time at its stated precision, {@code period} and issue-level assertion status exactly as the
 * producer gave them, action, target, geography and its evidence, articles and evidence of the issue, mention references, the
 * representative mention, latest publication time), relations (type, endpoints, role, assertion status, evidence, and per
 * structural basis its id, business relation type, verification time, validity days as stated, countries and every source article
 * version), article versions (title, URL, publication time at its stated precision) and evidence spans. The writer reads the
 * fields the verifier does not type from the verified raw bundle of the {@link VerifiedHandoff}, never from a second parse.
 *
 * <p><b>Mention references are a projection of the original mentions.</b> A source event becomes a mention only when the
 * article version its document belongs to ({@code documentId}, {@code documentVersion}, {@code rawVersion} and the observation
 * pin) is one the issue's own evidence cites; the reference carries that article version, so the read-time {@code asOf} filter that
 * covers the issue's articles covers its mentions too. The producer's {@code mentionId} is unique only within a document version
 * (two documents of one issue may legitimately use the same value), so the snapshot's mention id is the app's own
 * ({@link #mentionId}): {@code "mention-"} + the SHA-256 of the canonical JSON of the resolved article id, article version and the
 * producer's local id. Two documents with the same local id are two mentions with two ids; events of the same mention (the same
 * local id on the same article version, as one S2 comparison and one S2 snapshot both list it) are one mention. The same input
 * always gives the same ids. The representative event resolves to its article version the same way, and is written as
 * {@code null} when that mention is not among the written ones, never as a mention the snapshot lacks. A document identity that
 * matches more than one bundle article is genuinely ambiguous and refused ({@link GraphHandoffFailure#MENTION_ARTICLE_AMBIGUOUS});
 * the verifier of {@code zoop-graph-handoff-bundle-6} already requires exactly one article per mention document version, and every
 * original mention cites evidence of its own article, so under that schema the references cover every mention of an issue. The
 * snapshot does not carry the mention values (title, action, time, assertion status, background, participants): they are the
 * producer's S2 candidate or snapshot values ({@code verification: "none"}) and stay only in the receipt, which keeps the whole
 * bundle, the producer's own mention ids and decisions, source references and each producer field the snapshot has no place for.
 * Any later reader of receipt mentions must check {@code receipt.bundle.schemaVersion}: for {@code zoop-graph-handoff-bundle-1}
 * the mention values are unavailable, never empty and never copied from the issue, for {@code -1} and {@code -2} the issue's
 * {@code fieldProvenance} (which mentions state each selected headline value; a selection record, not a verification) is absent,
 * never rebuilt as {@code unanimous} from a null representative, and for {@code -1} to {@code -3} the issue's {@code fieldVerdicts}
 * (operator ALLOW/HOLD/REJECT judgements of one original mention's {@code eventTime} or {@code period}) and
 * {@code fieldProvenance.withheld} are absent, never reconstructed as "no verdict" from a headline value. The snapshot carries
 * no field provenance and no verdict either; it carries the issue's headline values as the verifier recomputed them, so an
 * {@code eventTime} or {@code period} that a HOLD/REJECT verdict withheld on the selection basis is {@code null} there (and
 * {@code eventTime} has {@code unknown} precision) while the receipt still holds every original mention value and verdict.
 * For {@code zoop-graph-handoff-bundle-1} to {@code -4} the top-level {@code pathCompanies}, every relation's {@code structuralPath}
 * and each basis's {@code businessScope}/{@code productScope} are absent from the receipt: a reader must treat them as unavailable,
 * never as an empty path or an empty scope. The snapshot carries none of them in any version. For {@code zoop-graph-handoff-bundle-1}
 * to {@code -5} the top-level {@code impacts} is absent from the receipt: a reader must treat impacts as unavailable, never as
 * {@code not-proposed} or {@code not-applicable}. From {@code -6} on, {@code impacts} (one row per S3 relation behind an INVOLVES
 * edge: the producer's unverified proposal, the verifier-mapped quote effects and the recomputed label) live ONLY in the receipt;
 * the snapshot carries no impact, proposal, effect, label or verifier digest.
 *
 * <p>{@code validUntil} is the last valid day (inclusive) and {@code null} is unknown, never "forever": days are written verbatim
 * or not at all ({@link HandoffTime#dayOrNull}); no midnight and no extra day is ever added.
 *
 * <p>The <b>receipt</b> is the {@code verification_receipt} artifact: the complete original manifest and bundle (so the private
 * structural paths, path companies and basis scopes live ONLY here, never in the snapshot), the producer's own receipt and attempts,
 * and what this app verified (and did not). Evidence rows point at it as their verification artifact.
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

    /**
     * The format 3 snapshot of a verified handoff. A pure function of the verified bundle: no catalog, clock or rights are read.
     *
     * @throws GraphHandoffException {@link GraphHandoffFailure#MENTION_ARTICLE_AMBIGUOUS} or {@link GraphHandoffFailure#TEMPORAL_UNSUPPORTED}
     * @throws StrictJson.Malformed  if a raw field the verifier already proved is missing (a broken invariant, never a producer case)
     */
    static byte[] snapshot(String versionId, VerifiedHandoff handoff) {
        HandoffBundle bundle = handoff.bundle();
        Obj source = Obj.of(handoff.bundleNode());
        Map<String, Obj> sourceIssues = byId(source.objects("issues"));
        Map<String, Obj> sourceRelations = byId(source.objects("relations"));

        Map<String, String> publishedByKey = new HashMap<>();
        for (Article article : bundle.articles()) {
            String key = article.articleId() + "\n" + article.articleVersion();
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
            Obj given = sourceIssues.get(issue.id());
            if (given == null) {
                throw new StrictJson.Malformed();
            }
            TreeSet<String> articleIds = new TreeSet<>();
            Set<String> citedVersions = new HashSet<>();
            Map<String, String> published = new HashMap<>();
            for (String evidenceId : issue.evidenceIds()) {
                Evidence evidence = evidenceById.get(evidenceId);
                String key = evidence.articleId() + "\n" + evidence.articleVersion();
                articleIds.add(evidence.articleId());
                citedVersions.add(key);
                published.put(key, publishedByKey.get(key));
            }
            Mentions mentions = mentions(given, bundle.articles(), citedVersions);
            ObjectNode node = issues.addObject();
            node.put("issueId", issue.id());
            node.put("label", issue.title());
            node.put("eventTime", HandoffTime.eventTime(issue.eventTime(), issue.timePrecision()));
            node.put("timePrecision", issue.timePrecision());
            node.put("period", given.stringOrNull("period"));
            node.put("assertionStatus", issue.assertionStatus());
            node.put("action", issue.action());
            node.put("target", issue.target());
            node.put("geography", issue.geography());
            node.put("geographyPolicyVersion", issue.geographyPolicyVersion());
            strings(node.putArray("geographyEvidenceIds"), issue.geographyEvidenceIds());
            strings(node.putArray("articleIds"), List.copyOf(articleIds));
            strings(node.putArray("evidenceIds"), issue.evidenceIds());
            ArrayNode mentionNodes = node.putArray("mentions");
            for (Map.Entry<String, Article> mention : mentions.byId().entrySet()) {
                ObjectNode mentionNode = mentionNodes.addObject();
                mentionNode.put("mentionId", mention.getKey());
                mentionNode.put("articleId", mention.getValue().articleId());
                mentionNode.put("articleVersion", mention.getValue().articleVersion());
            }
            node.put("representativeMentionId", mentions.representative());
            node.put("latestPublishedAt", latestPublished(published.values()));
        }

        ArrayNode relations = root.putArray("relations");
        for (Relation relation : bundle.relations()) {
            Obj given = sourceRelations.get(relation.id());
            if (given == null) {
                throw new StrictJson.Malformed();
            }
            List<Obj> givenBasis = given.objects("basis");
            if (givenBasis.size() != relation.basis().size()) {
                throw new StrictJson.Malformed();
            }
            ObjectNode node = relations.addObject();
            node.put("relationId", relation.id());
            node.put("relationType", relation.type());
            node.put("source", relation.source());
            node.put("target", relation.target());
            node.put("role", relation.role());
            node.put("assertionStatus", relation.assertionStatus());
            strings(node.putArray("evidenceIds"), relation.evidenceIds());
            ArrayNode basis = node.putArray("basis");
            for (int index = 0; index < givenBasis.size(); index++) {
                Basis item = relation.basis().get(index);
                Obj path = givenBasis.get(index);
                ObjectNode basisNode = basis.addObject();
                // The producer's relationKey is the basis's own id; the relation type is the business relation it rests on.
                basisNode.put("basisId", path.string("relationKey"));
                basisNode.put("relationType", path.string("relationType"));
                basisNode.put("verifiedAt", HandoffTime.instantText(item.verifiedAt()));
                basisNode.put("validFrom", HandoffTime.dayOrNull(item.validFrom()));
                basisNode.put("validUntil", HandoffTime.dayOrNull(item.validUntil()));
                strings(basisNode.putArray("countries"), path.strings("countries"));
                ArrayNode linked = basisNode.putArray("articles");
                for (Obj link : path.objects("sourceArticles")) {
                    ObjectNode linkNode = linked.addObject();
                    linkNode.put("articleId", link.string("articleId"));
                    linkNode.put("articleVersion", link.string("articleVersion"));
                }
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

    /** The written mentions of one issue (app mention id to its article version, ascending) and the representative's app id, if written. */
    private record Mentions(Map<String, Article> byId, String representative) {
    }

    /**
     * The app's mention id of a producer-local mention id on one resolved article version: {@code "mention-"} + the SHA-256 of the
     * canonical JSON (sorted ASCII keys) of {@code {articleId, articleVersion, sourceMentionId}}. Local ids repeat across documents;
     * the resolved article version makes the id unique within a snapshot.
     */
    static String mentionId(Article article, String sourceMentionId) {
        return MentionIds.of(article.articleId(), article.articleVersion(), sourceMentionId);
    }

    /**
     * Projects the verified source events of an issue to mention references; see the class documentation for the rule. Each event
     * is bound to its article by the document identity the verifier already closed ({@code documentId}, {@code documentVersion},
     * {@code rawVersion} and the observation pin).
     */
    private static Mentions mentions(Obj issue, List<Article> articles, Set<String> citedVersions) {
        Map<String, Article> written = new TreeMap<>();
        for (Obj event : issue.objects("sourceEvents")) {
            Article article = articleOf(event, articles);
            if (citedVersions.contains(article.articleId() + "\n" + article.articleVersion())) {
                written.put(mentionId(article, event.string("mentionId")), article);
            }
        }
        String representative = null;
        if (!issue.isNull("representative")) {
            Obj event = issue.object("representative");
            Article article = articleOf(event, articles);
            if (citedVersions.contains(article.articleId() + "\n" + article.articleVersion())) {
                representative = mentionId(article, event.string("mentionId"));
            }
        }
        return new Mentions(written, representative);
    }

    /** The one bundle article of an event's document version and observation; two matching articles are genuinely ambiguous. */
    private static Article articleOf(Obj event, List<Article> articles) {
        Obj observation = event.object("observation");
        String documentId = event.string("documentId");
        String documentVersion = event.string("documentVersion");
        String rawVersion = observation.string("rawVersion");
        String roundId = observation.string("roundId");
        String sourceId = observation.string("sourceId");
        int page = observation.count("page");
        int ordinal = observation.count("ordinal");
        Article found = null;
        for (Article article : articles) {
            if (article.documentId().equals(documentId) && article.documentVersion().equals(documentVersion)
                    && article.rawVersion().equals(rawVersion)
                    && article.observations().stream().anyMatch(pin -> pin.roundId().equals(roundId)
                            && pin.sourceId().equals(sourceId) && pin.page() == page && pin.ordinal() == ordinal)) {
                if (found != null) {
                    throw new GraphHandoffException(GraphHandoffFailure.MENTION_ARTICLE_AMBIGUOUS);
                }
                found = article;
            }
        }
        if (found == null) {
            // The verifier closed every source event against an article; reaching this is a broken invariant, not a producer case.
            throw new StrictJson.Malformed();
        }
        return found;
    }

    private static Map<String, Obj> byId(List<Obj> nodes) {
        Map<String, Obj> byId = new HashMap<>();
        for (Obj node : nodes) {
            byId.put(node.string("id"), node);
        }
        return byId;
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
                "company_ids_exist_with_equal_label", "evidence_ids_follow_app_formula_without_collision",
                "article_textSha256_equals_app_text_sha256", "source_support_recomputed_from_declared_origins_and_exact_text",
                "approval_basis_recomputed_and_bound_to_eligibility_revision",
                "structural_path_closed_over_involves_basis_and_catalog",
                "impact_rows_closed_over_involves_sources_approvals_and_labels")) {
            checks.add(check);
        }
        app.put("quoteIntegrity", "app-text-code-point-span-sha256-equals-bundle-quoteSha256");
        app.put("semanticTruth", "not-verified");
        app.put("structuralRelations", "manual-operator-review");
        app.put("structuralPath", "operator-mapped-basis-chain-not-causality-or-price-direction");
        app.put("approvalBasis", "audit-metadata-not-a-verifier-verdict");
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
