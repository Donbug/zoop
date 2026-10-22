package com.zoop.chat.tool;

import java.time.Instant;

/**
 * What every call of one run reads against, injected by the server from the job's frozen context: the pinned public graph
 * version (null when the question froze none) and the requested asOf inside it (null for none). {@code traceId} ties a
 * tool's own logs to the job.
 */
public record ChatToolScope(String traceId, String graphVersionId, Instant asOf) { }
