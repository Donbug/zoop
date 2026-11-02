package com.zoop.chat.tool;

import java.time.Instant;
import java.util.List;

/**
 * A public web search provider behind {@link ChatWebSearchTool} (web search design 7: selecting a real one is still an open
 * decision). It gets one query the server already checked, never a question, member or conversation, and returns
 * at most {@code limit} hits plus whether it had more. An outage or provider error throws {@link ChatToolUnavailable}; it is
 * never an empty list.
 */
public interface ChatWebSearchProvider {
    /** The provider's id as it appears on every hit, and in the source grant {@code web-search:<id>}. */
    String id();

    Page search(String query, int limit);

    /** One hit as the provider gave it, before the server bounds and checks it. */
    record Hit(String url, String title, String snippet, Instant publishedAt) { }

    record Page(List<Hit> hits, boolean more) {
        public Page {
            hits = List.copyOf(hits);
        }
    }
}
