package com.zoop.chat.tool;

import java.time.Instant;

/**
 * What every call of one run reads against, injected by the server from the job's frozen context: the pinned public graph
 * version (null when the question froze none) and the requested asOf inside it (null for none). {@code traceId} ties a
 * tool's own logs to the job. {@code memberId} is the job's member, from the authenticated job, never from a plan or a
 * model: only a member-scope read ({@code portfolio.scope.read}) uses it.
 */
public record ChatToolScope(String traceId, String graphVersionId, Instant asOf, String memberId) {
    /** A scope for reads that are not about the member. */
    public ChatToolScope(String traceId, String graphVersionId, Instant asOf) {
        this(traceId, graphVersionId, asOf, null);
    }
}
