package com.zoop.chat.mcp;

import com.zoop.chat.executor.ChatRun;
import java.util.Collection;
import java.util.Map;

/**
 * The chat grant registry's source id of evidence (api/docs/chat-mcp.md 5), the same one the direct path's quotes carry: an
 * article's provider, the company catalog for a profile quote, ZOOP's documents for a document section. Evidence the run
 * cannot cite now (at its pinned version and asOf) is absent from the map, so it is never sent. Throws
 * {@link com.zoop.chat.tool.ChatToolUnavailable} when the records cannot be read.
 */
@FunctionalInterface
public interface ChatMcpSources {
    Map<String, String> sourcesOf(ChatRun run, Collection<String> evidenceIds);
}
