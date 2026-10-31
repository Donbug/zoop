package com.zoop.chat.tool;

import java.util.EnumMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.stream.Collectors;
import org.springframework.stereotype.Component;

/**
 * Maps a logical capability to the one read adapter that implements it, with the values {@code chat_tool_calls} fixes per
 * call: registry version, registry group, tool id and schema version. Only a bound capability is ever executed; an unknown
 * id or a capability without an adapter has no binding. Adapters are in-process reads of the application. The chat MCP
 * endpoint ({@code com.zoop.chat.mcp}, ZOOP-AIG-001 v0.11) exposes these same bindings to a model and runs them through the
 * same runner; it adds no second implementation of any read.
 */
@Component
public class ChatToolRegistry {
    /** Changes whenever a binding or a tool's input or output meaning changes. */
    public static final String VERSION = "chat-tools/v10";
    /** The common request and result envelope. */
    public static final String SCHEMA_VERSION = "chat-tool/v1";

    /** A capability bound to its adapter. {@code toolId} names the adapter, never a model-made string. */
    public record Binding(ChatCapability capability, String toolId, ChatTool tool) { }

    private final Map<ChatCapability, ChatTool> tools = new EnumMap<>(ChatCapability.class);

    public ChatToolRegistry(List<ChatTool> adapters) {
        for (ChatTool tool : adapters) {
            if (tools.putIfAbsent(tool.capability(), tool) != null) {
                throw new IllegalStateException("two chat tools for " + tool.capability().id());
            }
        }
    }

    public Optional<Binding> bind(String capabilityId) {
        return ChatCapability.of(capabilityId).filter(tools::containsKey)
                .map(c -> new Binding(c, "app:" + c.id(), tools.get(c)));
    }

    /**
     * The capability ids a plan may name: those that can be executed now, without the web search (web search design 2: Jev
     * probabilities alone never start a search). It is never offered to the router; the MCP tools add it on their own, for
     * the server to decide each call of the agent path.
     */
    public Set<String> bound() {
        return tools.keySet().stream().filter(c -> !c.web()).map(ChatCapability::id)
                .collect(Collectors.toUnmodifiableSet());
    }
}
