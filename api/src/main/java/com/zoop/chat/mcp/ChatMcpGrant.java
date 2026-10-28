package com.zoop.chat.mcp;

import com.zoop.chat.tool.ChatCapability;
import java.time.Instant;
import java.util.List;

/**
 * What one MCP grant token lets its bearer do: call the listed read tools for one running attempt of one chat job, against
 * the graph version and asOf the job froze, until {@code expiresAt} (never past the run's deadline). The server issues it;
 * nothing in it comes from a model or a member's request, and it carries no member id.
 */
public record ChatMcpGrant(String jobId, int attemptNo, List<ChatCapability> tools, String graphVersionId, Instant asOf,
        Instant expiresAt) {
    public ChatMcpGrant {
        if (jobId == null || jobId.isBlank() || attemptNo < 1) throw new IllegalArgumentException("a grant needs a job attempt");
        tools = List.copyOf(tools);
        if (tools.isEmpty() || tools.contains(ChatCapability.PORTFOLIO_SCOPE_READ)) {
            throw new IllegalArgumentException("a grant lists one or more MCP tools and never the member scope read");
        }
        if (expiresAt == null) throw new IllegalArgumentException("a grant expires");
    }

    public boolean allows(ChatCapability capability) {
        return tools.contains(capability);
    }
}
