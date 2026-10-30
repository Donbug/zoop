package com.zoop.chat.tool;

import java.util.List;

/**
 * What a tool read: the data version it read ({@code dataVersion}), the items found (a target that is not visible is simply
 * absent), the evidence ids it passes on as answer candidates, whether something was cut by the limit ({@code truncated})
 * and whether a supplementary round could read more ({@code nextAllowed}). A path read also reports each pair it read
 * ({@code paths}), and a web search the hits it kept ({@code webResults}); other reads have neither.
 */
public record ChatToolOutput(String dataVersion, List<ChatToolItem> items, List<String> evidenceIds, boolean truncated,
        boolean nextAllowed, List<ChatToolPath> paths, List<ChatWebResult> webResults) {
    public ChatToolOutput {
        items = List.copyOf(items);
        evidenceIds = List.copyOf(evidenceIds);
        paths = List.copyOf(paths);
        webResults = List.copyOf(webResults);
    }

    public ChatToolOutput(String dataVersion, List<ChatToolItem> items, List<String> evidenceIds, boolean truncated,
            boolean nextAllowed, List<ChatToolPath> paths) {
        this(dataVersion, items, evidenceIds, truncated, nextAllowed, paths, List.of());
    }

    public ChatToolOutput(String dataVersion, List<ChatToolItem> items, List<String> evidenceIds, boolean truncated,
            boolean nextAllowed) {
        this(dataVersion, items, evidenceIds, truncated, nextAllowed, List.of());
    }
}
