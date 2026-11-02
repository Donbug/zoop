package com.zoop.graph.importer;

import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import com.zoop.common.json.StrictJson.Obj;
import com.zoop.common.json.Text;
import com.zoop.graph.snapshot.GraphSnapshotCodec;
import com.zoop.graph.snapshot.PublicGraphSnapshot;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.attribute.PosixFilePermission;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.node.ArrayNode;
import tools.jackson.databind.node.ObjectNode;

/** Deterministic projection of the retained PoC/BFF selection, with its effective review and separate geography review. */
public final class LegacyRealPackage {
    public static final String MANIFEST_SCHEMA = "zoop-legacy-real-manifest-2";
    public static final String BUNDLE_SCHEMA = "zoop-legacy-real-bundle-2";
    public static final String RECEIPT_SCHEMA = "zoop-legacy-real-import-receipt-2";
    public static final String POLICY = "legacy-real-projection-2";
    public static final String METADATA_MANIFEST_SCHEMA = "zoop-legacy-real-manifest-3";
    public static final String METADATA_BUNDLE_SCHEMA = "zoop-legacy-real-bundle-3";
    public static final String METADATA_RECEIPT_SCHEMA = "zoop-legacy-real-import-receipt-3";
    public static final String METADATA_POLICY = "legacy-real-projection-3";

    public static boolean isReceiptSchema(String schema) {
        return RECEIPT_SCHEMA.equals(schema) || METADATA_RECEIPT_SCHEMA.equals(schema);
    }

    public static boolean isBundleSchema(String schema) {
        return BUNDLE_SCHEMA.equals(schema) || METADATA_BUNDLE_SCHEMA.equals(schema);
    }
    public static final Set<String> RECEIPT_KEYS = Set.of("schemaVersion", "migrationId", "manifestDigest", "bundleDigest",
            "contentDigest", "manifest", "bundle", "legacyProvenance", "appVerification");
    private static final int MAX_BYTES = 16 * 1024 * 1024;
    private static final Map<String, List<String>> GEOGRAPHY_LITERALS = Map.ofEntries(
            Map.entry("KR", List.of("대한민국", "한국", "국내", "강남", "부산", "광주", "호남", "구미", "울산", "천안", "세종", "South Korea", "Korea", "Korean", "Yeongam", "Incheon", "Seoul")),
            Map.entry("US", List.of("United States", "U.S.", "Virginia", "Santa Clara", "San Francisco", "California")),
            Map.entry("GB", List.of("U.K.", "영국", "Bristol")), Map.entry("IN", List.of("인도", "India")),
            Map.entry("PH", List.of("필리핀", "Philippines")), Map.entry("TW", List.of("Taipei", "대만")),
            Map.entry("Africa", List.of("Africa")), Map.entry("South America", List.of("South America")),
            Map.entry("Worldwide including South Korea", List.of("전세계", "worldwide")));

    public record Request(String migrationId, String expectedManifestDigest, String expectedBundleDigest, String operator) {
        public static Request parse(byte[] bytes) {
            Obj root = StrictJson.parseObject(bytes).exactly(Set.of("schemaVersion", "migrationId", "expectedManifestDigest",
                    "expectedBundleDigest", "operator"));
            need("zoop-legacy-real-import-1".equals(root.string("schemaVersion")), "request_schema");
            String manifest = digest(root.string("expectedManifestDigest"));
            String bundle = digest(root.string("expectedBundleDigest"));
            need(root.string("migrationId").equals("legacy-real:" + manifest), "migration_identity");
            need(root.string("operator").matches("[A-Za-z0-9._@-]{1,100}"), "operator_invalid");
            return new Request(root.string("migrationId"), manifest, bundle, root.string("operator"));
        }
    }

    public record Article(Obj original, Obj projected, String body) { }
    public record Projection(Request request, Obj manifest, Obj bundle, byte[] snapshot, PublicGraphSnapshot graph, byte[] receipt,
            List<Article> articles, List<Obj> evidence) {
        public String versionId() { return graph.versionId(); }
        public String policyVersion() {
            return METADATA_MANIFEST_SCHEMA.equals(manifest.string("schemaVersion")) ? METADATA_POLICY : POLICY;
        }
    }
    public static final class Invalid extends RuntimeException {
        public Invalid(String code) { super(code, null, false, false); }
    }
    private LegacyRealPackage() { }

    public static Projection read(Path root, Request request) {
        Obj manifest = StrictJson.parseObject(readFile(root.resolve("manifest.json")));
        boolean metadata = METADATA_MANIFEST_SCHEMA.equals(manifest.string("schemaVersion"));
        Set<String> keys = new HashSet<>(Set.of("schemaVersion", "bundleDigest", "geographyDigest", "sourcePinsDigest", "provenanceDigest",
                "sourceInputDigests", "catalogueDigest", "legacyOrigin", "ruleDefinitionsDigest", "selectedIssueIds",
                "grantBindings", "companyBindings", "selectionLedger"));
        if (metadata) keys.add("metadataPolicyDigest");
        manifest.exactly(keys);
        need(metadata || MANIFEST_SCHEMA.equals(manifest.string("schemaVersion")), "manifest_schema");
        need(Canonical.digest(manifest.node()).equals(request.expectedManifestDigest()), "manifest_pin_conflict");
        Set<String> inputNames = new HashSet<>(Set.of("bundle.json", "geography.json", "source-pins.json", "source-provenance.json"));
        if (metadata) inputNames.add("metadata-policy.json");
        Obj sourceClaims = manifest.object("sourceInputDigests").exactly(inputNames);
        for (String name : inputNames) digest(sourceClaims.string(name));
        Obj selection = pinned(root, "bundle.json", request.expectedBundleDigest());
        need(request.expectedBundleDigest().equals(manifest.string("bundleDigest")), "bundle_pin_conflict");
        Obj geo = pinned(root, "geography.json", manifest.string("geographyDigest"));
        Obj pins = pinned(root, "source-pins.json", manifest.string("sourcePinsDigest"));
        Obj provenance = pinned(root, "source-provenance.json", manifest.string("provenanceDigest"));
        Obj policy = metadata ? pinned(root, "metadata-policy.json", manifest.string("metadataPolicyDigest")) : null;
        if (metadata) need(manifest.string("metadataPolicyDigest").equals(sourceClaims.string("metadata-policy.json")), "metadata_policy_pin_conflict");
        return project(request, manifest, selection, geo, pins, provenance, policy);
    }

    static void recheck(Path root, Projection first) {
        Obj manifest = StrictJson.parseObject(readFile(root.resolve("manifest.json")));
        need(Canonical.digest(manifest.node()).equals(first.request().expectedManifestDigest()), "manifest_pin_conflict");
        for (var file : Map.of("bundle.json", "bundleDigest", "geography.json", "geographyDigest",
                "source-pins.json", "sourcePinsDigest", "source-provenance.json", "provenanceDigest").entrySet()) {
            need(Canonical.sha256(readFile(root.resolve(file.getKey()))).equals(first.manifest().string(file.getValue())), "package_changed");
        }
        if (METADATA_MANIFEST_SCHEMA.equals(manifest.string("schemaVersion")))
            need(Canonical.sha256(readFile(root.resolve("metadata-policy.json"))).equals(first.manifest().string("metadataPolicyDigest")), "package_changed");
    }

    static Projection project(Request request, Obj manifest, Obj selection, Obj geo, Obj pins, Obj provenance, Obj metadataPolicy) {
        boolean metadata = metadataPolicy != null;
        selection.exactly(Set.of("schema", "format", "origin", "selection_basis", "articles", "companies", "issues",
                "candidate_audit", "effective_review_decisions", "enabled_rules", "review_exclusions"));
        need("zoop-legacy-company-issues/1".equals(selection.string("schema")) && "LEGACY".equals(selection.string("format")), "selection_schema");
        need((metadata ? "selected-bound-article-and-metadata-policy" : "selected-bound-article-and-geography")
                .equals(selection.string("selection_basis")), "selection_basis_invalid");
        Obj origin = selection.object("origin").exactly(Set.of("review_revision", "rule_revision", "snapshot"));
        need(origin.count("review_revision") >= 0 && origin.count("rule_revision") >= 0, "legacy_origin_invalid");
        Obj originSnapshot = origin.object("snapshot").exactly(Set.of("id", "sha256", "content_digest", "seed_sha256"));
        need(originSnapshot.string("id").matches("[A-Za-z0-9._-]{1,100}"), "legacy_origin_invalid");
        for (String field : List.of("sha256", "content_digest", "seed_sha256")) digest(originSnapshot.string(field));
        need(selection.raw("origin").equals(manifest.raw("legacyOrigin")), "legacy_origin_mismatch");
        need(Canonical.digest(selection.raw("companies")).equals(manifest.string("catalogueDigest")), "catalogue_pin_conflict");
        need(Canonical.digest(selection.raw("enabled_rules")).equals(manifest.string("ruleDefinitionsDigest")), "rule_pin_conflict");
        need("zoop-legacy-geography-review/1".equals(geo.string("schema")), "geography_schema");
        geo.exactly(Set.of("schema", "policy_version", "review_date", "records", "evidence"));
        need(geo.stringOrNull("policy_version") == null || "legacy-source-geography-review/1".equals(geo.string("policy_version")),
                "geography_export_closure");
        need(geo.stringOrNull("review_date") == null || geo.string("review_date").matches("[0-9]{4}-[0-9]{2}-[0-9]{2}"),
                "geography_export_closure");
        provenance.exactly(Set.of("schema", "articles"));
        need("zoop-legacy-export-provenance/1".equals(provenance.string("schema")), "provenance_schema");
        for (Obj rule : selection.objects("enabled_rules")) {
            rule.exactly(Set.of("id"));
            need(rule.string("id").matches("R[0-9]+@[0-9]+"), "rule_invalid");
        }
        Map<String, Obj> issues = index(selection.objects("issues"), "issue_id");
        Map<String, Obj> decisions = index(geo.objects("records"), "issue_id");
        Map<String, Obj> geoEvidence = index(geo.objects("evidence"), "evidence_id");
        Map<String, Obj> audits = index(selection.objects("candidate_audit"), "candidate_id");
        Map<String, Obj> metadataIssues = metadata ? metadataIssues(metadataPolicy, issues, audits) : Map.of();
        Map<String, Obj> companies = index(selection.objects("companies"), "company_id");
        for (Obj company : companies.values()) company.exactly(Set.of("company_id", "name"));
        Map<String, Obj> companyBindings = new LinkedHashMap<>();
        String previousCompany = null;
        for (Obj binding : manifest.objects("companyBindings")) {
            binding.exactly(Set.of("companyId", "originalName", "canonicalName"));
            String id = binding.string("companyId");
            need(!id.isBlank() && !binding.string("originalName").isBlank() && !binding.string("canonicalName").isBlank()
                    && (previousCompany == null || previousCompany.compareTo(id) < 0)
                    && companies.containsKey(id) && companies.get(id).string("name").equals(binding.string("originalName")),
                    "company_binding_invalid");
            companyBindings.put(id, binding);
            previousCompany = id;
        }
        need(companyBindings.keySet().equals(companies.keySet()), "company_binding_closure");
        for (Obj row : decisions.values()) {
            row.keys(Set.of("issue_id", "decision", "classification", "review_policy_version", "source_evidence_ids",
                    "country_codes", "regions", "reviewer", "reason"), Set.of("decision_id"));
            need("local-source-review".equals(row.string("reviewer"))
                    && "selected_source_evidence".equals(row.string("reason")), "geography_export_closure");
            if (row.has("decision_id")) need(row.string("decision_id").matches("legacy-geography-[0-9a-f]{64}"), "geography_export_closure");
        }
        for (Obj span : geoEvidence.values()) span.exactly(Set.of("article_id", "article_version", "start", "end", "quote", "evidence_id"));
        Set<String> selected = new LinkedHashSet<>(manifest.strings("selectedIssueIds"));
        need(issues.keySet().equals(selected), "issue_selection_invalid");
        Set<String> eligible = new LinkedHashSet<>(), ledgerIds = new HashSet<>();
        for (Obj row : manifest.objects("selectionLedger")) {
            row.exactly(Set.of("issueId", "reason"));
            String id = row.string("issueId"), reason = row.string("reason");
            need(id.matches("issue-[A-Za-z0-9-]{1,100}") && ledgerIds.add(id)
                    && (metadata ? Set.of("selected", "core_review_required", "current_grant_binding_missing")
                        : Set.of("selected", "geography_unresolved", "current_grant_binding_missing")).contains(reason), "selection_ledger_invalid");
            if ("selected".equals(reason)) eligible.add(id);
        }
        need(eligible.equals(selected), "selection_ledger_invalid");
        need(decisions.keySet().equals(selected), "geography_export_closure");
        Set<String> geographyIds = new HashSet<>();
        for (Obj row : decisions.values()) geographyIds.addAll(row.strings("source_evidence_ids"));
        need(geoEvidence.keySet().equals(geographyIds), "geography_export_closure");
        Set<String> articleKeys = new HashSet<>(), candidateIds = new HashSet<>(), companyIds = new HashSet<>(), relationIds = new HashSet<>();
        for (Obj issue : issues.values()) {
            issue.exactly(Set.of("article_refs", "candidate_ids", "field_decisions", "issue_id", "mentions", "relations", "source_support"));
            Set<String> issueArticleIds = new HashSet<>();
            for (Obj ref : issue.objects("article_refs")) {
                ref.exactly(Set.of("article_id", "article_version"));
                issueArticleIds.add(digest(ref.string("article_id"))); digest(ref.string("article_version"));
            }
            Obj support = issue.object("source_support").exactly(Set.of("article_count", "duplicate_groups",
                    "independent_source_count", "known_lineage_count", "unknown_lineage_articles"));
            need(issueArticleIds.containsAll(support.strings("unknown_lineage_articles")), "issue_article_closure");
            for (JsonNode group : support.array("duplicate_groups")) for (JsonNode member : group)
                need(issueArticleIds.contains(member.asString()), "issue_article_closure");
            for (Obj mention : issue.objects("mentions")) {
                mention.keys(Set.of("article_id", "article_version", "mention_id", "title", "action", "assertion_status",
                        "background", "participants", "evidence"),
                        Set.of("target", "period", "event_time", "countries", "event_type", "keywords"));
                for (Obj participant : mention.objects("participants"))
                    participant.keys(Set.of("company_id", "name", "role"), Set.of("role_unconfirmed"));
                for (Obj span : mention.objects("evidence"))
                    span.exactly(Set.of("article_id", "article_version", "start", "end", "quote"));
            }
            for (Obj field : issue.objects("field_decisions")) {
                field.exactly(Set.of("candidate_id", "mention_id", "outcomes"));
                for (Obj outcome : field.objects("outcomes")) outcome.exactly(Set.of("decision", "field", "reason"));
            }
        }
        for (Obj issue : issues.values()) {
            for (Obj ref : issue.objects("article_refs")) articleKeys.add(articleKey(ref));
            candidateIds.addAll(issue.strings("candidate_ids"));
            for (Obj relation : issue.objects("relations")) {
                relationIds.add(relation.string("relation_id"));
                if ("INVOLVES".equals(relation.string("relation_type"))) companyIds.add(relation.string("target"));
            }
        }
        need(audits.keySet().equals(candidateIds) && companies.keySet().equals(companyIds), "selection_export_closure");
        for (Obj audit : audits.values()) {
            audit.keys(Set.of("active", "candidate_id", "candidate_revision", "invalidation_reason",
                    "issue_id", "original_mention", "policy_version", "publication_resolution", "status", "validation"),
                    Set.of("source_audit_record_sha256"));
            if (audit.has("source_audit_record_sha256")) digest(audit.string("source_audit_record_sha256"));
            Obj resolution = audit.object("publication_resolution");
            if ("historical_allow".equals(resolution.string("type"))) resolution.exactly(Set.of("type"));
            else {
                resolution.exactly(Set.of("type", "rule_id", "effect"));
                need("existing_enabled_publication_rule".equals(resolution.string("type"))
                        && "R1@2".equals(resolution.string("rule_id")), "rule_resolution_invalid");
                Obj effect = resolution.object("effect").exactly(Set.of("participants", "relations", "dropped"));
                for (String key : List.of("relations", "dropped")) for (String id : effect.strings(key))
                    need(id.matches("relation-[A-Za-z0-9-]{1,100}"), "rule_effect_invalid");
            }
            Obj validation = audit.object("validation").keys(Set.of("candidate_id", "candidate_revision", "policy_version", "verdicts"),
                    metadata ? Set.of("field_verdicts", "trace") : Set.of("field_verdicts"));
            for (Obj verdict : validation.objects("verdicts")) {
                verdict.exactly(Set.of("target", "decision", "reason"));
                if (!metadata || !validation.has("trace")) reviewReason(verdict.string("reason"));
            }
            if (validation.has("field_verdicts")) for (Obj verdict : validation.objects("field_verdicts")) {
                verdict.exactly(Set.of("field", "decision", "reason"));
                if (!metadata || !validation.has("trace")) reviewReason(verdict.string("reason"));
            }
        }
        if (!metadata) for (Obj issue : issues.values()) for (Obj field : issue.objects("field_decisions"))
            for (Obj outcome : field.objects("outcomes")) reviewReason(outcome.string("reason"));
        for (Obj review : selection.objects("effective_review_decisions")) {
            review.exactly(Set.of("id", "target_id", "target_type", "decision"));
            need(Set.of("reject", "allow").contains(review.string("decision"))
                    && Set.of("issue", "candidate", "relation").contains(review.string("target_type"))
                    && (selected.contains(review.string("target_id")) || candidateIds.contains(review.string("target_id"))
                    || relationIds.contains(review.string("target_id"))), "review_export_closure");
        }
        for (Obj exclusion : selection.objects("review_exclusions")) {
            exclusion.exactly(Set.of("issue_id", "relation_id", "candidate_ids", "authority_decision", "publication_decision"));
            need(selected.contains(exclusion.string("issue_id"))
                    && exclusion.string("relation_id").matches("relation-[A-Za-z0-9-]{1,100}")
                    && candidateIds.containsAll(exclusion.strings("candidate_ids"))
                    && Set.of("ALLOW", "HOLD").contains(exclusion.string("authority_decision"))
                    && "EXCLUDED_AFTER_MANUAL_REVIEW".equals(exclusion.string("publication_decision")), "review_export_closure");
        }
        Map<String, Obj> sourceArticles = new LinkedHashMap<>();
        for (Obj article : provenance.objects("articles")) {
            article.exactly(Set.of("article_id", "article_version", "body_sha256",
                    "retained_input_record_hashes", "retained_acquisition_content_hashes"));
            digest(article.string("article_version")); digest(article.string("body_sha256"));
            for (String hash : article.strings("retained_input_record_hashes")) digest(hash);
            for (String hash : article.strings("retained_acquisition_content_hashes")) digest(hash);
            need(sourceArticles.putIfAbsent(article.string("article_id") + "\n" + article.string("article_version"), article) == null, "provenance_duplicate");
        }
        need(sourceArticles.keySet().equals(articleKeys), "provenance_export_closure");
        if (pins.has("schema")) {
            pins.exactly(Set.of("schema", "originalDigest", "upstreamInputClaims"));
            need("zoop-legacy-export-source-pins/1".equals(pins.string("schema"))
                    && manifest.object("sourceInputDigests").string("source-pins.json").equals(digest(pins.string("originalDigest"))), "source_pins_claim_invalid");
            for (Obj claim : pins.objects("upstreamInputClaims")) {
                claim.exactly(Set.of("bytes", "sha256"));
                need(claim.count("bytes") >= 0, "source_pins_claim_invalid");
                digest(claim.string("sha256"));
            }
        } else pins.exactly(Set.of());
        need(!selected.isEmpty() && selected.size() == manifest.strings("selectedIssueIds").size() && issues.keySet().containsAll(selected), "issue_selection_invalid");
        Set<String> rejected = new HashSet<>();
        for (Obj review : selection.objects("effective_review_decisions")) {
            if ("reject".equals(review.string("decision"))) rejected.add(review.string("target_id"));
        }
        Map<String, Obj> bindings = new LinkedHashMap<>();
        for (Obj binding : manifest.objects("grantBindings")) {
            binding.exactly(Set.of("originalArticleId", "originalArticleVersion", "sourceId", "grantId", "revision", "kind"));
            need(Set.of("news", "disclosure").contains(binding.string("kind")), "article_kind_invalid");
            for (String field : List.of("sourceId", "grantId", "revision")) need(!binding.string(field).isBlank(), "grant_pin_invalid");
            need(bindings.putIfAbsent(binding.string("originalArticleId") + "\n" + binding.string("originalArticleVersion"), binding) == null, "grant_ambiguous");
        }
        Map<String, Article> articles = new LinkedHashMap<>();
        for (Obj wrapper : selection.objects("articles")) {
            wrapper.exactly(Set.of("article_version", "record"));
            Obj raw = wrapper.object("record");
            raw.keys(Set.of("article_id", "body", "title", "url", "publisher", "published_at", "collected_at",
                    "synthetic", "withdrawn", "input_kind", "allow_model_send"), Set.of("language", "origin_id"));
            if (raw.has("origin_id") && !raw.isNull("origin_id")) digest(raw.string("origin_id"));
            need(!raw.bool("synthetic") && !raw.bool("withdrawn") && "body".equals(raw.string("input_kind")), "article_not_real_available_body");
            ObjectNode versioned = (ObjectNode) raw.node().deepCopy();
            versioned.remove("collected_at");
            String version = digest(wrapper.string("article_version"));
            need(version.equals(Canonical.digest(versioned)), "original_article_version_mismatch");
            String oldId = raw.string("article_id"), key = oldId + "\n" + version;
            ObjectNode node = StrictJson.newObject();
            node.put("articleId", articleId(oldId)); node.put("articleVersion", version);
            node.put("originalArticleId", oldId); node.put("originalArticleVersion", version);
            node.put("title", raw.string("title")); node.put("url", raw.string("url"));
            node.put("publisher", raw.stringOrNull("publisher")); node.put("collectedAt", raw.string("collected_at"));
            String published = raw.stringOrNull("published_at");
            String precision = published == null ? "unknown" : published.length() == 10 ? "day" : "datetime";
            node.put("publicationPrecision", precision);
            node.put("publishedAt", HandoffTime.eventTime(published, precision));
            String body = raw.string("body"); need(Text.storable(body), "body_invalid");
            node.put("textSha256", Canonical.sha256(body)); node.put("textBytes", Text.strictUtf8(body).length);
            Obj binding = bindings.get(key);
            if (binding == null) node.putNull("grantBinding");
            else node.set("grantBinding", binding.node());
            need(articles.putIfAbsent(key, new Article(raw, Obj.of(node), body)) == null, "article_duplicate");
        }
        need(articles.keySet().equals(articleKeys), "article_export_closure");
        for (var article : articles.entrySet())
            need(article.getValue().projected().string("textSha256").equals(sourceArticles.get(article.getKey()).string("body_sha256")),
                    "provenance_body_hash_mismatch");
        ObjectNode bundle = StrictJson.newObject(); bundle.put("schemaVersion", metadata ? METADATA_BUNDLE_SCHEMA : BUNDLE_SCHEMA); bundle.put("provenanceKind", "legacy-real");
        bundle.put("sourceSystem", "investmate-poc-bff");
        ArrayNode outIssues = bundle.putArray("issues"), outRelations = bundle.putArray("relations");
        ObjectNode snapshot = StrictJson.newObject(); snapshot.put("snapshotFormat", metadata ? PublicGraphSnapshot.EXPLICIT_UNKNOWN_FORMAT : PublicGraphSnapshot.FORMAT);
        String versionId = "gv-" + Canonical.sha256(request.migrationId());
        snapshot.put("versionId", versionId); snapshot.put("sourceBundleId", request.migrationId());
        ArrayNode snapIssues = snapshot.putArray("issues"), snapRelations = snapshot.putArray("relations");
        Map<String, Obj> evidence = new LinkedHashMap<>(); Set<String> usedArticles = new LinkedHashSet<>(), usedCompanies = new LinkedHashSet<>();
        Map<String, String> oldEvidenceIds = new LinkedHashMap<>(); Set<String> seenRelations = new HashSet<>();
        Set<String> publicCompanies = new HashSet<>();
        for (String issueId : selected) {
            for (Obj relation : issues.get(issueId).objects("relations"))
                if ("INVOLVES".equals(relation.string("relation_type"))) publicCompanies.add(relation.string("target"));
        }
        for (String id : selected) {
            need(!rejected.contains(id), "review_excluded_issue");
            Obj issue = issues.get(id), geography = decisions.get(id), fieldPolicy = metadataIssues.get(id);
            boolean unknownGeography = metadata && "unknown".equals(fieldPolicy.object("geography").string("mode"));
            need(geography != null && (unknownGeography || "source_supported".equals(geography.string("decision"))), "geography_unresolved");
            Set<String> ownArticles = new LinkedHashSet<>(), ownArticleKeys = new LinkedHashSet<>(), ownEvidence = new LinkedHashSet<>();
            ObjectNode out = outIssues.addObject(); out.put("id", id);
            ArrayNode mentions = out.putArray("mentions"), fields = out.putArray("fieldVerdicts");
            List<Obj> originalMentions = issue.objects("mentions"); need(!originalMentions.isEmpty(), "mentions_missing");
            Map<String, Obj> candidateByMention = new LinkedHashMap<>();
            Map<String, Boolean> metadataHolds = new LinkedHashMap<>();
            boolean ruleApproved = false, metadataApproved = false;
            for (String candidateId : issue.strings("candidate_ids")) {
                Obj audit = audits.get(candidateId); need(audit != null && audit.bool("active") && audit.isNull("invalidation_reason"), "candidate_inactive");
                need(!rejected.contains(candidateId), "review_excluded_candidate");
                Obj validation = audit.object("validation");
                need(candidateId.equals(validation.string("candidate_id")) && audit.string("candidate_revision").equals(validation.string("candidate_revision"))
                        && audit.string("policy_version").equals(validation.string("policy_version")), "candidate_revision_mismatch");
                Obj original = audit.object("original_mention");
                need(candidateByMention.putIfAbsent(mentionKey(original), audit) == null, "mention_candidate_ambiguous");
                boolean metadataHold = metadataOnlyHold(issue, audit, fieldPolicy);
                metadataHolds.put(candidateId, metadataHold);
                ruleApproved |= "HOLD".equals(audit.string("status")) && !metadataHold;
                metadataApproved |= metadataHold;
            }
            for (Obj mention : originalMentions) {
                Obj audit = candidateByMention.remove(mentionKey(mention)); need(audit != null, "mention_candidate_missing");
                validateReview(selection, issue, mention, audit, rejected, metadataHolds.get(audit.string("candidate_id")));
                String key = articleKey(mention); Article article = articles.get(key); need(article != null, "mention_article_missing");
                ownArticles.add(article.projected().string("articleId")); ownArticleKeys.add(key); usedArticles.add(key);
                need(mention.objects("evidence").stream().allMatch(e -> articleKey(e).equals(key)), "mention_evidence_article_mismatch");
                List<String> cited = citations(mention.objects("evidence"), articles, evidence, oldEvidenceIds, usedArticles);
                need(!cited.isEmpty(), "mention_evidence_missing"); ownEvidence.addAll(cited);
                ObjectNode m = mentions.addObject();
                m.put("documentId", mention.string("article_id")); m.put("documentVersion", mention.string("article_version"));
                m.put("articleId", article.projected().string("articleId")); m.put("articleVersion", mention.string("article_version"));
                m.put("mentionId", mention.string("mention_id"));
                for (String field : List.of("title", "action", "assertion_status")) m.put(field.equals("assertion_status") ? "assertionStatus" : field, mention.string(field));
                m.put("target", optional(mention, "target")); m.put("period", optional(mention, "period"));
                m.put("approvalBasis", "HOLD".equals(audit.string("status"))
                        ? (metadataHolds.get(audit.string("candidate_id")) ? "metadata-policy:" + METADATA_POLICY : "review-rule:R1@2") : "historical-allow");
                String time = optional(mention, "event_time"), timePrecision = precision(time);
                if (metadata && time != null && "unknown".equals(timePrecision)) timePrecision = "unresolved";
                m.put("eventTime", metadata ? time : "unknown".equals(timePrecision) ? null : HandoffTime.eventTime(time, timePrecision));
                m.put("timePrecision", timePrecision); m.put("background", mention.bool("background"));
                strings(m.putArray("evidenceIds"), cited);
                ArrayNode participants = m.putArray("participants");
                for (Obj p : mention.objects("participants")) {
                    String company = p.stringOrNull("company_id");
                    ObjectNode participant = participants.addObject();
                    participant.put("companyId", company != null && publicCompanies.contains(company) ? company : null);
                    participant.put("name", p.string("name")); participant.put("role", p.stringOrNull("role"));
                    participant.put("roleUnconfirmed", p.has("role_unconfirmed") && p.bool("role_unconfirmed"));
                }
                for (Obj fieldDecision : issue.objects("field_decisions")) {
                    if (!audit.string("candidate_id").equals(fieldDecision.string("candidate_id"))) continue;
                    for (Obj verdict : fieldDecision.objects("outcomes")) {
                        ObjectNode field = fields.addObject(); field.put("documentId", mention.string("article_id"));
                        field.put("documentVersion", mention.string("article_version")); field.put("mentionId", mention.string("mention_id"));
                        field.put("field", "event_time".equals(verdict.string("field")) ? "eventTime" : verdict.string("field"));
                        field.put("decision", verdict.string("decision")); field.put("reasonCode", verdict.string("reason"));
                    }
                }
            }
            need(candidateByMention.isEmpty(), "candidate_mention_missing");
            Set<String> declaredArticles = new LinkedHashSet<>();
            for (Obj ref : issue.objects("article_refs")) {
                need(articles.containsKey(articleKey(ref)), "issue_article_reference");
                declaredArticles.add(articleKey(ref));
            }
            need(declaredArticles.equals(ownArticleKeys), "issue_article_closure");
            List<String> geoIds = new ArrayList<>(); StringBuilder literal = new StringBuilder();
            for (String geoId : unknownGeography ? List.<String>of() : geography.strings("source_evidence_ids")) {
                Obj span = geoEvidence.get(geoId); need(span != null && ownArticleKeys.contains(articleKey(span)), "geography_reference");
                List<String> mapped = citations(List.of(span), articles, evidence, oldEvidenceIds, usedArticles);
                geoIds.addAll(mapped); literal.append(span.string("quote")).append('\n');
                oldEvidenceIds.put(geoId, mapped.getFirst());
            }
            if (!unknownGeography) {
                validateGeography(geography, literal.toString()); need(!geoIds.isEmpty(), "geography_evidence_missing");
            }
            Obj support = issue.object("source_support"); ObjectNode sourceSupport = out.putObject("sourceSupport");
            sourceSupport.set("articleCount", support.raw("article_count")); sourceSupport.set("knownLineageCount", support.raw("known_lineage_count"));
            sourceSupport.set("independentSourceCount", support.raw("independent_source_count"));
            strings(sourceSupport.putArray("unknownLineageArticles"), support.strings("unknown_lineage_articles").stream().map(LegacyRealPackage::articleId).toList());
            ArrayNode groups = sourceSupport.putArray("duplicateGroups");
            for (JsonNode group : support.array("duplicate_groups")) { ArrayNode mapped = groups.addArray(); for (JsonNode member : group) mapped.add(articleId(member.asString())); }
            out.set("legacy", issue.node()); out.put("approvalBasis", ruleApproved ? "review-rule:R1@2"
                    : metadataApproved ? "metadata-policy:" + METADATA_POLICY : "historical-allow");
            if (metadata) out.set("metadataPolicy", fieldPolicy.node());
            ObjectNode s = snapIssues.addObject(); s.put("issueId", id);
            // Match BFF build_dataset: first nonbackground mention, then first retained date/period when it has none.
            int representativeIndex = 0;
            for (int n = 0; n < originalMentions.size(); n++) {
                if (!originalMentions.get(n).bool("background")) { representativeIndex = n; break; }
            }
            int datedIndex = headField(originalMentions, representativeIndex, "event_time");
            int periodicIndex = headField(originalMentions, representativeIndex, "period");
            Obj representative = Obj.of(mentions.get(representativeIndex));
            Obj dated = Obj.of(mentions.get(datedIndex)), periodic = Obj.of(mentions.get(periodicIndex));
            s.put("label", representative.string("title"));
            for (String field : List.of("assertionStatus", "action", "target")) s.set(field, representative.raw(field));
            s.set("eventTime", dated.raw("eventTime")); s.set("timePrecision", dated.raw("timePrecision"));
            s.set("period", periodic.raw("period"));
            if (metadata) {
                if ("unknown".equals(fieldPolicy.object("eventTime").string("mode"))) {
                    s.putNull("eventTime"); s.put("timePrecision", "unknown");
                }
                if ("unknown".equals(fieldPolicy.object("period").string("mode"))) s.putNull("period");
            }
            s.put("geography", unknownGeography ? null : geography.string("classification"));
            s.put("geographyPolicyVersion", metadata ? METADATA_POLICY : geography.string("review_policy_version"));
            strings(s.putArray("geographyEvidenceIds"), geoIds); strings(s.putArray("evidenceIds"), ownEvidence); strings(s.putArray("articleIds"), ownArticles);
            ArrayNode refs = s.putArray("mentions");
            for (JsonNode m : mentions) { Obj mention = Obj.of(m); ObjectNode ref = refs.addObject(); ref.put("mentionId", MentionIds.of(mention.string("articleId"), mention.string("articleVersion"), mention.string("mentionId"))); ref.set("articleId", mention.raw("articleId")); ref.set("articleVersion", mention.raw("articleVersion")); }
            s.put("representativeMentionId", datedIndex == representativeIndex && periodicIndex == representativeIndex
                    ? MentionIds.of(representative.string("articleId"), representative.string("articleVersion"), representative.string("mentionId")) : null);
            String latest = originalMentions.stream().map(LegacyRealPackage::articleKey).distinct().map(articles::get).map(a -> a.projected().stringOrNull("publishedAt")).filter(Objects::nonNull).max(String::compareTo).orElse(null);
            s.put("latestPublishedAt", latest);
            boolean connected = false;
            for (Obj relation : issue.objects("relations")) {
                relation.keys(Set.of("relation_id", "relation_type", "source", "target", "role", "assertion_status",
                        "basis", "candidate_ids", "evidence"), Set.of("role_unconfirmed"));
                if (relation.has("role_unconfirmed")) relation.bool("role_unconfirmed");
                String type = relation.string("relation_type"), rid = relation.string("relation_id");
                need(!rejected.contains(rid), "review_excluded_relation");
                need(relation.objects("basis").isEmpty()
                        && issue.strings("candidate_ids").containsAll(relation.strings("candidate_ids")), "legacy_relation_unsupported");
                for (Obj span : relation.objects("evidence")) {
                    span.exactly(Set.of("article_id", "article_version", "start", "end", "quote"));
                    need(ownArticleKeys.contains(articleKey(span)), "relation_evidence_reference");
                }
                if (Set.of("REPORTS", "PROVIDES_BACKGROUND").contains(type)
                        || "FOLLOWS".equals(type) && !selected.contains(relation.string("target"))) {
                    if (!"FOLLOWS".equals(type)) need(issue.objects("article_refs").stream().anyMatch(
                            ref -> ref.string("article_id").equals(relation.string("source")))
                            && id.equals(relation.string("target")), "relation_source_mismatch");
                    else need(id.equals(relation.string("source"))
                            && relation.string("target").matches("issue-[A-Za-z0-9-]{1,100}"), "relation_source_mismatch");
                    for (Obj span : relation.objects("evidence")) {
                        Article article = articles.get(articleKey(span));
                        String quote = Text.codePointSlice(article.body(), span.count("start"), span.count("end"));
                        need(quote != null && !quote.isBlank() && quote.equals(span.string("quote")) && Text.storable(quote), "quote_mismatch");
                    }
                    continue;
                }
                need(Set.of("INVOLVES", "FOLLOWS").contains(type), "legacy_relation_unsupported");
                need(relation.string("source").equals(id), "relation_source_mismatch");
                need(seenRelations.add(rid), "relation_duplicate");
                List<String> cited = citations(relation.objects("evidence"), articles, evidence, oldEvidenceIds, usedArticles);
                need(!cited.isEmpty() && relation.objects("evidence").stream().allMatch(e -> ownArticleKeys.contains(articleKey(e))), "relation_evidence_reference");
                ownEvidence.addAll(cited);
                if ("INVOLVES".equals(type)) {
                    String company = relation.string("target");
                    need(companies.containsKey(company), "relation_company_missing");
                    need(originalMentions.stream().anyMatch(m -> relation.strings("candidate_ids").stream().anyMatch(cid ->
                            audits.containsKey(cid) && mentionKey(audits.get(cid).object("original_mention")).equals(mentionKey(m)))
                            && m.objects("participants").stream().anyMatch(p -> company.equals(p.stringOrNull("company_id")))), "relation_company_provenance");
                    usedCompanies.add(company); connected = true;
                }
                ObjectNode r = snapRelations.addObject(); r.put("relationId", rid); r.put("relationType", type);
                r.put("source", id); r.put("target", relation.string("target")); r.put("role", relation.stringOrNull("role"));
                r.put("assertionStatus", relation.stringOrNull("assertion_status")); strings(r.putArray("evidenceIds"), cited); r.putArray("basis");
                ObjectNode retained = outRelations.addObject(); retained.put("id", rid); retained.put("type", type); retained.put("source", id); retained.put("target", relation.string("target")); strings(retained.putArray("evidenceIds"), cited); retained.set("legacy", relation.node());
            }
            strings(s.putArray("evidenceIds"), ownEvidence);
            need(connected, "issue_company_connection_missing");
        }
        ArrayNode snapCompanies = snapshot.putArray("companies");
        for (String id : usedCompanies) { ObjectNode c = snapCompanies.addObject(); c.put("companyId", id); c.put("label", companyBindings.get(id).string("canonicalName")); }
        bundle.set("companies", snapCompanies.deepCopy());
        ArrayNode snapArticles = snapshot.putArray("articles"), outArticles = bundle.putArray("articles"); List<Article> retainedArticles = new ArrayList<>();
        for (String key : usedArticles) {
            Article a = articles.get(key); retainedArticles.add(a); outArticles.add(a.projected().node());
            Obj p = a.projected(); ObjectNode s = snapArticles.addObject(); s.put("articleId", p.string("articleId")); s.put("version", p.string("articleVersion"));
            s.put("title", p.string("title")); s.put("url", p.string("url")); s.put("publishedAt", p.stringOrNull("publishedAt"));
        }
        need(usedArticles.containsAll(bindings.keySet()), "grant_article_outside_projection");
        ArrayNode snapEvidence = snapshot.putArray("evidence"), outEvidence = bundle.putArray("evidence");
        for (Obj e : evidence.values()) { outEvidence.add(e.node()); ObjectNode s = snapEvidence.addObject(); s.put("evidenceId", e.string("id")); for (String field : List.of("articleId", "articleVersion", "start", "end")) s.set(field, e.raw(field)); }
        ObjectNode idMap = bundle.putObject("evidenceIdMap"); oldEvidenceIds.forEach(idMap::put);
        byte[] snapshotBytes = Canonical.bytes(snapshot);
        PublicGraphSnapshot graph = GraphSnapshotCodec.read(snapshotBytes, versionId);
        ObjectNode receipt = StrictJson.newObject(); receipt.put("schemaVersion", metadata ? METADATA_RECEIPT_SCHEMA : RECEIPT_SCHEMA); receipt.put("migrationId", request.migrationId());
        receipt.put("manifestDigest", request.expectedManifestDigest()); receipt.put("bundleDigest", request.expectedBundleDigest());
        receipt.put("contentDigest", Canonical.digest(bundle)); receipt.set("manifest", manifest.node()); receipt.set("bundle", bundle);
        ObjectNode legacy = receipt.putObject("legacyProvenance");
        legacy.set("selectionLedger", manifest.raw("selectionLedger"));
        for (String field : List.of("origin", "companies", "candidate_audit", "effective_review_decisions", "enabled_rules", "review_exclusions")) legacy.set(field, selection.raw(field));
        legacy.set("geography", geo.node()); legacy.set("sourcePins", pins.node()); legacy.set("sourceProvenance", provenance.node());
        if (metadata) legacy.set("metadataPolicy", metadataPolicy.node());
        ObjectNode verification = receipt.putObject("appVerification");
        verification.put("policy", metadata ? METADATA_POLICY : POLICY); verification.put("quoteIntegrity", "exact-retained-body-unicode-code-point-span");
        verification.put("nativeProvenance", "not-performed"); verification.put("newSemanticVerification", "not-performed");
        verification.put("publication", "staged-inactive");
        strings(verification.putArray("checks"), List.of("package-pins", "original-article-versions", "exact-quotes", "reference-closure", "effective-review-exclusions",
                metadata ? "pinned-metadata-policy" : "literal-geography", "current-catalogue", "current-rights-import-and-precommit", metadata ? "format-4" : "format-3"));
        verification.put("sourceInputDigests", "local-source-provenance-claims-not-remotely-verified");
        return new Projection(request, manifest, Obj.of(bundle), snapshotBytes, graph, Canonical.appBytes(receipt), List.copyOf(retainedArticles), List.copyOf(evidence.values()));
    }

    private static Map<String, Obj> metadataIssues(Obj policy, Map<String, Obj> issues, Map<String, Obj> audits) {
        policy.exactly(Set.of("schemaVersion", "policyVersion", "issues"));
        need("zoop-legacy-metadata-policy-1".equals(policy.string("schemaVersion"))
                && METADATA_POLICY.equals(policy.string("policyVersion")), "metadata_policy_invalid");
        Map<String, Obj> rows = index(policy.objects("issues"), "issueId");
        need(rows.keySet().equals(issues.keySet()), "metadata_policy_issue_closure");
        for (var entry : rows.entrySet()) {
            Obj row = entry.getValue().exactly(Set.of("issueId", "sourceAuditDigests", "geography", "eventTime", "period", "decisionRef", "decisionVersion"));
            for (String key : List.of("decisionRef", "decisionVersion"))
                need(row.string(key).matches("[A-Za-z0-9._:-]{1,200}"), "metadata_policy_identity");
            List<String> expected = issues.get(entry.getKey()).strings("candidate_ids").stream().map(id -> {
                Obj audit = audits.get(id);
                need(audit != null && audit.has("source_audit_record_sha256"), "metadata_policy_audit_missing");
                return digest(audit.string("source_audit_record_sha256"));
            }).distinct().sorted().toList();
            need(!expected.isEmpty() && expected.equals(row.strings("sourceAuditDigests")), "metadata_policy_audit_pin");
            for (String key : List.of("geography", "eventTime", "period")) {
                Obj field = row.object(key);
                if ("preserve".equals(field.string("mode"))) field.exactly(Set.of("mode"));
                else {
                    field.exactly(Set.of("mode", "reasonCode"));
                    need("unknown".equals(field.string("mode"))
                            && Set.of("not-stated", "not-supported", "conflicting").contains(field.string("reasonCode")), "metadata_policy_field");
                }
            }
        }
        return rows;
    }

    private static boolean metadataOnlyHold(Obj issue, Obj audit, Obj fieldPolicy) {
        if (fieldPolicy == null || !"HOLD".equals(audit.string("status")) || !audit.object("validation").has("trace")) return false;
        Obj validation = audit.object("validation");
        Obj trace = validation.object("trace").exactly(Set.of("contract_version", "decision_policy", "model", "observations", "provider"));
        digest(trace.string("contract_version"));
        need(!trace.string("model").isBlank() && !trace.string("provider").isBlank(), "core_proof_invalid");
        Obj thresholds = trace.object("decision_policy").exactly(Set.of("support_min", "contradiction_max", "reject_min"));
        double support = probability(thresholds.raw("support_min")), contradiction = probability(thresholds.raw("contradiction_max"));
        need(support == 0.65 && contradiction == 0.1 && probability(thresholds.raw("reject_min")) == 0.9, "core_proof_policy");
        Set<String> required = new HashSet<>();
        for (String check : List.of("concrete_event", "title", "event_type", "action", "assertion_status", "background"))
            required.add("issue\n" + check);
        Obj mention = audit.object("original_mention");
        if (optional(mention, "target") != null) required.add("issue\ntarget");
        for (int n = 0; n < mention.objects("participants").size(); n++) {
            required.add("issue\nparticipant_identity:" + n);
            required.add("issue\nparticipant_role:" + n);
        }
        for (Obj relation : issue.objects("relations")) {
            if (!relation.strings("candidate_ids").contains(audit.string("candidate_id"))) continue;
            String target = relation.string("relation_id"), type = relation.string("relation_type");
            required.add(target + "\n" + type);
            if ("INVOLVES".equals(type)) {
                required.add(target + "\nassertion_status");
                if (relation.stringOrNull("role") != null) required.add(target + "\nrole");
            }
        }
        Set<String> observed = new HashSet<>();
        boolean fieldFailure = false;
        for (Obj observation : trace.objects("observations")) {
            observation.exactly(Set.of("target", "check", "choice", "confidence", "probabilities", "question_id"));
            String target = observation.string("target"), check = observation.string("check");
            need(observed.add(target + "\n" + check), "core_proof_duplicate");
            probability(observation.raw("confidence"));
            Obj probabilities = observation.object("probabilities").exactly(Set.of("SUPPORTED", "INSUFFICIENT", "CONTRADICTED"));
            double supported = probability(probabilities.raw("SUPPORTED")), contradicted = probability(probabilities.raw("CONTRADICTED"));
            probability(probabilities.raw("INSUFFICIENT"));
            if ("SUPPORTED".equals(observation.string("choice")) && supported >= support && contradicted <= contradiction) continue;
            String field = switch (target) {
                case "field:countries" -> check.matches("country:[0-9]+") ? "geography" : null;
                case "field:event_time" -> "event_time".equals(check) ? "eventTime" : null;
                case "field:period" -> "period".equals(check) ? "period" : null;
                default -> null;
            };
            if (field == null || !"unknown".equals(fieldPolicy.object(field).string("mode"))) return false;
            fieldFailure = true;
        }
        if (!fieldFailure || !observed.containsAll(required)) return false;
        return validation.objects("verdicts").stream().allMatch(v -> "issue".equals(v.string("target"))
                ? "HOLD".equals(v.string("decision")) : "ALLOW".equals(v.string("decision")));
    }

    private static double probability(JsonNode value) {
        need(value.isNumber(), "core_proof_probability");
        double number = Double.parseDouble(value.toString());
        need(Double.isFinite(number) && number >= 0 && number <= 1, "core_proof_probability");
        return number;
    }

    private static void reviewReason(String reason) {
        need("Every required check satisfies the configured probability policy.".equals(reason)
                || reason.matches("Support or contradiction probability requires review: (?:participant_role:[0-9]+|country:[0-9]+|role)(?:, (?:participant_role:[0-9]+|country:[0-9]+|role))*"),
                "review_reason_invalid");
    }

    private static void validateReview(Obj selection, Obj issue, Obj mention, Obj audit, Set<String> rejected, boolean metadataHold) {
        Obj resolution = audit.object("publication_resolution"), validation = audit.object("validation");
        ObjectNode expected = (ObjectNode) audit.object("original_mention").node().deepCopy();
        String status = audit.string("status");
        need(Set.of("ALLOW", "HOLD").contains(status), "candidate_status_invalid");
        List<Obj> issueVerdicts = validation.objects("verdicts").stream().filter(v -> "issue".equals(v.string("target"))).toList();
        need(issueVerdicts.size() == 1 && status.equals(issueVerdicts.getFirst().string("decision")), "issue_verdict_mismatch");
        Set<Integer> heldParticipants = new LinkedHashSet<>(); Set<String> heldRelations = new LinkedHashSet<>();
        for (Obj verdict : validation.objects("verdicts")) {
            if (metadataHold) continue;
            String decision = verdict.string("decision");
            if ("ALLOW".equals(status) && !"issue".equals(verdict.string("target")) && !"ALLOW".equals(decision)) {
                need(Set.of("HOLD", "REJECT").contains(decision) && issue.objects("relations").stream()
                        .noneMatch(r -> r.string("relation_id").equals(verdict.string("target"))
                                && r.strings("candidate_ids").contains(audit.string("candidate_id"))), "withheld_relation_published");
                continue;
            }
            need(!"REJECT".equals(decision), "candidate_rejected");
            if ("ALLOW".equals(decision)) continue;
            need("HOLD".equals(status) && "HOLD".equals(decision), "candidate_verdict_invalid");
            String reason = verdict.string("reason"), prefix = "Support or contradiction probability requires review: ";
            need(reason.startsWith(prefix), "rule_hold_not_role");
            String checks = reason.substring(prefix.length()).split(" Numerical diagnostics: ", 2)[0].replaceAll("\\.$", "");
            for (String check : checks.split(",")) {
                check = check.strip();
                if ("issue".equals(verdict.string("target"))) {
                    need(check.matches("participant_role:[0-9]+"), "rule_hold_not_role"); heldParticipants.add(Integer.parseInt(check.substring(17)));
                } else { need("role".equals(check), "rule_hold_not_role"); heldRelations.add(verdict.string("target")); }
            }
        }
        if ("HOLD".equals(status) && !metadataHold) {
            need("existing_enabled_publication_rule".equals(resolution.string("type")) && "R1@2".equals(resolution.string("rule_id"))
                    && selection.objects("enabled_rules").stream().anyMatch(r -> "R1@2".equals(r.string("id"))) && !heldParticipants.isEmpty(), "rule_resolution_invalid");
            Obj effect = resolution.object("effect"); Set<Integer> declared = new HashSet<>();
            for (JsonNode n : effect.array("participants")) { need(n.isIntegralNumber(), "rule_effect_invalid"); declared.add(n.intValue()); }
            need(declared.equals(heldParticipants) && new HashSet<>(effect.strings("relations")).equals(heldRelations), "rule_effect_mismatch");
            ArrayNode participants = (ArrayNode) expected.get("participants");
            for (int index : heldParticipants) { need(index >= 0 && index < participants.size(), "rule_participant_invalid"); ObjectNode p = (ObjectNode) participants.get(index); p.putNull("role"); p.put("role_unconfirmed", true); }
            for (Obj relation : issue.objects("relations")) {
                need(!effect.strings("dropped").contains(relation.string("relation_id")), "rule_dropped_relation");
                if (heldRelations.contains(relation.string("relation_id"))) need(relation.isNull("role"), "rule_role_leaked");
                if (relation.strings("candidate_ids").contains(audit.string("candidate_id")) && "FOLLOWS".equals(relation.string("relation_type"))) need("occurred".equals(mention.string("assertion_status")), "rule_follows_invalid");
            }
        } else if (!metadataHold) need("historical_allow".equals(resolution.string("type")), "allow_resolution_invalid");
        if (validation.has("field_verdicts")) {
            for (Obj original : validation.objects("field_verdicts")) {
                need(issue.objects("field_decisions").stream().filter(f -> audit.string("candidate_id").equals(f.string("candidate_id")))
                        .flatMap(f -> f.objects("outcomes").stream()).anyMatch(o -> o.node().equals(original.node())), "field_verdict_mismatch");
            }
        }
        for (Obj field : issue.objects("field_decisions")) {
            if (!audit.string("candidate_id").equals(field.string("candidate_id"))) continue;
            need(field.string("mention_id").equals(mention.string("mention_id")), "field_mention_mismatch");
            for (Obj outcome : field.objects("outcomes")) {
                need(Set.of("ALLOW", "HOLD", "REJECT").contains(outcome.string("decision")), "field_decision_invalid");
                if (!"ALLOW".equals(outcome.string("decision"))) {
                    need(Set.of("event_time", "period", "countries").contains(outcome.string("field")), "field_invalid");
                    need(metadataHold || !"HOLD".equals(status) || !"REJECT".equals(outcome.string("decision")), "rule_field_rejected");
                    expected.remove(outcome.string("field"));
                }
            }
        }
        need(expected.equals(mention.node()), "effective_mention_mismatch");
        need(!rejected.contains(audit.string("issue_id")), "review_excluded_candidate_issue");
    }

    private static void validateGeography(Obj decision, String quote) {
        need("legacy-source-geography-review/1".equals(decision.string("review_policy_version")) && !decision.string("reviewer").isBlank() && !decision.string("reason").isBlank(), "geography_review_invalid");
        List<String> countries = decision.strings("country_codes"), regions = decision.strings("regions");
        need(!countries.isEmpty() || !regions.isEmpty(), "geography_location_missing");
        List<String> locations = new ArrayList<>(countries); locations.addAll(regions);
        for (String location : locations) need(GEOGRAPHY_LITERALS.containsKey(location) && GEOGRAPHY_LITERALS.get(location).stream().anyMatch(quote::contains), "geography_literal_missing");
        boolean domestic = countries.equals(List.of("KR")) && regions.isEmpty();
        need((domestic ? "domestic" : "international").equals(decision.string("classification")), "geography_classification_mismatch");
    }

    private static List<String> citations(List<Obj> spans, Map<String, Article> articles, Map<String, Obj> evidence,
            Map<String, String> oldIds, Set<String> usedArticles) {
        List<String> ids = new ArrayList<>();
        for (Obj span : spans) {
            String key = articleKey(span); Article article = articles.get(key); need(article != null, "evidence_article_missing");
            String quote = Text.codePointSlice(article.body(), span.count("start"), span.count("end"));
            need(quote != null && !quote.isBlank() && quote.equals(span.string("quote")) && Text.storable(quote), "quote_mismatch");
            String oldKey = span.string("article_id") + "|" + span.string("article_version") + "|" + span.count("start") + "|" + span.count("end");
            String id = "ev-" + Canonical.sha256("legacy-real-evidence-1\n" + oldKey);
            oldIds.put("ev-" + Canonical.sha256(oldKey).substring(0, 24), id);
            ObjectNode e = StrictJson.newObject(); e.put("id", id); e.put("articleId", article.projected().string("articleId"));
            e.put("articleVersion", span.string("article_version")); e.put("start", span.count("start")); e.put("end", span.count("end"));
            e.put("quote", quote); e.put("quoteSha256", Canonical.sha256(quote)); e.put("locatorKind", "legacy-retained-body");
            e.put("locatorId", "legacy-body-" + Canonical.sha256(key + "\n" + article.projected().string("textSha256")));
            Obj previous = evidence.putIfAbsent(id, Obj.of(e)); need(previous == null || previous.node().equals(e), "evidence_collision");
            usedArticles.add(key); ids.add(id);
        }
        return ids.stream().distinct().toList();
    }

    public static String articleId(String original) { return "doc-" + Canonical.sha256("legacy-real-article-1\n" + original); }
    private static String articleKey(Obj o) { return o.string("article_id") + "\n" + o.string("article_version"); }
    private static String mentionKey(Obj o) { return articleKey(o) + "\n" + o.string("mention_id"); }
    private static String optional(Obj o, String key) { return o.has(key) ? o.stringOrNull(key) : null; }
    private static int headField(List<Obj> mentions, int representative, String field) {
        String own = optional(mentions.get(representative), field);
        if (own != null && !own.isBlank()) return representative;
        for (int n = 0; n < mentions.size(); n++) {
            String value = optional(mentions.get(n), field);
            if (value != null && !value.isBlank()) return n;
        }
        return representative;
    }
    private static String precision(String value) {
        if (value == null) return "unknown";
        if (value.matches("[0-9]{4}")) return "year";
        if (value.matches("[0-9]{4}-[0-9]{2}")) return "month";
        if (value.matches("[0-9]{4}-[0-9]{2}-[0-9]{2}")) return "day";
        if (value.matches("[0-9]{4}-[0-9]{2}-[0-9]{2}T.*(?:Z|[+-][0-9]{2}:[0-9]{2})")) return "datetime";
        return "unknown";
    }
    private static Map<String, Obj> index(List<Obj> rows, String key) { Map<String, Obj> result = new LinkedHashMap<>(); for (Obj row : rows) need(result.putIfAbsent(row.string(key), row) == null, "duplicate_" + key); return result; }
    private static void strings(ArrayNode array, Iterable<String> values) { values.forEach(array::add); }
    private static String digest(String value) { need(StrictJson.SHA256.matcher(value).matches(), "digest_invalid"); return value; }
    private static Obj pinned(Path root, String file, String hash) { byte[] bytes = readFile(root.resolve(file)); need(Canonical.sha256(bytes).equals(digest(hash)), "package_pin_conflict"); return StrictJson.parseObject(bytes); }
    static byte[] readFile(Path path) {
        try {
            Path absolute = path.toAbsolutePath().normalize();
            for (Path part = absolute; part != null; part = part.getParent()) need(!Files.isSymbolicLink(part), "package_symlink");
            need(Files.isRegularFile(absolute, LinkOption.NOFOLLOW_LINKS), "package_file_invalid");
            Set<PosixFilePermission> permissions = Files.getPosixFilePermissions(absolute, LinkOption.NOFOLLOW_LINKS);
            need(!permissions.contains(PosixFilePermission.GROUP_WRITE) && !permissions.contains(PosixFilePermission.OTHERS_WRITE), "package_permissions");
            try (var in = Files.newInputStream(absolute, LinkOption.NOFOLLOW_LINKS)) { byte[] bytes = in.readNBytes(MAX_BYTES + 1); need(bytes.length <= MAX_BYTES, "package_too_large"); return bytes; }
        } catch (IOException error) { throw new Invalid("package_unavailable"); }
    }
    static void need(boolean condition, String code) { if (!condition) throw new Invalid(code); }
}
