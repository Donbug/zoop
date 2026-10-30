package com.zoop.chat.tool;

import com.zoop.common.json.Canonical;
import java.net.URI;
import java.time.Clock;
import java.time.Instant;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * {@code web.search} (web search design 3 and 6): one query per call, its single target, checked by
 * {@link ChatWebQueryPolicy} before anything is sent. A query that may not be sent is refused before the provider is
 * reached. At most {@link #MAX_HITS} hits are kept, each bounded and checked ({@link ChatWebResult}); a hit with no usable
 * URL or title is dropped, never repaired. A provider outage is {@link ChatToolUnavailable}, never an empty result.
 *
 * <p>Hits are no ZOOP evidence: they carry no evidence ids, and their items are {@code web_result} entries whose ids are the
 * server's own ({@code web-…}). The data version names the provider.
 */
public final class ChatWebSearchTool implements ChatTool {
    /** Hits one query keeps (web search design 3: 5 per query, 10 per job). */
    public static final int MAX_HITS = 5;

    private final ChatWebSearchProvider provider;
    private final Clock clock;

    public ChatWebSearchTool(ChatWebSearchProvider provider, Clock clock) {
        this.provider = provider;
        this.clock = clock;
    }

    @Override
    public ChatCapability capability() {
        return ChatCapability.WEB_SEARCH;
    }

    @Override
    public ChatToolOutput read(ChatToolScope scope, ChatToolRequest request) {
        // One query per call: three queries in one envelope would get around the web budget.
        if (request.targets().size() != 1) throw new IllegalArgumentException("a web search takes exactly one query");
        String query = ChatWebQueryPolicy.checked(request.targets().getFirst())
                .orElseThrow(() -> new IllegalArgumentException("the query may not be sent"));
        int limit = Math.min(MAX_HITS, request.limit());
        ChatWebSearchProvider.Page page = provider.search(query, limit);
        Instant searchedAt = clock.instant();
        Map<String, ChatWebResult> kept = new LinkedHashMap<>();
        for (ChatWebSearchProvider.Hit hit : page.hits()) {
            ChatWebResult result = bounded(hit, searchedAt);
            if (result != null) kept.putIfAbsent(result.id(), result);
        }
        List<ChatWebResult> results = new ArrayList<>(kept.values());
        boolean truncated = page.more() || results.size() > limit;
        if (results.size() > limit) results = results.subList(0, limit);
        List<ChatToolItem> items = results.stream()
                .map(r -> new ChatToolItem(r.id(), "web_result", r.title(), List.of(), List.of())).toList();
        return new ChatToolOutput("web:" + provider.id(), items, List.of(), truncated, false, List.of(), results);
    }

    /** The hit as the server keeps it, or null when it has no usable URL or title. */
    private ChatWebResult bounded(ChatWebSearchProvider.Hit hit, Instant searchedAt) {
        try {
            URI uri = URI.create(hit.url().strip());
            String url = uri.toString();
            String id = "web-" + Canonical.sha256(provider.id() + "\n" + url).substring(0, 32);
            return new ChatWebResult(id, url, uri.getHost(), cut(hit.title().strip(), ChatWebResult.MAX_TITLE),
                    cut(hit.snippet() == null ? "" : hit.snippet().strip(), ChatWebResult.MAX_SNIPPET), hit.publishedAt(),
                    provider.id(), searchedAt);
        } catch (IllegalArgumentException | NullPointerException unusable) {
            return null;
        }
    }

    private static String cut(String text, int max) {
        return text.codePointCount(0, text.length()) <= max ? text : text.substring(0, text.offsetByCodePoints(0, max));
    }
}
