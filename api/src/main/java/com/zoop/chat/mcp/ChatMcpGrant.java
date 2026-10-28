package com.zoop.chat.mcp;

import com.zoop.chat.tool.ChatCapability;
import java.time.Instant;
import java.util.List;

/**
 * What one MCP grant token lets its bearer do: call the listed read tools for one running attempt of one chat job, against
 * the graph version and asOf the job froze and the job's subject scope ({@code scope}, a digest of the member and the
 * frozen selection, see {@link ChatMcpGrants#scope}), until {@code expiresAt} (never past the run's deadline). The server
 * issues it; nothing in it comes from a model or a member's request, and it carries no member id.
 *
 * <p>A grant alone never runs a call: each call must also match a call the server approved and reserved for the attempt
 * ({@link ChatMcpTools#approve}), consumed once.
 */
public record ChatMcpGrant(String jobId, int attemptNo, List<ChatCapability> tools, String graphVersionId, Instant asOf,
        String scope, Instant expiresAt) {
    public ChatMcpGrant {
        if (jobId == null || jobId.isBlank() || attemptNo < 1) throw new IllegalArgumentException("a grant needs a job attempt");
        tools = List.copyOf(tools);
        if (tools.isEmpty() || tools.contains(ChatCapability.PORTFOLIO_SCOPE_READ)) {
            throw new IllegalArgumentException("a grant lists one or more MCP tools and never the member scope read");
        }
        if (scope == null || scope.isBlank()) throw new IllegalArgumentException("a grant is bound to a subject scope");
        if (expiresAt == null) throw new IllegalArgumentException("a grant expires");
    }

    public boolean allows(ChatCapability capability) {
        return tools.contains(capability);
    }
}
