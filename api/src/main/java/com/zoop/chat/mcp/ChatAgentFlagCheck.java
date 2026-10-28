package com.zoop.chat.mcp;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Configuration;

/**
 * Refuses startup when the agent path is switched on without the MCP endpoint it runs through. {@link ChatMcpConfiguration}
 * exists only with the endpoint on, so it cannot report the opposite itself; without this check the flag would be ignored and
 * every run would fall back to the direct path silently.
 */
@Configuration(proxyBeanMethods = false)
public class ChatAgentFlagCheck {
    ChatAgentFlagCheck(@Value("${zoop.chat.mcp.agent-enabled:false}") boolean agentEnabled,
            @Value("${zoop.chat.mcp.enabled:false}") boolean mcpEnabled) {
        if (agentEnabled && !mcpEnabled) {
            throw new IllegalStateException(
                    "zoop.chat.mcp.agent-enabled (ZOOP_CHAT_AGENT_ENABLED) needs zoop.chat.mcp.enabled (ZOOP_CHAT_MCP_ENABLED)");
        }
    }
}
