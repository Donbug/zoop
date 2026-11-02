package com.zoop.document.evidence.service;

import java.util.LinkedHashSet;
import java.util.Set;

import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import com.zoop.common.json.StrictJson.Obj;
import com.zoop.graph.importer.LegacyRealPackage;

/**
 * The one fact the public graph evidence read takes from a graph import's {@code verification_receipt} for the GRANTS: which grant
 * each recorded observation of an article version was imported under, as {@code (sourceId, grantId, revision)}. The receipt is
 * retained data, never authority: these pins only say which current registry entry must still allow the read. The receipt must be
 * the closed {@code zoop-graph-handoff-import-receipt-1} document of exactly the graph version being served ({@code gv-} + SHA-256
 * of its handoff id), and exactly one bundle article must carry the article version; anything else is a {@link Malformed} receipt.
 * {@link #bundle} parses and checks the receipt ONCE; {@link #pins} and {@link GraphReceiptBasis} read the same parsed bundle.
 */
public final class GraphReceiptGrants {
    static final String SCHEMA = "zoop-graph-handoff-import-receipt-1";
    private static final Set<String> ROOT = Set.of("schemaVersion", "handoffId", "bundle");

    /** The receipt is not the import receipt of this graph version, or does not describe this article version exactly once. */
    public static final class Malformed extends RuntimeException {
        Malformed(String reason) {
            super(reason, null, false, false);
        }
    }

    /** One observation's grant identity. */
    public record Pin(String sourceId, String grantId, String revision, String legacyArticleUrl) {
        public Pin(String sourceId, String grantId, String revision) { this(sourceId, grantId, revision, null); }
    }

    private GraphReceiptGrants() {
    }

    /** The bundle of a receipt that is the import receipt of exactly {@code versionId}; the receipt bytes are parsed only here. */
    public static Obj bundle(byte[] receipt, String versionId) {
        try {
            Obj root = StrictJson.parseObject(receipt);
            if (LegacyRealPackage.isReceiptSchema(root.string("schemaVersion"))) {
                root.exactly(LegacyRealPackage.RECEIPT_KEYS);
                boolean metadata = LegacyRealPackage.METADATA_RECEIPT_SCHEMA.equals(root.string("schemaVersion"));
                String manifest = root.string("manifestDigest");
                if (!root.string("migrationId").equals("legacy-real:" + manifest)
                        || !versionId.equals("gv-" + Canonical.sha256(root.string("migrationId")))
                        || !manifest.equals(Canonical.digest(root.raw("manifest")))
                        || !(metadata ? LegacyRealPackage.METADATA_MANIFEST_SCHEMA : LegacyRealPackage.MANIFEST_SCHEMA)
                            .equals(root.object("manifest").string("schemaVersion"))
                        || !root.string("bundleDigest").equals(root.object("manifest").string("bundleDigest"))
                        || !root.string("contentDigest").equals(Canonical.digest(root.raw("bundle")))
                        || !(metadata ? LegacyRealPackage.METADATA_BUNDLE_SCHEMA : LegacyRealPackage.BUNDLE_SCHEMA)
                            .equals(root.object("bundle").string("schemaVersion"))) {
                    throw new Malformed("legacy_receipt_pin_mismatch");
                }
                Obj bundle = root.object("bundle").exactly(Set.of("schemaVersion", "provenanceKind", "sourceSystem",
                        "issues", "relations", "companies", "articles", "evidence", "evidenceIdMap"));
                if (!"legacy-real".equals(bundle.string("provenanceKind")) || !"investmate-poc-bff".equals(bundle.string("sourceSystem")))
                    throw new Malformed("legacy_receipt_provenance");
                if (metadata && (!LegacyRealPackage.METADATA_POLICY.equals(root.object("appVerification").string("policy"))
                        || !LegacyRealPackage.METADATA_POLICY.equals(root.object("legacyProvenance").object("metadataPolicy").string("policyVersion"))
                        || !root.object("manifest").string("metadataPolicyDigest")
                            .equals(root.object("manifest").object("sourceInputDigests").string("metadata-policy.json"))))
                    throw new Malformed("legacy_metadata_policy_mismatch");
                return bundle;
            }
            root.requiring(ROOT);
            if (!SCHEMA.equals(root.string("schemaVersion"))) {
                throw new Malformed("receipt_schema");
            }
            if (!versionId.equals("gv-" + Canonical.sha256(root.string("handoffId")))) {
                throw new Malformed("receipt_version_mismatch");
            }
            Obj bundle = root.object("bundle");
            if (bundle.has("schemaVersion")) {
                String schema = bundle.string("schemaVersion");
                if ("zoop-graph-handoff-bundle-9".equals(schema) || "zoop-graph-handoff-bundle-8".equals(schema)) {
                    String policy = "zoop-graph-handoff-bundle-9".equals(schema)
                            ? "zoop-public-projection-policy-3" : "zoop-public-projection-policy-2";
                    if (!policy.equals(bundle.object("policy").string("version"))
                            || !policy.equals(root.object("manifest").string("policyVersion")))
                        throw new Malformed("native_metadata_policy_mismatch");
                }
            }
            return bundle;
        } catch (StrictJson.Malformed malformed) {
            throw new Malformed("receipt_shape");
        }
    }

    public static Set<Pin> pins(Obj bundle, String articleId, String articleVersion) {
        try {
            Obj match = null;
            for (Obj article : bundle.objects("articles")) {
                if (articleId.equals(article.string("articleId")) && articleVersion.equals(article.string("articleVersion"))) {
                    if (match != null) {
                        throw new Malformed("receipt_article_ambiguous");
                    }
                    match = article;
                }
            }
            if (match == null) {
                throw new Malformed("receipt_article_missing");
            }
            if (bundle.has("schemaVersion") && LegacyRealPackage.isBundleSchema(bundle.string("schemaVersion"))) {
                Obj grant = match.object("grantBinding").exactly(Set.of("originalArticleId", "originalArticleVersion",
                        "sourceId", "grantId", "revision", "kind"));
                if (!grant.string("originalArticleId").equals(match.string("originalArticleId"))
                        || !grant.string("originalArticleVersion").equals(articleVersion)
                        || !articleId.equals(LegacyRealPackage.articleId(match.string("originalArticleId")))) {
                    throw new Malformed("legacy_receipt_article_mismatch");
                }
                for (String key : Set.of("sourceId", "grantId", "revision")) {
                    if (grant.string(key).isBlank()) throw new Malformed("receipt_pin_blank");
                }
                return Set.of(new Pin(grant.string("sourceId"), grant.string("grantId"), grant.string("revision"), match.string("url")));
            }
            Set<Pin> pins = new LinkedHashSet<>();
            for (Obj observation : match.objects("observations")) {
                Obj grant = observation.object("grant");
                String sourceId = observation.string("sourceId");
                String grantId = grant.string("grantId");
                String revision = grant.string("revision");
                if (sourceId.isBlank() || grantId.isBlank() || revision.isBlank()) {
                    throw new Malformed("receipt_pin_blank");
                }
                pins.add(new Pin(sourceId, grantId, revision));
            }
            if (pins.isEmpty()) {
                throw new Malformed("receipt_pins_missing");
            }
            return pins;
        } catch (StrictJson.Malformed malformed) {
            throw new Malformed("receipt_shape");
        }
    }
}
