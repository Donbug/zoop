package com.zoop.graph.importer;

import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import tools.jackson.databind.node.ObjectNode;

/**
 * The app's mention id of a producer-local mention id on one resolved article version: {@code "mention-"} + the SHA-256 of the
 * canonical JSON (sorted ASCII keys) of {@code {articleId, articleVersion, sourceMentionId}}. The import writes snapshot mention
 * references with it, and getEvent uses it to find the receipt mention behind a reference, so both sides share one formula.
 */
public final class MentionIds {
    private MentionIds() {
    }

    public static String of(String articleId, String articleVersion, String sourceMentionId) {
        ObjectNode preimage = StrictJson.newObject();
        preimage.put("articleId", articleId);
        preimage.put("articleVersion", articleVersion);
        preimage.put("sourceMentionId", sourceMentionId);
        return "mention-" + Canonical.digest(preimage);
    }
}
