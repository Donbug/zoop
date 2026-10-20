package com.zoop.document.evidence.service;

import java.util.LinkedHashSet;
import java.util.Set;

import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import com.zoop.common.json.StrictJson.Obj;

/**
 * The one fact the public graph evidence read takes from a graph import's {@code verification_receipt}: which grant each recorded
 * observation of an article version was imported under, as {@code (sourceId, grantId, revision)}. The receipt is retained data,
 * never authority: these pins only say which current registry entry must still allow the read. The receipt must be the closed
 * {@code zoop-graph-handoff-import-receipt-1} document of exactly the graph version being served ({@code gv-} + SHA-256 of its
 * handoff id), and exactly one bundle article must carry the article version; anything else is a {@link Malformed} receipt.
 */
final class GraphReceiptGrants {
    static final String SCHEMA = "zoop-graph-handoff-import-receipt-1";
    private static final Set<String> ROOT = Set.of("schemaVersion", "handoffId", "bundle");

    /** The receipt is not the import receipt of this graph version, or does not describe this article version exactly once. */
    static final class Malformed extends RuntimeException {
        Malformed(String reason) {
            super(reason, null, false, false);
        }
    }

    /** One observation's grant identity. */
    record Pin(String sourceId, String grantId, String revision) {
    }

    private GraphReceiptGrants() {
    }

    static Set<Pin> pins(byte[] receipt, String versionId, String articleId, String articleVersion) {
        try {
            Obj root = StrictJson.parseObject(receipt).requiring(ROOT);
            if (!SCHEMA.equals(root.string("schemaVersion"))) {
                throw new Malformed("receipt_schema");
            }
            if (!versionId.equals("gv-" + Canonical.sha256(root.string("handoffId")))) {
                throw new Malformed("receipt_version_mismatch");
            }
            Obj match = null;
            for (Obj article : root.object("bundle").objects("articles")) {
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
